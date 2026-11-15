"""Tests for MCP connection."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blender_mcp_server.connection import STREAM_LIMIT, BlenderConnection, load_auth_token

from .helpers import _echo_stream


class TestBlenderConnection:
    """Test the TCP client that communicates with the Blender add-on."""

    @pytest.mark.asyncio
    async def test_send_command_success(self):
        conn = BlenderConnection()
        conn._reader, conn._writer = _echo_stream({"success": True, "result": {"name": "Cube"}})

        result = await conn.send_command("scene.get_info")
        assert result == {"name": "Cube"}

    @pytest.mark.asyncio
    async def test_send_command_error_response(self):
        conn = BlenderConnection()
        conn._reader, conn._writer = _echo_stream({"success": False, "error": "Object not found"})

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
        mock_writer.close = MagicMock()

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
    async def test_unreachable_blender_gives_actionable_error(self, monkeypatch):
        monkeypatch.delenv("BLENDER_MCP_PORT", raising=False)
        conn = BlenderConnection(host="127.0.0.1", port=19999)
        with (
            patch("asyncio.open_connection", new=AsyncMock(side_effect=ConnectionRefusedError("refused"))),
            pytest.raises(ConnectionError, match=r"Cannot reach Blender at 127\.0\.0\.1:19999 \(refused\).*add-on"),
        ):
            await conn.send_command("scene.get_info")

    @pytest.mark.asyncio
    async def test_auto_reconnect_on_first_call(self):
        conn = BlenderConnection()
        mock_reader, mock_writer = _echo_stream({"success": True, "result": {}})

        with patch("asyncio.open_connection", return_value=(mock_reader, mock_writer)):
            result = await conn.send_command("scene.get_info")
            assert result == {}


class TestConnectionHardening:
    @pytest.mark.asyncio
    async def test_requests_carry_auth_token(self):
        conn = BlenderConnection()
        conn._reader, conn._writer = _echo_stream({"success": True, "result": {}})
        await conn.send_command("scene.get_info")
        assert conn._writer.sent[0]["token"] == "test-token"

    def test_token_read_from_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("BLENDER_MCP_TOKEN")
        token_file = tmp_path / "token"
        token_file.write_text("from-file\n")
        monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(token_file))
        assert load_auth_token() == "from-file"

    def test_missing_token_raises_helpful_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("BLENDER_MCP_TOKEN")
        monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(tmp_path / "absent"))
        with pytest.raises(ConnectionError, match="auth token not found"):
            load_auth_token()

    def test_host_and_port_from_environment(self, monkeypatch):
        monkeypatch.setenv("BLENDER_MCP_HOST", "10.0.0.5")
        monkeypatch.setenv("BLENDER_MCP_PORT", "9999")
        conn = BlenderConnection()
        assert (conn.host, conn.port) == ("10.0.0.5", 9999)

    @pytest.mark.asyncio
    async def test_stream_limit_allows_large_responses(self):
        with patch("asyncio.open_connection", new=AsyncMock(return_value=(AsyncMock(), AsyncMock()))) as open_conn:
            await BlenderConnection().connect()
        assert open_conn.await_args.kwargs["limit"] == STREAM_LIMIT
        assert STREAM_LIMIT > 150_000

    @pytest.mark.asyncio
    async def test_stale_response_is_discarded(self):
        conn = BlenderConnection()
        stale = {"id": "old-request", "success": True, "result": "stale"}
        conn._reader, conn._writer = _echo_stream({"success": True, "result": "fresh"}, stale_first=stale)
        assert await conn.send_command("scene.get_info") == "fresh"

    @pytest.mark.asyncio
    async def test_connection_level_rejection_resets_connection(self):
        conn = BlenderConnection()
        reader, writer = _echo_stream({})
        rejection = json.dumps({"id": None, "success": False, "error": "Unauthorized"}).encode() + b"\n"
        reader.readline = AsyncMock(return_value=rejection)
        conn._reader, conn._writer = reader, writer
        with pytest.raises(ConnectionError, match="Unauthorized"):
            await conn.send_command("scene.get_info")
        assert conn._writer is None

    @pytest.mark.asyncio
    async def test_cancelled_request_resets_connection(self):
        conn = BlenderConnection()
        reader, writer = _echo_stream({})

        async def never():
            await asyncio.sleep(10)

        reader.readline = never
        conn._reader, conn._writer = reader, writer
        task = asyncio.create_task(conn.send_command("render.animation"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert conn._writer is None, "a late response must not be read by the next request"

    @pytest.mark.asyncio
    async def test_timeout_resets_connection(self):
        conn = BlenderConnection(timeout=0.01)
        reader, writer = _echo_stream({})

        async def never():
            await asyncio.sleep(10)

        reader.readline = never
        conn._reader, conn._writer = reader, writer
        with pytest.raises(TimeoutError):
            await conn.send_command("scene.get_info")
        assert conn._writer is None
