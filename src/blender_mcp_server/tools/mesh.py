"""MCP tools for mesh inspection."""

from typing import Literal

from mcp.server.fastmcp import Context

from blender_mcp_server.app import bridge_result, mcp


@mcp.tool(
    name="blender_mesh_inspect",
    description=(
        "Read-only topology check of one mesh object: raw and evaluated (viewport modifier) counts, local and "
        "world bounds, materials, vertex groups, modifiers, connected components and defect findings with sample "
        "element IDs. 'source' picks the mesh that bounds, components, findings and IDs describe. "
        "'tolerance' is in local units."
    ),
)
async def mesh_inspect(
    ctx: Context,
    name: str,
    source: Literal["raw", "evaluated"] = "raw",
    check_duplicates: bool = False,
    include_regions: bool = False,
    tolerance: float = 1e-5,
    max_ids: int = 10,
    element_budget: int = 500_000,
) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "mesh.inspect",
            name=name,
            source=source,
            check_duplicates=check_duplicates,
            include_regions=include_regions,
            tolerance=tolerance,
            max_ids=max_ids,
            element_budget=element_budget,
        )
    }
