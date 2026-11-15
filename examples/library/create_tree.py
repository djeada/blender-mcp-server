"""Create a seeded low-poly tree as one mesh with bark and leaf material slots.

Run with blender_python_exec and script_path pointing to this file.

Args:
    name (str): Object name. Default: Tree
    location (list[float]): Trunk base [x, y, z]. Default: [0, 0, 0]
    height (float): Trunk height; the canopy extends above it. Default: 3.0
    seed (int): Optional random seed for canopy placement.
    trunk_material (str): Existing material name, or use/create TreeBark.
    leaves_material (str): Existing material name, or use/create TreeLeaves.

Result:
    name, location, height, vertices, faces, and materials of the created tree.

Uses Blender's data API and bmesh, so it also works with transport="headless"
and does not depend on the add-on's private geometry helpers.
"""

import math
import random

import bmesh
import bpy
from mathutils import Matrix


def material(existing_name, default_name, color, roughness):
    name = existing_name or default_name
    mat = bpy.data.materials.get(name)
    if mat is not None:
        return mat
    if existing_name:
        raise ValueError(f"Material '{existing_name}' not found")
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def create_tree(params):
    height = float(params.get("height", 3.0))
    if not math.isfinite(height) or height <= 0:
        raise ValueError("'height' must be a positive finite number")
    location = tuple(params.get("location", [0, 0, 0]))
    if len(location) != 3 or not all(math.isfinite(value) for value in location):
        raise ValueError("'location' must contain three finite numbers")
    name = params.get("name") or "Tree"
    trunk = material(params.get("trunk_material"), "TreeBark", (0.08, 0.05, 0.035), 0.9)
    leaves = material(params.get("leaves_material"), "TreeLeaves", (0.03, 0.18, 0.06), 0.7)

    rng = random.Random(params.get("seed"))
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    bm = bmesh.new()
    try:
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            segments=12,
            radius1=max(height * 0.055, 0.03),
            radius2=0.0,
            depth=height,
            matrix=Matrix.Translation((0, 0, height / 2)),
        )
        for blob in range(3):
            if blob == 0:
                center = (0, 0, height * 0.95)
                radius = height * 0.34
            else:
                angle = rng.uniform(0, math.tau)
                distance = rng.uniform(0.15, 0.3) * height
                center = (math.cos(angle) * distance, math.sin(angle) * distance, height * rng.uniform(0.78, 0.9))
                radius = height * rng.uniform(0.24, 0.3)
            canopy = bmesh.ops.create_uvsphere(
                bm,
                u_segments=16,
                v_segments=10,
                radius=radius,
                matrix=Matrix.Translation(center) @ Matrix.Diagonal((1, 1, 0.8, 1)),
            )
            for vert in canopy["verts"]:
                for face in vert.link_faces:
                    face.material_index = 1
                    face.smooth = True
        bm.to_mesh(mesh)
    finally:
        bm.free()
    mesh.materials.append(trunk)
    mesh.materials.append(leaves)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return {
        "name": obj.name,
        "location": list(obj.location),
        "height": height,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.polygons),
        "materials": [trunk.name, leaves.name],
    }


__result__ = create_tree(globals().get("args", {}))
