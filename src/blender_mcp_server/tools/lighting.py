"""MCP tools for lighting."""

from mcp.server.fastmcp import Context

from blender_mcp_server.app import bridge, mcp


@mcp.tool(
    name="blender_light_create",
    description=(
        "Create a light. type is POINT, SUN, SPOT, or AREA (default POINT). Optionally set name, location, "
        "orientation via rotation (degrees) or look_at [x, y, z] target (not both), color [r, g, b] (0-1), "
        "energy, size (POINT/SPOT radius, AREA size), size_y (AREA rectangle only), angle in degrees (SUN "
        "only), spot_angle in degrees (SPOT only), and spot_blend 0-1 (SPOT only). Unsupported parameters "
        "for the chosen type produce explicit errors."
    ),
)
async def light_create(
    ctx: Context,
    light_type: str = "POINT",
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    color: list[float] | None = None,
    energy: float | None = None,
    size: float | None = None,
    size_y: float | None = None,
    angle: float | None = None,
    spot_angle: float | None = None,
    spot_blend: float | None = None,
) -> str:
    return await bridge(
        ctx,
        "light.create",
        type=light_type,
        name=name,
        location=location,
        rotation=rotation,
        look_at=look_at,
        color=color,
        energy=energy,
        size=size,
        size_y=size_y,
        angle=angle,
        spot_angle=spot_angle,
        spot_blend=spot_blend,
    )


@mcp.tool(
    name="blender_light_update",
    description=(
        "Update an existing light by name. Optionally change type (POINT, SUN, SPOT, AREA), location, "
        "orientation via rotation (degrees) or look_at [x, y, z] target (not both), color [r, g, b] (0-1), "
        "energy, size (POINT/SPOT radius, AREA size), size_y (AREA rectangle only), angle in degrees (SUN "
        "only), spot_angle in degrees (SPOT only), and spot_blend 0-1 (SPOT only). Unsupported parameters "
        "for the current type produce explicit errors."
    ),
)
async def light_update(
    ctx: Context,
    name: str,
    light_type: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    color: list[float] | None = None,
    energy: float | None = None,
    size: float | None = None,
    size_y: float | None = None,
    angle: float | None = None,
    spot_angle: float | None = None,
    spot_blend: float | None = None,
) -> str:
    return await bridge(
        ctx,
        "light.update",
        name=name,
        type=light_type,
        location=location,
        rotation=rotation,
        look_at=look_at,
        color=color,
        energy=energy,
        size=size,
        size_y=size_y,
        angle=angle,
        spot_angle=spot_angle,
        spot_blend=spot_blend,
    )
