"""Blender lighting commands and their local helpers."""

import math

import bpy

from .objects import get_object_of_type
from .placement import apply_placement

LIGHT_TYPES = ("POINT", "SUN", "SPOT", "AREA")


def create(params: dict) -> dict:
    light_type = params.get("type", "POINT").strip().upper()
    if light_type not in LIGHT_TYPES:
        raise ValueError(f"Unsupported light type '{params.get('type')}': use {', '.join(LIGHT_TYPES)}")
    name = params.get("name") or f"{light_type.capitalize()}Light"
    light_data = bpy.data.lights.new(name, type=light_type)
    obj = bpy.data.objects.new(name, light_data)
    bpy.context.scene.collection.objects.link(obj)
    apply_light_settings(light_data, obj, params)
    return result(light_data, obj)


def update(params: dict) -> dict:
    obj = get_object_of_type(params["name"], "LIGHT")
    light_data = obj.data
    if light_data is None:
        raise ValueError(f"Object '{params['name']}' has no light data")
    new_type = params.get("type")
    if new_type is not None:
        light_type = new_type.strip().upper()
        if light_type not in LIGHT_TYPES:
            raise ValueError(f"Unsupported light type '{new_type}': use {', '.join(LIGHT_TYPES)}")
        light_data.type = light_type
    apply_light_settings(light_data, obj, params)
    return result(light_data, obj)


def result(light_data, obj) -> dict:
    return {
        "name": obj.name,
        "type": obj.type,
        "light_type": light_data.type,
        "location": list(obj.location),
        "energy": light_data.energy,
        "color": list(light_data.color),
    }


def apply_light_settings(light_data, obj, params: dict) -> None:
    light_type = light_data.type
    energy = params.get("energy")
    if energy is not None:
        light_data.energy = energy
    color = params.get("color")
    if color is not None:
        if any(component < 0 or component > 1 for component in color):
            raise ValueError("Light 'color' components must be between 0 and 1")
        light_data.color = color[:3]
    size = params.get("size")
    if size is not None:
        if light_type == "SUN":
            raise ValueError("'size' does not apply to SUN lights; use 'angle'")
        if light_type in {"POINT", "SPOT"}:
            light_data.shadow_soft_size = size
        else:  # AREA
            light_data.size = size
    size_y = params.get("size_y")
    if size_y is not None:
        if light_type != "AREA":
            raise ValueError(f"'size_y' applies to AREA lights, not {light_type}")
        light_data.shape = "RECTANGLE"
        light_data.size_y = size_y
    angle = params.get("angle")
    if angle is not None:
        if light_type != "SUN":
            raise ValueError(f"'angle' applies to SUN lights, not {light_type}")
        light_data.angle = math.radians(angle)
    spot_angle = params.get("spot_angle")
    if spot_angle is not None:
        if light_type != "SPOT":
            raise ValueError(f"'spot_angle' applies to SPOT lights, not {light_type}")
        light_data.spot_size = math.radians(spot_angle)
    spot_blend = params.get("spot_blend")
    if spot_blend is not None:
        if light_type != "SPOT":
            raise ValueError(f"'spot_blend' applies to SPOT lights, not {light_type}")
        if not 0 <= spot_blend <= 1:
            raise ValueError("'spot_blend' must be between 0 and 1")
        light_data.spot_blend = spot_blend
    apply_placement(obj, params)
