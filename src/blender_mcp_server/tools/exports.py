"""MCP tools for exports."""

import json

from mcp.server.fastmcp import Context

from blender_mcp_server.app import Transport, bridge, headless_executor, mcp


async def _headless_export(
    ctx: Context, command: str, filepath: str, blend_file: str | None, factory_startup: bool | None
) -> str:
    result = await (await headless_executor(ctx, command)).execute_command(
        command,
        {"filepath": filepath},
        blend_file=blend_file,
        factory_startup=factory_startup,
        legacy_result=True,
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_export_gltf",
    description=(
        "Export the scene as glTF/GLB and return the absolute path written. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with blend_file="
        "'/path/to/file.blend' to export in a separate background Blender process."
    ),
)
async def export_gltf(
    ctx: Context,
    filepath: str,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        return await _headless_export(ctx, "export.gltf", filepath, blend_file, factory_startup)
    return await bridge(ctx, "export.gltf", filepath=filepath)


@mcp.tool(
    name="blender_export_obj",
    description=(
        "Export the scene as OBJ and return the absolute path written. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with blend_file="
        "'/path/to/file.blend' to export in a separate background Blender process."
    ),
)
async def export_obj(
    ctx: Context,
    filepath: str,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        return await _headless_export(ctx, "export.obj", filepath, blend_file, factory_startup)
    return await bridge(ctx, "export.obj", filepath=filepath)


@mcp.tool(
    name="blender_export_fbx",
    description=(
        "Export the scene as FBX and return the absolute path written. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with blend_file="
        "'/path/to/file.blend' to export in a separate background Blender process."
    ),
)
async def export_fbx(
    ctx: Context,
    filepath: str,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        return await _headless_export(ctx, "export.fbx", filepath, blend_file, factory_startup)
    return await bridge(ctx, "export.fbx", filepath=filepath)
