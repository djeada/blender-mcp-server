"""Bounded inspection and all-or-nothing patching of material, world and shader group node trees.

Only listed node types and settings can be changed; there is no general property setter and
no way to run code. A patch is first applied to a temporary copy of the tree, so that
Blender's own rules, including sockets that appear after a setting changes, are checked
before the real tree is touched.
"""

from __future__ import annotations

import math
from typing import Any

import bpy

from .paging import paginate
from .protocol import BridgeError, MissingResourceError, UnsupportedError

MAX_OPERATIONS = 64
MAX_GROUP_DEPTH = 3
MAX_RAMP_STOPS = 32
MAX_NODES_PER_TREE = 1_000
SHARED_DATA_MODES = ("error", "update_all", "make_single_user")
OUTPUT_TYPES = ("OUTPUT_MATERIAL", "OUTPUT_WORLD", "GROUP_OUTPUT")

# bl_idname -> settings that may be changed. Settings absent from a Blender version are reported.
NODE_TYPES: dict[str, tuple[str, ...]] = {
    "ShaderNodeTexCoord": (),
    "ShaderNodeUVMap": ("uv_map",),
    "ShaderNodeAttribute": ("attribute_name", "attribute_type"),
    "ShaderNodeNewGeometry": (),
    "ShaderNodeObjectInfo": (),
    "ShaderNodeLayerWeight": (),
    "ShaderNodeFresnel": (),
    "ShaderNodeMapping": ("vector_type",),
    "ShaderNodeTexNoise": ("noise_dimensions", "noise_type", "normalize"),
    "ShaderNodeTexVoronoi": ("voronoi_dimensions", "distance", "feature", "normalize"),
    "ShaderNodeTexWave": ("wave_type", "bands_direction", "rings_direction", "wave_profile"),
    "ShaderNodeTexGradient": ("gradient_type",),
    "ShaderNodeTexChecker": (),
    "ShaderNodeTexBrick": ("offset", "offset_frequency", "squash", "squash_frequency"),
    "ShaderNodeTexImage": ("image", "interpolation", "projection", "extension"),
    "ShaderNodeTexEnvironment": ("image", "interpolation", "projection"),
    "ShaderNodeValToRGB": (),
    "ShaderNodeMath": ("operation", "use_clamp"),
    "ShaderNodeVectorMath": ("operation",),
    "ShaderNodeMix": ("data_type", "blend_type", "factor_mode", "clamp_factor", "clamp_result"),
    "ShaderNodeMapRange": ("data_type", "interpolation_type", "clamp"),
    "ShaderNodeClamp": ("clamp_type",),
    "ShaderNodeSeparateColor": ("mode",),
    "ShaderNodeCombineColor": ("mode",),
    "ShaderNodeSeparateXYZ": (),
    "ShaderNodeCombineXYZ": (),
    "ShaderNodeRGB": ("value",),
    "ShaderNodeValue": ("value",),
    "ShaderNodeInvert": (),
    "ShaderNodeHueSaturation": (),
    "ShaderNodeBrightContrast": (),
    "ShaderNodeBump": ("invert",),
    "ShaderNodeNormalMap": ("space", "uv_map"),
    "ShaderNodeDisplacement": ("space",),
    "ShaderNodeBsdfPrincipled": (),
    "ShaderNodeBsdfDiffuse": (),
    "ShaderNodeBsdfTransparent": (),
    "ShaderNodeEmission": (),
    "ShaderNodeBackground": (),
    "ShaderNodeMixShader": (),
    "ShaderNodeAddShader": (),
    "NodeReroute": (),
    "NodeFrame": (),
}

# operation -> (required keys, optional keys)
OPERATIONS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "add_node": (("id", "type"), ("location", "label", "properties", "inputs")),
    "remove_node": (("node",), ()),
    "set_input": (("node", "socket", "value"), ()),
    "set_property": (("node", "property", "value"), ()),
    "set_color_ramp": (("node", "stops"), ("interpolation",)),
    "connect": (("from", "from_socket", "to", "to_socket"), ("replace",)),
    "disconnect": (("to", "to_socket"), ()),
    "move_node": (("node", "location"), ()),
}


