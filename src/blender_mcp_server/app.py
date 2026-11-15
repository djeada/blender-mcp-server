"""Blender MCP Server — External MCP server that bridges Claude Desktop to Blender."""

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP

from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.headless import HeadlessBlenderExecutor, HeadlessJobManager

logger = logging.getLogger(__name__)

HEADLESS_JOB_MANAGER = HeadlessJobManager()
Transport = Literal["bridge", "headless"]


@asynccontextmanager
async def blender_lifespan(server: FastMCP):
    """Manage the Blender connection lifecycle."""
    conn = BlenderConnection()
    try:
        await conn.connect()
    except OSError:
        logger.warning("Could not connect to Blender on startup. Will retry on first tool call.")
    try:
        yield conn
    finally:
        await conn.disconnect()


mcp = FastMCP(
    "Blender MCP Server",
    lifespan=blender_lifespan,
    log_level="INFO",
)


def get_connection(ctx: Context) -> BlenderConnection:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


async def bridge(ctx: Context, command: str, **params: Any) -> str:
    """Forward a command to the add-on, omitting unset (None) parameters."""
    payload = {key: value for key, value in params.items() if value is not None}
    result = await get_connection(ctx).send_command(command, payload)
    return json.dumps(result, indent=2)


def headless_executor() -> HeadlessBlenderExecutor:
    if os.environ.get("BLENDER_MCP_HEADLESS", "1").lower() in {"0", "false", "no", "off"}:
        raise PermissionError("Headless transport is disabled (BLENDER_MCP_HEADLESS=0)")
    return HeadlessBlenderExecutor()
