"""Insert transform keyframes on objects at specified frames.

Args:
    keyframes (list[dict]): List of keyframe specs. Each dict:
        - object (str): Object name (required)
        - frame (int): Frame number (required)
        - location (list[float]|None): [x, y, z] location to set
        - rotation (list[float]|None): [rx, ry, rz] Euler rotation in radians
        - scale (list[float]|None): [sx, sy, sz] scale

Result:
    inserted (int): Number of keyframes inserted
    objects (list[str]): Unique object names that received keyframes
    skipped (list[str]): Objects not found
"""
import bpy

keyframes = args.get("keyframes", [])
inserted = 0
objects_set = set()
skipped = set()

for kf in keyframes:
    obj_name = kf.get("object")
    frame = kf.get("frame")
    if not obj_name or frame is None:
        continue

    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        skipped.add(obj_name)
        continue

    loc = kf.get("location")
    if loc is not None:
        obj.location = tuple(loc)
        obj.keyframe_insert(data_path="location", frame=frame)
        inserted += 1

    rot = kf.get("rotation")
    if rot is not None:
        obj.rotation_euler = tuple(rot)
        obj.keyframe_insert(data_path="rotation_euler", frame=frame)
        inserted += 1

    scl = kf.get("scale")
    if scl is not None:
        obj.scale = tuple(scl)
        obj.keyframe_insert(data_path="scale", frame=frame)
        inserted += 1

    objects_set.add(obj_name)

__result__ = {
    "inserted": inserted,
    "objects": sorted(objects_set),
    "skipped": sorted(skipped),
}
