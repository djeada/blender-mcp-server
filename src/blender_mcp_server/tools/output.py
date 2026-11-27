"""Read the rest of a response that exceeded the compact budget."""

from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from blender_mcp_server.app import mcp
from blender_mcp_server.wire import read_part


@mcp.tool(
    name="blender_output_read",
    description=(
        "Read part of a truncated response by its output_id without rerunning the command. 'path' selects a field, "
        "e.g. 'stdout' or 'result.findings.0.ids'. Follow next_offset for more."
    ),
)
async def output_read(
    ctx: Context,
    output_id: str,
    path: str = "",
    offset: Annotated[int, Field(ge=0)] = 0,
    limit: Annotated[int | None, Field(ge=1)] = None,
) -> dict[str, Any]:
    value = mcp.outputs.get(ctx.session, output_id)
    return read_part(value, path, offset, limit, mcp.exposure.output.max_response_bytes)
