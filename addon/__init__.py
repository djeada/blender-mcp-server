bl_info = {
    "name": "Blender MCP Bridge",
    "author": "Adam Djellouli",
    "version": (0, 2, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "TCP bridge for MCP server to control Blender",
    "category": "Development",
}

import builtins
import contextlib
import errno
import hmac
import io
import json
import logging
import math
import os
import queue
import random
import secrets
import socket
import sys
import tempfile
import threading
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from typing import TYPE_CHECKING, Any

import bpy
from bpy.app.handlers import persistent

if TYPE_CHECKING:
    from collections.abc import Callable

from .models import (
    BridgeParams,
    ExportFileParams,
    JobIdParams,
    MaterialAssignParams,
    MaterialCreateEmissiveParams,
    MaterialCreateParams,
    MaterialSetColorParams,
    MaterialSetTextureParams,
    ObjectCreateMeshParams,
    ObjectCreateTreeParams,
    ObjectDeleteParams,
    ObjectDuplicateParams,
    ObjectGetHierarchyParams,
    ObjectGetTransformParams,
    ObjectRotateParams,
    ObjectScaleParams,
    ObjectScatterParams,
    ObjectTranslateParams,
    PythonExecuteParams,
    RenderAnimationParams,
    RenderStillParams,
    SceneListObjectsParams,
)

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 9876
BUFFER_SIZE = 65536
MAX_REQUEST_SIZE = 16 * 1024 * 1024  # Drop clients that send more than this without a newline

# Authentication: every request must carry this shared secret (see _load_or_create_token)
TOKEN_ENV_VAR = "BLENDER_MCP_TOKEN"
TOKEN_FILE_ENV_VAR = "BLENDER_MCP_TOKEN_FILE"
AUTH_TOKEN: str | None = None

# Security: restrict file operations to these directories (set via addon preferences)
SAFE_MODE = False
ALLOWED_PATHS: list[str] = []
TOOL_WHITELIST: set[str] | None = None  # None = all tools allowed

# Python execution settings (set via addon preferences)
ALLOW_INLINE_CODE = True
APPROVED_SCRIPT_ROOTS: list[str] = []
BLOCKED_MODULES: set[str] = {
    "subprocess",
    "socket",
    "webbrowser",
    "ctypes",
    "multiprocessing",
}
DEFAULT_SYNC_TIMEOUT = 30
DEFAULT_ASYNC_TIMEOUT = 300
MAX_SYNC_TIMEOUT = 300
MAX_ASYNC_TIMEOUT = 3600
MAX_OUTPUT_SIZE = 50000  # Cap stdout/stderr returned to client
LOG_CODE_PREVIEW_LEN = 120  # Max chars of code shown in log messages
MAX_FINISHED_JOBS = 100  # Finished async jobs kept for status queries
MAX_SCATTER_COUNT = 500  # Upper bound for a single object.scatter request

# EEVEE's identifier is BLENDER_EEVEE_NEXT in Blender 4.2-4.5 and BLENDER_EEVEE everywhere else,
# so each spelling falls back to the one the running Blender knows.
RENDER_ENGINE_ALIASES: dict[str, tuple[str, ...]] = {
    "EEVEE": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"),
    "EEVEE_NEXT": ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"),
    "BLENDER_EEVEE": ("BLENDER_EEVEE_NEXT",),
    "BLENDER_EEVEE_NEXT": ("BLENDER_EEVEE",),
    "WORKBENCH": ("BLENDER_WORKBENCH",),
}


def _token_file_path() -> str:
    """Location of the shared auth token, overridable via BLENDER_MCP_TOKEN_FILE."""
    return os.environ.get(TOKEN_FILE_ENV_VAR) or os.path.join(os.path.expanduser("~"), ".blender-mcp", "token")


def _load_or_create_token() -> str:
    """Return the bridge auth token, creating a private token file on first use.

    The MCP server reads the same file (or the BLENDER_MCP_TOKEN environment
    variable), so only processes that can read the user's files can talk to
    the bridge. This keeps web pages and other users from driving Blender.
    """
    env_token = os.environ.get(TOKEN_ENV_VAR)
    if env_token:
        return env_token
    path = _token_file_path()
    try:
        with open(path, encoding="utf-8") as f:
            existing = f.read().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    token = secrets.token_urlsafe(32)
    tmp_path = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(token)
    os.replace(tmp_path, path)
    return token


def _is_within(path: str, root: str) -> bool:
    """True when the resolved path is the root itself or inside it."""
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    try:
        return os.path.commonpath([real_path, real_root]) == real_root
    except ValueError:  # Different drives on Windows
        return False


def _default_root() -> str:
    """Directory of the saved .blend file; refuse to guess when the file is unsaved."""
    if not bpy.data.filepath:
        raise PermissionError(
            "No approved directories are configured and the .blend file is unsaved. "
            "Save the file or set 'Approved Script Roots' in the add-on preferences."
        )
    return os.path.dirname(os.path.realpath(str(bpy.data.filepath)))


def _resolve_output_path(filepath: str) -> str:
    """Absolute location for a render/export target.

    ``//`` means "next to the .blend file". An unsaved file has no such folder and Blender then
    fails to write at all, so those paths go to a ``blender-mcp`` folder in the temp directory.
    """
    if filepath.startswith("//") and not bpy.data.filepath:
        resolved = os.path.join(tempfile.gettempdir(), "blender-mcp", filepath[2:].lstrip("/\\"))
    else:
        resolved = bpy.path.abspath(filepath)
    absolute = os.path.abspath(resolved)
    # A trailing separator means "write into this folder" for renders; abspath() would drop it.
    if filepath.endswith(("/", os.sep)) and not absolute.endswith(os.sep):
        absolute += os.sep
    return absolute


def _set_render_engine(scene, engine: str) -> None:
    """Select a render engine by name, accepting any EEVEE/Workbench spelling for this Blender version."""
    requested = engine.strip().upper().replace(" ", "_")
    first_error: TypeError | None = None
    for candidate in (requested, *RENDER_ENGINE_ALIASES.get(requested, ())):
        try:
            scene.render.engine = candidate
            return
        except TypeError as exc:  # bpy rejects unknown enum values with TypeError
            first_error = first_error or exc
    raise ValueError(f"Unknown render engine '{engine}': {first_error}")


def _truncate(text: str, limit: int) -> str:
    """Truncate text with an ellipsis indicator."""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _cap_output(text: str) -> str:
    """Cap output string to MAX_OUTPUT_SIZE."""
    if len(text) <= MAX_OUTPUT_SIZE:
        return text
    return text[:MAX_OUTPUT_SIZE] + f"\n… (truncated, {len(text)} total chars)"


def _build_cube_pydata(
    size: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    half = size / 2.0
    verts = [
        (-half, -half, -half),
        (half, -half, -half),
        (half, half, -half),
        (-half, half, -half),
        (-half, -half, half),
        (half, -half, half),
        (half, half, half),
        (-half, half, half),
    ]
    faces: list[tuple[int, ...]] = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return verts, faces


def _build_plane_pydata(
    size: float,
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    half = size / 2.0
    verts = [
        (-half, -half, 0.0),
        (half, -half, 0.0),
        (half, half, 0.0),
        (-half, half, 0.0),
    ]
    return verts, [(0, 1, 2, 3)]


def _build_cylinder_pydata(
    size: float, segments: int = 24
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    radius = size / 2.0
    half_depth = size / 2.0
    verts: list[tuple[float, float, float]] = []
    for ring_z in (-half_depth, half_depth):
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            verts.append((radius * math.cos(angle), radius * math.sin(angle), ring_z))

    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append((i, nxt, segments + nxt, segments + i))
    faces.append(tuple(range(segments - 1, -1, -1)))
    faces.append(tuple(range(segments, 2 * segments)))
    return verts, faces


def _build_cone_pydata(
    size: float, segments: int = 24
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    radius = size / 2.0
    half_depth = size / 2.0
    verts: list[tuple[float, float, float]] = []
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        verts.append((radius * math.cos(angle), radius * math.sin(angle), -half_depth))
    apex_index = len(verts)
    verts.append((0.0, 0.0, half_depth))

    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append((i, nxt, apex_index))
    faces.append(tuple(range(segments - 1, -1, -1)))
    return verts, faces


def _build_uv_sphere_pydata(
    size: float, segments: int = 24, rings: int = 12
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    radius = size / 2.0
    verts: list[tuple[float, float, float]] = [(0.0, 0.0, radius)]
    for ring in range(1, rings):
        phi = math.pi * ring / rings
        sin_phi = math.sin(phi)
        cos_phi = math.cos(phi)
        for seg in range(segments):
            theta = 2.0 * math.pi * seg / segments
            verts.append(
                (
                    radius * sin_phi * math.cos(theta),
                    radius * sin_phi * math.sin(theta),
                    radius * cos_phi,
                )
            )
    bottom_index = len(verts)
    verts.append((0.0, 0.0, -radius))

    faces: list[tuple[int, ...]] = []
    for seg in range(segments):
        nxt = (seg + 1) % segments
        faces.append((0, 1 + nxt, 1 + seg))

    for ring in range(rings - 2):
        ring_start = 1 + ring * segments
        next_start = ring_start + segments
        for seg in range(segments):
            nxt = (seg + 1) % segments
            faces.append(
                (
                    ring_start + seg,
                    ring_start + nxt,
                    next_start + nxt,
                    next_start + seg,
                )
            )

    last_ring_start = 1 + (rings - 2) * segments
    for seg in range(segments):
        nxt = (seg + 1) % segments
        faces.append((last_ring_start + seg, last_ring_start + nxt, bottom_index))
    return verts, faces


def _build_torus_pydata(
    size: float, major_segments: int = 24, minor_segments: int = 12
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    major_radius = size * 0.35
    minor_radius = size * 0.15
    verts: list[tuple[float, float, float]] = []
    for major in range(major_segments):
        major_angle = 2.0 * math.pi * major / major_segments
        cos_major = math.cos(major_angle)
        sin_major = math.sin(major_angle)
        for minor in range(minor_segments):
            minor_angle = 2.0 * math.pi * minor / minor_segments
            ring = major_radius + minor_radius * math.cos(minor_angle)
            verts.append(
                (
                    ring * cos_major,
                    ring * sin_major,
                    minor_radius * math.sin(minor_angle),
                )
            )

    faces: list[tuple[int, ...]] = []
    for major in range(major_segments):
        major_next = (major + 1) % major_segments
        for minor in range(minor_segments):
            minor_next = (minor + 1) % minor_segments
            v0 = major * minor_segments + minor
            v1 = major * minor_segments + minor_next
            v2 = major_next * minor_segments + minor_next
            v3 = major_next * minor_segments + minor
            faces.append((v0, v1, v2, v3))
    return verts, faces


def _build_primitive_pydata(
    mesh_type: str, size: float
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    builders = {
        "cube": _build_cube_pydata,
        "sphere": _build_uv_sphere_pydata,
        "cylinder": _build_cylinder_pydata,
        "plane": _build_plane_pydata,
        "cone": _build_cone_pydata,
        "torus": _build_torus_pydata,
    }
    builder = builders.get(mesh_type)
    if builder is None:
        raise ValueError(f"Unknown mesh type: {mesh_type}. Options: {list(builders.keys())}")
    return builder(size)


def _create_primitive_mesh_object(
    mesh_type: str,
    *,
    name: str | None = None,
    location: list[float] | tuple[float, float, float] | None = None,
    size: float = 2.0,
):
    obj_name = name or mesh_type.capitalize()
    verts, faces = _build_primitive_pydata(mesh_type.lower(), size)
    mesh = bpy.data.meshes.new(f"{obj_name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(obj_name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if location is not None:
        obj.location = tuple(location)
    return obj


def _build_tree_pydata(
    height: float, seed: int | None = None
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]], list[int]]:
    """Build a low-poly tree (tapered trunk plus canopy blobs) as one mesh.

    Faces are tagged with material slots: 0 = bark, 1 = leaves.
    """
    rng = random.Random(seed)
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, ...]] = []
    material_indices: list[int] = []

    def append_part(part_verts, part_faces, material_index):
        offset = len(verts)
        verts.extend(part_verts)
        for face in part_faces:
            faces.append(tuple(index + offset for index in face))
            material_indices.append(material_index)

    trunk_radius = max(height * 0.055, 0.03)
    trunk_verts, trunk_faces = _build_cone_pydata(1.0, segments=12)
    append_part(
        [(x * 2.0 * trunk_radius, y * 2.0 * trunk_radius, z * height + height / 2.0) for x, y, z in trunk_verts],
        trunk_faces,
        0,
    )

    for blob in range(3):
        if blob == 0:
            ox = oy = 0.0
            oz = height * 0.95
            radius = height * 0.34
        else:
            angle = rng.uniform(0.0, math.tau)
            distance = rng.uniform(0.15, 0.3) * height
            ox = math.cos(angle) * distance
            oy = math.sin(angle) * distance
            oz = height * rng.uniform(0.78, 0.9)
            radius = height * rng.uniform(0.24, 0.3)
        blob_verts, blob_faces = _build_uv_sphere_pydata(1.0, segments=16, rings=10)
        append_part(
            [(x * 2.0 * radius + ox, y * 2.0 * radius + oy, z * 1.6 * radius + oz) for x, y, z in blob_verts],
            blob_faces,
            1,
        )

    return verts, faces, material_indices


def _get_or_create_material(name: str, base_color: tuple[float, float, float], roughness: float = 0.7):
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _make_exec_builtins(blocked_modules: set[str]) -> dict[str, Any]:
    """Create a per-execution builtins dict with a guarded __import__."""
    exec_builtins = dict(builtins.__dict__)
    original_import = exec_builtins["__import__"]

    def guarded_import(name, *a, **kw):
        top_level = name.split(".")[0]
        if top_level in blocked_modules:
            raise ImportError(f"Import of '{name}' is blocked by MCP safety policy")
        return original_import(name, *a, **kw)

    exec_builtins["__import__"] = guarded_import
    return exec_builtins


# Last execution status — shown in the Blender UI panel
_last_execution: dict[str, Any] = {
    "request_id": None,
    "source": None,
    "status": None,
    "duration_seconds": None,
    "error_summary": None,
}


# These derive from BaseException so a script's own ``except Exception:`` cannot swallow them.
class ScriptExecutionTimeout(BaseException):
    """Raised when script execution exceeds the configured timeout."""


class ScriptExecutionCancelled(BaseException):
    """Raised when script execution is cancelled cooperatively."""


def _get_addon_preferences():
    """Return this add-on's preferences object when available."""
    context = getattr(bpy, "context", None)
    preferences = getattr(context, "preferences", None)
    addons = getattr(preferences, "addons", None)
    if addons is None:
        return None

    addon_entry = None
    getter = getattr(addons, "get", None)
    if callable(getter):
        addon_entry = getter(__name__)
    elif isinstance(addons, dict):
        addon_entry = addons.get(__name__)

    return getattr(addon_entry, "preferences", None)


def _sync_runtime_settings():
    """Apply add-on preferences to module-level runtime settings."""
    global SAFE_MODE, PORT, ALLOW_INLINE_CODE, APPROVED_SCRIPT_ROOTS, ALLOWED_PATHS, TOOL_WHITELIST

    prefs = _get_addon_preferences()
    env_port = os.environ.get("BLENDER_MCP_PORT")
    if prefs is None:
        if env_port:
            PORT = int(env_port)
        return

    SAFE_MODE = bool(getattr(prefs, "safe_mode", SAFE_MODE))
    # BLENDER_MCP_PORT (shared with the MCP server) wins over the preference
    PORT = int(env_port) if env_port else int(getattr(prefs, "port", PORT))
    ALLOW_INLINE_CODE = bool(getattr(prefs, "allow_inline_code", ALLOW_INLINE_CODE))

    raw_roots = getattr(prefs, "approved_script_roots", "") or ""
    path_helper = getattr(getattr(bpy, "path", None), "abspath", None)
    approved_roots = []
    for root in raw_roots.split(";"):
        root = root.strip()
        if not root:
            continue
        resolved = path_helper(root) if callable(path_helper) else root
        approved_roots.append(os.path.realpath(resolved))

    APPROVED_SCRIPT_ROOTS = approved_roots
    ALLOWED_PATHS = approved_roots.copy() if SAFE_MODE else []

    raw_commands = getattr(prefs, "allowed_commands", "") or ""
    commands = {command.strip() for command in raw_commands.replace(";", ",").split(",") if command.strip()}
    TOOL_WHITELIST = commands or None


def _inline_code_allowed() -> bool:
    """Safe Mode always forces file-based execution from approved roots."""
    return ALLOW_INLINE_CODE and not SAFE_MODE


class CommandHandler:
    """Dispatches JSON commands to the appropriate bpy operations."""

    def __init__(self):
        self._handlers: dict[str, Callable[[dict], Any]] = {}
        self._register_builtins()

    def _register_builtins(self):
        self._handlers["scene.get_info"] = self._scene_get_info
        self._handlers["scene.list_objects"] = self._scene_list_objects
        self._handlers["object.get_transform"] = self._object_get_transform
        self._handlers["object.get_hierarchy"] = self._object_get_hierarchy
        self._handlers["material.list"] = self._material_list
        self._handlers["object.create_mesh"] = self._object_create_mesh
        self._handlers["object.delete"] = self._object_delete
        self._handlers["object.translate"] = self._object_translate
        self._handlers["object.rotate"] = self._object_rotate
        self._handlers["object.scale"] = self._object_scale
        self._handlers["object.duplicate"] = self._object_duplicate
        self._handlers["object.create_tree"] = self._object_create_tree
        self._handlers["object.scatter"] = self._object_scatter
        self._handlers["material.create"] = self._material_create
        self._handlers["material.create_emissive"] = self._material_create_emissive
        self._handlers["material.assign"] = self._material_assign
        self._handlers["material.set_color"] = self._material_set_color
        self._handlers["material.set_texture"] = self._material_set_texture
        self._handlers["render.still"] = self._render_still
        self._handlers["render.animation"] = self._render_animation
        self._handlers["export.gltf"] = self._export_gltf
        self._handlers["export.obj"] = self._export_obj
        self._handlers["export.fbx"] = self._export_fbx
        self._handlers["history.undo"] = self._history_undo
        self._handlers["history.redo"] = self._history_redo
        self._handlers["python.execute"] = self._python_execute
        self._handlers["python.execute_async"] = self._python_execute_async
        self._handlers["job.status"] = self._job_status
        self._handlers["job.cancel"] = self._job_cancel
        self._handlers["job.list"] = self._job_list

    _VALIDATORS: dict[str, type[BridgeParams]] = {
        "scene.list_objects": SceneListObjectsParams,
        "object.get_transform": ObjectGetTransformParams,
        "object.get_hierarchy": ObjectGetHierarchyParams,
        "object.create_mesh": ObjectCreateMeshParams,
        "object.delete": ObjectDeleteParams,
        "object.translate": ObjectTranslateParams,
        "object.rotate": ObjectRotateParams,
        "object.scale": ObjectScaleParams,
        "object.duplicate": ObjectDuplicateParams,
        "object.create_tree": ObjectCreateTreeParams,
        "object.scatter": ObjectScatterParams,
        "material.create": MaterialCreateParams,
        "material.create_emissive": MaterialCreateEmissiveParams,
        "material.assign": MaterialAssignParams,
        "material.set_color": MaterialSetColorParams,
        "material.set_texture": MaterialSetTextureParams,
        "render.still": RenderStillParams,
        "render.animation": RenderAnimationParams,
        "export.gltf": ExportFileParams,
        "export.obj": ExportFileParams,
        "export.fbx": ExportFileParams,
        "python.execute": PythonExecuteParams,
        "python.execute_async": PythonExecuteParams,
        "job.status": JobIdParams,
        "job.cancel": JobIdParams,
    }

    def handle(self, command: str, params: dict, sync_settings: bool = True) -> Any:
        if sync_settings:
            _sync_runtime_settings()
        # Security: check tool whitelist
        if TOOL_WHITELIST is not None and command not in TOOL_WHITELIST:
            raise PermissionError(f"Command '{command}' is not in the tool whitelist")
        handler = self._handlers.get(command)
        if not handler:
            raise ValueError(f"Unknown command: {command}")
        validator = self._VALIDATORS.get(command)
        if validator is not None:
            params = validator.model_validate(params).model_dump(exclude_none=True)
        return handler(params)

    # -- Scene tools --

    @staticmethod
    def _validate_filepath(filepath: str) -> str:
        """Security: validate that a filepath is within allowed directories."""
        if not SAFE_MODE:
            return filepath
        abs_path = os.path.abspath(bpy.path.abspath(filepath))
        # In safe mode with no allowed paths, only allow the blend file directory
        allowed_paths = ALLOWED_PATHS or [_default_root()]
        if any(_is_within(abs_path, allowed) for allowed in allowed_paths):
            return filepath
        raise PermissionError(
            f"File access denied: '{filepath}' is outside allowed directories. Allowed: {allowed_paths}"
        )

    def _prepare_output_path(self, filepath: str, extensions: tuple[str, ...] = ()) -> str:
        """Resolve a render/export target, enforce Safe Mode on it, and make sure its folder exists.

        ``extensions`` lists the suffixes the exporter accepts; the first is appended when none is present.
        """
        abs_path = _resolve_output_path(filepath)
        if extensions and not abs_path.lower().endswith(extensions):
            abs_path += extensions[0]
        self._validate_filepath(abs_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        return abs_path

    def _scene_get_info(self, params: dict) -> dict:
        scene = bpy.context.scene
        return {
            "name": scene.name,
            "frame_current": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "render_engine": scene.render.engine,
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "object_count": len(scene.objects),
        }

    def _scene_list_objects(self, params: dict) -> dict:
        type_filter = params.get("type")
        objects = []
        for obj in bpy.context.scene.objects:
            if type_filter and obj.type != type_filter.upper():
                continue
            objects.append(
                {
                    "name": obj.name,
                    "type": obj.type,
                    "location": list(obj.location),
                    "visible": obj.visible_get(),
                }
            )
        return {"objects": objects}

    def _object_get_transform(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        return {
            "name": obj.name,
            "location": list(obj.location),
            "rotation_euler": list(obj.rotation_euler),
            "scale": list(obj.scale),
        }

    def _object_get_hierarchy(self, params: dict) -> dict:
        def build_tree(obj):
            return {
                "name": obj.name,
                "type": obj.type,
                "children": [build_tree(c) for c in obj.children],
            }

        name = params.get("name")
        if name:
            obj = bpy.data.objects.get(name)
            if not obj:
                raise ValueError(f"Object '{name}' not found")
            subtree: dict = build_tree(obj)
            return subtree

        roots = [o for o in bpy.context.scene.objects if o.parent is None]
        return {"roots": [build_tree(r) for r in roots]}

    def _material_list(self, params: dict) -> dict:
        materials = []
        for mat in bpy.data.materials:
            materials.append(
                {
                    "name": mat.name,
                    "use_nodes": mat.use_nodes,
                    "user_count": mat.users,
                }
            )
        return {"materials": materials}

    # -- Object mutation tools --

    def _object_create_mesh(self, params: dict) -> dict:
        mesh_type = params.get("type", "cube").lower()
        name = params.get("name")
        location = params.get("location", [0, 0, 0])
        size = params.get("size", 2.0)
        obj = _create_primitive_mesh_object(
            mesh_type,
            name=name,
            location=location,
            size=size,
        )
        return {"name": obj.name, "type": obj.type, "location": list(obj.location)}

    def _object_delete(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"deleted": name}

    def _object_translate(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        offset = params.get("offset", [0, 0, 0])
        absolute = params.get("location")
        if absolute is not None and "offset" in params:
            raise ValueError("Provide either 'location' or 'offset', not both")
        if absolute is not None:
            obj.location = absolute
        else:
            obj.location.x += offset[0]
            obj.location.y += offset[1]
            obj.location.z += offset[2]
        return {"name": obj.name, "location": list(obj.location)}

    def _object_rotate(self, params: dict) -> dict:
        import math

        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        rotation = params.get("rotation", [0, 0, 0])
        degrees = params.get("degrees", True)
        if degrees:
            rotation = [math.radians(r) for r in rotation]
        obj.rotation_euler = rotation
        return {"name": obj.name, "rotation_euler": list(obj.rotation_euler)}

    def _object_scale(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        scale = params.get("scale", [1, 1, 1])
        obj.scale = scale
        return {"name": obj.name, "scale": list(obj.scale)}

    def _object_duplicate(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        new_obj = obj.copy()
        if obj.data is not None:  # Empties carry no data block
            new_obj.data = obj.data.copy()
        new_name = params.get("new_name")
        if new_name:
            new_obj.name = new_name
        bpy.context.collection.objects.link(new_obj)
        return {
            "name": new_obj.name,
            "original": obj.name,
            "location": list(new_obj.location),
        }

    def _object_create_tree(self, params: dict) -> dict:
        name = params.get("name") or "Tree"
        location = params.get("location", [0, 0, 0])
        height = params.get("height", 3.0)
        verts, faces, material_indices = _build_tree_pydata(height, params.get("seed"))

        mesh = bpy.data.meshes.new(f"{name}Mesh")
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        for poly, material_index in zip(mesh.polygons, material_indices, strict=False):
            poly.material_index = material_index
            poly.use_smooth = material_index == 1

        trunk_material_name = params.get("trunk_material")
        if trunk_material_name:
            trunk_mat = bpy.data.materials.get(trunk_material_name)
            if trunk_mat is None:
                raise ValueError(f"Material '{trunk_material_name}' not found")
        else:
            trunk_mat = _get_or_create_material("TreeBark", (0.08, 0.05, 0.035), 0.9)
        leaves_material_name = params.get("leaves_material")
        if leaves_material_name:
            leaves_mat = bpy.data.materials.get(leaves_material_name)
            if leaves_mat is None:
                raise ValueError(f"Material '{leaves_material_name}' not found")
        else:
            leaves_mat = _get_or_create_material("TreeLeaves", (0.03, 0.18, 0.06), 0.7)
        mesh.materials.append(trunk_mat)
        mesh.materials.append(leaves_mat)

        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        obj.location = tuple(location)
        return {
            "name": obj.name,
            "location": list(obj.location),
            "height": height,
            "vertices": len(verts),
            "faces": len(faces),
            "materials": [trunk_mat.name, leaves_mat.name],
        }

    def _object_scatter(self, params: dict) -> dict:
        source_name = params["source"]
        source = bpy.data.objects.get(source_name)
        if not source:
            raise ValueError(f"Object '{source_name}' not found")
        count = params.get("count", 10)
        if count > MAX_SCATTER_COUNT:
            raise ValueError(f"'count' must be at most {MAX_SCATTER_COUNT}")
        scale_min = params.get("scale_min", 1.0)
        scale_max = params.get("scale_max", 1.0)
        if scale_max < scale_min:
            raise ValueError("'scale_max' must be greater than or equal to 'scale_min'")
        location = params.get("location", [0, 0, 0])
        radius = params.get("radius", 5.0)
        rotation_z_min = params.get("rotation_z_min", 0.0)
        rotation_z_max = params.get("rotation_z_max", 360.0)
        name_prefix = params.get("name_prefix") or f"{source.name}_scatter"

        rng = random.Random(params.get("seed"))
        created: list[str] = []
        for index in range(count):
            distance = radius * math.sqrt(rng.random())
            angle = rng.uniform(0.0, math.tau)
            duplicate = source.copy()
            duplicate.name = f"{name_prefix}_{index:03d}"
            bpy.context.collection.objects.link(duplicate)
            duplicate.location = (
                location[0] + math.cos(angle) * distance,
                location[1] + math.sin(angle) * distance,
                location[2],
            )
            duplicate.rotation_euler = (
                source.rotation_euler[0],
                source.rotation_euler[1],
                math.radians(rng.uniform(rotation_z_min, rotation_z_max)),
            )
            scale = rng.uniform(scale_min, scale_max)
            duplicate.scale = (
                source.scale[0] * scale,
                source.scale[1] * scale,
                source.scale[2] * scale,
            )
            created.append(duplicate.name)
        return {
            "source": source.name,
            "count": len(created),
            "names": created,
            "location": location,
            "radius": radius,
        }

    # -- Material tools --

    def _material_create(self, params: dict) -> dict:
        name = params.get("name", "Material")
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        color = params.get("color")
        if color:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                # color is [r, g, b] or [r, g, b, a], values 0-1
                rgba = list(color) + [1.0] * (4 - len(color))
                bsdf.inputs["Base Color"].default_value = rgba[:4]
        return {"name": mat.name, "use_nodes": mat.use_nodes}

    def _material_create_emissive(self, params: dict) -> dict:
        name = params["name"]
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf:
            raise ValueError("Material has no Principled BSDF node")

        color = params.get("color")
        if color:
            rgba = list(color) + [1.0] * (4 - len(color))
            bsdf.inputs["Base Color"].default_value = rgba[:4]

        emission = list(params.get("emission_color", [1, 1, 1]))
        rgba = (emission + [1.0] * (4 - len(emission)))[:4]
        emission_socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if emission_socket is None:
            raise ValueError("Material has no emission input")
        emission_socket.default_value = rgba

        strength = params.get("emission_strength", 5.0)
        strength_socket = bsdf.inputs.get("Emission Strength")
        if strength_socket is not None:
            strength_socket.default_value = strength
        return {
            "name": mat.name,
            "emission_color": rgba,
            "emission_strength": strength,
        }

    def _material_assign(self, params: dict) -> dict:
        obj_name = params["object"]
        mat_name = params["material"]
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            raise ValueError(f"Object '{obj_name}' not found")
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            raise ValueError(f"Material '{mat_name}' not found")
        materials = getattr(obj.data, "materials", None)
        if materials is None:
            raise ValueError(f"Object '{obj_name}' is of type {obj.type}, which cannot have materials")
        if materials:
            materials[0] = mat
        else:
            materials.append(mat)
        return {"object": obj.name, "material": mat.name}

    def _material_set_color(self, params: dict) -> dict:
        mat_name = params["name"]
        color = params["color"]  # [r, g, b] or [r, g, b, a]
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            raise ValueError(f"Material '{mat_name}' not found")
        if not mat.use_nodes:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf:
            raise ValueError(f"Material '{mat_name}' has no Principled BSDF node")
        rgba = list(color) + [1.0] * (4 - len(color))
        bsdf.inputs["Base Color"].default_value = rgba[:4]
        return {"name": mat.name, "color": rgba[:4]}

    def _material_set_texture(self, params: dict) -> dict:
        mat_name = params["name"]
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            raise ValueError(f"Material '{mat_name}' not found")
        if not mat.use_nodes:
            mat.use_nodes = True
        tree = mat.node_tree
        bsdf = tree.nodes.get("Principled BSDF")
        if not bsdf:
            raise ValueError(f"Material '{mat_name}' has no Principled BSDF node")
        # Load first: a missing or unreadable file must not leave a dangling node behind.
        image = bpy.data.images.load(filepath, check_existing=True)
        base_color = bsdf.inputs["Base Color"]
        tex_node = next(
            (link.from_node for link in base_color.links if link.from_node.bl_idname == "ShaderNodeTexImage"),
            None,
        )
        if tex_node is None:
            tex_node = tree.nodes.new("ShaderNodeTexImage")
            tree.links.new(tex_node.outputs["Color"], base_color)
        tex_node.image = image
        return {"name": mat.name, "texture": filepath}

    # -- Render tools --

    def _render_still(self, params: dict) -> dict:
        scene = bpy.context.scene
        abs_path = self._prepare_output_path(params.get("output_path", "//render.png"))
        resolution_x = params.get("resolution_x")
        resolution_y = params.get("resolution_y")
        engine = params.get("engine")

        if engine:
            _set_render_engine(scene, engine)
        if resolution_x:
            scene.render.resolution_x = resolution_x
        if resolution_y:
            scene.render.resolution_y = resolution_y

        scene.render.filepath = abs_path
        bpy.ops.render.render(write_still=True)
        return {
            "output_path": abs_path,
            "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        }

    def _render_animation(self, params: dict) -> dict:
        scene = bpy.context.scene
        abs_path = self._prepare_output_path(params.get("output_path", "//render_"))
        frame_start = params.get("frame_start")
        frame_end = params.get("frame_end")
        engine = params.get("engine")

        if engine:
            _set_render_engine(scene, engine)
        if frame_start is not None:
            scene.frame_start = frame_start
        if frame_end is not None:
            scene.frame_end = frame_end

        scene.render.filepath = abs_path
        bpy.ops.render.render(animation=True)
        return {
            "output_path": abs_path,
            "frame_range": [scene.frame_start, scene.frame_end],
            "engine": scene.render.engine,
        }

    # -- Export tools --

    def _export_gltf(self, params: dict) -> dict:
        filepath = self._prepare_output_path(params["filepath"], extensions=(".glb", ".gltf"))
        bpy.ops.export_scene.gltf(filepath=filepath)
        return {"filepath": filepath, "format": "glTF"}

    def _export_obj(self, params: dict) -> dict:
        filepath = self._prepare_output_path(params["filepath"], extensions=(".obj",))
        bpy.ops.wm.obj_export(filepath=filepath)
        return {"filepath": filepath, "format": "OBJ"}

    def _export_fbx(self, params: dict) -> dict:
        filepath = self._prepare_output_path(params["filepath"], extensions=(".fbx",))
        bpy.ops.export_scene.fbx(filepath=filepath)
        return {"filepath": filepath, "format": "FBX"}

    # -- History tools --

    def _history_undo(self, params: dict) -> dict:
        bpy.ops.ed.undo()
        return {"action": "undo"}

    def _history_redo(self, params: dict) -> dict:
        bpy.ops.ed.redo()
        return {"action": "redo"}

    # -- Python execution tools --

    @staticmethod
    def _validate_script_path(script_path: str) -> str:
        """Validate that a script path is under an approved root directory."""
        real_path = os.path.realpath(script_path)
        if not os.path.isfile(real_path):
            raise FileNotFoundError(f"Script not found: {script_path}")
        if not real_path.endswith(".py"):
            raise ValueError(f"Script must be a .py file: {script_path}")

        roots = APPROVED_SCRIPT_ROOTS or [_default_root()]

        for root in roots:
            if _is_within(real_path, root):
                return real_path
        raise PermissionError(f"Script path denied: '{script_path}' is outside approved roots. Approved: {roots}")

    @staticmethod
    def _make_namespace(args: dict, cancel_event: threading.Event | None = None) -> dict:
        """Build the execution namespace for exec()."""
        import mathutils

        ns: dict[str, Any] = {
            "bpy": bpy,
            "math": math,
            "mathutils": mathutils,
            "mcp_create_mesh": _create_primitive_mesh_object,
            "args": args or {},
            "__result__": None,
            "__builtins__": _make_exec_builtins(BLOCKED_MODULES),
        }
        if cancel_event is not None:
            ns["__cancel_event__"] = cancel_event
        return ns

    @staticmethod
    def _safe_json(value: Any) -> Any:
        """Ensure a value is JSON-serializable, falling back to repr()."""
        if value is None:
            return None
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return repr(value)

    def _run_code(
        self,
        code: str,
        namespace: dict,
        timeout_seconds: float,
        request_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict:
        """Execute code with stdout/stderr capture and cooperative timeout checks."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        start = time.monotonic()
        previous_trace = sys.gettrace()

        def trace_calls(frame, event, arg):
            if event == "line":
                if cancel_event is not None and cancel_event.is_set():
                    raise ScriptExecutionCancelled("Execution cancelled")
                if timeout_seconds > 0 and (time.monotonic() - start) > timeout_seconds:
                    raise ScriptExecutionTimeout(f"Execution exceeded timeout of {timeout_seconds:.3f}s")
            return trace_calls

        sys.settrace(trace_calls)
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<mcp-script>", "exec"), namespace)
        except BaseException as exc:  # Includes SystemExit/KeyboardInterrupt, which must not reach Blender
            elapsed = time.monotonic() - start
            tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
            # Filter out internal bridge frames
            filtered = [line for line in tb_lines if "addon/__init__" not in line]
            error_str = "".join(filtered).strip()
            logger.warning(
                "Script execution failed [%s] after %.3fs: %s",
                request_id or "?",
                elapsed,
                _truncate(str(exc), 200),
            )
            return {
                "result": None,
                "stdout": _cap_output(stdout_buf.getvalue()),
                "stderr": _cap_output(stderr_buf.getvalue()),
                "error": error_str,
                "duration_seconds": round(elapsed, 4),
                "timed_out": isinstance(exc, ScriptExecutionTimeout),
                "cancelled": isinstance(exc, ScriptExecutionCancelled),
            }
        finally:
            sys.settrace(previous_trace)

        elapsed = time.monotonic() - start
        logger.info(
            "Script execution succeeded [%s] in %.3fs",
            request_id or "?",
            elapsed,
        )
        return {
            "result": self._safe_json(namespace.get("__result__")),
            "stdout": _cap_output(stdout_buf.getvalue()),
            "stderr": _cap_output(stderr_buf.getvalue()),
            "error": None,
            "duration_seconds": round(elapsed, 4),
            "timed_out": False,
            "cancelled": False,
        }

    def _python_execute(self, params: dict) -> dict:
        global _last_execution
        code = params.get("code")
        script_path = params.get("script_path")
        args = params.get("args", {})
        timeout_seconds = min(params.get("timeout_seconds", DEFAULT_SYNC_TIMEOUT), MAX_SYNC_TIMEOUT)

        request_id = f"exec-{uuid.uuid4().hex[:8]}"

        if code and script_path:
            raise ValueError("Provide either 'code' or 'script_path', not both")
        if not code and not script_path:
            raise ValueError("Either 'code' or 'script_path' must be provided")

        if code is not None:
            if not _inline_code_allowed():
                raise PermissionError(
                    "Inline code execution is disabled (Allow Inline Code is off or Safe Mode is on). "
                    "Use script_path instead."
                )
            source_label = f"inline ({_truncate(code, LOG_CODE_PREVIEW_LEN)})"
        else:
            validated = self._validate_script_path(str(script_path))
            with open(validated, encoding="utf-8") as f:
                code = f.read()
            source_label = f"file ({script_path})"

        logger.info("python.execute [%s] starting: %s", request_id, source_label)

        namespace = self._make_namespace(args)
        result = self._run_code(code, namespace, timeout_seconds, request_id, cancel_event=None)

        _last_execution = {
            "request_id": request_id,
            "source": source_label,
            "status": "error" if result.get("error") else "ok",
            "duration_seconds": result.get("duration_seconds"),
            "error_summary": (_truncate(result["error"], 200) if result.get("error") else None),
        }
        return result

    def _python_execute_async(self, params: dict) -> dict:
        code = params.get("code")
        script_path = params.get("script_path")
        args = params.get("args", {})
        timeout_seconds = min(params.get("timeout_seconds", DEFAULT_ASYNC_TIMEOUT), MAX_ASYNC_TIMEOUT)

        if code and script_path:
            raise ValueError("Provide either 'code' or 'script_path', not both")
        if not code and not script_path:
            raise ValueError("Either 'code' or 'script_path' must be provided")

        if code is not None:
            if not _inline_code_allowed():
                raise PermissionError(
                    "Inline code execution is disabled (Allow Inline Code is off or Safe Mode is on). "
                    "Use script_path instead."
                )
            source_label = f"inline ({_truncate(code, LOG_CODE_PREVIEW_LEN)})"
        else:
            validated = self._validate_script_path(str(script_path))
            with open(validated, encoding="utf-8") as f:
                code = f.read()
            source_label = f"file ({script_path})"

        job_id = _job_manager.create_job(code, args, timeout_seconds, self)
        logger.info("python.execute_async [%s] queued: %s", job_id, source_label)
        return {"job_id": job_id}

    def _job_status(self, params: dict) -> dict:
        job_id = params.get("job_id")
        if not job_id:
            raise ValueError("'job_id' is required")
        return _job_manager.get_status(job_id)

    def _job_cancel(self, params: dict) -> dict:
        job_id = params.get("job_id")
        if not job_id:
            raise ValueError("'job_id' is required")
        return _job_manager.cancel(job_id)

    def _job_list(self, params: dict) -> dict:
        return _job_manager.list_jobs()


class JobManager:
    """Manages async job lifecycle for long-running Blender scripts."""

    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_job(
        self,
        code: str,
        args: dict,
        timeout_seconds: float,
        handler: CommandHandler,
    ) -> str:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        now = time.time()
        cancel_event = threading.Event()

        job = {
            "job_id": job_id,
            "status": "queued",
            "cancellation_requested": False,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "result": None,
            "stdout": "",
            "stderr": "",
            "error": None,
            "code": code,
            "args": args,
            "timeout_seconds": timeout_seconds,
            "cancel_event": cancel_event,
            "handler": handler,
        }

        with self._lock:
            self._prune_finished_jobs()
            self._jobs[job_id] = job

        bpy.app.timers.register(lambda: self._execute_job(job_id), first_interval=0.01)
        return job_id

    def _prune_finished_jobs(self) -> None:
        """Drop the oldest finished jobs so the job table cannot grow without bound. Caller holds the lock."""
        finished = [j for j in self._jobs.values() if j["status"] in {"succeeded", "failed", "cancelled"}]
        excess = len(finished) - MAX_FINISHED_JOBS + 1
        for job in sorted(finished, key=lambda j: j["created_at"])[: max(excess, 0)]:
            del self._jobs[job["job_id"]]

    @staticmethod
    def _release_job_inputs(job: dict[str, Any]) -> None:
        """Free the script source and handler once a job can no longer run. Caller holds the lock."""
        job["code"] = None
        job["args"] = None
        job["handler"] = None

    def _execute_job(self, job_id: str) -> None:
        global _last_execution
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "queued":
                return
            job["status"] = "running"
            job["started_at"] = time.time()

        logger.info("Job [%s] running", job_id)

        cancel_event = job["cancel_event"]
        if cancel_event.is_set():
            with self._lock:
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                self._release_job_inputs(job)
            logger.info("Job [%s] cancelled before start", job_id)
            return

        handler = job["handler"]
        namespace = handler._make_namespace(job["args"], cancel_event)
        result = handler._run_code(
            job["code"],
            namespace,
            job["timeout_seconds"],
            job_id,
            cancel_event=cancel_event,
        )

        with self._lock:
            job["result"] = result.get("result")
            job["stdout"] = result.get("stdout", "")
            job["stderr"] = result.get("stderr", "")
            job["error"] = result.get("error")
            if result.get("cancelled") or cancel_event.is_set():
                job["status"] = "cancelled"
            else:
                job["status"] = "failed" if result.get("error") else "succeeded"
            job["completed_at"] = time.time()
            self._release_job_inputs(job)

        elapsed = (job["completed_at"] - job["started_at"]) if job["started_at"] else 0
        logger.info("Job [%s] %s in %.3fs", job_id, job["status"], elapsed)

        _last_execution = {
            "request_id": job_id,
            "source": "async job",
            "status": job["status"],
            "duration_seconds": round(elapsed, 4),
            "error_summary": _truncate(job["error"], 200) if job.get("error") else None,
        }

    def get_status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            raise ValueError(f"Unknown job: {job_id}")
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "cancellation_requested": job["cancellation_requested"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "result": job["result"],
            "stdout": job["stdout"],
            "stderr": job["stderr"],
            "error": job["error"],
        }

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError(f"Unknown job: {job_id}")

            job["cancel_event"].set()
            job["cancellation_requested"] = True

            if job["status"] == "queued":
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                self._release_job_inputs(job)

            status = job["status"]
            cancellation_requested = job["cancellation_requested"]

        return {
            "job_id": job_id,
            "status": status,
            "cancellation_requested": cancellation_requested,
        }

    def list_jobs(self) -> dict:
        with self._lock:
            jobs = [
                {
                    "job_id": j["job_id"],
                    "status": j["status"],
                    "created_at": j["created_at"],
                }
                for j in self._jobs.values()
            ]
        return {"jobs": jobs}


# Global job manager instance
_job_manager = JobManager()


class BlenderMCPServer:
    """TCP socket server running inside Blender."""

    def __init__(self):
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._host = HOST
        self._port = PORT
        self._handler = CommandHandler()
        self._request_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._drain_timer_callback = self._drain_request_queue

    def start(self):
        global AUTH_TOKEN
        if self._running:
            self._register_request_queue_timer()
            return
        _sync_runtime_settings()
        AUTH_TOKEN = _load_or_create_token()
        self._host = HOST
        self._port = PORT
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        try:
            self._server_socket.bind((self._host, self._port))
        except OSError as exc:
            if self._server_socket is not None:
                self._server_socket.close()
                self._server_socket = None
            if exc.errno == errno.EADDRINUSE:
                logger.warning(
                    "Blender MCP Bridge port %s already in use; skipping bridge startup",
                    self._port,
                )
                self._running = False
                return
            raise
        self._running = True
        self._server_socket.listen(1)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        self._register_request_queue_timer()
        logger.info(f"Blender MCP Bridge listening on {self._host}:{self._port}")

    def _register_request_queue_timer(self):
        timers = bpy.app.timers
        is_registered = getattr(timers, "is_registered", None)
        if callable(is_registered):
            try:
                if is_registered(self._drain_timer_callback):
                    return
            except Exception:
                logger.debug("Unable to check MCP Bridge queue timer registration", exc_info=True)
        try:
            timers.register(self._drain_timer_callback, first_interval=0.01, persistent=True)
        except TypeError:
            # Blender versions before the persistent timer flag still need the bridge to run.
            timers.register(self._drain_timer_callback, first_interval=0.01)
        logger.debug("Registered MCP Bridge request queue timer")

    def stop(self):
        self._running = False
        if self._server_socket:
            self._server_socket.close()
            self._server_socket = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        while not self._request_queue.empty():
            queued = self._request_queue.get_nowait()
            queued["response"] = {
                "id": queued["request"].get("id"),
                "success": False,
                "error": "Blender MCP Bridge stopped",
            }
            queued["event"].set()
        logger.info("Blender MCP Bridge stopped")

    def _accept_loop(self):
        while self._running:
            try:
                assert self._server_socket is not None
                conn, addr = self._server_socket.accept()
                logger.info(f"MCP client connected from {addr}")
                client_thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                client_thread.start()
            except TimeoutError:
                continue
            except OSError:
                break

    @staticmethod
    def _is_authorized(request: dict) -> bool:
        token = request.get("token")
        if AUTH_TOKEN is None or not isinstance(token, str):
            return False
        return hmac.compare_digest(token.encode(), AUTH_TOKEN.encode())

    @staticmethod
    def _reject(conn: socket.socket, request_id: Any, error: str) -> None:
        with contextlib.suppress(OSError):
            conn.sendall(json.dumps({"id": request_id, "success": False, "error": error}).encode() + b"\n")

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(None)
        buffer = b""
        try:
            while self._running:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                buffer += data
                if b"\n" not in buffer and len(buffer) > MAX_REQUEST_SIZE:
                    self._reject(conn, None, f"Request exceeds {MAX_REQUEST_SIZE} bytes")
                    return
                # Messages are newline-delimited JSON
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    # Any malformed line closes the connection. This stops cross-protocol
                    # payloads (e.g. a browser POST whose body smuggles a JSON command).
                    try:
                        request = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        self._reject(conn, None, f"Invalid JSON: {e}")
                        return
                    if not isinstance(request, dict):
                        self._reject(conn, None, "Request must be a JSON object")
                        return
                    if not self._is_authorized(request):
                        logger.warning("Rejected unauthenticated MCP bridge request")
                        # id=None marks a connection-level rejection; the connection is closed next.
                        self._reject(conn, None, "Unauthorized: missing or invalid token")
                        return
                    response = self._submit_request(request)
                    conn.sendall(json.dumps(response).encode() + b"\n")
        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            conn.close()

    # Commands that modify scene state and need undo push
    MUTATION_COMMANDS = {
        "object.create_mesh",
        "object.delete",
        "object.translate",
        "object.rotate",
        "object.scale",
        "object.duplicate",
        "object.create_tree",
        "object.scatter",
        "material.create",
        "material.create_emissive",
        "material.assign",
        "material.set_color",
        "material.set_texture",
    }

    # Commands answered on the socket thread. They only touch the thread-safe JobManager,
    # so they stay responsive while an async job occupies Blender's main thread.
    WORKER_THREAD_COMMANDS = {"job.status", "job.cancel", "job.list"}

    def _submit_request(self, request: dict) -> dict:
        if request.get("command") in self.WORKER_THREAD_COMMANDS:
            return self._process_request(request, sync_settings=False)
        event = threading.Event()
        queued: dict[str, Any] = {"request": request, "event": event, "response": None}
        logger.debug("Enqueue MCP request id=%s command=%s", request.get("id"), request.get("command"))
        self._request_queue.put(queued)
        event.wait()
        response: dict = queued["response"]
        return response

    def _drain_request_queue(self):
        while True:
            try:
                queued = self._request_queue.get_nowait()
            except queue.Empty:
                break
            request = queued["request"]
            logger.debug(
                "Processing MCP request id=%s command=%s",
                request.get("id"),
                request.get("command"),
            )
            try:
                queued["response"] = self._process_request(queued["request"])
            except BaseException as exc:  # Never leave a client waiting or let this kill the timer
                queued["response"] = {"id": request.get("id"), "success": False, "error": repr(exc)}
            finally:
                queued["event"].set()
            logger.debug(
                "Finished MCP request id=%s command=%s",
                request.get("id"),
                request.get("command"),
            )
        return 0.01 if self._running else None

    @staticmethod
    def _maybe_push_undo(command: str):
        undo_push = bpy.ops.ed.undo_push
        poll = getattr(undo_push, "poll", None)
        if callable(poll) and not poll():
            logger.debug(f"Skipping undo push for {command}: context poll failed")
            return
        undo_push(message=f"MCP: {command}")

    def _process_request(self, request: dict, sync_settings: bool = True) -> dict:
        req_id = request.get("id")
        command = request.get("command", "")
        params = request.get("params", {})
        try:
            # Auto-push undo before mutations
            if command in self.MUTATION_COMMANDS:
                self._maybe_push_undo(command)
            result = self._handler.handle(command, params, sync_settings=sync_settings)
            return {"id": req_id, "success": True, "result": result}
        except Exception as e:
            logger.error(f"Command '{command}' failed: {e}\n{traceback.format_exc()}")
            return {"id": req_id, "success": False, "error": str(e)}


# Global server instance
_server: BlenderMCPServer | None = None


def _server_healthy() -> bool:
    global _server
    return bool(
        _server
        and _server._running
        and _server._server_socket is not None
        and _server._thread is not None
        and _server._thread.is_alive()
        and _server._port == PORT
    )


def _ensure_server_running():
    global _server
    _sync_runtime_settings()
    if _server is not None and _server_healthy():
        _server._register_request_queue_timer()
        return None
    if _server:
        try:
            _server.stop()
        except Exception:
            logger.exception("Failed stopping stale MCP Bridge during restart")
    _sync_runtime_settings()
    _server = BlenderMCPServer()
    _server.start()
    return None


@persistent
def _on_load_post(_dummy):
    bpy.app.timers.register(_ensure_server_running, first_interval=0.1)


def _on_port_changed(_prefs, _context):
    """Rebind the bridge when the port preference changes."""
    bpy.app.timers.register(_ensure_server_running, first_interval=0.1)


class MCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    safe_mode: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Safe Mode",
        description=(
            "Restrict file access to the approved directories (or the .blend file's directory) "
            "and disable inline Python code"
        ),
        default=False,
    )
    port: bpy.props.IntProperty(  # type: ignore[valid-type]
        name="Port",
        description="TCP port for the MCP bridge",
        default=9876,
        min=1024,
        max=65535,
        update=_on_port_changed,
    )
    allow_inline_code: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Allow Inline Code",
        description="Allow python.execute to run inline code strings. Disable to only allow script files",
        default=True,
    )
    approved_script_roots: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Approved Script Roots",
        description="Semicolon-separated list of directories from which script files may be loaded",
        default="",
    )
    allowed_commands: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Allowed Commands",
        description="Comma-separated bridge commands to accept (e.g. scene.get_info,object.create_mesh). Empty = all",
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "safe_mode")
        layout.prop(self, "port")
        layout.prop(self, "allowed_commands")
        layout.label(text=f"Auth token file: {_token_file_path()}")
        layout.separator()
        layout.label(text="Python Execution")
        layout.prop(self, "allow_inline_code")
        layout.prop(self, "approved_script_roots")


class MCP_PT_Panel(bpy.types.Panel):
    bl_label = "MCP Bridge"
    bl_idname = "MCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP"

    def draw(self, context):
        layout = self.layout
        global _server
        if _server and _server._running:
            layout.label(text=f"● Listening on {_server._host}:{_server._port}", icon="LINKED")
            layout.operator("mcp.stop_server", text="Stop Server")
        else:
            layout.label(text="○ Server stopped", icon="UNLINKED")
            layout.operator("mcp.start_server", text="Start Server")

        # Last script execution status
        if _last_execution["request_id"]:
            layout.separator()
            layout.label(text="Last Execution", icon="SCRIPT")
            box = layout.box()
            status = _last_execution["status"]
            icon = "CHECKMARK" if status in ("ok", "succeeded") else "ERROR"
            box.label(text=f"Status: {status}", icon=icon)
            box.label(text=f"ID: {_last_execution['request_id']}")
            if _last_execution["duration_seconds"] is not None:
                box.label(text=f"Duration: {_last_execution['duration_seconds']:.3f}s")
            if _last_execution["error_summary"]:
                box.label(text=f"Error: {_last_execution['error_summary']}", icon="ERROR")


class MCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "mcp.start_server"
    bl_label = "Start MCP Server"

    def execute(self, context):
        global _server
        if _server is None:
            _server = BlenderMCPServer()
        _server.start()
        self.report({"INFO"}, f"MCP Bridge started on {_server._host}:{_server._port}")
        return {"FINISHED"}


class MCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "mcp.stop_server"
    bl_label = "Stop MCP Server"

    def execute(self, context):
        global _server
        if _server:
            _server.stop()
        self.report({"INFO"}, "MCP Bridge stopped")
        return {"FINISHED"}


classes = (MCP_AddonPreferences, MCP_PT_Panel, MCP_OT_StartServer, MCP_OT_StopServer)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    _ensure_server_running()


def unregister():
    global _server
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if _server:
        _server.stop()
        _server = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
