"""Blender camera commands and their local helpers."""

import bpy

from .objects import get_object_of_type
from .placement import apply_placement


def create(params: dict) -> dict:
    name = params.get("name") or "Camera"
    cam_data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, cam_data)
    bpy.context.scene.collection.objects.link(obj)
    apply_camera_settings(cam_data, obj, params)
    return _camera_result(cam_data, obj)


def update(params: dict) -> dict:
    obj = get_object_of_type(params["name"], "CAMERA")
    cam_data = obj.data
    if cam_data is None:
        raise ValueError(f"Object '{params['name']}' has no camera data")
    apply_camera_settings(cam_data, obj, params)
    return _camera_result(cam_data, obj)


def apply_camera_settings(cam_data, obj, params: dict) -> None:
    projection = params.get("projection")
    if projection is not None:
        proj = projection.strip().upper()
        if proj not in {"PERSP", "ORTHO"}:
            raise ValueError(f"Unsupported camera projection '{projection}': use 'PERSP' or 'ORTHO'")
        cam_data.type = proj
    lens = params.get("lens")
    if lens is not None:
        if cam_data.type != "PERSP":
            raise ValueError("'lens' applies to PERSP cameras; use 'ortho_scale' for ORTHO")
        cam_data.lens = lens
    ortho_scale = params.get("ortho_scale")
    if ortho_scale is not None:
        if cam_data.type != "ORTHO":
            raise ValueError("'ortho_scale' applies to ORTHO cameras; use 'lens' for PERSP")
        cam_data.ortho_scale = ortho_scale
    clip_start = params.get("clip_start")
    clip_end = params.get("clip_end")
    if clip_start is not None:
        cam_data.clip_start = clip_start
    if clip_end is not None:
        cam_data.clip_end = clip_end
    if clip_start is not None and clip_end is not None and clip_start >= clip_end:
        raise ValueError("'clip_start' must be smaller than 'clip_end'")
    apply_placement(obj, params)
    if params.get("set_active"):
        bpy.context.scene.camera = obj


def _camera_result(cam_data, obj) -> dict:
    return {
        "name": obj.name,
        "type": obj.type,
        "location": list(obj.location),
        "projection": cam_data.type,
        "lens": cam_data.lens,
        "ortho_scale": cam_data.ortho_scale,
        "clip_start": cam_data.clip_start,
        "clip_end": cam_data.clip_end,
        "active": bpy.context.scene.camera is obj,
    }
