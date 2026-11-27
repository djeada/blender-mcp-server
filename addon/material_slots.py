"""Material slots and face assignment, without surprising other users of a mesh.

Slot count, data-linked materials and face assignments live on the mesh, which linked
duplicates share. Object-linked materials belong to one object. Every request is validated
completely before anything changes.
"""

from collections import Counter

import bpy

from .paging import paginate
from .protocol import MissingResourceError, UnsupportedError

SHARED_DATA_MODES = ("error", "update_all", "make_single_user")
LINKS = ("DATA", "OBJECT")
MATCH_MODES = ("all", "any")
MAX_FACE_SELECTION = 100_000
MAX_SLOTS = 256


def _mesh_object(name: str, *, editing: bool = True):
    obj = bpy.data.objects.get(name)
    if obj is None:
        raise MissingResourceError("Object not found")
    if obj.type != "MESH":
        raise UnsupportedError(f"Material slot tools need a MESH object, not {obj.type}")
    if obj.data.is_editmode:
        raise UnsupportedError("The mesh is in Edit Mode; leave Edit Mode first")
    if editing and (obj.library is not None or obj.data.library is not None):
        raise UnsupportedError("Linked library data cannot be edited")
    return obj


def _material(name: str):
    material = bpy.data.materials.get(name)
    if material is None:
        raise MissingResourceError("Material not found")
    return material


def _users(mesh) -> list:
    return sorted((obj for obj in bpy.data.objects if obj.data == mesh), key=lambda item: item.name)


def _check_index(obj, index: int, label: str = "index") -> None:
    if not 0 <= index < len(obj.material_slots):
        raise ValueError(f"'{label}' must name an existing slot; the object has {len(obj.material_slots)}")


def _shared_choice(obj, params: dict) -> bool:
    """Check a change to mesh data. Returns True if the mesh must be copied for this object first."""
    mode = params.get("shared_data", "error")
    if mode not in SHARED_DATA_MODES:
        raise ValueError(f"'shared_data' must be one of: {', '.join(SHARED_DATA_MODES)}")
    users = _users(obj.data)
    if len(users) <= 1 or mode == "update_all":
        return False
    if mode == "error":
        names = ", ".join(user.name for user in users[:5])
        raise ValueError(
            f"This changes mesh data shared by {len(users)} objects ({names}). Pass shared_data='update_all' to "
            "change them all, or 'make_single_user' to change only this one"
        )
    return True


def _single_user(obj) -> None:
    links = [(slot.link, slot.material) for slot in obj.material_slots]
    obj.data = obj.data.copy()
    _restore_slots(obj, links)


def _restore_slots(obj, links: list) -> None:
    """Reapply each slot's link type, and the material of object-linked slots."""
    for slot, (link, material) in zip(obj.material_slots, links, strict=False):
        if slot.link != link:
            slot.link = link
        if link == "OBJECT" and slot.material != material:
            slot.material = material


def describe(obj, params: dict | None = None) -> dict:
    mesh = obj.data
    usage = Counter(polygon.material_index for polygon in mesh.polygons)
    entries = []
    for index, slot in enumerate(obj.material_slots):
        entry = {
            "index": index,
            "material": slot.material.name if slot.material else None,
            "link": slot.link,
            "faces": usage[index],
        }
        if slot.link == "OBJECT":
            data = mesh.materials[index]
            entry["data_material"] = data.name if data else None
        entries.append(entry)
    page, metadata = paginate(entries, params or {})
    result = {
        "object": obj.name,
        "mesh": mesh.name,
        "face_count": len(mesh.polygons),
        "slots": page,
        "faces_without_slot": sum(count for index, count in usage.items() if index >= len(entries)),
        **metadata,
    }
    users = _users(mesh)
    if len(users) > 1:
        result["mesh_shared_by"] = {"count": len(users), "objects": [user.name for user in users[:10]]}
    return result


def list_slots(params: dict) -> dict:
    return describe(_mesh_object(params["object"], editing=False), params)


def append(params: dict) -> dict:
    obj = _mesh_object(params["object"])
    material = _material(params["material"]) if params.get("material") else None
    link = params.get("link", "DATA").upper()
    if link not in LINKS:
        raise ValueError(f"'link' must be one of: {', '.join(LINKS)}")
    if len(obj.material_slots) >= MAX_SLOTS:
        raise ValueError(f"A mesh may have at most {MAX_SLOTS} slots through this tool")
    # The slot itself is added to the mesh, so every user gets it, whatever its link.
    if _shared_choice(obj, params):
        _single_user(obj)
    obj.data.materials.append(material if link == "DATA" else None)
    index = len(obj.material_slots) - 1
    if link == "OBJECT":
        slot = obj.material_slots[index]
        slot.link = "OBJECT"
        slot.material = material
    return {"added_index": index, **describe(obj)}


