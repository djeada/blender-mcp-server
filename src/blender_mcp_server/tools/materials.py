"""MCP tools for materials."""

from mcp.server.fastmcp import Context

from blender_mcp_server.app import bridge, mcp


@mcp.tool(
    name="blender_material_list",
    description="List all materials in the Blender file.",
)
async def material_list(ctx: Context) -> str:
    return await bridge(ctx, "material.list")


@mcp.tool(
    name="blender_material_create",
    description="Create a new material. Optionally set an initial base color as [r, g, b] or [r, g, b, a] with values 0-1.",
)
async def material_create(ctx: Context, name: str = "Material", color: list[float] | None = None) -> str:
    return await bridge(ctx, "material.create", name=name, color=color)


@mcp.tool(
    name="blender_material_assign",
    description="Assign an existing material to an object.",
)
async def material_assign(ctx: Context, object: str, material: str) -> str:
    return await bridge(ctx, "material.assign", object=object, material=material)


@mcp.tool(
    name="blender_material_set_color",
    description="Set the base color of a material. Color is [r, g, b] or [r, g, b, a] with values 0-1.",
)
async def material_set_color(ctx: Context, name: str, color: list[float]) -> str:
    return await bridge(ctx, "material.set_color", name=name, color=color)


@mcp.tool(
    name="blender_material_set_texture",
    description="Set an image texture as the base color of a material. Provide the file path to the image.",
)
async def material_set_texture(ctx: Context, name: str, filepath: str) -> str:
    return await bridge(ctx, "material.set_texture", name=name, filepath=filepath)
