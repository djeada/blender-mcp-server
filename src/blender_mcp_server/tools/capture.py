"""Inspection views returned as MCP image content."""

from typing import Annotated, Any, Literal

from mcp import types
from mcp.server.fastmcp import Context
from pydantic import Field

from blender_mcp_server.app import Transport, bridge_result, headless_executor, mcp
from blender_mcp_server.wire import dumps

View = Literal["front", "back", "right", "left", "top", "bottom", "three_quarter"]
# Compact output starts smaller; image tokens grow with resolution.
COMPACT_RESOLUTION, DEFAULT_RESOLUTION = 384, 512


def image_content(report: dict[str, Any]) -> list[types.TextContent | types.ImageContent]:
    """Split a capture report into one metadata block and a labelled image per view."""
    images: list[types.TextContent | types.ImageContent] = []
    for entry in report["views"]:
        if data := entry.pop("png_base64", None):
            images.append(types.TextContent(type="text", text=f"view: {entry['view']}"))
            images.append(types.ImageContent(type="image", data=data, mimeType="image/png"))
    return [types.TextContent(type="text", text=dumps(report)), *images]


@mcp.tool(
    name="blender_view_capture",
    description=(
        "See an object or collection: returns labelled PNG images from chosen directions, framed to fit, without "
        "changing the scene, camera or lights. Give 'object' or 'collection'. mode 'solid' shows shape, 'material' "
        "shows materials, 'wireframe' shows topology. include_images=false returns only framing data, or file "
        "paths when save_directory is set, for clients that cannot view images."
    ),
    structured_output=False,
)
async def view_capture(
    ctx: Context,
    object: str | None = None,
    collection: str | None = None,
    views: Annotated[list[View] | None, Field(max_length=6)] = None,
    mode: Literal["solid", "material", "wireframe"] = "solid",
    projection: Literal["orthographic", "perspective"] = "orthographic",
    resolution: Annotated[int | None, Field(ge=64, le=1024)] = None,
    include_children: bool = True,
    include_images: bool = True,
    save_directory: str | None = None,
    max_bytes: int | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
):
    params = {
        "object": object,
        "collection": collection,
        "views": views,
        "mode": mode,
        "projection": projection,
        "resolution": resolution or (COMPACT_RESOLUTION if mcp.exposure.compact_output else DEFAULT_RESOLUTION),
        "include_children": include_children,
        "include_images": include_images,
        "save_directory": save_directory,
        "max_bytes": max_bytes,
    }
    if transport == "headless":
        executor = await headless_executor(ctx, "view.capture")
        report = await executor.execute_command(
            "view.capture", params, blend_file=blend_file, factory_startup=factory_startup
        )
    else:
        report = await bridge_result(ctx, "view.capture", **params)
    return image_content(report)