def check_operations(operations: list) -> None:
    """Reject malformed patches before touching Blender."""
    if not 1 <= len(operations) <= MAX_OPERATIONS:
        raise ValueError(f"A patch has 1-{MAX_OPERATIONS} operations")
    added: set[str] = set()
    for index, operation in enumerate(operations):
        where = f"Operation {index}"
        if not isinstance(operation, dict) or operation.get("op") not in OPERATIONS:
            raise ValueError(f"{where}: 'op' must be one of: {', '.join(OPERATIONS)}")
        required, optional = OPERATIONS[operation["op"]]
        if missing := [key for key in required if key not in operation]:
            raise ValueError(f"{where} ({operation['op']}) needs: {', '.join(missing)}")
        if unknown := sorted(set(operation) - {"op", *required, *optional}):
            raise ValueError(f"{where} ({operation['op']}) does not accept: {', '.join(unknown)}")
        for key in ("id", "node", "from", "to", "socket", "from_socket", "to_socket", "property", "type"):
            if key in operation and not (isinstance(operation[key], str) and operation[key]):
                raise ValueError(f"{where}: '{key}' must be a nonempty string")
        if operation["op"] == "add_node":
            node_id = operation["id"]
            if len(node_id.encode()) > 63 or not node_id.isprintable():
                raise ValueError(f"{where}: 'id' must be printable and at most 63 bytes")
            if node_id in added:
                raise ValueError(f"{where}: duplicate node id '{node_id}'")
            added.add(node_id)
            if operation["type"] not in NODE_TYPES:
                raise UnsupportedError(f"{where}: node type '{operation['type'][:60]}' is not supported")
            for key in ("properties", "inputs"):
                if key in operation and not isinstance(operation[key], dict):
                    raise ValueError(f"{where}: '{key}' must be an object")


# --- finding the tree -------------------------------------------------------------------


def _owner(params: dict):
    """The material or world named by the request, and its node tree."""
    material_name, use_world = params.get("material"), params.get("world", False)
    if bool(material_name) == bool(use_world):
        raise ValueError("Provide exactly one of 'material' or 'world'=true")
    if use_world:
        owner = bpy.context.scene.world
        if owner is None:
            raise MissingResourceError("The scene has no world; create one with blender_world_set")
    else:
        owner = bpy.data.materials.get(material_name)
        if owner is None:
            raise MissingResourceError("Material not found")
    if not owner.use_nodes or owner.node_tree is None:
        raise UnsupportedError(f"'{owner.name}' does not use nodes")
    return owner


def _descend(tree, path: list):
    """Follow group nodes named in `path`. Returns the tree and the group node that holds it."""
    if len(path) > MAX_GROUP_DEPTH or not all(isinstance(name, str) for name in path):
        raise ValueError(f"'group_path' names at most {MAX_GROUP_DEPTH} nested group nodes")
    holder, holder_tree = None, None
    for name in path:
        node = tree.nodes.get(name)
        if node is None or node.type != "GROUP" or node.node_tree is None:
            raise MissingResourceError(f"No shader group node named '{name}' at this level")
        holder, holder_tree, tree = node, tree, node.node_tree
    return tree, holder, holder_tree


# --- reading ----------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    if isinstance(value, (bool, int, str)) or value is None:
        return value
    if isinstance(value, float):
        return round(value, 6) if math.isfinite(value) else None
    try:
        return [_plain(item) for item in list(value)[:16]]
    except TypeError:
        return getattr(value, "name", str(value)[:80])


