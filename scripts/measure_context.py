"""Report how many bytes each tool profile advertises over MCP. No Blender needed.

Usage: python scripts/measure_context.py
"""

import asyncio
import logging

from mcp.shared.memory import create_connected_server_and_client_session

from blender_mcp_server.capabilities import PROFILES, Exposure
from blender_mcp_server.server import mcp


async def measure_tool_lists() -> dict[str, tuple[int, int]]:
    """Return {profile: (tool count, bytes of the serialized tools/list result)}."""
    previous = mcp.exposure
    sizes = {}
    try:
        for profile in PROFILES:
            mcp.exposure = Exposure.create(profile)
            async with create_connected_server_and_client_session(mcp) as client:
                listed = await client.list_tools()
            sizes[profile] = (len(listed.tools), len(listed.model_dump_json(exclude_none=True, by_alias=True)))
    finally:
        mcp.exposure = previous
    return sizes


def main() -> None:
    logging.disable(logging.INFO)
    print(f"{'profile':10} {'tools':>5} {'tools/list bytes':>17}")
    for profile, (count, size) in asyncio.run(measure_tool_lists()).items():
        print(f"{profile:10} {count:5} {size:17,}")


if __name__ == "__main__":
    main()
