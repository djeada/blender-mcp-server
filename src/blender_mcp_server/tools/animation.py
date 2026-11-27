"""MCP tools for animation."""

from mcp.server.fastmcp import Context

from blender_mcp_server.app import bridge, mcp, page_limit


@mcp.tool(
    name="blender_timeline_get",
    description="Get the current frame and scene frame range (frame_start, frame_current, frame_end).",
)
async def timeline_get(ctx: Context) -> str:
    return await bridge(ctx, "timeline.get")


@mcp.tool(
    name="blender_timeline_set",
    description=(
        "Set the current frame and/or scene frame range. Rotation-independent; frames are integers. "
        "Provide any subset of frame_current, frame_start, frame_end. Returns the resulting timeline."
    ),
)
async def timeline_set(
    ctx: Context,
    frame_current: int | None = None,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> str:
    return await bridge(ctx, "timeline.set", frame_current=frame_current, frame_start=frame_start, frame_end=frame_end)


@mcp.tool(
    name="blender_keyframe_add",
    description=(
        "Insert a keyframe on an object for a common animatable property: 'location', 'rotation' (values in "
        "degrees) or 'scale'. Optionally set the property's value at the given frame and an interpolation mode "
        "(BEZIER, LINEAR, CONSTANT) applied to the inserted keys. Returns the action name, keyframe count, "
        "and whether the key was inserted or overwrote an existing key."
    ),
)
async def keyframe_add(
    ctx: Context,
    name: str,
    property: str,
    frame: int,
    value: list[float] | None = None,
    interpolation: str | None = None,
) -> str:
    return await bridge(
        ctx,
        "keyframe.insert",
        name=name,
        property=property,
        frame=frame,
        value=value,
        interpolation=interpolation,
    )


@mcp.tool(
    name="blender_keyframe_list",
    description=(
        "List keyframes on an object for 'location', 'rotation' or 'scale'. Returns channel index, frame and "
        "value for each key (rotation values are radians as stored by Blender). Fails clearly when the "
        "object has no animation data."
    ),
)
async def keyframe_list(
    ctx: Context, name: str, property: str | None = None, limit: int | None = None, offset: int | None = None
) -> str:
    return await bridge(ctx, "keyframe.list", name=name, property=property, limit=page_limit(limit), offset=offset)


@mcp.tool(
    name="blender_keyframe_remove",
    description=(
        "Remove the keyframe(s) at a given frame on an object for 'location', 'rotation' or 'scale'. "
        "Returns how many keys were removed and the remaining count; fails clearly when none exist."
    ),
)
async def keyframe_remove(ctx: Context, name: str, property: str, frame: int) -> str:
    return await bridge(ctx, "keyframe.remove", name=name, property=property, frame=frame)
