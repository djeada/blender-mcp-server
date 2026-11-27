"""Read-only description of the scene's world, which provides environment light and background."""

MAX_LISTED_NODES = 32


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
