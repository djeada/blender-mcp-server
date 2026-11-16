"""Non-destructive editing of a bounded set of Blender modifier properties."""

import math
from typing import Any

import bpy

from .protocol import MissingResourceError, UnsupportedError

# (kind, minimum, maximum). These limits apply in addition to Blender's RNA limits.
PROPERTIES: dict[str, dict[str, tuple[type, Any, Any]]] = {
    "BEVEL": {
        "width": (float, 0, 1000),
        "segments": (int, 1, 32),
        "profile": (float, 0, 1),
    },
    "SUBSURF": {
        "levels": (int, 0, 4),
        "render_levels": (int, 0, 6),
        "show_only_control_edges": (bool, None, None),
    },
    "MIRROR": {
        "use_axis": (list, None, None),
        "use_clip": (bool, None, None),
        "use_mirror_merge": (bool, None, None),
        "merge_threshold": (float, 0, 1),
    },
    "SOLIDIFY": {
        "thickness": (float, -1000, 1000),
        "offset": (float, -1, 1),
        "use_even_offset": (bool, None, None),
        "use_rim": (bool, None, None),
    },
}


def _object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise MissingResourceError("Object not found")
    return obj


def _modifier(obj, name):
    modifier = obj.modifiers.get(name)
    if modifier is None:
        raise MissingResourceError("Modifier not found")
    return modifier


def _format_modifier(modifier) -> dict:
    properties = {}
    for name in PROPERTIES.get(modifier.type, {}):
        if hasattr(modifier, name):
            value = getattr(modifier, name)
            properties[name] = list(value) if name == "use_axis" else value
    return {"name": modifier.name, "type": modifier.type, "properties": properties}


def _validate(kind: str, properties: dict):
    allowed = PROPERTIES.get(kind)
    if allowed is None:
        raise UnsupportedError("Modifier type is outside the supported edit allowlist")
    # Blender exposes the derived types under stable API names.
    type_name = {
        "BEVEL": "BevelModifier",
        "SUBSURF": "SubsurfModifier",
        "MIRROR": "MirrorModifier",
        "SOLIDIFY": "SolidifyModifier",
    }[kind]
    modifier_class = getattr(bpy.types, type_name, None)
    if modifier_class is None:
        raise UnsupportedError("This Blender build does not provide the modifier type")
    rna = modifier_class.bl_rna
    for name, value in properties.items():
        if name not in allowed:
            raise ValueError("Unknown or forbidden modifier property")
        prop = rna.properties.get(name)
        if prop is None or prop.is_readonly:
            raise UnsupportedError(f"Modifier property '{name}' is unavailable on this Blender version")
        expected, low, high = allowed[name]
        if expected is list:
            valid = isinstance(value, list) and len(value) == 3 and all(type(item) is bool for item in value)
        elif expected is bool:
            valid = type(value) is bool
        elif expected is int:
            valid = type(value) is int and max(low, prop.hard_min) <= value <= min(high, prop.hard_max)
        else:
            valid = (
                type(value) in {int, float}
                and max(low, prop.hard_min) <= value <= min(high, prop.hard_max)
                and math.isfinite(value)
            )
        if not valid:
            raise ValueError(f"Invalid value for modifier property '{name}'")


def _require_mesh(obj):
    if obj.type != "MESH" or obj.library is not None:
        raise UnsupportedError("Modifier editing requires a local mesh object")


def list_modifiers(params: dict) -> dict:
    obj = _object(params["name"])
    return {"object": obj.name, "modifiers": [_format_modifier(modifier) for modifier in obj.modifiers]}


def add(params: dict) -> dict:
    obj = _object(params["name"])
    _require_mesh(obj)
    kind = params["modifier_type"].upper()
    name = params.get("modifier_name", kind.title())
    if not name.strip() or "\0" in name or len(name.encode("utf-8")) > 63:
        raise ValueError("Modifier name must contain 1–63 UTF-8 bytes")
    properties = params["properties"]
    _validate(kind, properties)
    if obj.modifiers.get(name) is not None:
        raise ValueError("A modifier with this name already exists")
    modifier = obj.modifiers.new(name=name, type=kind)
    try:
        for key, value in properties.items():
            setattr(modifier, key, value)
    except Exception:
        obj.modifiers.remove(modifier)
        raise
    return {"object": obj.name, "modifier": _format_modifier(modifier)}


def update(params: dict) -> dict:
    obj = _object(params["name"])
    _require_mesh(obj)
    modifier = _modifier(obj, params["modifier_name"])
    properties = params["properties"]
    _validate(modifier.type, properties)
    previous = _format_modifier(modifier)["properties"]
    applied = []
    try:
        for key, value in properties.items():
            setattr(modifier, key, value)
            applied.append(key)
    except Exception:
        for key in reversed(applied):
            setattr(modifier, key, previous[key])
        raise
    return {"object": obj.name, "modifier": _format_modifier(modifier)}


def remove(params: dict) -> dict:
    obj = _object(params["name"])
    _require_mesh(obj)
    modifier = _modifier(obj, params["modifier_name"])
    if modifier.type not in PROPERTIES:
        raise UnsupportedError("Modifier type is outside the supported edit allowlist")
    removed = _format_modifier(modifier)
    obj.modifiers.remove(modifier)
    return {"object": obj.name, "removed": removed}
