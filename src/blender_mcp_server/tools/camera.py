"""MCP tools for camera."""

from mcp.server.fastmcp import Context

from blender_mcp_server.app import bridge, mcp


@mcp.tool(
    name="blender_camera_create",
    description=(
        "Create a camera. Optionally set name, location, orientation via rotation (degrees) or look_at "
        "[x, y, z] target (not both), projection ('PERSP' or 'ORTHO'), focal length in mm (PERSP only), "
        "ortho_scale (ORTHO only), clip_start/clip_end, and set_active to make it the active scene camera."
    ),
)
async def camera_create(
    ctx: Context,
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    projection: str | None = None,
    lens: float | None = None,
    ortho_scale: float | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    set_active: bool | None = None,
) -> str:
    return await bridge(
        ctx,
        "camera.create",
        name=name,
        location=location,
        rotation=rotation,
        look_at=look_at,
        projection=projection,
        lens=lens,
        ortho_scale=ortho_scale,
        clip_start=clip_start,
        clip_end=clip_end,
        set_active=set_active,
    )


@mcp.tool(
    name="blender_camera_update",
    description=(
        "Update an existing camera by name. Optionally change location, orientation via rotation (degrees) "
        "or look_at [x, y, z] target (not both), projection ('PERSP' or 'ORTHO'), focal length in mm "
        "(PERSP only), ortho_scale (ORTHO only), clip_start/clip_end, and set_active to make it the "
        "active scene camera."
    ),
)
async def camera_update(
    ctx: Context,
    name: str,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    projection: str | None = None,
    lens: float | None = None,
    ortho_scale: float | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    set_active: bool | None = None,
) -> str:
    return await bridge(
        ctx,
        "camera.update",
        name=name,
        location=location,
        rotation=rotation,
        look_at=look_at,
        projection=projection,
        lens=lens,
        ortho_scale=ortho_scale,
        clip_start=clip_start,
        clip_end=clip_end,
        set_active=set_active,
    )