def replace(params: dict) -> dict:
    obj = _mesh_object(params["object"])
    index = params["index"]
    _check_index(obj, index)
    material = _material(params["material"]) if params.get("material") else None
    current = obj.material_slots[index].link
    link = (params.get("link") or current).upper()
    if link not in LINKS:
        raise ValueError(f"'link' must be one of: {', '.join(LINKS)}")
    # An object-linked material belongs to this object alone; a data-linked one is the mesh's.
    if link == "DATA" and _shared_choice(obj, params):
        _single_user(obj)
    slot = obj.material_slots[index]
    if slot.link != link:
        slot.link = link
    slot.material = material
    return describe(obj)


def remove(params: dict) -> dict:
    obj = _mesh_object(params["object"])
    index = params["index"]
    _check_index(obj, index)
    count = len(obj.material_slots)
    remap_to = params.get("remap_to")
    used = sum(1 for polygon in obj.data.polygons if polygon.material_index == index)
    if remap_to is not None:
        _check_index(obj, remap_to, "remap_to")
        if remap_to == index:
            raise ValueError("'remap_to' must be a different slot from the one being removed")
    elif used and count > 1:
        raise ValueError(f"{used} faces use slot {index}; pass 'remap_to' with the slot that should take them")
    if _shared_choice(obj, params):
        _single_user(obj)
    mesh = obj.data
    # Blender's own slot removal drops or misaligns object-linked materials, and renumbers
    # faces implicitly. Record everything first, then restore it at the new positions.
    assignments = [polygon.material_index for polygon in mesh.polygons]
    links = {user.name: [(slot.link, slot.material) for slot in user.material_slots] for user in _users(mesh)}
    mesh.materials.pop(index=index)
    for user in _users(mesh):
        previous = links[user.name]
        _restore_slots(user, previous[:index] + previous[index + 1 :])

    def moved(old: int) -> int:
        if old == index:
            old = remap_to if remap_to is not None else 0
        return old - 1 if old > index else old

    for polygon, old in zip(mesh.polygons, assignments, strict=True):
        polygon.material_index = max(moved(old), 0)
    mesh.update()
    return {"removed_index": index, "faces_moved": used, **describe(obj)}


def _selection(obj, params: dict) -> list[int]:
    """Resolve exactly one selector to face indices."""
    chosen = [name for name in ("face_indices", "vertex_group", "from_slot") if params.get(name) is not None]
    if len(chosen) != 1:
        raise ValueError("Provide exactly one of 'face_indices', 'vertex_group' or 'from_slot'")
    mesh = obj.data
    if chosen[0] == "face_indices":
        indices = params["face_indices"]
        if len(indices) > MAX_FACE_SELECTION:
            raise ValueError(f"'face_indices' accepts at most {MAX_FACE_SELECTION} faces")
        if any(type(index) is not int or not 0 <= index < len(mesh.polygons) for index in indices):
            raise ValueError(f"'face_indices' must be integers from 0 to {len(mesh.polygons) - 1}")
        return sorted(set(indices))
    if chosen[0] == "from_slot":
        _check_index(obj, params["from_slot"], "from_slot")
        return [i for i, polygon in enumerate(mesh.polygons) if polygon.material_index == params["from_slot"]]
    group = obj.vertex_groups.get(params["vertex_group"])
    if group is None:
        raise MissingResourceError("Vertex group not found")
    match = params.get("match", "all")
    if match not in MATCH_MODES:
        raise ValueError(f"'match' must be one of: {', '.join(MATCH_MODES)}")
    threshold = params.get("min_weight", 0.0)
    members = {
        index
        for index, vertex in enumerate(mesh.vertices)
        if any(item.group == group.index and item.weight > threshold for item in vertex.groups)
    }
    test = all if match == "all" else any
    return [i for i, polygon in enumerate(mesh.polygons) if test(vertex in members for vertex in polygon.vertices)]


def assign_faces(params: dict) -> dict:
    obj = _mesh_object(params["object"])
    if (params.get("slot") is None) == (params.get("material") is None):
        raise ValueError("Provide exactly one of 'slot' or 'material'")
    if params.get("slot") is not None:
        slot = params["slot"]
        _check_index(obj, slot, "slot")
    else:
        material = _material(params["material"])
        slot = next((i for i, item in enumerate(obj.material_slots) if item.material == material), None)
        if slot is None:
            raise ValueError("The material is not in any slot of this object; add it with blender_material_slot_append")
    faces = _selection(obj, params)
    if not faces:
        raise ValueError("The selection contains no faces")
    changed = sum(1 for i in faces if obj.data.polygons[i].material_index != slot)
    if changed and _shared_choice(obj, params):
        _single_user(obj)
    for i in faces:
        obj.data.polygons[i].material_index = slot
    obj.data.update()
    return {"slot": slot, "selected_faces": len(faces), "changed_faces": changed, **describe(obj)}
