"""The stdio server, connection lifecycle and versioned tool result handling."""

import json
import os
import shutil
from contextlib import asynccontextmanager
from importlib.metadata import version
from typing import Any, Literal

from mcp import types
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.headless import HeadlessBlenderExecutor, HeadlessJobManager
from blender_mcp_server.shared import protocol

HEADLESS_JOB_MANAGER = HeadlessJobManager()
Transport = Literal["bridge", "headless"]


class BlenderMCP(FastMCP):
    async def call_tool(self, name: str, arguments: dict[str, Any]):
        try:
            return await super().call_tool(name, arguments)
        except ToolError as exc:
            cause = exc.__cause__ or exc
            if isinstance(cause, ValidationError):
                error = protocol.BridgeError(
                    "invalid_arguments", "Tool arguments do not match the input schema", command=name
                )
            elif isinstance(cause, protocol.BridgeError):
                error = cause
            else:
                error = protocol.command_error(cause, None, None)
            data = error.as_dict()
            return types.CallToolResult(
                isError=True,
                structuredContent={"error": data},
                content=[types.TextContent(type="text", text=str(error))],
            )


@asynccontextmanager
async def blender_lifespan(server: FastMCP):
    conn = BlenderConnection()
    try:
        yield conn
    finally:
        await conn.disconnect()
        await HEADLESS_JOB_MANAGER.close()


mcp = BlenderMCP("Blender MCP Server", lifespan=blender_lifespan, log_level="INFO")


def get_connection(ctx: Context) -> BlenderConnection:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


async def bridge_result(ctx: Context, command: str, **params: Any) -> Any:
    payload = {key: value for key, value in params.items() if value is not None}
    return await get_connection(ctx).send_command(command, payload)


async def bridge(ctx: Context, command: str, **params: Any) -> str:
    return json.dumps(await bridge_result(ctx, command, **params), indent=2)


@mcp.tool(name="blender_status", description="Check live Blender queue health, versions and effective command policy.")
async def blender_status(ctx: Context, reconnect: bool = False) -> dict[str, Any]:
    conn = get_connection(ctx)
    live = None
    error = None
    if "bridge" in conn.policy.transports:
        try:
            live = await conn.send_command(protocol.BRIDGE_STATUS, reconnect=reconnect)
        except protocol.BridgeError as exc:
            error = exc.as_dict()
    headless_enabled = "headless" in conn.policy.transports
    binary_found = shutil.which(os.environ.get("BLENDER_BIN", "blender")) is not None
    headless_ready = (
        headless_enabled
        and binary_found
        and ("bridge" not in conn.policy.transports or (live is not None and not live["policy"]["local_restrictions"]))
    )
    return {
        "server_version": version("blender-mcp-server"),
        "protocol_version": protocol.PROTOCOL_VERSION,
        "mcp_tools": sorted(tool.name for tool in await mcp.list_tools()),
        "policy": conn.policy.summary(),
        "bridge": live,
        "bridge_error": error,
        "headless": {
            "enabled": headless_enabled,
            "ready": headless_ready,
            "blender_binary_found": binary_found,
            "commands": HeadlessBlenderExecutor.available_commands(conn.policy) if headless_ready else [],
        },
    }


async def headless_executor(ctx: Context, command: str) -> HeadlessBlenderExecutor:
    conn = get_connection(ctx)
    conn.policy.require_transport("headless")
    conn.policy.require_command(command)
    if "bridge" in conn.policy.transports:
        try:
            status = await conn.send_command(protocol.BRIDGE_STATUS)
        except protocol.BridgeError as exc:
            raise protocol.BridgeError(
                "policy_mismatch", "Headless requires a responsive bridge with the same policy", command=command
            ) from exc
        if status["policy"]["local_restrictions"]:
            raise protocol.BridgeError(
                "policy_mismatch",
                "Move local Blender safety preferences to the shared policy before using headless",
                command=command,
            )
    return HeadlessBlenderExecutor(configured_policy=conn.policy)
