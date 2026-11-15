"""Create collections and move objects into them.

Args:
    collections (list[dict]): List of collection specs. Each dict:
        - name (str): Collection name (required)
        - objects (list[str]): Object names to move into the collection
        - parent (str|None): Parent collection name. Default: scene collection
        - color_tag (str|None): Color tag, e.g. "COLOR_01". Default: None

Result:
    created (list[str]): Collections created
    moved (dict[str, list[str]]): Map of collection name to objects moved in
    skipped (list[str]): Objects not found
"""

import bpy

collections_spec = args.get("collections", [])
created = []
moved = {}
skipped = []

for spec in collections_spec:
    col_name = spec.get("name")
    if not col_name:
        continue

    # Create or get collection
    col = bpy.data.collections.get(col_name)
    if col is None:
        col = bpy.data.collections.new(col_name)
        parent_name = spec.get("parent")
        if parent_name:
            parent = bpy.data.collections.get(parent_name)
            if parent:
                parent.children.link(col)
            else:
                bpy.context.scene.collection.children.link(col)
        else:
            bpy.context.scene.collection.children.link(col)
        created.append(col_name)

    color_tag = spec.get("color_tag")
    if color_tag:
        col.color_tag = color_tag

    moved[col_name] = []
    for obj_name in spec.get("objects", []):
        obj = bpy.data.objects.get(obj_name)
        if obj is None:
            skipped.append(obj_name)
            continue

        # Unlink from current collections
        for existing_col in obj.users_collection:
            existing_col.objects.unlink(obj)

        col.objects.link(obj)
        moved[col_name].append(obj_name)

__result__ = {
    "created": created,
    "moved": moved,
    "skipped": skipped,
}
