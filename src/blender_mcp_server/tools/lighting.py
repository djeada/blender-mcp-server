"""MCP tools for lighting."""

from typing import Annotated, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from blender_mcp_server.app import bridge, bridge_result, mcp, page_limit

AreaShape = Literal["SQUARE", "RECTANGLE", "DISK", "ELLIPSE"]


@mcp.tool(
    name="blender_lighting_inspect",
    description=(
        "Report the scene's lighting without changing it: each light's world position, direction, energy, color and "
        "type-specific settings, shared light data, the active camera, the world, render engine and color "
        "management. include_options=true also lists valid view transforms, looks and displays."
    ),
)
async def lighting_inspect(
    ctx: Context,
    include_options: bool = False,
    limit: Annotated[int | None, Field(ge=1)] = None,
    offset: Annotated[int | None, Field(ge=0)] = None,
) -> dict:
    return {
        "result": await bridge_result(
            ctx, "lighting.inspect", include_options=include_options, limit=page_limit(limit), offset=offset
        )
    }


@mcp.tool(
    name="blender_color_management_set",
    description=(
        "Change render color management: view_transform, look, exposure (stops, -32 to 32), gamma (0-5) and "
        "display_device. Only the given settings change. Valid names vary by Blender version; see "
        "blender_lighting_inspect with include_options."
    ),
)
async def color_management_set(
    ctx: Context,
    view_transform: str | None = None,
    look: str | None = None,
    exposure: Annotated[float | None, Field(ge=-32, le=32)] = None,
    gamma: Annotated[float | None, Field(ge=0, le=5)] = None,
    display_device: str | None = None,
) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "render.set_color_management",
            view_transform=view_transform,
            look=look,
            exposure=exposure,
            gamma=gamma,
            display_device=display_device,
        )
    }


@mcp.tool(
    name="blender_light_create",
    description=(
        "Create a light. type is POINT, SUN, SPOT, or AREA (default POINT). Optionally set name, location, "
        "orientation via rotation (degrees) or look_at [x, y, z] target (not both), color [r, g, b] (0-1), "
        "energy, size (POINT/SPOT radius, AREA size), size_y (AREA rectangle only), angle in degrees (SUN "
        "only), spot_angle in degrees (SPOT only), spot_blend 0-1 (SPOT only), shape (AREA) and temperature in "
        "kelvin instead of color. Parameters that do not fit the type are rejected and nothing is created."
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
    shape: AreaShape | None = None,
    temperature: float | None = None,
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
        shape=shape,
        temperature=temperature,
    )


@mcp.tool(
    name="blender_light_update",
    description=(
        "Update an existing light by name. Optionally change type (POINT, SUN, SPOT, AREA), location, "
        "orientation via rotation (degrees) or look_at [x, y, z] target (not both), color [r, g, b] (0-1), "
        "energy, size (POINT/SPOT radius, AREA size), size_y (AREA rectangle only), angle in degrees (SUN "
        "only), spot_angle in degrees (SPOT only), spot_blend 0-1 (SPOT only), shape (AREA) and temperature in "
        "kelvin instead of color. A rejected update changes nothing. If other objects share the light data, set "
        "shared_data to 'update_all' or 'make_single_user'."
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
    shape: AreaShape | None = None,
    temperature: float | None = None,
    shared_data: Literal["error", "update_all", "make_single_user"] | None = None,
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
        shape=shape,
        temperature=temperature,
        shared_data=shared_data,
    )
