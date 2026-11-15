"""Scatter linked duplicates of an object uniformly across a disk.

Args:
    source (str): Required source object name.
    count (int): Number of copies, from 1 to 500. Default: 10
    location (list[float]): Disk center [x, y, z]. Default: [0, 0, 0]
    radius (float): Positive disk radius. Default: 5.0
    scale_min, scale_max (float): Positive uniform scale multipliers. Default: 1.0
    rotation_z_min, rotation_z_max (float): Z rotation bounds in degrees. Defaults: 0, 360
    name_prefix (str): Copy name prefix. Default: <source>_scatter
    seed (int): Optional random seed.

Result:
    source, count, names, location, and radius. Copies share the source's mesh.
"""

import math
import random

import bpy


def scatter_objects(params):
    source_name = params["source"]
    source = bpy.data.objects.get(source_name)
    if source is None:
        raise ValueError(f"Object '{source_name}' not found")
    count = params.get("count", 10)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 500:
        raise ValueError("'count' must be an integer from 1 to 500")
    scale_min = params.get("scale_min", 1.0)
    scale_max = params.get("scale_max", 1.0)
    radius = params.get("radius", 5.0)
    for key, value in (("scale_min", scale_min), ("scale_max", scale_max), ("radius", radius)):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"'{key}' must be a positive finite number")
    if scale_max < scale_min:
        raise ValueError("'scale_max' must be greater than or equal to 'scale_min'")
    location = params.get("location", [0, 0, 0])
    if len(location) != 3 or not all(math.isfinite(value) for value in location):
        raise ValueError("'location' must contain three finite numbers")
    rotation_z_min = params.get("rotation_z_min", 0.0)
    rotation_z_max = params.get("rotation_z_max", 360.0)
    if not all(math.isfinite(value) for value in (rotation_z_min, rotation_z_max)):
        raise ValueError("Rotation bounds must be finite numbers")
    name_prefix = params.get("name_prefix") or f"{source.name}_scatter"

    rng = random.Random(params.get("seed"))
    created = []
    for index in range(count):
        distance = radius * math.sqrt(rng.random())
        angle = rng.uniform(0.0, math.tau)
        duplicate = source.copy()
        duplicate.name = f"{name_prefix}_{index:03d}"
        bpy.context.scene.collection.objects.link(duplicate)
        duplicate.location = (
            location[0] + math.cos(angle) * distance,
            location[1] + math.sin(angle) * distance,
            location[2],
        )
        duplicate.rotation_euler = (
            source.rotation_euler[0],
            source.rotation_euler[1],
            math.radians(rng.uniform(rotation_z_min, rotation_z_max)),
        )
        scale = rng.uniform(scale_min, scale_max)
        duplicate.scale = tuple(value * scale for value in source.scale)
        created.append(duplicate.name)
    return {"source": source.name, "count": len(created), "names": created, "location": location, "radius": radius}


__result__ = scatter_objects(args)
