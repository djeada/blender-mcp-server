"""Blender animation commands and their local helpers."""

import math

import bpy

KEYFRAME_DATA_PATHS = {
    "location": "location",
    "rotation": "rotation_euler",
    "scale": "scale",
}


KEYFRAME_INTERPOLATIONS = {"BEZIER", "LINEAR", "CONSTANT"}


def timeline_get(params: dict) -> dict:
    scene = bpy.context.scene
    return {
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
    }


def timeline_set(params: dict) -> dict:
    scene = bpy.context.scene
    frame_start = params.get("frame_start")
    frame_end = params.get("frame_end")
    if frame_start is not None:
        scene.frame_start = frame_start
    if frame_end is not None:
        scene.frame_end = frame_end
    if scene.frame_start > scene.frame_end:
        raise ValueError(f"'frame_start' ({scene.frame_start}) must not exceed 'frame_end' ({scene.frame_end})")
    frame_current = params.get("frame_current")
    if frame_current is not None:
        scene.frame_set(frame_current)
    return {
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
    }


def keyframe_data_path(property_name: str) -> str:
    data_path = KEYFRAME_DATA_PATHS.get(property_name)
    if data_path is None:
        raise ValueError(
            f"Unsupported animatable property '{property_name}': use {', '.join(sorted(KEYFRAME_DATA_PATHS))}"
        )
    return data_path


def keyframe_interpolation(value: str) -> str:
    interp = value.strip().upper()
    if interp not in KEYFRAME_INTERPOLATIONS:
        raise ValueError(f"Unsupported interpolation '{value}': use {', '.join(sorted(KEYFRAME_INTERPOLATIONS))}")
    return interp


def action_fcurves(obj):
    """fcurve collection for an object's action, across Blender versions.

    Blender 4.4+ stores fcurves in slotted actions (layers > strips > channelbag);
    older releases expose them directly on the action.
    """
    anim = getattr(obj, "animation_data", None)
    action = getattr(anim, "action", None) if anim is not None else None
    if action is None:
        return None
    fcurves = getattr(action, "fcurves", None)
    if fcurves is not None:
        try:
            iter(fcurves)
            return fcurves
        except TypeError:
            pass
    slot = getattr(anim, "action_slot", None)
    for layer in getattr(action, "layers", []) or []:
        for strip in getattr(layer, "strips", []) or []:
            getter = getattr(strip, "channelbag", None)
            if callable(getter) and slot is not None:
                bag = getter(slot)
                if bag is not None:
                    return getattr(bag, "fcurves", None)
    return None


def fcurves_for_path(obj, data_path: str) -> list:
    fcurves = action_fcurves(obj)
    if fcurves is None:
        return []
    return [fc for fc in fcurves if getattr(fc, "data_path", None) == data_path]


def count_keys(fcurves: list) -> int:
    return sum(len(fc.keyframe_points) for fc in fcurves)


def keyframe_insert(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise ValueError(f"Object '{name}' not found")
    property_name = params["property"]
    data_path = keyframe_data_path(property_name)
    frame = params["frame"]

    value = params.get("value")
    if value is not None:
        if property_name == "rotation":
            # Rotation values are degrees, matching blender_object_rotate.
            setattr(obj, data_path, [math.radians(v) for v in value])
        else:
            setattr(obj, data_path, value)

    anim = obj.animation_data_create()
    before = count_keys(fcurves_for_path(obj, data_path))
    if not obj.keyframe_insert(data_path=data_path, frame=frame):
        raise ValueError(f"Keyframe insertion failed for '{property_name}' on '{obj.name}' at frame {frame}")
    fcurves = fcurves_for_path(obj, data_path)
    after = count_keys(fcurves)

    interpolation = params.get("interpolation")
    if interpolation is not None:
        interp = keyframe_interpolation(interpolation)
        for fc in fcurves:
            for key in fc.keyframe_points:
                if abs(key.co[0] - frame) < 0.5:
                    key.interpolation = interp

    action = getattr(anim, "action", None)
    return {
        "name": obj.name,
        "property": property_name,
        "frame": frame,
        "action": getattr(action, "name", None),
        "keyframe_count": after,
        "result": "overwritten" if after == before else "inserted",
    }


def keyframe_list(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise ValueError(f"Object '{name}' not found")
    property_name = params.get("property")
    anim = getattr(obj, "animation_data", None)
    if anim is None or getattr(anim, "action", None) is None:
        raise ValueError(f"Object '{name}' has no animation data")
    fcurves = fcurves_for_path(obj, keyframe_data_path(property_name or ""))
    keys = []
    for fc in fcurves:
        for key in fc.keyframe_points:
            keys.append({"channel": getattr(fc, "array_index", 0), "frame": key.co[0], "value": key.co[1]})
    keys.sort(key=lambda k: (k["channel"], k["frame"]))
    return {"name": obj.name, "property": property_name, "keys": keys, "keyframe_count": len(keys)}


def keyframe_remove(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise ValueError(f"Object '{name}' not found")
    property_name = params["property"]
    data_path = keyframe_data_path(property_name)
    frame = params["frame"]
    anim = getattr(obj, "animation_data", None)
    if anim is None or getattr(anim, "action", None) is None:
        raise ValueError(f"Object '{name}' has no animation data")
    before = count_keys(fcurves_for_path(obj, data_path))
    if not obj.keyframe_delete(data_path=data_path, frame=frame):
        raise ValueError(f"No keyframe for '{property_name}' on '{obj.name}' at frame {frame}")
    after = count_keys(fcurves_for_path(obj, data_path))
    return {
        "name": obj.name,
        "property": property_name,
        "frame": frame,
        "removed": before - after,
        "keyframe_count": after,
    }