def _sockets(sockets, *, defaults: bool) -> list[dict]:
    listed = []
    for socket in sockets:
        if not getattr(socket, "enabled", True):
            continue  # unused by the node's current settings
        entry = {"id": socket.identifier, "name": socket.name, "type": socket.type, "linked": bool(socket.links)}
        if defaults and not socket.links and hasattr(socket, "default_value"):
            entry["value"] = _plain(socket.default_value)
        listed.append(entry)
    return listed


def _properties(node) -> dict:
    values = {}
    for name in NODE_TYPES.get(node.bl_idname, ()):
        if name == "value":
            values[name] = _plain(node.outputs[0].default_value)
        elif hasattr(node, name):
            values[name] = _plain(getattr(node, name))
    return values


def describe_node(node, *, sockets: bool) -> dict:
    entry: dict = {"id": node.name, "type": node.bl_idname, "supported": node.bl_idname in NODE_TYPES}
    if node.label:
        entry["label"] = node.label[:80]
    if node.type == "GROUP" and node.node_tree is not None:
        entry["group"] = {"name": node.node_tree.name, "users": node.node_tree.users}
    if not sockets:
        return entry
    entry["location"] = [round(node.location[0]), round(node.location[1])]
    if properties := _properties(node):
        entry["properties"] = properties
    if node.bl_idname == "ShaderNodeValToRGB":
        ramp = node.color_ramp
        entry["color_ramp"] = {
            "interpolation": ramp.interpolation,
            "stops": [{"position": _plain(e.position), "color": _plain(e.color)} for e in ramp.elements],
        }
    entry["inputs"] = _sockets(node.inputs, defaults=True)
    entry["outputs"] = _sockets(node.outputs, defaults=False)
    return entry


def _link(link) -> dict:
    return {
        "from": link.from_node.name,
        "from_socket": link.from_socket.identifier,
        "to": link.to_node.name,
        "to_socket": link.to_socket.identifier,
    }


def inspect(params: dict) -> dict:
    owner = _owner(params)
    path = params.get("group_path") or []
    tree, _, _ = _descend(owner.node_tree, path)
    wanted = params.get("nodes")
    if wanted is not None:
        if missing := [name for name in wanted if not isinstance(name, str) or tree.nodes.get(name) is None]:
            raise MissingResourceError(f"No node named '{str(missing[0])[:60]}'")
        selected = [tree.nodes.get(name) for name in wanted]
    else:
        selected = sorted(tree.nodes, key=lambda node: node.name)
    page, metadata = paginate(selected, params)
    detailed = wanted is not None or params.get("sockets", False)
    shown = {node.name for node in page}
    # Each link is listed once, with the node it feeds.
    links = sorted(
        (_link(link) for link in tree.links if link.to_node.name in shown),
        key=lambda item: (item["to"], item["to_socket"], item["from"]),
    )
    result = {
        "target": {"world" if params.get("world") else "material": owner.name},
        "tree": tree.name,
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "nodes": [describe_node(node, sockets=detailed) for node in page],
        "links": links,
        **metadata,
    }
    if path:
        result["group_path"] = path
        result["tree_users"] = tree.users
    return result


# --- patching ---------------------------------------------------------------------------


def _node(tree, name: str):
    node = tree.nodes.get(name)
    if node is None:
        raise MissingResourceError(f"No node named '{name[:60]}'")
    return node


def _socket(sockets, key: str, node, direction: str):
    enabled = [socket for socket in sockets if getattr(socket, "enabled", True)]
    for socket in enabled:
        if socket.identifier == key:
            return socket
    named = [socket for socket in enabled if socket.name == key]
    if len(named) == 1:
        return named[0]
    problem = "is ambiguous" if named else "does not exist or is disabled"
    available = ", ".join(socket.identifier for socket in enabled)
    raise ValueError(f"{direction} '{key[:60]}' {problem} on node '{node.name}'. Use one of: {available}")


def _numbers(value, count: int | tuple) -> bool:
    counts = count if isinstance(count, tuple) else (count,)
    return (
        isinstance(value, list)
        and len(value) in counts
        and all(type(item) in (int, float) and math.isfinite(item) for item in value)
    )


