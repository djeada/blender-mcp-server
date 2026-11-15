"""Blender rendering commands and their local helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

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


def render_still(params: dict, *, policy: PathPolicy) -> dict:
    scene = bpy.context.scene
    abs_path = policy.prepare_output_path(params.get("output_path", "//render.png"))
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


def render_animation(params: dict, *, policy: PathPolicy) -> dict:
    scene = bpy.context.scene
    abs_path = policy.prepare_output_path(params.get("output_path", "//render_"))
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


def export_gltf(params: dict, *, policy: PathPolicy) -> dict:
    filepath = policy.prepare_output_path(params["filepath"], extensions=(".glb", ".gltf"))
    bpy.ops.export_scene.gltf(filepath=filepath)
    return {"filepath": filepath, "format": "glTF"}


def export_obj(params: dict, *, policy: PathPolicy) -> dict:
    filepath = policy.prepare_output_path(params["filepath"], extensions=(".obj",))
    bpy.ops.wm.obj_export(filepath=filepath)
    return {"filepath": filepath, "format": "OBJ"}


def export_fbx(params: dict, *, policy: PathPolicy) -> dict:
    filepath = policy.prepare_output_path(params["filepath"], extensions=(".fbx",))
    bpy.ops.export_scene.fbx(filepath=filepath)
    return {"filepath": filepath, "format": "FBX"}
