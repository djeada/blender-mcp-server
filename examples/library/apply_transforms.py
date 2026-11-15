"""Apply location, rotation, and/or scale transforms to objects.

Args:
    objects (list[str]): Object names to apply transforms to.
    location (bool): Apply location. Default: True
    rotation (bool): Apply rotation. Default: True
    scale (bool): Apply scale. Default: True

Result:
    applied (list[str]): Objects that had transforms applied
    skipped (list[str]): Objects not found
"""

import bpy

obj_names = args.get("objects", [])
apply_location = args.get("location", True)
apply_rotation = args.get("rotation", True)
apply_scale = args.get("scale", True)

applied = []
skipped = []

# Deselect all first
bpy.ops.object.select_all(action="DESELECT")

for name in obj_names:
    obj = bpy.data.objects.get(name)
    if obj is None:
        skipped.append(name)
        continue

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.transform_apply(
        location=apply_location,
        rotation=apply_rotation,
        scale=apply_scale,
    )
    obj.select_set(False)
    applied.append(name)

__result__ = {
    "applied": applied,
    "skipped": skipped,
}
