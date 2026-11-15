"""Blender materials commands and their local helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from .policy import resolve_path
from .protocol import MissingResourceError, UnsupportedError

if TYPE_CHECKING:
    from .paths import PathPolicy


def list_materials(params: dict) -> dict:
    materials = []
    for mat in bpy.data.materials:
        materials.append(
            {
                "name": mat.name,
                "use_nodes": mat.use_nodes,
                "user_count": mat.users,
            }
        )
    return {"materials": materials}


def create(params: dict) -> dict:
    name = params.get("name", "Material")
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    color = params.get("color")
    if color:
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            # color is [r, g, b] or [r, g, b, a], values 0-1
            rgba = list(color) + [1.0] * (4 - len(color))
            bsdf.inputs["Base Color"].default_value = rgba[:4]
    return {"name": mat.name, "use_nodes": mat.use_nodes}


def assign(params: dict) -> dict:
    obj_name = params["object"]
    mat_name = params["material"]
    obj = bpy.data.objects.get(obj_name)
    if not obj:
        raise MissingResourceError("Object not found")
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        raise MissingResourceError("Material not found")
    materials = getattr(obj.data, "materials", None)
    if materials is None:
        raise ValueError(f"Object '{obj_name}' is of type {obj.type}, which cannot have materials")
    if materials:
        materials[0] = mat
    else:
        materials.append(mat)
    return {"object": obj.name, "material": mat.name}


def set_color(params: dict) -> dict:
    mat_name = params["name"]
    color = params["color"]  # [r, g, b] or [r, g, b, a]
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        raise MissingResourceError("Material not found")
    if not mat.use_nodes:
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if not bsdf:
        raise UnsupportedError("Material has no Principled BSDF node")
    rgba = list(color) + [1.0] * (4 - len(color))
    bsdf.inputs["Base Color"].default_value = rgba[:4]
    return {"name": mat.name, "color": rgba[:4]}


def set_texture(params: dict, *, policy: PathPolicy) -> dict:
    mat_name = params["name"]
    filepath = policy.validate_filepath(resolve_path(params["filepath"], str(bpy.data.filepath)))
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        raise MissingResourceError("Material not found")
    if not mat.use_nodes:
        mat.use_nodes = True
    tree = mat.node_tree
    bsdf = tree.nodes.get("Principled BSDF")
    if not bsdf:
        raise UnsupportedError("Material has no Principled BSDF node")
    # Load first: a missing or unreadable file must not leave a dangling node behind.
    try:
        image = bpy.data.images.load(filepath, check_existing=True)
    except RuntimeError as exc:
        raise FileNotFoundError("Cannot read texture file") from exc
    base_color = bsdf.inputs["Base Color"]
    tex_node = next(
        (link.from_node for link in base_color.links if link.from_node.bl_idname == "ShaderNodeTexImage"),
        None,
    )
    if tex_node is None:
        tex_node = tree.nodes.new("ShaderNodeTexImage")
        tree.links.new(tex_node.outputs["Color"], base_color)
    tex_node.image = image
    return {"name": mat.name, "texture": filepath}
