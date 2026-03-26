bl_info = {
    "name": "Blender MCP Bridge",
    "author": "Blender MCP Server",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "TCP bridge for MCP server to control Blender",
    "category": "Development",
}

import bpy
import builtins
import errno
import json
import io
import math
import os
import queue
import socket
import sys
import threading
import traceback
import logging
import time
import uuid
from contextlib import redirect_stdout, redirect_stderr
from typing import Any

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 9876
BUFFER_SIZE = 65536

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


def _build_cube_pydata(size: float) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
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
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return verts, faces


def _build_plane_pydata(size: float) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
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
        raise ValueError(
            f"Unknown mesh type: {mesh_type}. Options: {list(builders.keys())}"
        )
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


def _make_exec_builtins(blocked_modules: set[str]) -> dict[str, Any]:
    """Create a per-execution builtins dict with a guarded __import__."""
    exec_builtins = dict(builtins.__dict__)
    original_import = exec_builtins["__import__"]

    def guarded_import(name, *a, **kw):
        top_level = name.split(".")[0]
        if top_level in blocked_modules:
            raise ImportError(
                f"Import of '{name}' is blocked by MCP safety policy"
            )
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


class ScriptExecutionTimeout(TimeoutError):
    """Raised when script execution exceeds the configured timeout."""


class ScriptExecutionCancelled(RuntimeError):
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
    global SAFE_MODE, PORT, ALLOW_INLINE_CODE, APPROVED_SCRIPT_ROOTS, ALLOWED_PATHS

    prefs = _get_addon_preferences()
    if prefs is None:
        return

    SAFE_MODE = bool(getattr(prefs, "safe_mode", SAFE_MODE))
    PORT = int(getattr(prefs, "port", PORT))
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


