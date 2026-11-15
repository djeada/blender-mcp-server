"""Blender scene commands and their local helpers."""

import bpy


def get_info(params: dict) -> dict:
    scene = bpy.context.scene
    return {
        "name": scene.name,
        "frame_current": scene.frame_current,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "render_engine": scene.render.engine,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "object_count": len(scene.objects),
    }


def list_objects(params: dict) -> dict:
    type_filter = params.get("type")
    name_filter = params.get("name")
    collection_name = params.get("collection")
    visible_filter = params.get("visible")
    limit = params.get("limit")
    offset = params.get("offset") or 0

    collection_objects = None
    if collection_name:
        coll = bpy.data.collections.get(collection_name)
        if coll is None:
            raise ValueError(f"Collection '{collection_name}' not found")
        collection_objects = {obj.name for obj in coll.objects}

    matching = []
    for obj in sorted(bpy.context.scene.objects, key=lambda o: o.name):
        if type_filter and obj.type != type_filter.upper():
            continue
        if name_filter and name_filter.lower() not in obj.name.lower():
            continue
        if collection_objects is not None and obj.name not in collection_objects:
            continue
        if visible_filter is not None and bool(obj.visible_get()) != visible_filter:
            continue
        matching.append(obj)

    total = len(matching)
    page = matching[offset:]
    if limit is not None:
        page = page[:limit]
    objects = [
        {
            "name": obj.name,
            "type": obj.type,
            "location": list(obj.location),
            "visible": obj.visible_get(),
        }
        for obj in page
    ]
    return {"objects": objects, "total": total, "count": len(objects), "offset": offset}
