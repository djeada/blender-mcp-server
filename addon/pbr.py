"""Bind a set of PBR texture maps to a material's Principled BSDF.

Only nodes created here are ever removed. Every file is validated and loaded, and every
conflict found, before the material changes.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

import bpy

from . import images
from .protocol import BridgeError, MissingResourceError, UnsupportedError

if TYPE_CHECKING:
    from .paths import PathPolicy

_TAG = "mcp_pbr_role"  # custom property marking nodes created here
GLTF_GROUP = "glTF Material Output"  # the name Blender's glTF exporter looks for
CHANNELS = ("R", "G", "B", "A")
ON_CONFLICT = ("error", "replace")

# map -> (color space, may select a channel)
MAPS: dict[str, tuple[str, bool]] = {
    "base_color": ("sRGB", False),
    "metallic": ("Non-Color", True),
    "roughness": ("Non-Color", True),
    "normal": ("Non-Color", False),
    "ao": ("Non-Color", True),
    "emission": ("sRGB", False),
    "opacity": ("Non-Color", True),
    "height": ("Non-Color", True),
}
OPTIONS: dict[str, tuple[str, ...]] = {
    "normal": ("convention", "strength"),
    "ao": ("mode",),
    "emission": ("strength",),
    "opacity": ("mode", "threshold"),
    "height": ("mode", "strength", "distance", "midlevel"),
}
# The packed layout used by glTF: occlusion in red, roughness in green, metallic in blue.
ORM_CHANNELS = {"ao": "R", "roughness": "G", "metallic": "B"}
_CHOICES = {
    ("normal", "convention"): ("opengl", "directx"),
    ("ao", "mode"): ("gltf", "multiply"),
    ("opacity", "mode"): ("blend", "clip"),
    ("height", "mode"): ("bump", "displacement"),
}
_NUMBERS = {
    ("normal", "strength"): (0.0, 10.0),
    ("emission", "strength"): (0.0, 1000.0),
    ("opacity", "threshold"): (0.0, 1.0),
    ("height", "strength"): (0.0, 1.0),
    ("height", "distance"): (0.0, 1000.0),
    ("height", "midlevel"): (0.0, 1.0),
}
# Nodes that exist only to feed other nodes; removed once nothing uses them.
_SUPPORT_ROLES = frozenset({"texture", "separate", "mapping", "uv", "invert-green"})


def _validate_spec(name: str, spec: Any) -> dict:
    if name not in MAPS:
        raise ValueError(f"Unknown map '{name}'. Choose from: {', '.join(MAPS)}")
    if isinstance(spec, str):
        spec = {"path": spec}
    if not isinstance(spec, dict):
        raise ValueError(f"Map '{name}' must be a path or an object with a 'path'")
    _, has_channel = MAPS[name]
    allowed = {"path", *OPTIONS.get(name, ())} | ({"channel"} if has_channel else set())
    if unknown := sorted(set(spec) - allowed):
        raise ValueError(f"Map '{name}' does not accept: {', '.join(unknown)}")
    if not isinstance(spec.get("path"), str) or not spec["path"].strip():
        raise ValueError(f"Map '{name}' needs a 'path'")
    result = dict(spec)
    if has_channel:
        channel = str(result.get("channel", "R")).upper()
        if channel not in CHANNELS:
            raise ValueError(f"Map '{name}' channel must be one of: {', '.join(CHANNELS)}")
        result["channel"] = channel
    for (owner, option), choices in _CHOICES.items():
        if owner != name:
            continue
        if result.get(option) not in choices:
            # Conventions and modes change the result in ways that cannot be guessed.
            raise ValueError(f"Map '{name}' needs '{option}': {' or '.join(choices)}")
    for (owner, option), (low, high) in _NUMBERS.items():
        if owner == name and option in result:
            value = result[option]
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"Map '{name}' {option} must be a number from {low:g} to {high:g}")
    if name == "height" and result["mode"] == "bump" and "midlevel" in result:
        raise ValueError("'midlevel' applies to displacement, not bump")
    return result


def _validate_mapping(mapping: dict | None) -> dict | None:
    if mapping is None:
        return None
    if unknown := sorted(set(mapping) - {"scale", "offset", "rotation"}):
        raise ValueError(f"'mapping' does not accept: {', '.join(unknown)}")
    result: dict[str, Any] = {}
    for key in ("scale", "offset"):
        if key in mapping:
            value = mapping[key]
            if not (isinstance(value, list) and len(value) == 2) or not all(
                type(item) in (int, float) and math.isfinite(item) for item in value
            ):
                raise ValueError(f"'mapping.{key}' must be two numbers")
            result[key] = [float(item) for item in value]
    if "rotation" in mapping:
        value = mapping["rotation"]
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("'mapping.rotation' must be a number of degrees")
        result["rotation"] = float(value)
    return result


def _requested_maps(params: dict) -> dict[str, dict]:
    supplied = dict(params.get("maps") or {})
    if orm := params.get("orm"):
        if overlap := sorted(set(supplied) & {"roughness", "metallic"}):
            raise ValueError(f"'orm' already provides {', '.join(overlap)}")
        for name, channel in ORM_CHANNELS.items():
            if name == "ao" and "ao" in supplied:
                continue
            spec: dict = {"path": orm, "channel": channel}
            if name == "ao":
                spec["mode"] = "gltf"
            supplied[name] = spec
    return {name: _validate_spec(name, spec) for name, spec in supplied.items()}


# --- graph helpers ----------------------------------------------------------------------


def _role(node) -> str | None:
    role: str | None = node.get(_TAG)
    return role


def _find(tree, role: str):
    return next((node for node in tree.nodes if _role(node) == role), None)


def _principled(tree):
    outputs = [node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"]
    output = next((node for node in outputs if node.is_active_output), outputs[0] if outputs else None)
    if output is not None:
        queue, seen = [output], []
        while queue:
            node = queue.pop(0)
            if node.type == "BSDF_PRINCIPLED":
                return node, output
            for socket in node.inputs:
                for link in socket.links:
                    if link.from_node not in seen:
                        seen.append(link.from_node)
                        queue.append(link.from_node)
    raise UnsupportedError("The material has no Principled BSDF connected to its active output")


def _emission_socket(shader):
    return shader.inputs.get("Emission Color") or shader.inputs["Emission"]


def _targets(tree, shader, output) -> dict[str, Any]:
    gltf = next((node for node in tree.nodes if node.type == "GROUP" and _group_name(node) == GLTF_GROUP), None)
    return {
        "base_color": shader.inputs["Base Color"],
        "metallic": shader.inputs["Metallic"],
        "roughness": shader.inputs["Roughness"],
        "normal": shader.inputs["Normal"],
        "emission": _emission_socket(shader),
        "opacity": shader.inputs["Alpha"],
        "displacement": output.inputs["Displacement"],
        "occlusion": gltf.inputs["Occlusion"] if gltf is not None else None,
    }


def _group_name(node) -> str | None:
    if getattr(node, "node_tree", None) is None:
        return None
    return str(node.node_tree.name).split(".")[0]


def _target_for(name: str, spec: dict) -> str:
    if name == "ao":
        return "occlusion" if spec["mode"] == "gltf" else "base_color"
    if name == "height":
        return "normal" if spec["mode"] == "bump" else "displacement"
    return name


def _foreign_link(socket) -> str | None:
    """The type of a node not created here that feeds this socket."""
    if socket is None:
        return None
    for link in socket.links:
        if _role(link.from_node) is None:
            return str(link.from_node.bl_idname)
    return None


class _Builder:
    def __init__(self, tree, shader):
        self.tree = tree
        self.shader = shader

    def add(self, kind: str, role: str, column: int, row: int = 0):
        node = self.tree.nodes.new(kind)
        node[_TAG] = role
        node.name = f"MCP {role}"
        node.location = (self.shader.location[0] - 260 * column, self.shader.location[1] - 220 * row)
        return node

    def link(self, source, target):
        self.tree.links.new(source, target)

    def texture(self, image):
        """One texture node per image, so packed maps share it."""
        for node in self.tree.nodes:
            if _role(node) == "texture" and node.image == image:
                return node
        node = self.add("ShaderNodeTexImage", "texture", 4, len([n for n in self.tree.nodes if _role(n) == "texture"]))
        node.image = image
        return node

    def channel(self, image, channel: str):
        texture = self.texture(image)
        if channel == "A":
            return texture.outputs["Alpha"]
        for node in self.tree.nodes:
            if _role(node) == "separate" and any(
                link.from_node == texture for socket in node.inputs for link in socket.links
            ):
                return node.outputs[CHANNELS.index(channel)]
        node = self.add("ShaderNodeSeparateColor", "separate", 3, 1)
        self.link(texture.outputs["Color"], node.inputs[0])
        return node.outputs[CHANNELS.index(channel)]


def _source(socket):
    return socket.links[0].from_socket if socket.links else None


def _remove_role(tree, name: str) -> bool:
    """Remove the nodes that implement one map. Support nodes are collected afterwards."""
    nodes = [node for node in tree.nodes if (_role(node) or "").split(":")[0] == name]
    for node in nodes:
        tree.nodes.remove(node)
    return bool(nodes)


def _collect_unused(tree) -> None:
    while True:
        unused = [
            node
            for node in tree.nodes
            if _role(node) in _SUPPORT_ROLES and not any(socket.links for socket in node.outputs)
        ]
        if not unused:
            return
        for node in unused:
            tree.nodes.remove(node)


def _bind(builder: _Builder, targets: dict, name: str, spec: dict, image) -> None:
    """Create the nodes of one map. Marker reroutes record maps that connect straight from a texture."""
    if name in {"base_color", "emission"} or name == "normal":
        source = builder.texture(image).outputs["Color"]
    else:
        source = builder.channel(image, spec["channel"])

    if name == "normal":
        if spec["convention"] == "directx":
            # DirectX maps store -Y in green: flip it to Blender's OpenGL convention.
            separate = builder.add("ShaderNodeSeparateColor", "normal:split", 3, 3)
            flip = builder.add("ShaderNodeMath", "normal:flip", 3, 4)
            flip.operation = "SUBTRACT"
            flip.inputs[0].default_value = 1.0
            combine = builder.add("ShaderNodeCombineColor", "normal:combine", 2, 3)
            builder.link(source, separate.inputs[0])
            builder.link(separate.outputs[1], flip.inputs[1])
            builder.link(separate.outputs[0], combine.inputs[0])
            builder.link(flip.outputs[0], combine.inputs[1])
            builder.link(separate.outputs[2], combine.inputs[2])
            source = combine.outputs[0]
        node = builder.add("ShaderNodeNormalMap", "normal:map", 1, 3)
        node.space = "TANGENT"
        node.inputs["Strength"].default_value = float(spec.get("strength", 1.0))
        builder.link(source, node.inputs["Color"])
    elif name == "height" and spec["mode"] == "bump":
        node = builder.add("ShaderNodeBump", "height:bump", 1, 4)
        node.inputs["Strength"].default_value = float(spec.get("strength", 0.5))
        node.inputs["Distance"].default_value = float(spec.get("distance", 0.1))
        builder.link(source, node.inputs["Height"])
    elif name == "height":
        node = builder.add("ShaderNodeDisplacement", "height:displacement", 1, 5)
        node.inputs["Midlevel"].default_value = float(spec.get("midlevel", 0.5))
        node.inputs["Scale"].default_value = float(spec.get("distance", 0.1)) * float(spec.get("strength", 1.0))
        builder.link(source, node.inputs["Height"])
        builder.link(node.outputs["Displacement"], targets["displacement"])
    elif name == "ao" and spec["mode"] == "gltf":
        group_node = next(
            (node for node in builder.tree.nodes if node.type == "GROUP" and _group_name(node) == GLTF_GROUP), None
        )
        if group_node is None:
            group_node = builder.add("ShaderNodeGroup", "ao:output", 0, 5)
            group_node.node_tree = _gltf_group()
        builder.link(source, group_node.inputs["Occlusion"])
    elif name == "ao":
        node = builder.add("ShaderNodeMix", "ao:multiply", 1, -1)
        node.data_type = "RGBA"
        node.blend_type = "MULTIPLY"
        node.inputs[0].default_value = 1.0
        builder.link(source, node.inputs[7])  # color B
    elif name == "opacity" and spec["mode"] == "clip":
        node = builder.add("ShaderNodeMath", "opacity:clip", 1, 2)
        node.operation = "GREATER_THAN"
        node.inputs[1].default_value = float(spec.get("threshold", 0.5))
        builder.link(source, node.inputs[0])
        builder.link(node.outputs[0], targets["opacity"])
    else:
        marker = builder.add("NodeReroute", f"{name}:through", 1, list(MAPS).index(name))
        builder.link(source, marker.inputs[0])
        if name != "base_color":
            builder.link(marker.outputs[0], targets[name])
    if name == "emission":
        builder.shader.inputs["Emission Strength"].default_value = float(spec.get("strength", 1.0))


def _gltf_group():
    group = bpy.data.node_groups.get(GLTF_GROUP)
    if group is not None:
        return group
    group = bpy.data.node_groups.new(GLTF_GROUP, "ShaderNodeTree")
    if hasattr(group, "interface"):  # Blender 4.0+
        group.interface.new_socket("Occlusion", in_out="INPUT", socket_type="NodeSocketFloat")
    else:
        group.inputs.new("NodeSocketFloat", "Occlusion")
    return group


def _wire_shared_inputs(builder: _Builder, targets: dict, original_base: tuple) -> None:
    """Base color and normal can each be fed by two maps, so they are connected together at the end."""
    tree = builder.tree
    base = _find(tree, "base_color:through")
    multiply = _find(tree, "ao:multiply")
    if multiply is not None:
        color_a = multiply.inputs[6]
        if base is not None:
            builder.link(base.outputs[0], color_a)
        else:
            color_a.default_value = original_base
        builder.link(multiply.outputs[2], targets["base_color"])  # color result
    elif base is not None:
        builder.link(base.outputs[0], targets["base_color"])
    normal = _find(tree, "normal:map")
    bump = _find(tree, "height:bump")
    if bump is not None:
        if normal is not None:
            builder.link(normal.outputs["Normal"], bump.inputs["Normal"])
        builder.link(bump.outputs["Normal"], targets["normal"])
    elif normal is not None:
        builder.link(normal.outputs["Normal"], targets["normal"])


def _apply_coordinates(builder: _Builder, uv_map: str | None, mapping: dict | None) -> None:
    tree = builder.tree
    textures = [node for node in tree.nodes if _role(node) == "texture"]
    existing_uv, existing_mapping = _find(tree, "uv"), _find(tree, "mapping")
    if uv_map is None and mapping is None and existing_uv is None and existing_mapping is None:
        return  # textures use the active UV map without extra nodes
    uv = existing_uv
    if uv is None:
        uv = builder.add("ShaderNodeUVMap", "uv", 6, 0)
    if uv_map is not None:
        uv.uv_map = uv_map
    vector = uv.outputs[0]
    node = existing_mapping
    if node is None and mapping is not None:
        node = builder.add("ShaderNodeMapping", "mapping", 5, 0)
    if node is not None:
        if mapping is not None:
            if "scale" in mapping:
                node.inputs["Scale"].default_value = (*mapping["scale"], 1.0)
            if "offset" in mapping:
                node.inputs["Location"].default_value = (*mapping["offset"], 0.0)
            if "rotation" in mapping:
                node.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(mapping["rotation"]))
        builder.link(vector, node.inputs["Vector"])
        vector = node.outputs["Vector"]
    for texture in textures:
        if _foreign_link(texture.inputs["Vector"]) is None:
            builder.link(vector, texture.inputs["Vector"])


def _set_render_mode(material, spec: dict) -> None:
    clip = spec["mode"] == "clip"
    if hasattr(material, "surface_render_method"):  # Blender 4.2+
        material.surface_render_method = "DITHERED" if clip else "BLENDED"
    else:
        material.blend_method = "CLIP" if clip else "BLEND"
        if clip:
            material.alpha_threshold = float(spec.get("threshold", 0.5))


def _set_displacement_method(material) -> None:
    target = material if hasattr(material, "displacement_method") else getattr(material, "cycles", None)
    if target is not None:
        target.displacement_method = "BOTH"


# --- describing what is bound -----------------------------------------------------------


def _trace_texture(socket, depth: int = 0):
    """Follow the managed chain upstream from a node output to its texture node and channel."""
    node = socket.node
    if _role(node) == "texture":
        return node, "A" if socket.name == "Alpha" else None
    if depth > 6:
        return None, None
    if _role(node) == "separate":
        texture, _ = _trace_texture(_source(node.inputs[0]), depth + 1)
        return texture, CHANNELS[list(node.outputs).index(socket)]
    for candidate in node.inputs:
        upstream = _source(candidate)
        if upstream is not None and _role(upstream.node) is not None:
            return _trace_texture(upstream, depth + 1)
    return None, None


_ENTRY_INPUTS = {
    "normal:map": "Color",
    "height:bump": "Height",
    "height:displacement": "Height",
    "ao:multiply": 7,
    "opacity:clip": 0,
}


def bindings(tree) -> list[dict]:
    """The maps currently bound by this tool, read back from the node graph."""
    found = []
    for node in tree.nodes:
        role = _role(node) or ""
        name, _, part = role.partition(":")
        if part == "through":
            upstream = _source(node.inputs[0])
        elif role in _ENTRY_INPUTS:
            upstream = _source(node.inputs[_ENTRY_INPUTS[role]])
        elif role == "ao:output":
            upstream = _source(node.inputs["Occlusion"])
        else:
            continue
        if upstream is None:
            continue
        texture, channel = _trace_texture(upstream)
        if texture is None or texture.image is None:
            continue
        entry: dict = {
            "map": name,
            "image": texture.image.name,
            "color_space": texture.image.colorspace_settings.name,
        }
        if channel and MAPS[name][1]:
            entry["channel"] = channel
        if name == "normal":
            entry["convention"] = "directx" if _find(tree, "normal:flip") else "opengl"
            entry["strength"] = round(float(node.inputs["Strength"].default_value), 4)
        elif role in {"height:bump", "height:displacement", "opacity:clip", "ao:multiply", "ao:output"}:
            entry["mode"] = {
                "bump": "bump",
                "displacement": "displacement",
                "clip": "clip",
                "multiply": "multiply",
            }.get(part, "gltf")
        elif name == "opacity":
            entry["mode"] = "blend"
        found.append(entry)
    # An occlusion link into a pre-existing glTF group has no tagged entry node of its own.
    if not any(entry["map"] == "ao" for entry in found):
        for node in tree.nodes:
            if node.type == "GROUP" and _group_name(node) == GLTF_GROUP:
                upstream = _source(node.inputs["Occlusion"])
                if upstream is not None and _role(upstream.node) is not None:
                    texture, channel = _trace_texture(upstream)
                    if texture is not None and texture.image is not None:
                        found.append(
                            {
                                "map": "ao",
                                "image": texture.image.name,
                                "color_space": texture.image.colorspace_settings.name,
                                "channel": channel or "R",
                                "mode": "gltf",
                            }
                        )
    return sorted(found, key=lambda entry: list(MAPS).index(entry["map"]))


def _warnings(applied: dict[str, dict]) -> list[str]:
    warnings = []
    height = applied.get("height")
    if height and height["mode"] == "bump":
        warnings.append(
            "glTF has no height or bump input, so the bump map is not exported. Bake it into the normal map."
        )
    if height and height["mode"] == "displacement":
        warnings.append(
            "Displacement needs enough geometry, differs between Cycles and EEVEE, and is not exported to glTF."
        )
    if applied.get("ao", {}).get("mode") == "multiply":
        warnings.append(
            "Occlusion multiplied into base color is for Blender renders only: glTF export writes the base color "
            "without it. Use ao mode 'gltf' for export."
        )
    if applied.get("normal", {}).get("convention") == "directx":
        warnings.append(
            "The green channel is flipped with nodes, which renders correctly in Blender, but glTF export writes the "
            "original DirectX image without the flip, so its normals are inverted in glTF viewers. Before exporting, "
            "convert the file to an OpenGL normal map and bind it with convention 'opengl'."
        )
    return warnings


def set_texture_set(params: dict, *, policy: PathPolicy) -> dict:
    material = bpy.data.materials.get(params["name"])
    if material is None:
        raise MissingResourceError("Material not found")
    if material.library is not None:
        raise UnsupportedError("A linked library material cannot be edited")
    requested = _requested_maps(params)
    mapping = _validate_mapping(params.get("mapping"))
    uv_map = params.get("uv_map")
    removals = params.get("remove") or []
    if any(item not in MAPS for item in removals):
        raise ValueError(f"'remove' lists map names: {', '.join(MAPS)}")
    if both := sorted(set(removals) & set(requested)):
        raise ValueError(f"Cannot both set and remove: {', '.join(both)}")
    if not (requested or removals or mapping is not None or uv_map is not None):
        raise ValueError("Provide 'maps', 'orm', 'remove', 'mapping' or 'uv_map'")
    on_conflict = params.get("on_conflict", "error")
    if on_conflict not in ON_CONFLICT:
        raise ValueError(f"'on_conflict' must be one of: {', '.join(ON_CONFLICT)}")

    conflicts: list[tuple[str, Any, str]] = []
    if material.use_nodes and material.node_tree is not None:
        shader, output = _principled(material.node_tree)
        targets = _targets(material.node_tree, shader, output)
        for name, spec in requested.items():
            key = _target_for(name, spec)
            if foreign := _foreign_link(targets[key]):
                conflicts.append((name, key, foreign))
    if conflicts and on_conflict == "error":
        listed = "; ".join(f"{name}: the {key} input is fed by {kind}" for name, key, kind in conflicts)
        raise BridgeError(
            "conflict",
            f"Existing links would be replaced. {listed}. Pass on_conflict='replace' to disconnect them "
            "(their nodes are kept)",
        )

    # Validate every path, then load every image, before touching the material.
    resolved = {name: images.validate_path(spec["path"], policy, "Texture") for name, spec in requested.items()}
    created: list = []
    try:
        loaded = {
            name: images.load_with_color_space(resolved[name], MAPS[name][0], created, "Texture") for name in requested
        }
    except Exception:
        for image in created:
            bpy.data.images.remove(image)
        raise

    if not material.use_nodes:
        material.use_nodes = True
    tree = material.node_tree
    shader, output = _principled(tree)
    builder = _Builder(tree, shader)
    original_base = tuple(shader.inputs["Base Color"].default_value)

    replaced = [name for name in requested if _remove_role(tree, name)]
    removed = [name for name in removals if _remove_role(tree, name)]
    targets = _targets(tree, shader, output)
    for name, key, _ in conflicts:
        if targets[key] is not None:
            for link in list(targets[key].links):
                tree.links.remove(link)
        replaced.append(name)
    for name, spec in requested.items():
        _bind(builder, _targets(tree, shader, output), name, spec, loaded[name])
    _wire_shared_inputs(builder, _targets(tree, shader, output), original_base)
    _collect_unused(tree)
    _apply_coordinates(builder, uv_map, mapping)
    if "opacity" in requested:
        _set_render_mode(material, requested["opacity"])
    if requested.get("height", {}).get("mode") == "displacement":
        _set_displacement_method(material)

    result: dict = {
        "material": material.name,
        "bindings": bindings(tree),
        "replaced": sorted(set(replaced)),
        "removed": sorted(removed),
        "warnings": _warnings(requested),
        "material_users": material.users,
    }
    node = _find(tree, "mapping")
    uv = _find(tree, "uv")
    if uv is not None:
        result["uv_map"] = uv.uv_map or "(active)"
    if node is not None:
        result["mapping"] = {
            "scale": [round(float(value), 6) for value in node.inputs["Scale"].default_value[:2]],
            "offset": [round(float(value), 6) for value in node.inputs["Location"].default_value[:2]],
            "rotation": round(math.degrees(node.inputs["Rotation"].default_value[2]), 4),
        }
    return result