class CommandHandler:
    """Dispatches JSON commands to the appropriate bpy operations."""

    def __init__(self):
        self._handlers: dict[str, callable] = {}
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
        self._handlers["material.create"] = self._material_create
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

    def handle(self, command: str, params: dict) -> Any:
        _sync_runtime_settings()
        # Security: check tool whitelist
        if TOOL_WHITELIST is not None and command not in TOOL_WHITELIST:
            raise PermissionError(f"Command '{command}' is not in the tool whitelist")
        handler = self._handlers.get(command)
        if not handler:
            raise ValueError(f"Unknown command: {command}")
        return handler(params)

    # -- Scene tools --

    @staticmethod
    def _validate_filepath(filepath: str) -> str:
        """Security: validate that a filepath is within allowed directories."""
        if not SAFE_MODE:
            return filepath
        abs_path = os.path.abspath(bpy.path.abspath(filepath))
        if not ALLOWED_PATHS:
            # In safe mode with no allowed paths, only allow the blend file directory
            blend_dir = (
                os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
            )
            ALLOWED_PATHS.append(blend_dir)
        for allowed in ALLOWED_PATHS:
            if abs_path.startswith(os.path.abspath(allowed)):
                return filepath
        raise PermissionError(
            f"File access denied: '{filepath}' is outside allowed directories. "
            f"Allowed: {ALLOWED_PATHS}"
        )

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
            return build_tree(obj)

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
        if absolute:
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

    def _material_assign(self, params: dict) -> dict:
        obj_name = params["object"]
        mat_name = params["material"]
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            raise ValueError(f"Object '{obj_name}' not found")
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            raise ValueError(f"Material '{mat_name}' not found")
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
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
        tex_node = tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = bpy.data.images.load(filepath)
        tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        return {"name": mat.name, "texture": filepath}

    # -- Render tools --

    def _render_still(self, params: dict) -> dict:
        scene = bpy.context.scene
        output_path = params.get("output_path", "//render.png")
        self._validate_filepath(output_path)
        resolution_x = params.get("resolution_x")
        resolution_y = params.get("resolution_y")
        engine = params.get("engine")

        if engine:
            scene.render.engine = engine.upper()
        if resolution_x:
            scene.render.resolution_x = resolution_x
        if resolution_y:
            scene.render.resolution_y = resolution_y

        scene.render.filepath = output_path
        bpy.ops.render.render(write_still=True)
        abs_path = bpy.path.abspath(output_path)
        return {
            "output_path": abs_path,
            "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        }

    def _render_animation(self, params: dict) -> dict:
        scene = bpy.context.scene
        output_path = params.get("output_path", "//render_")
        self._validate_filepath(output_path)
        frame_start = params.get("frame_start")
        frame_end = params.get("frame_end")
        engine = params.get("engine")

        if engine:
            scene.render.engine = engine.upper()
        if frame_start is not None:
            scene.frame_start = frame_start
        if frame_end is not None:
            scene.frame_end = frame_end

        scene.render.filepath = output_path
        bpy.ops.render.render(animation=True)
        abs_path = bpy.path.abspath(output_path)
        return {
            "output_path": abs_path,
            "frame_range": [scene.frame_start, scene.frame_end],
            "engine": scene.render.engine,
        }

    # -- Export tools --

    def _export_gltf(self, params: dict) -> dict:
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        if not filepath.endswith((".glb", ".gltf")):
            filepath += ".glb"
        bpy.ops.export_scene.gltf(filepath=filepath)
        return {"filepath": filepath, "format": "glTF"}

    def _export_obj(self, params: dict) -> dict:
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        if not filepath.endswith(".obj"):
            filepath += ".obj"
        bpy.ops.wm.obj_export(filepath=filepath)
        return {"filepath": filepath, "format": "OBJ"}

    def _export_fbx(self, params: dict) -> dict:
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        if not filepath.endswith(".fbx"):
            filepath += ".fbx"
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

        roots = APPROVED_SCRIPT_ROOTS
        if not roots:
            blend_dir = (
                os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
            )
            roots = [blend_dir]

        for root in roots:
            if real_path.startswith(os.path.realpath(root) + os.sep) or real_path == os.path.realpath(root):
                return real_path
        raise PermissionError(
            f"Script path denied: '{script_path}' is outside approved roots. "
            f"Approved: {roots}"
        )

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
                    raise ScriptExecutionTimeout(
                        f"Execution exceeded timeout of {timeout_seconds:.3f}s"
                    )
            return trace_calls

        sys.settrace(trace_calls)
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<mcp-script>", "exec"), namespace)
        except Exception as exc:
            elapsed = time.monotonic() - start
            tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
            # Filter out internal bridge frames
            filtered = [l for l in tb_lines if "addon/__init__" not in l]
            error_str = "".join(filtered).strip()
            logger.warning(
                "Script execution failed [%s] after %.3fs: %s",
                request_id or "?", elapsed, _truncate(str(exc), 200),
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
            request_id or "?", elapsed,
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
        timeout_seconds = min(
            params.get("timeout_seconds", DEFAULT_SYNC_TIMEOUT), MAX_SYNC_TIMEOUT
        )

        request_id = f"exec-{uuid.uuid4().hex[:8]}"

        if code and script_path:
            raise ValueError("Provide either 'code' or 'script_path', not both")
        if not code and not script_path:
            raise ValueError("Either 'code' or 'script_path' must be provided")

        if code is not None:
            if not ALLOW_INLINE_CODE:
                raise PermissionError(
                    "Inline code execution is disabled. Use script_path instead."
                )
            source_label = f"inline ({_truncate(code, LOG_CODE_PREVIEW_LEN)})"
        else:
            validated = self._validate_script_path(script_path)
            with open(validated, "r") as f:
                code = f.read()
            source_label = f"file ({script_path})"

        logger.info("python.execute [%s] starting: %s", request_id, source_label)

        namespace = self._make_namespace(args)
        result = self._run_code(
            code, namespace, timeout_seconds, request_id, cancel_event=None
        )

        _last_execution = {
            "request_id": request_id,
            "source": source_label,
            "status": "error" if result.get("error") else "ok",
            "duration_seconds": result.get("duration_seconds"),
            "error_summary": _truncate(result["error"], 200) if result.get("error") else None,
        }
        return result

    def _python_execute_async(self, params: dict) -> dict:
        code = params.get("code")
        script_path = params.get("script_path")
        args = params.get("args", {})
        timeout_seconds = min(
            params.get("timeout_seconds", DEFAULT_ASYNC_TIMEOUT), MAX_ASYNC_TIMEOUT
        )

        if code and script_path:
            raise ValueError("Provide either 'code' or 'script_path', not both")
        if not code and not script_path:
            raise ValueError("Either 'code' or 'script_path' must be provided")

        if code is not None:
            if not ALLOW_INLINE_CODE:
                raise PermissionError(
                    "Inline code execution is disabled. Use script_path instead."
                )
            source_label = f"inline ({_truncate(code, LOG_CODE_PREVIEW_LEN)})"
        else:
            validated = self._validate_script_path(script_path)
            with open(validated, "r") as f:
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
            self._jobs[job_id] = job

        bpy.app.timers.register(
            lambda: self._execute_job(job_id), first_interval=0.01
        )
        return job_id

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

        elapsed = (job["completed_at"] - job["started_at"]) if job["started_at"] else 0
        logger.info("Job [%s] %s in %.3fs", job_id, job["status"], elapsed)

        _last_execution = {
            "request_id": job_id,
            "source": f"async job",
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

    def start(self):
        if self._running:
            return
        _sync_runtime_settings()
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
        bpy.app.timers.register(self._drain_request_queue, first_interval=0.01)
        logger.info(f"Blender MCP Bridge listening on {self._host}:{self._port}")

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
                conn, addr = self._server_socket.accept()
                logger.info(f"MCP client connected from {addr}")
                client_thread = threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(None)
        buffer = b""
        try:
            while self._running:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                buffer += data
                # Messages are newline-delimited JSON
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        request = json.loads(line)
                        response = self._submit_request(request)
                    except json.JSONDecodeError as e:
                        response = {
                            "id": None,
                            "success": False,
                            "error": f"Invalid JSON: {e}",
                        }
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
        "material.create",
        "material.assign",
        "material.set_color",
        "material.set_texture",
    }

    def _submit_request(self, request: dict) -> dict:
        queued = {"request": request, "event": threading.Event(), "response": None}
        self._request_queue.put(queued)
        queued["event"].wait()
        return queued["response"]

    def _drain_request_queue(self):
        while True:
            try:
                queued = self._request_queue.get_nowait()
            except queue.Empty:
                break
            queued["response"] = self._process_request(queued["request"])
            queued["event"].set()
        return 0.01 if self._running else None

    @staticmethod
    def _maybe_push_undo(command: str):
        undo_push = bpy.ops.ed.undo_push
        poll = getattr(undo_push, "poll", None)
        if callable(poll) and not poll():
            logger.debug(f"Skipping undo push for {command}: context poll failed")
            return
        undo_push(message=f"MCP: {command}")

    def _process_request(self, request: dict) -> dict:
        req_id = request.get("id")
        command = request.get("command", "")
        params = request.get("params", {})
        try:
            # Auto-push undo before mutations
            if command in self.MUTATION_COMMANDS:
                self._maybe_push_undo(command)
            result = self._handler.handle(command, params)
            return {"id": req_id, "success": True, "result": result}
        except Exception as e:
            logger.error(f"Command '{command}' failed: {e}\n{traceback.format_exc()}")
            return {"id": req_id, "success": False, "error": str(e)}


# Global server instance
_server: BlenderMCPServer | None = None


class MCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    safe_mode: bpy.props.BoolProperty(
        name="Safe Mode",
        description="Restrict file access to project directory and enable tool whitelist",
        default=False,
    )
    port: bpy.props.IntProperty(
        name="Port",
        description="TCP port for the MCP bridge",
        default=9876,
        min=1024,
        max=65535,
    )
    allow_inline_code: bpy.props.BoolProperty(
        name="Allow Inline Code",
        description="Allow python.execute to run inline code strings. Disable to only allow script files",
        default=True,
    )
    approved_script_roots: bpy.props.StringProperty(
        name="Approved Script Roots",
        description="Semicolon-separated list of directories from which script files may be loaded",
        default="",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "safe_mode")
        layout.prop(self, "port")
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
    # Auto-start the server
    _sync_runtime_settings()
    global _server
    _server = BlenderMCPServer()
    _server.start()


def unregister():
    global _server
    if _server:
        _server.stop()
        _server = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
