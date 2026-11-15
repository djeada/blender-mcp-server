"""Blender rendering and export commands shared by both transports."""

from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

from .protocol import BridgeError, UnsupportedError

if TYPE_CHECKING:
    from .paths import PathPolicy

RENDER_ENGINE_ALIASES: dict[str, tuple[str, ...]] = {
    "EEVEE": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"),
    "EEVEE_NEXT": ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"),
    "BLENDER_EEVEE": ("BLENDER_EEVEE_NEXT",),
    "BLENDER_EEVEE_NEXT": ("BLENDER_EEVEE",),
    "WORKBENCH": ("BLENDER_WORKBENCH",),
}


def _set_render_engine(scene, engine: str) -> None:
    requested = engine.strip().upper().replace(" ", "_")
    for candidate in (requested, *RENDER_ENGINE_ALIASES.get(requested, ())):
        try:
            scene.render.engine = candidate
            return
        except TypeError:
            continue
    raise UnsupportedError("Unknown render engine on this Blender version")


@contextmanager
def _checked_outputs(filepath: str, policy: PathPolicy):
    """Stage generated files so companion files and frame suffixes get checked too."""
    if not policy.restricts_outputs:
        yield filepath
        return
    folder = Path(os.path.dirname(filepath))
    with tempfile.TemporaryDirectory(prefix=".mcp-output-", dir=folder) as directory:
        staging = Path(directory)
        path = str(staging / os.path.basename(filepath))
        yield path + os.sep if filepath.endswith(os.sep) else path
        outputs = []
        for source in staging.rglob("*"):
            if source.is_symlink():
                raise PermissionError("Blender produced an unexpected symlink")
            if source.is_file():
                target = folder / source.relative_to(staging)
                policy.validate_filepath(str(target))
                outputs.append((source, target))
        for source, target in outputs:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)


def _check_pixels(scene, width: int, height: int, policy: PathPolicy) -> None:
    percentage = int(scene.render.resolution_percentage)
    pixels = max(1, width * percentage // 100) * max(1, height * percentage // 100)
    if pixels > policy.settings.policy.max_render_pixels:
        raise ValueError("Render exceeds the configured pixel limit")


def _render(scene, filepath: str, policy: PathPolicy, *, animation=False) -> str:
    with _checked_outputs(filepath, policy) as destination:
        scene.render.filepath = destination
        use_compositing = scene.render.use_compositing
        try:
            if policy.restricts_outputs:
                # File Output nodes may write to arbitrary destinations outside the staging directory.
                scene.render.use_compositing = False
            if animation:
                result = bpy.ops.render.render(animation=True)
            else:
                result = bpy.ops.render.render(write_still=True)
            if "CANCELLED" in result:
                raise BridgeError("command_failed", "Blender cancelled the render")
            actual = scene.render.frame_path() if scene.render.use_file_extension and not animation else destination
        finally:
            scene.render.filepath = filepath
            scene.render.use_compositing = use_compositing
    if isinstance(actual, str) and actual != destination and os.path.isfile(actual):
        return actual
    if policy.restricts_outputs and isinstance(actual, str) and actual != destination:
        candidate = os.path.join(os.path.dirname(filepath), os.path.basename(actual))
        if os.path.isfile(candidate):
            return candidate
    if not animation and not os.path.isfile(filepath):
        candidate = filepath + str(scene.render.file_extension)
        if os.path.isfile(candidate):
            return candidate
    return filepath


def render_still(params: dict, *, policy: PathPolicy) -> dict:
    scene = bpy.context.scene
    width = params.get("resolution_x", scene.render.resolution_x)
    height = params.get("resolution_y", scene.render.resolution_y)
    _check_pixels(scene, width, height, policy)
    filepath = policy.prepare_output_path(params.get("output_path", "//render.png"))
    if params.get("engine"):
        _set_render_engine(scene, params["engine"])
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    return {
        "output_path": _render(scene, filepath, policy),
        "engine": scene.render.engine,
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
    }


def render_animation(params: dict, *, policy: PathPolicy) -> dict:
    scene = bpy.context.scene
    start = params.get("frame_start", scene.frame_start)
    end = params.get("frame_end", scene.frame_end)
    if end < start or end - start + 1 > policy.settings.policy.max_render_frames:
        raise ValueError("Animation frame range is invalid or exceeds the configured frame limit")
    _check_pixels(scene, scene.render.resolution_x, scene.render.resolution_y, policy)
    filepath = policy.prepare_output_path(params.get("output_path", "//render_"))
    if params.get("engine"):
        _set_render_engine(scene, params["engine"])
    scene.frame_start = start
    scene.frame_end = end
    return {
        "output_path": _render(scene, filepath, policy, animation=True),
        "frame_range": [scene.frame_start, scene.frame_end],
        "engine": scene.render.engine,
    }


def _export(params: dict, policy: PathPolicy, extensions: tuple[str, ...], operator, name: str, **options) -> dict:
    filepath = policy.prepare_output_path(params["filepath"], extensions)
    # Blender can expose an operator proxy even when the exporter is unavailable.
    try:
        operator.get_rna_type()
    except (AttributeError, KeyError) as exc:
        raise UnsupportedError(f"{name} exporter is unavailable in this Blender installation") from exc
    with _checked_outputs(filepath, policy) as destination:
        if "CANCELLED" in operator(filepath=destination, **options):
            raise BridgeError("command_failed", f"Blender cancelled the {name} export")
    return {"filepath": filepath, "format": name}


def export_gltf(params: dict, *, policy: PathPolicy) -> dict:
    operator = bpy.ops.export_scene.gltf
    separate = params["filepath"].lower().endswith(".gltf")
    return _export(
        params, policy, (".glb", ".gltf"), operator, "glTF", export_format="GLTF_SEPARATE" if separate else "GLB"
    )


def export_obj(params: dict, *, policy: PathPolicy) -> dict:
    return _export(params, policy, (".obj",), bpy.ops.wm.obj_export, "OBJ")


def export_fbx(params: dict, *, policy: PathPolicy) -> dict:
    return _export(params, policy, (".fbx",), bpy.ops.export_scene.fbx, "FBX")