def _set_input(node, key: str, value) -> None:
    socket = _socket(node.inputs, key, node, "Input")
    if socket.links:
        raise ValueError(f"Input '{key}' of '{node.name}' is linked, so a value would have no effect")
    kind = socket.type
    if kind == "VALUE":
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Input '{key}' needs a finite number")
        socket.default_value = float(value)
    elif kind == "RGBA":
        if not _numbers(value, (3, 4)):
            raise ValueError(f"Input '{key}' needs a linear [r, g, b] or [r, g, b, a] color")
        socket.default_value = [*value, 1.0][:4]
    elif kind in {"VECTOR", "ROTATION"}:
        if not _numbers(value, len(socket.default_value)):
            raise ValueError(f"Input '{key}' needs {len(socket.default_value)} numbers")
        socket.default_value = value
    else:
        raise ValueError(f"Input '{key}' of type {kind} has no settable value; connect it instead")


def _set_property(node, name: str, value) -> None:
    allowed = NODE_TYPES.get(node.bl_idname, ())
    if name not in allowed:
        raise ValueError(
            f"Property '{name[:60]}' of {node.bl_idname} cannot be set. Allowed: {', '.join(allowed) or 'none'}"
        )
    if name == "value":
        count = None if node.bl_idname == "ShaderNodeValue" else (3, 4)
        valid = _numbers(value, count) if count else type(value) in (int, float) and math.isfinite(value)
        if not valid:
            raise ValueError("'value' needs a number for a Value node, or a color for an RGB node")
        node.outputs[0].default_value = float(value) if count is None else [*value, 1.0][:4]
        return
    if name == "image":
        image = bpy.data.images.get(value) if isinstance(value, str) else None
        if image is None:
            raise MissingResourceError(
                "No loaded image has that name. Load files with blender_material_set_texture_set or blender_world_set"
            )
        node.image = image
        return
    definition = node.bl_rna.properties.get(name)
    if definition is None or definition.is_readonly:
        raise UnsupportedError(f"This Blender version has no '{name}' setting on {node.bl_idname}")
    if definition.type == "ENUM":
        choices = [item.identifier for item in definition.enum_items]
        if value not in choices:
            raise ValueError(f"'{name}' must be one of: {', '.join(choices)}")
    elif definition.type == "BOOLEAN":
        if type(value) is not bool:
            raise ValueError(f"'{name}' must be true or false")
    elif definition.type in {"INT", "FLOAT"}:
        expected = (int,) if definition.type == "INT" else (int, float)
        if type(value) not in expected or not definition.hard_min <= value <= definition.hard_max:
            raise ValueError(f"'{name}' must be a number from {definition.hard_min} to {definition.hard_max}")
    elif definition.type == "STRING":
        if not isinstance(value, str) or len(value) > 255:
            raise ValueError(f"'{name}' must be a short string")
    else:
        raise UnsupportedError(f"'{name}' has an unsupported setting type")
    setattr(node, name, value)


def _set_color_ramp(node, stops, interpolation) -> None:
    if node.bl_idname != "ShaderNodeValToRGB":
        raise ValueError(f"'{node.name}' is not a Color Ramp node")
    if not isinstance(stops, list) or not 1 <= len(stops) <= MAX_RAMP_STOPS:
        raise ValueError(f"'stops' lists 1-{MAX_RAMP_STOPS} stops")
    for stop in stops:
        if not (
            isinstance(stop, dict)
            and set(stop) == {"position", "color"}
            and type(stop["position"]) in (int, float)
            and 0 <= stop["position"] <= 1
            and _numbers(stop["color"], (3, 4))
        ):
            raise ValueError("Each stop is {position: 0-1, color: [r, g, b] or [r, g, b, a]}")
    ramp = node.color_ramp
    if interpolation is not None:
        choices = [item.identifier for item in ramp.bl_rna.properties["interpolation"].enum_items]
        if interpolation not in choices:
            raise ValueError(f"'interpolation' must be one of: {', '.join(choices)}")
        ramp.interpolation = interpolation
    ordered = sorted(stops, key=lambda stop: stop["position"])
    elements = ramp.elements
    while len(elements) > 1:
        elements.remove(elements[-1])
    elements[0].position = ordered[0]["position"]
    elements[0].color = [*ordered[0]["color"], 1.0][:4]
    for stop in ordered[1:]:
        element = elements.new(stop["position"])
        element.color = [*stop["color"], 1.0][:4]


