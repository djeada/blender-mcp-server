"""The scene's world, which provides environment light and background.

Editing never silently destroys existing work: a world with a custom node setup, or one
that other scenes use, is only changed when the caller says how.
"""

import math
from typing import Any

import bpy

from . import images
from .protocol import BridgeError, UnsupportedError


def _background_input(tree):
    """Follow the active world output to the node that feeds its surface."""
    outputs = [node for node in tree.nodes if node.type == "OUTPUT_WORLD"]
    output = next((node for node in outputs if node.is_active_output), outputs[0] if outputs else None)
    if output is None or not output.inputs["Surface"].links:
        return None
    return output.inputs["Surface"].links[0].from_node


def summary(world) -> dict | None:
    if world is None:
        return None
    info: dict = {"name": world.name, "users": world.users, "use_nodes": bool(world.use_nodes)}
    if not world.use_nodes or world.node_tree is None:
        info.update(kind="color", color=[round(channel, 6) for channel in world.color], strength=1.0)
        return info
    shader = _background_input(world.node_tree)
    info["node_count"] = len(world.node_tree.nodes)
    if shader is None:
        info["kind"] = "none"
        return info
    if shader.type != "BACKGROUND":
        info.update(kind="custom", surface_node=shader.bl_idname)
        return info
    color, strength = shader.inputs["Color"], shader.inputs["Strength"]
    if strength.links:
        info["strength_is_linked"] = True
    else:
        info["strength"] = round(float(strength.default_value), 6)
    if not color.links:
        info.update(kind="color", color=[round(float(value), 6) for value in color.default_value[:3]])
        return info
    source = color.links[0].from_node
    if source.type == "TEX_ENVIRONMENT":
        info.update(kind="environment", image=source.image.name if source.image else None)
    elif source.type == "TEX_SKY":
        info.update(kind="sky", sky_type=source.sky_type)
    else:
        info.update(kind="custom", color_node=source.bl_idname)
    return info


# --- typed world editing ---------------------------------------------------------------

MODES = ("color", "environment", "sky")
CONFLICT_MODES = ("error", "new_world", "replace")
# Sky models, by what controls them. Names differ between Blender versions.
PHYSICAL_SKIES = ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING")
ANALYTIC_SKIES = ("HOSEK_WILKIE", "PREETHAM")
MODE_PARAMETERS = {
    "color": ("color",),
    "environment": ("filepath", "rotation"),
    "sky": ("sky_type", "sun_elevation", "sun_rotation", "sun_intensity", "sun_disc", "turbidity"),
}
_TAG = "mcp_world_role"  # custom property marking the nodes this module created
_DEFAULT_COLOR = (0.05, 0.05, 0.05)


def _managed(tree) -> dict:
    return {node[_TAG]: node for node in tree.nodes if node.get(_TAG)}


def _surface_chain(tree) -> tuple[Any, list]:
    """The active output and every node that feeds it."""
    outputs = [node for node in tree.nodes if node.type == "OUTPUT_WORLD"]
    output = next((node for node in outputs if node.is_active_output), outputs[0] if outputs else None)
    if output is None:
        return None, []
    seen, queue = [], [output]
    while queue:
        node = queue.pop()
        for socket in node.inputs:
            for link in socket.links:
                if link.from_node not in seen:
                    seen.append(link.from_node)
                    queue.append(link.from_node)
    return output, seen


def conflict(world, scene) -> str | None:
    """Why editing this world in place could damage something, or None if it is safe."""
    if world is None:
        return None
    users = [other.name for other in bpy.data.scenes if other.world == world and other != scene]
    if users:
        return f"World '{world.name}' is shared with scene(s) {', '.join(sorted(users)[:5])}"
    if world.library is not None:
        return f"World '{world.name}' is linked from another file"
    if not world.use_nodes or world.node_tree is None:
        return None
    _, chain = _surface_chain(world.node_tree)
    if all(node.get(_TAG) for node in chain):
        return None
    if len(chain) == 1 and chain[0].type == "BACKGROUND" and not any(socket.links for socket in chain[0].inputs):
        return None  # a plain color, such as the factory world
    kinds = sorted({node.bl_idname for node in chain})
    return f"World '{world.name}' has a custom node setup ({', '.join(kinds[:6])})"


