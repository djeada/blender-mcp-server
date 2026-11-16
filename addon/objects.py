"""Blender objects commands and their local helpers."""

import math

import bpy

from .geometry import build_primitive_pydata
from .protocol import MissingResourceError


def create_primitive_mesh_object(
    mesh_type: str,
    *,
    name: str | None = None,
    location: list[float] | tuple[float, float, float] | None = None,
    size: float = 2.0,
):
    obj_name = name or mesh_type.capitalize()
    verts, faces = build_primitive_pydata(mesh_type.lower(), size)
    mesh = bpy.data.meshes.new(f"{obj_name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(obj_name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    if location is not None:
        obj.location = tuple(location)
    return obj


def get_transform(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise MissingResourceError(f"Object '{name}' not found")
    return {
        "name": obj.name,
        "location": list(obj.location),
        "rotation_euler": list(obj.rotation_euler),
        "scale": list(obj.scale),
    }


def get_hierarchy(params: dict) -> dict:
    def build_tree(obj):
        return {
            "name": obj.name,
            "type": obj.type,
            "children": [build_tree(c) for c in obj.children],
        }

    name = params.get("name")
    if name:
        obj = bpy.data.objects.get(name)
        if not obj:
            raise MissingResourceError(f"Object '{name}' not found")
        subtree: dict = build_tree(obj)
        return subtree

    roots = [o for o in bpy.context.scene.objects if o.parent is None]
    return {"roots": [build_tree(r) for r in roots]}


def create_mesh(params: dict) -> dict:
    mesh_type = params.get("type", "cube").lower()
    name = params.get("name")
    location = params.get("location", [0, 0, 0])
    size = params.get("size", 2.0)
    obj = create_primitive_mesh_object(
        mesh_type,
        name=name,
        location=location,
        size=size,
    )
    return {"name": obj.name, "type": obj.type, "location": list(obj.location)}


def delete(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise MissingResourceError(f"Object '{name}' not found")
    bpy.data.objects.remove(obj, do_unlink=True)
    return {"deleted": name}


def translate(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise MissingResourceError(f"Object '{name}' not found")
    offset = params.get("offset", [0, 0, 0])
    absolute = params.get("location")
    if absolute is not None and "offset" in params:
        raise ValueError("Provide either 'location' or 'offset', not both")
    if absolute is not None:
        obj.location = absolute
    else:
        obj.location.x += offset[0]
        obj.location.y += offset[1]
        obj.location.z += offset[2]
    return {"name": obj.name, "location": list(obj.location)}


def rotate(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise MissingResourceError(f"Object '{name}' not found")
    rotation = params.get("rotation", [0, 0, 0])
    degrees = params.get("degrees", True)
    if degrees:
        rotation = [math.radians(r) for r in rotation]
    obj.rotation_euler = rotation
    return {"name": obj.name, "rotation_euler": list(obj.rotation_euler)}


def scale(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise MissingResourceError(f"Object '{name}' not found")
    scale = params.get("scale", [1, 1, 1])
    obj.scale = scale
    return {"name": obj.name, "scale": list(obj.scale)}


def duplicate(params: dict) -> dict:
    name = params["name"]
    obj = bpy.data.objects.get(name)
    if not obj:
        raise MissingResourceError(f"Object '{name}' not found")
    new_obj = obj.copy()
    if obj.data is not None:  # Empties carry no data block
        new_obj.data = obj.data.copy()
    new_name = params.get("new_name")
    if new_name:
        new_obj.name = new_name
    bpy.context.collection.objects.link(new_obj)
    return {
        "name": new_obj.name,
        "original": obj.name,
        "location": list(new_obj.location),
    }


def rename(params: dict) -> dict:
    obj = bpy.data.objects.get(params["name"])
    if not obj:
        raise MissingResourceError(f"Object '{params['name']}' not found")
    new_name = params["new_name"].strip()
    if not new_name:
        raise ValueError("Object name must not be empty")
    obj.name = new_name
    # Blender appends a .001 suffix when the name is taken; report the canonical name.
    return {"name": obj.name, "requested": new_name}


def parent(params: dict) -> dict:
    obj = bpy.data.objects.get(params["name"])
    if not obj:
        raise MissingResourceError(f"Object '{params['name']}' not found")
    parent_obj = bpy.data.objects.get(params["parent"])
    if not parent_obj:
        raise MissingResourceError(f"Object '{params['parent']}' not found")
    if parent_obj is obj:
        raise ValueError(f"Object '{obj.name}' cannot be parented to itself")
    ancestor = parent_obj
    seen: set[int] = set()
    while ancestor is not None and id(ancestor) not in seen:
        seen.add(id(ancestor))
        if ancestor is obj:
            raise ValueError(f"Parenting '{obj.name}' under '{parent_obj.name}' would create a cycle")
        ancestor = ancestor.parent

    keep_transform = bool(params.get("keep_transform"))
    world_transform = obj.matrix_world.copy() if keep_transform else None
    obj.parent = parent_obj
    if keep_transform:
        obj.matrix_parent_inverse = parent_obj.matrix_world.inverted()
        obj.matrix_world = world_transform
    return {
        "name": obj.name,
        "parent": parent_obj.name,
        "keep_transform": keep_transform,
    }


def unparent(params: dict) -> dict:
    obj = bpy.data.objects.get(params["name"])
    if not obj:
        raise MissingResourceError(f"Object '{params['name']}' not found")
    if obj.parent is None:
        raise ValueError(f"Object '{obj.name}' has no parent")
    keep_transform = bool(params.get("keep_transform"))
    world_transform = obj.matrix_world.copy() if keep_transform else None
    obj.parent = None
    if keep_transform:
        obj.matrix_world = world_transform
    return {"name": obj.name, "unparented": True, "keep_transform": keep_transform}


def get_object_of_type(name: str, expected_type: str):
    obj = bpy.data.objects.get(name)
    if not obj:
        raise MissingResourceError(f"Object '{name}' not found")
    if obj.type != expected_type:
        raise ValueError(f"Object '{name}' is of type {obj.type}, not {expected_type}")
    return obj


def history_undo(params: dict) -> dict:
    bpy.ops.ed.undo()
    return {"action": "undo"}


def history_redo(params: dict) -> dict:
    bpy.ops.ed.redo()
    return {"action": "redo"}
