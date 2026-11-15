"""MCP tools for objects."""

from mcp.server.fastmcp import Context

from blender_mcp_server.app import bridge, mcp


@mcp.tool(
    name="blender_object_get_transform",
    description="Get the position, rotation, and scale of a Blender object by name.",
)
async def object_get_transform(ctx: Context, name: str) -> str:
    return await bridge(ctx, "object.get_transform", name=name)


@mcp.tool(
    name="blender_object_get_hierarchy",
    description="Get the parent/child hierarchy of objects. If name is provided, returns the subtree for that object. Otherwise returns the full scene hierarchy.",
)
async def object_get_hierarchy(ctx: Context, name: str | None = None) -> str:
    return await bridge(ctx, "object.get_hierarchy", name=name or None)


@mcp.tool(
    name="blender_object_create",
    description="Create a new mesh object in Blender. Supported types: cube, sphere, cylinder, plane, cone, torus.",
)
async def object_create(
    ctx: Context,
    mesh_type: str = "cube",
    name: str | None = None,
    location: list[float] | None = None,
    size: float = 2.0,
) -> str:
    return await bridge(ctx, "object.create_mesh", type=mesh_type, name=name or None, location=location, size=size)


@mcp.tool(
    name="blender_object_delete",
    description="Delete an object from the Blender scene by name.",
)
async def object_delete(ctx: Context, name: str) -> str:
    return await bridge(ctx, "object.delete", name=name)


@mcp.tool(
    name="blender_object_translate",
    description="Move an object. Provide either 'location' for absolute positioning or 'offset' for relative movement, not both.",
)
async def object_translate(
    ctx: Context,
    name: str,
    location: list[float] | None = None,
    offset: list[float] | None = None,
) -> str:
    return await bridge(ctx, "object.translate", name=name, location=location, offset=offset)


@mcp.tool(
    name="blender_object_rotate",
    description="Set the rotation of an object. Provide rotation as [x, y, z] angles. By default angles are in degrees.",
)
async def object_rotate(
    ctx: Context,
    name: str,
    rotation: list[float],
    degrees: bool = True,
) -> str:
    return await bridge(ctx, "object.rotate", name=name, rotation=rotation, degrees=degrees)


@mcp.tool(
    name="blender_object_scale",
    description="Set the scale of an object. Provide scale as [x, y, z].",
)
async def object_scale(ctx: Context, name: str, scale: list[float]) -> str:
    return await bridge(ctx, "object.scale", name=name, scale=scale)


@mcp.tool(
    name="blender_object_duplicate",
    description="Duplicate an object in the Blender scene. Optionally provide a new name.",
)
async def object_duplicate(ctx: Context, name: str, new_name: str | None = None) -> str:
    return await bridge(ctx, "object.duplicate", name=name, new_name=new_name or None)


@mcp.tool(
    name="blender_object_rename",
    description=(
        "Rename an object. Blender appends a .001 suffix when the requested name is taken; "
        "the returned 'name' is the canonical one."
    ),
)
async def object_rename(ctx: Context, name: str, new_name: str) -> str:
    return await bridge(ctx, "object.rename", name=name, new_name=new_name)


@mcp.tool(
    name="blender_object_parent",
    description=(
        "Parent an object to another object. Parenting to itself or a descendant is refused (cycle detection). "
        "Set keep_transform=true to preserve the object's current world transform via the parent inverse "
        "matrix; otherwise the object moves with the parent's local space."
    ),
)
async def object_parent(ctx: Context, name: str, parent: str, keep_transform: bool | None = None) -> str:
    return await bridge(ctx, "object.parent", name=name, parent=parent, keep_transform=keep_transform)


@mcp.tool(
    name="blender_object_unparent",
    description=(
        "Clear an object's parent. Set keep_transform=true to bake the current world transform first so the "
        "object stays in place; otherwise it keeps its local transform."
    ),
)
async def object_unparent(ctx: Context, name: str, keep_transform: bool | None = None) -> str:
    return await bridge(ctx, "object.unparent", name=name, keep_transform=keep_transform)


@mcp.tool(
    name="blender_history_undo",
    description="Undo the last operation in Blender.",
)
async def history_undo(ctx: Context) -> str:
    return await bridge(ctx, "history.undo")


@mcp.tool(
    name="blender_history_redo",
    description="Redo the last undone operation in Blender.",
)
async def history_redo(ctx: Context) -> str:
    return await bridge(ctx, "history.redo")
