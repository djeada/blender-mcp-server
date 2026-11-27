"""Read-only checks of materials and their textures for a chosen delivery target.

Findings are 'error' (will look or export wrong), 'warning' (likely a problem) or
'heuristic' (a guess from names or typical values). Anything that cannot be judged is
listed as unchecked instead of being assumed fine.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

import bpy

from .paging import paginate
from .protocol import MissingResourceError, UnsupportedError

if TYPE_CHECKING:
    from .paths import PathPolicy

PROFILES: dict[str, dict] = {
    "gltf": {"max_texture_size": 4096, "max_texture_memory_mb": 256, "gltf": True},
    "mobile": {"max_texture_size": 2048, "max_texture_memory_mb": 64, "gltf": True},
    "render": {"max_texture_size": 16384, "max_texture_memory_mb": 4096, "gltf": False},
}
MAX_MATERIALS = 32
MAX_NODES_WALKED = 500
MAX_FINDINGS = 100
MAX_LISTED_NAMES = 10
MEMORY_ASSUMPTION = (
    "Estimate of uncompressed GPU memory: width x height x 4 channels (1 byte each, 4 for float images) plus one "
    "third for mipmaps. GPU texture compression, tiling and engine limits change the real figure."
)

# Principled input -> what a texture connected to it means.
SEMANTICS = {
    "Base Color": "base_color",
    "Metallic": "metallic",
    "Roughness": "roughness",
    "Normal": "normal",
    "Alpha": "alpha",
    "Emission": "emission",
    "Emission Color": "emission",
}
COLOR_SEMANTICS = frozenset({"base_color", "emission"})
DATA_SEMANTICS = frozenset({"metallic", "roughness", "normal", "height", "occlusion"})
_LINEAR_SPACES = ("non-color", "linear", "raw")
# Nodes the glTF exporter follows between a texture and a shader input.
_PASSTHROUGH = frozenset({"NodeReroute", "ShaderNodeSeparateColor", "ShaderNodeSeparateRGB"})
_PROCEDURAL = frozenset(
    {
        "ShaderNodeTexNoise",
        "ShaderNodeTexVoronoi",
        "ShaderNodeTexWave",
        "ShaderNodeTexGradient",
        "ShaderNodeTexChecker",
        "ShaderNodeTexBrick",
        "ShaderNodeTexMagic",
        "ShaderNodeTexMusgrave",
        "ShaderNodeValToRGB",
        "ShaderNodeBump",
    }
)
_NAME_HINTS = {
    "normal": re.compile(r"(^|[_\-. ])(normal|nrm|nor)([_\-. ]|$)"),
    "roughness": re.compile(r"(^|[_\-. ])(rough|roughness|rgh)([_\-. ]|$)"),
    "metallic": re.compile(r"(^|[_\-. ])(metal|metallic|metalness|mtl)([_\-. ]|$)"),
    "base_color": re.compile(r"(^|[_\-. ])(basecolor|base_color|albedo|diffuse)([_\-. ]|$)"),
}


class _Report:
    def __init__(self, allow: list[str]):
        self.allow = set(allow)
        self.findings: list[dict] = []
        self.allowed: list[dict] = []
        self.unchecked: list[dict] = []

    def add(self, check: str, severity: str, material: str, message: str, subject: str | None = None) -> None:
        entry = {"check": check, "severity": severity, "material": material, "message": message}
        if subject:
            entry["subject"] = subject
        excused = {check, f"{check}:{subject}", f"{check}:{material}"} & self.allow
        target = self.allowed if excused else self.findings
        if entry not in target:
            target.append(entry)

    def skip(self, material: str, what: str, reason: str) -> None:
        entry = {"material": material, "item": what, "reason": reason}
        if entry not in self.unchecked:
            self.unchecked.append(entry)


def _walk(socket, semantic: str, state: dict, channel: str | None, path: frozenset, depth: int) -> None:
    """Follow a shader input upstream, recording each image it reads and the nodes in between."""
    for link in socket.links:
        node = link.from_node
        if getattr(link, "is_valid", True) is False:
            state["invalid"].add(f"{node.name} -> {link.to_node.name}")
        if depth > 32 or len(state["visited"]) > MAX_NODES_WALKED:
            state["truncated"] = True
            return
        state["visited"].add(node.name)
        output = link.from_socket.name
        if node.type == "TEX_IMAGE" or node.type == "TEX_ENVIRONMENT":
            state["images"].append(
                {
                    "node": node,
                    "semantic": semantic,
                    "channel": "A" if output == "Alpha" else channel,
                    "through": path,
                }
            )
            vector = node.inputs.get("Vector")
            if vector is not None and vector.links:
                _walk_coordinates(vector, state, depth + 1)
            continue
        if node.type == "GROUP":
            state["groups"].add(node.name)
            continue
        next_channel, next_semantic = channel, semantic
        if node.bl_idname in {"ShaderNodeSeparateColor", "ShaderNodeSeparateRGB"}:
            next_channel = "RGBA"[list(node.outputs).index(link.from_socket)]
        if node.bl_idname == "ShaderNodeNormalMap":
            state["normal_maps"].append(node)
        if node.bl_idname in _PROCEDURAL:
            state["procedural"].add(node.bl_idname)
        state["via"].setdefault(semantic, set()).add(node.bl_idname)
        for item in node.inputs:
            if not item.links:
                continue
            if node.bl_idname == "ShaderNodeBump":
                next_semantic = "height" if item.name == "Height" else semantic
            if item.type == "VECTOR" and item.name == "Vector" and node.bl_idname.startswith("ShaderNodeTex"):
                _walk_coordinates(item, state, depth + 1)
                continue
            _walk(item, next_semantic, state, next_channel, path | {node.bl_idname}, depth + 1)


def _walk_coordinates(socket, state: dict, depth: int) -> None:
    for link in socket.links:
        node = link.from_node
        if depth > 32 or node.name in state["coordinates"]:
            return
        state["coordinates"].add(node.name)
        state["visited"].add(node.name)
        if node.bl_idname == "ShaderNodeTexCoord" and link.from_socket.name != "UV":
            state["coordinate_sources"].add(f"{link.from_socket.name} coordinates")
        elif node.bl_idname not in {"ShaderNodeTexCoord", "ShaderNodeUVMap", "ShaderNodeMapping", "NodeReroute"}:
            state["coordinate_sources"].add(node.bl_idname)
        for item in node.inputs:
            _walk_coordinates(item, state, depth + 1)


def _is_linear(color_space: str) -> bool:
    return any(color_space.lower().startswith(name) for name in _LINEAR_SPACES)


def _image_info(image, policy: PathPolicy) -> dict:
    """Describe an image without opening files outside the approved roots."""
    info: dict = {"name": image.name, "color_space": image.colorspace_settings.name}
    if image.source == "GENERATED":
        info["storage"] = "generated"
    elif image.packed_file is not None:
        info["storage"] = "packed"
    elif image.source in {"FILE", "TILED", "SEQUENCE", "MOVIE"}:
        path = os.path.realpath(str(bpy.path.abspath(image.filepath, library=image.library)))
        info["storage"] = "external"
        info["file"] = os.path.basename(path)  # full paths are not reported
        try:
            policy.validate_filepath(path)
        except PermissionError:
            info["status"] = "outside_approved_roots"
            return info
        if image.source != "FILE":
            info["status"] = "unchecked_sequence_or_tiles"
        elif not os.path.isfile(path):
            info["status"] = "missing"
            return info
    else:
        info["storage"] = image.source.lower()
    width, height = image.size[0], image.size[1]
    if width <= 0 or height <= 0:
        info.setdefault("status", "unreadable")
        return info
    info["size"] = [width, height]
    per_channel = 4 if image.is_float else 1
    info["estimated_bytes"] = int(width * height * 4 * per_channel * 4 / 3)
    return info


def _active_output(tree):
    outputs = [node for node in tree.nodes if node.type == "OUTPUT_MATERIAL"]
    return next((node for node in outputs if node.is_active_output), outputs[0] if outputs else None)


def _surface_shader(output):
    if output is None or not output.inputs["Surface"].links:
        return None
    node = output.inputs["Surface"].links[0].from_node
    seen = set()
    while node.bl_idname == "NodeReroute" and node.name not in seen and node.inputs[0].links:
        seen.add(node.name)
        node = node.inputs[0].links[0].from_node
    return node


def _check_material(material, profile: dict, report: _Report, images: dict, policy: PathPolicy) -> dict:
    name = material.name
    entry: dict = {"material": name, "users": material.users, "bindings": []}
    if not material.use_nodes or material.node_tree is None:
        report.skip(name, "node graph", "the material does not use nodes")
        entry["gltf_export"] = {"status": "unknown", "reasons": ["no node graph"]}
        return entry
    tree = material.node_tree
    output = _active_output(tree)
    shader = _surface_shader(output)
    if output is None:
        report.add("broken_shader_chain", "error", name, "The material has no output node")
    elif shader is None:
        report.add("broken_shader_chain", "error", name, "Nothing feeds the output's Surface input")

    state: dict = {
        "images": [],
        "visited": set(),
        "groups": set(),
        "procedural": set(),
        "normal_maps": [],
        "invalid": set(),
        "coordinates": set(),
        "coordinate_sources": set(),
        "via": {},
        "truncated": False,
    }
    export_reasons: list[str] = []
    unknown_reasons: list[str] = []
    principled = shader if shader is not None and shader.type == "BSDF_PRINCIPLED" else None
    if principled is not None:
        for socket in principled.inputs:
            semantic = SEMANTICS.get(socket.name)
            if not socket.links:
                continue
            if semantic is None:
                report.skip(name, f"Principled input '{socket.name}'", "its texture semantics are not checked")
                unknown_reasons.append(f"linked '{socket.name}' input")
                semantic = "other"
            if semantic == "normal":
                source = socket.links[0].from_node
                if source.type == "TEX_IMAGE":
                    report.add(
                        "normal_without_normal_map",
                        "error",
                        name,
                        "An image feeds Normal directly; it needs a Normal Map node",
                        source.name,
                    )
            _walk(socket, semantic, state, None, frozenset(), 0)
        metallic = principled.inputs["Metallic"]
        if not metallic.links and 0.1 < metallic.default_value < 0.9:
            report.add(
                "partial_metallic",
                "heuristic",
                name,
                f"Metallic is {metallic.default_value:.2f}; physical surfaces are usually 0 or 1",
            )
    elif shader is not None:
        report.skip(name, shader.bl_idname, "only Principled BSDF surfaces are analyzed")
        unknown_reasons.append(f"surface shader {shader.bl_idname}")
        for socket in shader.inputs:
            _walk(socket, "other", state, None, frozenset(), 0)

    occlusion_nodes = [
        node
        for node in tree.nodes
        if node.type == "GROUP"
        and node.node_tree is not None
        and node.node_tree.name.startswith("glTF Material Output")
    ]
    for node in occlusion_nodes:
        state["visited"].add(node.name)
        if (socket := node.inputs.get("Occlusion")) is not None:
            _walk(socket, "occlusion", state, None, frozenset(), 0)
    if output is not None:
        state["visited"].add(output.name)
        if shader is not None:
            state["visited"].add(shader.name)
        displacement = output.inputs.get("Displacement")
        if displacement is not None and displacement.links:
            export_reasons.append("displacement is not exported")
            _walk(displacement, "height", state, None, frozenset(), 0)

    for item in sorted(state["groups"]):
        if item not in {node.name for node in occlusion_nodes}:
            report.skip(name, f"node group '{item}'", "node groups are not traversed")
            unknown_reasons.append(f"node group '{item}'")
    if state["truncated"]:
        report.skip(name, "node graph", "traversal budget reached")
        unknown_reasons.append("graph too large to analyze")
    for link in sorted(state["invalid"]):
        report.add("invalid_link", "error", name, f"Blender marks the link {link} invalid", link)

    for node in state["normal_maps"]:
        if not node.inputs["Color"].links:
            report.add("empty_normal_map", "warning", name, "A Normal Map node has no texture connected", node.name)
        if node.space != "TANGENT":
            report.add("normal_space", "warning", name, f"Normal Map uses {node.space} space", node.name)
            export_reasons.append("only tangent-space normal maps are exported")
    if any(node.bl_idname == "ShaderNodeTexImage" and node.image is None for node in tree.nodes):
        for node in tree.nodes:
            if node.bl_idname == "ShaderNodeTexImage" and node.image is None and node.name in state["visited"]:
                report.add("no_image", "error", name, "A connected Image Texture node has no image", node.name)

    semantics_by_image: dict[str, set[str]] = {}
    seen_bindings = set()
    for use in state["images"]:
        node = use["node"]
        if node.image is None:
            continue
        image = node.image
        info = images.get(image.name)
        if info is None:
            info = images[image.name] = _image_info(image, policy)
        semantic, channel = use["semantic"], use["channel"]
        key = (semantic, image.name, channel)
        if key not in seen_bindings:
            seen_bindings.add(key)
            binding = {"semantic": semantic, "image": image.name, "node": node.name}
            if channel:
                binding["channel"] = channel
            entry["bindings"].append(binding)
        status = info.get("status")
        if status == "missing":
            report.add("missing_file", "error", name, f"The file '{info['file']}' does not exist", image.name)
        elif status == "unreadable":
            report.add("unreadable_image", "error", name, "Blender cannot read this image", image.name)
        elif status:
            report.skip(name, f"image '{image.name}'", status.replace("_", " "))
        # Alpha is stored linearly whatever the image's color space, so it is never a mismatch.
        if channel != "A":
            linear = _is_linear(info["color_space"])
            if semantic in DATA_SEMANTICS and not linear:
                report.add(
                    "color_space",
                    "error",
                    name,
                    f"{semantic} data is read as {info['color_space']}; use Non-Color",
                    image.name,
                )
            elif semantic in COLOR_SEMANTICS and linear and not image.is_float:
                report.add(
                    "color_space",
                    "warning",
                    name,
                    f"{semantic} is read as {info['color_space']}; color textures are normally sRGB",
                    image.name,
                )
            semantics_by_image.setdefault(image.name, set()).add("color" if semantic in COLOR_SEMANTICS else "data")
        lowered = os.path.splitext(image.name.lower())[0]
        hinted = {kind for kind, pattern in _NAME_HINTS.items() if pattern.search(lowered)}
        if len(hinted) == 1 and semantic in _NAME_HINTS and semantic not in hinted:
            report.add(
                "name_mismatch",
                "heuristic",
                name,
                f"The name suggests a {next(iter(hinted))} map but it is used as {semantic}",
                image.name,
            )
    for image_name, kinds in sorted(semantics_by_image.items()):
        if kinds == {"color", "data"}:
            report.add("mixed_use", "warning", name, "One image supplies both color and data channels", image_name)

    passive = {"NodeFrame", "ShaderNodeOutputMaterial"}
    unused = sorted(
        node.name for node in tree.nodes if node.name not in state["visited"] and node.bl_idname not in passive
    )
    if unused:
        listed = ", ".join(unused[:MAX_LISTED_NAMES])
        report.add("unused_nodes", "warning", name, f"{len(unused)} node(s) do not affect the output: {listed}")

    if profile["gltf"]:
        entry["gltf_export"] = _exportability(principled, shader, state, export_reasons, unknown_reasons)
        if entry["gltf_export"]["status"] == "unsupported":
            for reason in entry["gltf_export"]["reasons"]:
                report.add("gltf_unsupported", "error", name, f"glTF export: {reason}", name)
    return entry


def _exportability(principled, shader, state: dict, unsupported: list[str], unknown: list[str]) -> dict:
    """Judge only graph patterns known to export or not. Everything else is 'unknown'."""
    if shader is None:
        unsupported.append("no surface shader")
    elif principled is None:
        unknown.append("the surface is not a Principled BSDF")
    for kind in sorted(state["procedural"]):
        unsupported.append(f"{kind} is not exported; bake it to an image")
    for source in sorted(state["coordinate_sources"]):
        unsupported.append(f"textures use {source}; glTF supports UV coordinates")
    for semantic, kinds in sorted(state["via"].items()):
        extra = kinds - _PASSTHROUGH - _PROCEDURAL - {"ShaderNodeNormalMap"}
        if semantic == "normal" and extra & {"ShaderNodeCombineColor", "ShaderNodeMath"}:
            unsupported.append("the normal map is changed by nodes (such as a green flip) that are not exported")
            extra -= {"ShaderNodeCombineColor", "ShaderNodeMath"}
        if semantic == "alpha":
            extra -= {"ShaderNodeMath"}  # thresholds become alpha masks
        if semantic == "base_color" and "ShaderNodeMix" in extra:
            unknown.append("base color is mixed by nodes; the exporter keeps only some mix patterns")
            extra -= {"ShaderNodeMix"}
        if extra:
            unknown.append(f"{semantic} passes through {', '.join(sorted(extra))}")
    status = "unsupported" if unsupported else "unknown" if unknown else "supported"
    return {"status": status, "reasons": list(dict.fromkeys(unsupported + unknown))[:MAX_LISTED_NAMES]}


def _selected_materials(params: dict) -> tuple[list, dict]:
    if params.get("material") and params.get("object"):
        raise ValueError("Provide 'material' or 'object', not both")
    if params.get("material"):
        material = bpy.data.materials.get(params["material"])
        if material is None:
            raise MissingResourceError("Material not found")
        return [material], {}
    if params.get("object"):
        obj = bpy.data.objects.get(params["object"])
        if obj is None:
            raise MissingResourceError("Object not found")
        if not hasattr(obj, "material_slots") or obj.type not in {"MESH", "CURVE", "SURFACE", "META", "FONT"}:
            raise UnsupportedError(f"{obj.type} objects have no materials")
        found = {slot.material.name: slot.material for slot in obj.material_slots if slot.material}
        return [found[name] for name in sorted(found)], {}
    found = {
        slot.material.name: slot.material
        for obj in bpy.context.scene.objects
        for slot in getattr(obj, "material_slots", ())
        if slot.material
    }
    return [found[name] for name in sorted(found)], {"scope": "materials used in the scene"}


def _slot_findings(params: dict, report: _Report) -> None:
    if not params.get("object"):
        return
    obj = bpy.data.objects.get(params["object"])
    empty = [index for index, slot in enumerate(obj.material_slots) if slot.material is None]
    if empty:
        report.add("empty_slot", "warning", obj.name, f"Material slots {empty[:10]} are empty", obj.name)
    if not len(obj.material_slots):
        report.add("no_material", "warning", obj.name, "The object has no material slots", obj.name)


def diagnose(params: dict, *, policy: PathPolicy) -> dict:
    profile_name = params.get("profile", "gltf")
    if profile_name not in PROFILES:
        raise ValueError(f"'profile' must be one of: {', '.join(PROFILES)}")
    profile = dict(PROFILES[profile_name])
    for key in ("max_texture_size", "max_texture_memory_mb"):
        if params.get(key) is not None:
            profile[key] = params[key]
    allow = params.get("allow") or []
    if len(allow) > 100 or not all(isinstance(item, str) for item in allow):
        raise ValueError("'allow' lists up to 100 'check' or 'check:subject' strings")
    materials, scope = _selected_materials(params)
    limit = min(params.get("limit") or MAX_MATERIALS, MAX_MATERIALS)
    page, metadata = paginate(materials, {"limit": limit, "offset": params.get("offset") or 0})

    report = _Report(allow)
    images: dict[str, dict] = {}
    entries = [_check_material(material, profile, report, images, policy) for material in page]
    _slot_findings(params, report)

    total_bytes = 0
    for image_name, info in sorted(images.items()):
        total_bytes += info.get("estimated_bytes", 0)
        if size := info.get("size"):
            if max(size) > profile["max_texture_size"]:
                report.add(
                    "texture_size",
                    "error",
                    "(all)",
                    f"{size[0]}x{size[1]} exceeds the {profile['max_texture_size']} pixel limit",
                    image_name,
                )
            if profile["gltf"] and any(value & (value - 1) for value in size):
                report.add(
                    "non_power_of_two",
                    "heuristic",
                    "(all)",
                    f"{size[0]}x{size[1]} is not a power of two; some engines resize it",
                    image_name,
                )
    if total_bytes > profile["max_texture_memory_mb"] * 1024 * 1024:
        report.add(
            "texture_memory",
            "error",
            "(all)",
            f"About {total_bytes / 1024 / 1024:.0f} MB exceeds the {profile['max_texture_memory_mb']} MB budget",
        )

    order = {"error": 0, "warning": 1, "heuristic": 2}
    findings = sorted(report.findings, key=lambda f: (order[f["severity"]], f["material"], f["check"]))
    counts = {severity: sum(f["severity"] == severity for f in findings) for severity in order}
    status = "errors" if counts["error"] else "warnings" if counts["warning"] else "ok"
    if status == "ok" and report.unchecked:
        status = "ok_with_unchecked_items"
    listed_images = [images[name] for name in sorted(images)]
    return {
        "profile": {"name": profile_name, **profile},
        **scope,
        "summary": {
            "status": status,
            "errors": counts["error"],
            "warnings": counts["warning"],
            "heuristics": counts["heuristic"],
            "allowed": len(report.allowed),
            "unchecked": len(report.unchecked),
        },
        "findings": findings[:MAX_FINDINGS],
        "findings_truncated": len(findings) > MAX_FINDINGS,
        "allowed_findings": report.allowed[:MAX_FINDINGS],
        "unchecked": report.unchecked[:MAX_FINDINGS],
        "materials": entries,
        "images": listed_images[:MAX_FINDINGS],
        "estimated_texture_bytes": total_bytes,
        "memory_assumption": MEMORY_ASSUMPTION,
        "material_count": len(materials),
        **{key: metadata[key] for key in ("offset", "next_offset") if key in metadata},
    }