def _depends_on(node, other) -> bool:
    """Whether `node` receives, directly or indirectly, anything from `other`."""
    pending, seen = [node], set()
    while pending:
        current = pending.pop()
        if current.name == other.name:
            return True
        for socket in current.inputs:
            for link in socket.links:
                if link.from_node.name not in seen:
                    seen.add(link.from_node.name)
                    pending.append(link.from_node)
    return False


def _compatible(source: str, target: str) -> bool:
    if "SHADER" in (source, target):
        return source == target
    if "ROTATION" in (source, target):
        return source == target
    return {source, target} <= {"VALUE", "RGBA", "VECTOR", "INT", "BOOLEAN"}


def _connect(tree, operation: dict) -> None:
    source_node, target_node = _node(tree, operation["from"]), _node(tree, operation["to"])
    source = _socket(source_node.outputs, operation["from_socket"], source_node, "Output")
    target = _socket(target_node.inputs, operation["to_socket"], target_node, "Input")
    if not _compatible(source.type, target.type):
        raise ValueError(f"A {source.type} output cannot feed a {target.type} input")
    # Blender accepts cycles and even reports them as valid, so they are checked here.
    if _depends_on(source_node, target_node):
        raise ValueError(f"Connecting '{source_node.name}' to '{target_node.name}' would create a cycle")
    if target.links:
        existing = target.links[0]
        if existing.from_node.name == source_node.name and existing.from_socket.identifier == source.identifier:
            return
        if not operation.get("replace", False):
            raise BridgeError(
                "conflict",
                f"Input '{target.identifier}' of '{target_node.name}' is already fed by "
                f"'{existing.from_node.name}'. Set replace=true on this operation to change it",
            )
    tree.links.new(source, target)


def _apply_one(tree, operation: dict) -> None:
    kind = operation["op"]
    if kind == "add_node":
        if tree.nodes.get(operation["id"]) is not None:
            raise ValueError(f"A node named '{operation['id']}' already exists")
        if len(tree.nodes) >= MAX_NODES_PER_TREE:
            raise ValueError(f"The tree already has {MAX_NODES_PER_TREE} nodes")
        try:
            node = tree.nodes.new(operation["type"])
        except RuntimeError as exc:
            raise UnsupportedError(f"This Blender version cannot add {operation['type']} here") from exc
        node.name = operation["id"]
        if node.name != operation["id"]:
            raise ValueError(f"Blender could not use the id '{operation['id']}'")
        if "label" in operation:
            node.label = str(operation["label"])[:63]
        if "location" in operation:
            _move(node, operation["location"])
        # Settings first: they decide which sockets exist.
        for name, value in operation.get("properties", {}).items():
            _set_property(node, name, value)
        for key, value in operation.get("inputs", {}).items():
            _set_input(node, key, value)
    elif kind == "remove_node":
        node = _node(tree, operation["node"])
        if node.type in OUTPUT_TYPES:
            raise ValueError("Output nodes cannot be removed")
        tree.nodes.remove(node)
    elif kind == "set_input":
        _set_input(_node(tree, operation["node"]), operation["socket"], operation["value"])
    elif kind == "set_property":
        _set_property(_node(tree, operation["node"]), operation["property"], operation["value"])
    elif kind == "set_color_ramp":
        _set_color_ramp(_node(tree, operation["node"]), operation["stops"], operation.get("interpolation"))
    elif kind == "connect":
        _connect(tree, operation)
    elif kind == "disconnect":
        node = _node(tree, operation["to"])
        socket = _socket(node.inputs, operation["to_socket"], node, "Input")
        if not socket.links:
            raise ValueError(f"Input '{socket.identifier}' of '{node.name}' is not connected")
        for link in list(socket.links):
            tree.links.remove(link)
    else:
        _move(_node(tree, operation["node"]), operation["location"])


