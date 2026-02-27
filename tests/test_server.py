"""Tests for the MCP server — tool registration, connection handling, JSON schemas."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from blender_mcp_server.server import (
    mcp,
    BlenderConnection,
)


class TestToolRegistration:
    """Verify all expected tools are registered with correct metadata."""

    def _get_tool_names(self):
        return [t.name for t in mcp._tool_manager._tools.values()]

    def test_scene_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_scene_get_info" in names
        assert "blender_scene_list_objects" in names

    def test_object_read_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_object_get_transform" in names
        assert "blender_object_get_hierarchy" in names

    def test_object_mutation_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "blender_object_create",
            "blender_object_delete",
            "blender_object_translate",
            "blender_object_rotate",
            "blender_object_scale",
            "blender_object_duplicate",
        ]:
            assert tool in names

    def test_material_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "blender_material_list",
            "blender_material_create",
            "blender_material_assign",
            "blender_material_set_color",
            "blender_material_set_texture",
        ]:
            assert tool in names

    def test_render_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_render_still" in names
        assert "blender_render_animation" in names

    def test_export_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "blender_export_gltf",
            "blender_export_obj",
            "blender_export_fbx",
        ]:
            assert tool in names

    def test_history_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_history_undo" in names
        assert "blender_history_redo" in names

    def test_total_tool_count(self):
        assert len(self._get_tool_names()) == 22

    def test_all_tools_have_descriptions(self):
        for tool in mcp._tool_manager._tools.values():
            assert tool.description, f"Tool {tool.name} has no description"


class TestBlenderConnection:
    """Test the TCP client that communicates with the Blender add-on."""

    @pytest.mark.asyncio
    async def test_send_command_success(self):
        conn = BlenderConnection()
        response = {"id": "test-id", "success": True, "result": {"name": "Cube"}}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(
            return_value=json.dumps(response).encode() + b"\n"
        )
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        result = await conn.send_command("scene.get_info")
        assert result == {"name": "Cube"}

    @pytest.mark.asyncio
    async def test_send_command_error_response(self):
        conn = BlenderConnection()
        response = {"id": "test-id", "success": False, "error": "Object not found"}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(
            return_value=json.dumps(response).encode() + b"\n"
        )
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        with pytest.raises(RuntimeError, match="Object not found"):
            await conn.send_command("object.get_transform", {"name": "Missing"})

    @pytest.mark.asyncio
    async def test_send_command_connection_closed(self):
        conn = BlenderConnection()

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(return_value=b"")
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        conn._reader = mock_reader
        conn._writer = mock_writer

        with pytest.raises(ConnectionError):
            await conn.send_command("scene.get_info")

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        conn = BlenderConnection(host="127.0.0.1", port=19999)
        with pytest.raises(OSError):
            await conn.connect()

    @pytest.mark.asyncio
    async def test_auto_reconnect_on_first_call(self):
        conn = BlenderConnection()
        response = {"id": "test-id", "success": True, "result": {}}

        mock_reader = AsyncMock()
        mock_reader.readline = AsyncMock(
            return_value=json.dumps(response).encode() + b"\n"
        )
        mock_writer = AsyncMock()
        mock_writer.write = MagicMock()
        mock_writer.drain = AsyncMock()

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            result = await conn.send_command("scene.get_info")
            assert result == {}


class TestMCPProtocol:
    """Test the MCP server responds correctly to protocol messages."""

    def test_initialize_response(self):
        """MCP server should respond to initialize with capabilities."""
        import subprocess
        import sys

        init_msg = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.1"},
            },
        })

        result = subprocess.run(
            [sys.executable, "-m", "blender_mcp_server.server"],
            input=init_msg,
            capture_output=True,
            text=True,
            timeout=10,
        )

        response = json.loads(result.stdout.strip())
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "capabilities" in response["result"]
        assert "tools" in response["result"]["capabilities"]
