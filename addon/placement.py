"""Blender placement commands and their local helpers."""

import math


def look_at_rotation(location, target):
    """Euler angles (radians) that point -Z at `target` from `location`."""
    import mathutils

    direction = mathutils.Vector(target) - mathutils.Vector(location)
    if direction.length == 0:
        raise ValueError("'look_at' target must differ from the object location")
    return direction.to_track_quat("-Z", "Y").to_euler()


def apply_placement(obj, params: dict) -> None:
    """Apply location/orientation parameters shared by camera and light objects."""
    location = params.get("location")
    if location is not None:
        obj.location = location
    rotation = params.get("rotation")
    look_at = params.get("look_at")
    if rotation is not None and look_at is not None:
        raise ValueError("Provide either 'rotation' or 'look_at', not both")
    if look_at is not None:
        obj.rotation_euler = look_at_rotation(obj.location, look_at)
    elif rotation is not None:
        obj.rotation_euler = [math.radians(r) for r in rotation]
