"""Tests for the MCP server — tool registration, connection handling, JSON schemas."""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from blender_mcp_server.server import (
    mcp,
    BlenderConnection,
    HEADLESS_JOB_MANAGER,
    python_exec,
    python_exec_async,
    render_still,
    job_status,
    job_cancel,
    job_list,
    main,
)
from blender_mcp_server.headless import HeadlessBlenderExecutor


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

    def test_python_exec_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_python_exec" in names
        assert "blender_python_exec_async" in names

    def test_job_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_job_status" in names
        assert "blender_job_cancel" in names
        assert "blender_job_list" in names

    def test_total_tool_count(self):
        assert len(self._get_tool_names()) == 27

    def test_all_tools_have_descriptions(self):
        for tool in mcp._tool_manager._tools.values():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_context_parameter_not_exposed_in_tool_schema(self):
        for tool in mcp._tool_manager._tools.values():
            schema = getattr(tool, "inputSchema", None) or getattr(
                tool, "parameters", {}
            )
            properties = schema.get("properties", {})
            assert "ctx" not in properties, f"Tool {tool.name} exposes ctx in schema"


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


class TestHeadlessExecutor:
    @pytest.mark.asyncio
    async def test_execute_parses_structured_payload(self):
        executor = HeadlessBlenderExecutor(blender_binary="blender")
        payload = {
            "result": {"ok": True},
            "stdout": "inner stdout\n",
            "stderr": "",
            "error": None,
            "timed_out": False,
            "cancelled": False,
        }

        proc = AsyncMock()
        proc.communicate = AsyncMock(
            return_value=(
                (
                    "noise before\n"
                    "__BLENDER_MCP_RESULT__=" + json.dumps(payload) + "\n"
                ).encode(),
                b"",
            )
        )
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc):
            result = await executor.execute(code="__result__ = {'ok': True}")

        assert result["result"] == {"ok": True}
        assert "noise before" in result["stdout"]
        assert "inner stdout" in result["stdout"]
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_execute_uses_factory_startup_by_default_with_blend_file(self):
        executor = HeadlessBlenderExecutor(blender_binary="blender")

        proc = AsyncMock()
        proc.communicate = AsyncMock(
            return_value=(( "__BLENDER_MCP_RESULT__=" + json.dumps({
                "result": {"ok": True},
                "stdout": "",
                "stderr": "",
                "error": None,
                "timed_out": False,
                "cancelled": False,
            }) + "\n").encode(), b"")
        )
        proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=proc) as create_proc:
            await executor.execute(code="__result__ = {'ok': True}", blend_file="/tmp/test.blend")

        cmd = create_proc.await_args.args
        assert "--factory-startup" in cmd
        assert "/tmp/test.blend" in cmd


class TestHeadlessTransportTools:
    @pytest.mark.asyncio
    async def test_python_exec_uses_headless_transport(self):
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        with patch(
            "blender_mcp_server.server.HeadlessBlenderExecutor.execute",
            new=AsyncMock(return_value={"result": {"mode": "headless"}}),
        ) as execute:
            result = await python_exec(
                ctx,
                code="__result__ = {'mode': 'headless'}",
                transport="headless",
            )

        assert json.loads(result) == {"result": {"mode": "headless"}}
        execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_headless_async_job_lifecycle(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        with patch(
            "blender_mcp_server.server.HeadlessBlenderExecutor.execute",
            new=AsyncMock(return_value={"result": {"ok": True}, "stdout": "", "stderr": "", "error": None, "cancelled": False, "timed_out": False}),
        ):
            created = json.loads(
                await python_exec_async(
                    ctx,
                    code="__result__ = {'ok': True}",
                    transport="headless",
                )
            )
            job_id = created["job_id"]
            await asyncio.sleep(0)
            status = json.loads(await job_status(ctx, job_id))

        assert job_id.startswith("headless-job-")
        assert status["status"] == "succeeded"
        assert status["result"] == {"ok": True}

    @pytest.mark.asyncio
    async def test_render_still_uses_headless_transport(self):
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        with patch(
            "blender_mcp_server.server.HeadlessBlenderExecutor.execute",
            new=AsyncMock(return_value={"result": {"output_path": "/tmp/test.png"}}),
        ) as execute:
            result = await render_still(
                ctx,
                output_path="/tmp/test.png",
                transport="headless",
                blend_file="/tmp/test.blend",
            )

        assert json.loads(result) == {"result": {"output_path": "/tmp/test.png"}}
        execute.assert_awaited_once()
        assert execute.await_args.kwargs["factory_startup"] is None

    @pytest.mark.asyncio
    async def test_job_list_merges_headless_jobs(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        HEADLESS_JOB_MANAGER._jobs["headless-job-1"] = {
            "job_id": "headless-job-1",
            "status": "queued",
            "created_at": 1.0,
        }
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()
        ctx.request_context.lifespan_context.send_command = AsyncMock(
            return_value={"jobs": [{"job_id": "bridge-job-1", "status": "running", "created_at": 2.0}]}
        )
        result = json.loads(await job_list(ctx))

        ids = {job["job_id"] for job in result["jobs"]}
        assert ids == {"bridge-job-1", "headless-job-1"}

    @pytest.mark.asyncio
    async def test_headless_job_cancel(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        ctx = MagicMock()
        ctx.request_context.lifespan_context = MagicMock()

        async def slow_execute(**_kwargs):
            await asyncio.sleep(10)
            return {"result": None, "stdout": "", "stderr": "", "error": None, "cancelled": False, "timed_out": False}

        with patch(
            "blender_mcp_server.server.HeadlessBlenderExecutor.execute",
            new=slow_execute,
        ):
            created = json.loads(
                await python_exec_async(ctx, code="pass", transport="headless")
            )
            job_id = created["job_id"]
            cancelled = json.loads(await job_cancel(ctx, job_id))

        assert cancelled["status"] == "cancelled"


class TestMCPProtocol:
    """Test the MCP server entrypoint configuration."""

    def test_main_runs_stdio_transport(self):
        with patch.object(mcp, "run") as run:
            main()
        run.assert_called_once_with(transport="stdio")
