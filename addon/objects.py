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
    name = params.get("name")
    obj = None
    if name:
        obj = bpy.data.objects.get(name)
        if not obj:
            raise MissingResourceError(f"Object '{name}' not found")

    if any(params.get(key) is not None for key in ("max_nodes", "max_depth", "offset")):
        return _bounded_hierarchy(obj, params)

    def build_tree(obj):
        return {
            "name": obj.name,
            "type": obj.type,
            "children": [build_tree(c) for c in obj.children],
        }

    if obj is not None:
        subtree: dict = build_tree(obj)
        return subtree

    roots = [o for o in bpy.context.scene.objects if o.parent is None]
    return {"roots": [build_tree(r) for r in roots]}


def _bounded_hierarchy(obj, params: dict) -> dict:
    """Name-ordered tree limited by node count and depth.

    `offset` pages through the top level: the roots, or the named object's children. A node
    with `children_omitted` continues by requesting it by name.
    """
    budget = params.get("max_nodes")
    max_depth = params.get("max_depth")
    offset = params.get("offset") or 0
    used = 0

    def ordered(objects):
        return sorted(objects, key=lambda item: item.name)

    def full():
        return budget is not None and used >= budget

    def build(node, depth):
        nonlocal used
        used += 1
        entry = {"name": node.name, "type": node.type, "children": []}
        children = ordered(node.children)
        if max_depth is None or depth < max_depth:
            for child in children:
                if full():
                    break
                entry["children"].append(build(child, depth + 1))
        if omitted := len(children) - len(entry["children"]):
            entry["children_omitted"] = omitted
        return entry

    top = ordered(obj.children if obj is not None else [o for o in bpy.context.scene.objects if o.parent is None])
    if obj is not None:
        used = 1  # the named object itself
    built = []
    for node in top[offset:]:
        if full() or (obj is not None and max_depth == 0):
            break
        built.append(build(node, 1 if obj is not None else 0))
    end = offset + len(built)
    metadata = {
        "total": len(top),
        "count": len(built),
        "offset": offset,
        "next_offset": end if end < len(top) and (obj is None or max_depth != 0) else None,
    }
    if obj is None:
        return {"roots": built, **metadata}
    result = {"name": obj.name, "type": obj.type, "children": built, **metadata}
    if omitted := len(top) - len(built):
        result["children_omitted"] = omitted
    return result


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
