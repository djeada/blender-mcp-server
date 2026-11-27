"""MCP tools for objects."""

from typing import Literal

from mcp.server.fastmcp import Context

from blender_mcp_server.app import bridge, bridge_result, mcp, page_limit


@mcp.tool(
    name="blender_object_get_transform",
    description="Get the position, rotation, and scale of a Blender object by name.",
)
async def object_get_transform(ctx: Context, name: str) -> str:
    return await bridge(ctx, "object.get_transform", name=name)


@mcp.tool(
    name="blender_object_get_hierarchy",
    description=(
        "Get the parent/child hierarchy of objects: the subtree of 'name', or the whole scene. Limit it with "
        "max_nodes and max_depth; offset pages the top level. Request a node with children_omitted by name for more."
    ),
)
async def object_get_hierarchy(
    ctx: Context,
    name: str | None = None,
    max_nodes: int | None = None,
    max_depth: int | None = None,
    offset: int | None = None,
) -> str:
    return await bridge(
        ctx,
        "object.get_hierarchy",
        name=name or None,
        max_nodes=page_limit(max_nodes),
        max_depth=max_depth,
        offset=offset,
    )


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


@mcp.tool(name="blender_object_list_modifiers", description="List the ordered modifier stack on an object.")
async def object_list_modifiers(ctx: Context, name: str) -> dict:
    return {"result": await bridge_result(ctx, "object.list_modifiers", name=name)}


@mcp.tool(name="blender_object_add_modifier", description="Add a Bevel, Subsurf, Mirror, or Solidify mesh modifier.")
async def object_add_modifier(
    ctx: Context,
    name: str,
    modifier_type: Literal["BEVEL", "SUBSURF", "MIRROR", "SOLIDIFY"],
    modifier_name: str | None = None,
    properties: dict | None = None,
) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "object.add_modifier",
            name=name,
            modifier_type=modifier_type,
            modifier_name=modifier_name,
            properties=properties,
        )
    }


@mcp.tool(name="blender_object_update_modifier", description="Update permitted settings on a named mesh modifier.")
async def object_update_modifier(ctx: Context, name: str, modifier_name: str, properties: dict) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "object.update_modifier",
            name=name,
            modifier_name=modifier_name,
            properties=properties,
        )
    }


@mcp.tool(name="blender_object_remove_modifier", description="Remove a supported modifier without baking it.")
async def object_remove_modifier(ctx: Context, name: str, modifier_name: str) -> dict:
    return {"result": await bridge_result(ctx, "object.remove_modifier", name=name, modifier_name=modifier_name)}
