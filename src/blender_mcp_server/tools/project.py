"""MCP tools for .blend project files."""

from mcp.server.fastmcp import Context

from blender_mcp_server.app import Transport, bridge_result, headless_executor, mcp


@mcp.tool(
    name="blender_project_get_info", description="Inspect the active or explicitly supplied headless .blend project."
)
async def project_get_info(ctx: Context, transport: Transport = "bridge", blend_file: str | None = None) -> dict:
    if transport == "headless":
        executor = await headless_executor(ctx, "project.get_info")
        return {"result": await executor.execute_command("project.get_info", {}, blend_file=blend_file)}
    return {"result": await bridge_result(ctx, "project.get_info")}


@mcp.tool(
    name="blender_project_save",
    description="Save the active project or save-as. Headless saves require an explicit output distinct from the source.",
)
async def project_save(
    ctx: Context,
    filepath: str | None = None,
    overwrite: bool = False,
    transport: Transport = "bridge",
    blend_file: str | None = None,
) -> dict:
    params = {"filepath": filepath, "overwrite": overwrite}
    if transport == "headless":
        executor = await headless_executor(ctx, "project.save")
        return {"result": await executor.execute_command("project.save", params, blend_file=blend_file)}
    return {"result": await bridge_result(ctx, "project.save", **params)}


@mcp.tool(name="blender_project_open", description="Open an existing .blend project. Confirm before discarding edits.")
async def project_open(ctx: Context, filepath: str, discard_changes: bool = False) -> dict:
    return {"result": await bridge_result(ctx, "project.open", filepath=filepath, discard_changes=discard_changes)}


@mcp.tool(name="blender_project_revert", description="Reload the active .blend file and discard unsaved edits.")
async def project_revert(ctx: Context, confirm: bool) -> dict:
    return {"result": await bridge_result(ctx, "project.revert", confirm=confirm)}