def current_settings(world) -> dict:
    """The settings of a world this module built, or of a plain one."""
    info = summary(world) or {}
    if world is None or not world.use_nodes or world.node_tree is None:
        return {"mode": "color", "color": info.get("color", list(_DEFAULT_COLOR)), "strength": 1.0}
    nodes = _managed(world.node_tree)
    if "lighting" not in nodes:
        if info.get("kind") == "color":
            return {"mode": "color", "color": info["color"], "strength": info.get("strength", 1.0)}
        return {}
    background = nodes["lighting"]
    settings: dict = {"strength": round(float(background.inputs["Strength"].default_value), 6)}
    if "camera" in nodes:
        color = nodes["camera"].inputs["Color"].default_value
        settings["camera_background"] = [round(float(value), 6) for value in color[:3]]
    if "environment" in nodes:
        image = nodes["environment"].image
        settings.update(
            mode="environment",
            rotation=round(math.degrees(nodes["mapping"].inputs["Rotation"].default_value[2]), 4),
            image=None
            if image is None
            else {
                "name": image.name,
                "size": list(image.size),
                "color_space": image.colorspace_settings.name,
            },
        )
    elif "sky" in nodes:
        sky = nodes["sky"]
        settings.update(mode="sky", sky_type=sky.sky_type)
        if sky.sky_type in PHYSICAL_SKIES:
            settings.update(
                sun_elevation=round(math.degrees(sky.sun_elevation), 4),
                sun_rotation=round(math.degrees(sky.sun_rotation), 4),
                sun_intensity=round(sky.sun_intensity, 6),
                sun_disc=bool(sky.sun_disc),
            )
        else:
            x, y, z = sky.sun_direction
            settings.update(
                sun_elevation=round(math.degrees(math.asin(max(-1.0, min(1.0, z)))), 4),
                sun_rotation=round(math.degrees(math.atan2(x, y)), 4),
                turbidity=round(sky.turbidity, 4),
            )
    else:
        color = background.inputs["Color"].default_value
        settings.update(mode="color", color=[round(float(value), 6) for value in color[:3]])
    return settings


def sky_types() -> list[str]:
    node_type = getattr(bpy.types, "ShaderNodeTexSky", None)
    if node_type is None:
        return []
    return [item.identifier for item in node_type.bl_rna.properties["sky_type"].enum_items]


def get(params: dict) -> dict:
    scene = bpy.context.scene
    world = scene.world
    reason = conflict(world, scene)
    return {
        "world": summary(world),
        "settings": current_settings(world),
        "editable_in_place": reason is None,
        "conflict": reason,
        "sky_types": sky_types(),
        "film_transparent": bool(scene.render.film_transparent),
        "engine": scene.render.engine,
    }


def _choose_sky(requested: str | None) -> str:
    available_types = sky_types()
    if requested is None or requested.upper() == "PHYSICAL":
        found = next((name for name in PHYSICAL_SKIES if name in available_types), None)
    else:
        found = requested.upper() if requested.upper() in available_types else None
    if found is None:
        raise UnsupportedError(
            f"This Blender build has no '{requested or 'physical'}' sky. Available: {', '.join(available_types)}"
        )
    return found


def _load_environment(filepath: str, policy):
    """Validate and load before anything changes. Returns the image and whether this call created it."""
    resolved = images.validate_path(filepath, policy, "Environment image")
    before = len(bpy.data.images)
    try:
        image = bpy.data.images.load(resolved, check_existing=True)
    except RuntimeError as exc:
        raise ValueError("Blender cannot read this environment image") from exc
    created = len(bpy.data.images) > before
    if problem := images.decode_problem(image, "Environment image"):
        if created:
            bpy.data.images.remove(image)
        raise ValueError(problem)
    return image, created


