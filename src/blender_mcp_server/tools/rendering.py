"""MCP tools for rendering."""

import json

from mcp.server.fastmcp import Context

from blender_mcp_server.app import Transport, bridge, headless_executor, mcp
from blender_mcp_server.headless_scripts import RENDER_ANIMATION, RENDER_STILL


@mcp.tool(
    name="blender_render_still",
    description=(
        "Render the current scene as a still image and return the absolute path of the written file. "
        "Optionally set output path, resolution, and render engine (EEVEE, CYCLES, or WORKBENCH). "
        "A path starting with '//' is relative to the .blend file, or to a temp folder while the file is unsaved. "
        "Use transport='bridge' for the live Blender add-on session, or "
        "transport='headless' with blend_file='/path/to/file.blend' to render in a separate background Blender process."
    ),
)
async def render_still(
    ctx: Context,
    output_path: str = "//render.png",
    resolution_x: int | None = None,
    resolution_y: int | None = None,
    engine: str | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        result = await headless_executor().execute(
            code=RENDER_STILL,
            args={
                "output_path": output_path,
                "resolution_x": resolution_x,
                "resolution_y": resolution_y,
                "engine": engine,
            },
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps(result, indent=2)
    return await bridge(
        ctx,
        "render.still",
        output_path=output_path,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
        engine=engine or None,
    )


@mcp.tool(
    name="blender_render_animation",
    description=(
        "Render an animation and return the absolute output path prefix. Optionally set output path, frame range, "
        "and render engine (EEVEE, CYCLES, or WORKBENCH). "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with a blend_file "
        "to render in a separate background Blender process."
    ),
)
async def render_animation(
    ctx: Context,
    output_path: str = "//render_",
    frame_start: int | None = None,
    frame_end: int | None = None,
    engine: str | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        result = await headless_executor().execute(
            code=RENDER_ANIMATION,
            args={
                "output_path": output_path,
                "frame_start": frame_start,
                "frame_end": frame_end,
                "engine": engine,
            },
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps(result, indent=2)
    return await bridge(
        ctx,
        "render.animation",
        output_path=output_path,
        frame_start=frame_start,
        frame_end=frame_end,
        engine=engine or None,
    )
