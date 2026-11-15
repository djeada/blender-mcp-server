"""Blender collections commands and their local helpers."""

import bpy

from .protocol import MissingResourceError


def create(params: dict) -> dict:
    name = params["name"].strip()
    if not name:
        raise ValueError("Collection name must not be empty")
    if bpy.data.collections.get(name):
        raise ValueError(f"Collection '{name}' already exists")
    coll = bpy.data.collections.new(name)
    parent_name = params.get("parent")
    if parent_name:
        parent_coll = bpy.data.collections.get(parent_name)
        if not parent_coll:
            raise MissingResourceError(f"Parent collection '{parent_name}' not found")
        parent_coll.children.link(coll)
        parent_label = parent_coll.name
    else:
        bpy.context.scene.collection.children.link(coll)
        parent_label = bpy.context.scene.collection.name
    return {"name": coll.name, "parent": parent_label}


def list_collections(params: dict) -> dict:
    return {"collections": [{"name": coll.name, "object_count": len(coll.objects)} for coll in bpy.data.collections]}


def rename(params: dict) -> dict:
    coll = bpy.data.collections.get(params["name"])
    if not coll:
        raise MissingResourceError(f"Collection '{params['name']}' not found")
    new_name = params["new_name"].strip()
    if not new_name:
        raise ValueError("Collection name must not be empty")
    coll.name = new_name
    # Blender appends a .001 suffix when the name is taken; report the canonical name.
    return {"name": coll.name, "requested": new_name}


def get_collection_and_object(params: dict):
    coll = bpy.data.collections.get(params["collection"])
    if not coll:
        raise MissingResourceError(f"Collection '{params['collection']}' not found")
    obj = bpy.data.objects.get(params["object"])
    if not obj:
        raise MissingResourceError(f"Object '{params['object']}' not found")
    return coll, obj


def add_object(params: dict) -> dict:
    coll, obj = get_collection_and_object(params)
    members = list(getattr(obj, "users_collection", []))
    if coll in members:
        return {"object": obj.name, "collection": coll.name, "moved": False}
    for member in members:
        member.objects.unlink(obj)
    coll.objects.link(obj)
    return {
        "object": obj.name,
        "collection": coll.name,
        "moved": True,
        "previous_collections": [member.name for member in members],
    }


def remove_object(params: dict) -> dict:
    coll, obj = get_collection_and_object(params)
    if coll.objects.get(obj.name) is None:
        raise ValueError(f"Object '{obj.name}' is not in collection '{coll.name}'")
    coll.objects.unlink(obj)
    orphaned = not list(getattr(obj, "users_collection", []))
    if orphaned:
        bpy.context.scene.collection.objects.link(obj)
    return {
        "object": obj.name,
        "collection": coll.name,
        "relinked_to_scene": orphaned,
    }