def _move(node, location) -> None:
    if not _numbers(location, 2):
        raise ValueError("'location' must be [x, y]")
    node.location = location


def apply_operations(tree, operations: list) -> None:
    for index, operation in enumerate(operations):
        try:
            _apply_one(tree, operation)
        except Exception as exc:
            code = getattr(exc, "code", None) or (
                "not_found" if isinstance(exc, MissingResourceError) else "invalid_arguments"
            )
            if not isinstance(exc, (ValueError, MissingResourceError, BridgeError)):
                raise
            raise BridgeError(
                code, f"Operation {index} ({operation['op']}): {exc}", details={"operation": index}
            ) from exc


def edit(params: dict) -> dict:
    operations = params["operations"]
    check_operations(operations)
    mode = params.get("shared_data", "error")
    if mode not in SHARED_DATA_MODES:
        raise ValueError(f"'shared_data' must be one of: {', '.join(SHARED_DATA_MODES)}")
    owner = _owner(params)
    if owner.library is not None:
        raise UnsupportedError("Linked library data cannot be edited")
    path = params.get("group_path") or []
    tree, holder, holder_tree = _descend(owner.node_tree, path)
    if tree.library is not None:
        raise UnsupportedError("Linked library node groups cannot be edited")

    copy_group = False
    if holder is not None and tree.users > 1:
        if mode == "error":
            raise ValueError(
                f"Node group '{tree.name}' is used {tree.users} times. Pass shared_data='update_all' to change "
                "every use, or 'make_single_user' to change only this one"
            )
        copy_group = mode == "make_single_user"
    if params.get("world"):
        scenes = [scene.name for scene in bpy.data.scenes if scene.world == owner]
        if len(scenes) > 1 and mode != "update_all":
            raise ValueError(
                f"World '{owner.name}' is used by {len(scenes)} scenes. Pass shared_data='update_all', or give this "
                "scene its own world with blender_world_set on_conflict='new_world'"
            )
    if len(path) > 1 and copy_group and holder_tree.users > 1:
        raise UnsupportedError("An enclosing node group is shared too; make that one single-user first")

    # Dry run on a copy: if anything fails, the real tree has not been touched.
    if holder is not None:
        trial_owner, trial_collection = tree.copy(), bpy.data.node_groups
        trial_tree = trial_owner
    else:
        trial_owner = owner.copy()
        trial_collection = bpy.data.worlds if params.get("world") else bpy.data.materials
        trial_tree = trial_owner.node_tree
    try:
        apply_operations(trial_tree, operations)
    finally:
        trial_collection.remove(trial_owner)

    if copy_group:
        holder.node_tree = tree = tree.copy()
    apply_operations(tree, operations)

    touched = []
    for operation in operations:
        for key in ("id", "node", "to"):
            name = operation.get(key)
            if name and name not in touched and tree.nodes.get(name) is not None:
                touched.append(name)
    result = {
        "target": {"world" if params.get("world") else "material": owner.name},
        "tree": tree.name,
        "applied": len(operations),
        "node_count": len(tree.nodes),
        "link_count": len(tree.links),
        "changed_nodes": [describe_node(tree.nodes.get(name), sockets=False) for name in touched[:32]],
    }
    if not path:
        outputs = [node for node in tree.nodes if node.type in OUTPUT_TYPES]
        active = next((node for node in outputs if getattr(node, "is_active_output", False)), None)
        if active is not None and not active.inputs["Surface"].links:
            result["warnings"] = ["Nothing is connected to the output's Surface input, so it renders black"]
    return result
