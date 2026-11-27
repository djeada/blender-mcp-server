"""MCP tools for camera."""

from typing import Annotated, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from blender_mcp_server.app import bridge, bridge_result, mcp


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


@mcp.tool(
    name="blender_camera_frame",
    description=(
        "Move a camera (created if it does not exist) so an object or collection fits the frame with a margin. "
        "azimuth 0 views from the front, 90 from the right; elevation tilts up. aspect defaults to the render "
        "resolution. The subject is not changed and the active camera only changes with set_active."
    ),
)
async def camera_frame(
    ctx: Context,
    camera: str,
    object: str | None = None,
    collection: str | None = None,
    include_children: bool = True,
    azimuth: Annotated[float, Field(ge=-360, le=360)] = 0.0,
    elevation: Annotated[float, Field(ge=-90, le=90)] = 10.0,
    projection: Literal["PERSP", "ORTHO"] = "PERSP",
    lens: Annotated[float, Field(ge=1, le=5000)] = 70.0,
    margin: Annotated[float, Field(ge=1, le=10)] = 1.15,
    aspect: Annotated[float | None, Field(ge=0.05, le=20)] = None,
    set_active: bool = False,
) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "camera.frame",
            camera=camera,
            object=object,
            collection=collection,
            include_children=include_children,
            azimuth=azimuth,
            elevation=elevation,
            projection=projection,
            lens=lens,
            margin=margin,
            aspect=aspect,
            set_active=set_active,
        )
    }