def _resolve(params: dict, existing: dict) -> dict:
    """Merge a request over the current settings and reject what does not apply, before any change."""
    mode = params.get("mode") or existing.get("mode")
    if mode not in MODES:
        raise ValueError(f"'mode' must be one of: {', '.join(MODES)}")
    for other, names in MODE_PARAMETERS.items():
        if other != mode and (wrong := [name for name in names if params.get(name) is not None]):
            raise ValueError(f"{', '.join(wrong)} applies to mode '{other}', not '{mode}'")
    same_mode = existing.get("mode") == mode
    settings = dict(existing) if same_mode else {}
    settings["mode"] = mode
    settings["strength"] = existing.get("strength", 1.0)
    if "camera_background" in existing:
        settings["camera_background"] = existing["camera_background"]
    for name in ("strength", "camera_background", *MODE_PARAMETERS[mode]):
        if params.get(name) is not None:
            settings[name] = params[name]
    if params.get("clear_camera_background"):
        if params.get("camera_background") is not None:
            raise ValueError("Provide 'camera_background' or 'clear_camera_background', not both")
        settings.pop("camera_background", None)
    for name in ("color", "camera_background"):
        value = settings.get(name)
        if value is not None and (len(value) != 3 or any(channel < 0 for channel in value)):
            raise ValueError(f"'{name}' must have three non-negative linear values")
    if mode == "color":
        settings.setdefault("color", list(_DEFAULT_COLOR))
    if mode == "environment" and params.get("filepath") is None and not (same_mode and existing.get("image")):
        raise ValueError("Environment mode needs 'filepath'")
    if mode == "sky":
        keep_type = existing.get("sky_type") if same_mode and params.get("sky_type") is None else None
        settings["sky_type"] = kind = keep_type or _choose_sky(params.get("sky_type"))
        physical = kind in PHYSICAL_SKIES
        wrong_names = ("turbidity",) if physical else ("sun_intensity", "sun_disc")
        if wrong := [name for name in wrong_names if params.get(name) is not None]:
            raise UnsupportedError(f"{', '.join(wrong)} does not apply to the {kind} sky")
        if not -90 <= settings.get("sun_elevation", 30.0) <= 90:
            raise ValueError("'sun_elevation' must be between -90 and 90 degrees")
        if not 1 <= settings.get("turbidity", 2.2) <= 10:
            raise ValueError("'turbidity' must be between 1 and 10")
        if settings.get("sun_intensity", 1.0) < 0:
            raise ValueError("'sun_intensity' must not be negative")
    return settings


