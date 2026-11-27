"""The MCP image contract of inspection captures, over the protocol."""

import base64
import json
from unittest.mock import AsyncMock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from blender_mcp_server.app import mcp
from blender_mcp_server.capabilities import Exposure
from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.server import main  # noqa: F401  (importing registers every tool)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40_000).decode()


@pytest.fixture
def bridge(monkeypatch):
    def respond(command, params):
        views = params.get("views") or ["three_quarter"]
        return {
            "target": {"object": params.get("object")},
            "resolution": [params["resolution"]] * 2,
            "views": [{"view": view, **({"png_base64": PNG} if params["include_images"] else {})} for view in views],
        }

    send = AsyncMock(side_effect=respond)

    async def send_command(connection, command, params=None, **kwargs):
        return await send(command, params)

    monkeypatch.setattr(BlenderConnection, "send_command", send_command)
    return send


async def _call(monkeypatch, profile, tool, arguments, describe=None):
    monkeypatch.setattr(mcp, "exposure", Exposure.create(profile))
    mcp._mcp_server._tool_cache.clear()
    async with create_connected_server_and_client_session(mcp) as client:
        await client.list_tools()
        if describe:
            await client.call_tool("blender_capability_describe", {"actions": [describe]})
        return await client.call_tool(tool, arguments)


@pytest.mark.parametrize("profile", ["full", "compact"])
@pytest.mark.asyncio
async def test_views_arrive_as_labelled_image_content(monkeypatch, bridge, profile):
    arguments = {"object": "Orc", "views": ["front", "right"]}
    if profile == "compact":
        result = await _call(
            monkeypatch,
            profile,
            "blender_capability_invoke",
            {"action": "blender_view_capture", "arguments": arguments},
            describe="blender_view_capture",
        )
    else:
        result = await _call(monkeypatch, profile, "blender_view_capture", arguments)
    assert not result.isError, result.content[0].text
    assert [block.type for block in result.content] == ["text", "text", "image", "text", "image"]
    assert [result.content[1].text, result.content[3].text] == ["view: front", "view: right"]
    for block in (result.content[2], result.content[4]):
        assert block.mimeType == "image/png" and block.data == PNG
    metadata = result.content[0].text
    assert json.loads(metadata)["views"] == [{"view": "front"}, {"view": "right"}]
    assert "png_base64" not in metadata and result.structuredContent is None
    assert bridge.await_args.args[1]["resolution"] == (384 if profile == "compact" else 512)


@pytest.mark.asyncio
async def test_text_only_clients_can_ask_for_metadata(monkeypatch, bridge):
    result = await _call(monkeypatch, "full", "blender_view_capture", {"object": "Orc", "include_images": False})
    assert [block.type for block in result.content] == ["text"]


@pytest.mark.parametrize(
    "arguments", [{"object": "Orc", "resolution": 4096}, {"object": "Orc", "views": ["front"] * 7}]
)
@pytest.mark.asyncio
async def test_oversized_requests_are_rejected_before_blender(monkeypatch, bridge, arguments):
    result = await _call(monkeypatch, "full", "blender_view_capture", arguments)
    assert result.isError and result.structuredContent["error"]["code"] == "invalid_arguments"
    bridge.assert_not_awaited()
