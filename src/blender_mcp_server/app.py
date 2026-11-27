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

from blender_mcp_server.capabilities import OUTPUT_TOOL, SUPPORT_TOOLS, TOOL_GROUPS, Exposure
from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.headless import HeadlessBlenderExecutor, HeadlessJobManager
from blender_mcp_server.shared import protocol
from blender_mcp_server.wire import OutputStore, compact_result, compact_tool

HEADLESS_JOB_MANAGER = HeadlessJobManager()
Transport = Literal["bridge", "headless"]


class BlenderMCP(FastMCP):
    # Replaced once at startup from the command line and environment.
    exposure = Exposure()
    outputs = OutputStore()

    async def list_tools(self) -> list[types.Tool]:
        tools = [tool for tool in await super().list_tools() if self.exposure.advertises(tool.name)]
        return [compact_tool(tool) for tool in tools] if self.exposure.compact_output else tools

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        try:
            if name in TOOL_GROUPS or name in SUPPORT_TOOLS:
                self.exposure.require_advertised(name)
                self.exposure.require_arguments(name, arguments)
            result = await super().call_tool(name, arguments)
            if not self.exposure.compact_output:
                return result
            if name == OUTPUT_TOOL:  # its pages are already sized to the budget
                return compact_result(result, self.exposure.output)
            return compact_result(result, self.exposure.output, self.outputs, self.get_context().session)
        except (ToolError, protocol.BridgeError) as exc:
            cause: BaseException = exc
            while isinstance(cause, ToolError) and cause.__cause__ is not None:
                cause = cause.__cause__
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


def page_limit(limit: int | None) -> int | None:
    """Compact output pages every listing; full output keeps returning everything unless asked."""
    if limit is None and mcp.exposure.compact_output:
        return mcp.exposure.output.page_size
    return limit


async def bridge(ctx: Context, command: str, **params: Any) -> str:
    return json.dumps(await bridge_result(ctx, command, **params), indent=2)


@mcp.tool(
    name="blender_status",
    description=(
        "Check live Blender queue health, versions and effective command policy. detail='full' lists every tool "
        "and command; 'auto' summarizes them in the compact profile."
    ),
)
async def blender_status(
    ctx: Context, reconnect: bool = False, detail: Literal["auto", "summary", "full"] = "auto"
) -> dict[str, Any]:
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
    status = {
        "server_version": version("blender-mcp-server"),
        "protocol_version": protocol.PROTOCOL_VERSION,
        "profile": mcp.exposure.profile,
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
    if detail == "full" or (detail == "auto" and mcp.exposure.profile != "compact"):
        return status
    return _summarize_status(status)


def _summarize_status(status: dict[str, Any]) -> dict[str, Any]:
    """Keep what a client needs to act on; replace name lists with counts."""
    live = status["bridge"]
    if live is not None:
        keep = ("blender_version", "bridge_version", "generation", "main_thread_progress", "queue_depth")
        optional = ("oldest_queue_age_seconds", "active_request")
        live = {
            **{key: live[key] for key in keep if key in live},
            **{key: live[key] for key in optional if live.get(key) is not None},
            "command_count": len(live.get("commands", ())),
            "local_restrictions": live.get("policy", {}).get("local_restrictions"),
        }
    policy = status["policy"]
    return {
        "detail": "summary",
        "server_version": status["server_version"],
        "protocol_version": status["protocol_version"],
        "capabilities": {
            "profile": status["profile"],
            "advertised_groups": sorted(mcp.exposure.advertised),
            "on_demand_groups": sorted(mcp.exposure.on_demand),
            "advertised_tool_count": len(status["mcp_tools"]),
        },
        "policy": {key: policy[key] for key in ("id", "transports", "allow_python", "allow_inline_code")},
        "bridge": live,
        "bridge_error": status["bridge_error"],
        "headless": {key: status["headless"][key] for key in ("enabled", "ready")},
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