def _build(world, settings: dict, image) -> None:
    """Replace the nodes this module manages. Unconnected nodes made by others are left alone."""
    world.use_nodes = True
    tree = world.node_tree
    previous = _managed(tree)
    if image is None and "environment" in previous:
        image = previous["environment"].image
    output, chain = _surface_chain(tree)
    for node in {*previous.values(), *chain}:
        if node != output:
            tree.nodes.remove(node)
    if output is None:
        output = tree.nodes.new("ShaderNodeOutputWorld")

    def add(kind: str, role: str, x: float, y: float = 0.0):
        node = tree.nodes.new(kind)
        node[_TAG] = role
        node.name = f"MCP {role}"
        node.location = (output.location[0] + x, output.location[1] + y)
        return node

    lighting = add("ShaderNodeBackground", "lighting", -400)
    lighting.inputs["Strength"].default_value = settings["strength"]
    if settings["mode"] == "color":
        lighting.inputs["Color"].default_value = (*settings["color"], 1.0)
    elif settings["mode"] == "environment":
        coordinates = add("ShaderNodeTexCoord", "coordinates", -1200)
        mapping = add("ShaderNodeMapping", "mapping", -1000)
        # A 'TEXTURE' mapping applies the inverse transform, so the environment itself turns by +rotation.
        mapping.vector_type = "TEXTURE"
        mapping.inputs["Rotation"].default_value = (0.0, 0.0, math.radians(settings.get("rotation", 0.0)))
        environment = add("ShaderNodeTexEnvironment", "environment", -700)
        environment.image = image
        tree.links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])
        tree.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
        tree.links.new(environment.outputs["Color"], lighting.inputs["Color"])
    else:
        sky = add("ShaderNodeTexSky", "sky", -700)
        sky.sky_type = settings["sky_type"]
        elevation = math.radians(settings.get("sun_elevation", 30.0))
        heading = math.radians(settings.get("sun_rotation", 0.0))
        if sky.sky_type in PHYSICAL_SKIES:
            sky.sun_elevation = elevation
            sky.sun_rotation = heading
            sky.sun_intensity = settings.get("sun_intensity", 1.0)
            sky.sun_disc = settings.get("sun_disc", True)
        else:
            flat = math.cos(elevation)
            sky.sun_direction = (flat * math.sin(heading), flat * math.cos(heading), math.sin(elevation))
            sky.turbidity = settings.get("turbidity", 2.2)
        tree.links.new(sky.outputs["Color"], lighting.inputs["Color"])

    shader = lighting.outputs["Background"]
    if "camera_background" in settings:
        camera = add("ShaderNodeBackground", "camera", -400, -300)
        camera.inputs["Color"].default_value = (*settings["camera_background"], 1.0)
        camera.inputs["Strength"].default_value = 1.0
        path = add("ShaderNodeLightPath", "light-path", -400, 300)
        mix = add("ShaderNodeMixShader", "mix", -200)
        tree.links.new(path.outputs["Is Camera Ray"], mix.inputs[0])
        tree.links.new(shader, mix.inputs[1])
        tree.links.new(camera.outputs["Background"], mix.inputs[2])
        shader = mix.outputs[0]
    tree.links.new(shader, output.inputs["Surface"])


def update(params: dict, *, policy) -> dict:
    scene = bpy.context.scene
    world = scene.world
    on_conflict = params.get("on_conflict", "error")
    if on_conflict not in CONFLICT_MODES:
        raise ValueError(f"'on_conflict' must be one of: {', '.join(CONFLICT_MODES)}")
    reason = conflict(world, scene)
    isolate = on_conflict == "new_world"
    if reason and on_conflict == "error":
        raise BridgeError(
            "conflict",
            f"{reason}. Pass on_conflict='new_world' to give this scene its own world and keep that one, or "
            "'replace' to overwrite its surface for every user",
        )
    if reason and on_conflict == "replace" and world.library is not None:
        raise UnsupportedError("A linked world cannot be replaced; use on_conflict='new_world'")

    # A plain or managed world supplies defaults. A custom setup has nothing reusable.
    settings = _resolve(params, current_settings(world))
    image = None
    if params.get("filepath") is not None:
        image, _ = _load_environment(params["filepath"], policy)
    elif settings["mode"] == "environment" and world is not None and world.use_nodes:
        existing = _managed(world.node_tree).get("environment")
        image = existing.image if existing else None

    created = world is None or isolate
    previous = world
    if created:
        world = bpy.data.worlds.new("MCP World")
    try:
        _build(world, settings, image)
    except Exception:
        if created:
            bpy.data.worlds.remove(world)
        raise
    result: dict = {}
    if created:
        if previous is not None:
            previous.use_fake_user = True  # otherwise Blender drops an unused world when the file is saved
            result["kept_world"] = previous.name
        scene.world = world
    result.update(world=world.name, created_world=created, settings=current_settings(world))
    notes = []
    if settings["mode"] == "sky" and settings["sky_type"] in PHYSICAL_SKIES:
        notes.append(
            "A physical sky is far brighter than a studio setup. Lower exposure with blender_color_management_set "
            "or reduce strength, and check the result in your render engine."
        )
    if reason and on_conflict == "replace":
        notes.append(f"Replaced the surface of a world that had a conflict: {reason}")
    if notes:
        result["notes"] = notes
    return result
