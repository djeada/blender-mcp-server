"""Tests for the MCP server — tool registration, connection handling, JSON schemas."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blender_mcp_server.headless import HeadlessBlenderExecutor, HeadlessJobManager
from blender_mcp_server.server import (
    HEADLESS_JOB_MANAGER,
    STREAM_LIMIT,
    BlenderConnection,
    job_cancel,
    job_list,
    job_status,
    load_auth_token,
    main,
    mcp,
    python_exec,
    python_exec_async,
    render_still,
)
from blender_mcp_server.server import (
    material_set_color as material_set_color_tool,
)
from blender_mcp_server.server import (
    object_create as object_create_tool,
)


def _echo_stream(response_fields: dict, stale_first: dict | None = None):
    """Mock reader/writer pair that answers each written request with a matching id."""
    sent: list[dict] = []
    mock_writer = AsyncMock()
    mock_writer.write = MagicMock(side_effect=lambda data: sent.append(json.loads(data)))
    mock_writer.drain = AsyncMock()
    mock_writer.close = MagicMock()
    mock_writer.sent = sent
    lines: list[bytes] = []

    async def readline():
        if not lines:
            if stale_first is not None:
                lines.append(json.dumps(stale_first).encode() + b"\n")
            lines.append(json.dumps({"id": sent[-1]["id"], **response_fields}).encode() + b"\n")
        return lines.pop(0)

    mock_reader = AsyncMock()
    mock_reader.readline = readline
    return mock_reader, mock_writer


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
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "parameters", {})
            properties = schema.get("properties", {})
            assert "ctx" not in properties, f"Tool {tool.name} exposes ctx in schema"


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
    async def test_auto_reconnect_on_first_call(self):
        conn = BlenderConnection()
        mock_reader, mock_writer = _echo_stream({"success": True, "result": {}})

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
                ("noise before\n__BLENDER_MCP_RESULT__=" + json.dumps(payload) + "\n").encode(),
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
            return_value=(
                (
                    "__BLENDER_MCP_RESULT__="
                    + json.dumps(
                        {
                            "result": {"ok": True},
                            "stdout": "",
                            "stderr": "",
                            "error": None,
                            "timed_out": False,
                            "cancelled": False,
                        }
                    )
                    + "\n"
                ).encode(),
                b"",
            )
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
            new=AsyncMock(
                return_value={
                    "result": {"ok": True},
                    "stdout": "",
                    "stderr": "",
                    "error": None,
                    "cancelled": False,
                    "timed_out": False,
                }
            ),
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
            created = json.loads(await python_exec_async(ctx, code="pass", transport="headless"))
            job_id = created["job_id"]
            cancelled = json.loads(await job_cancel(ctx, job_id))

        assert cancelled["status"] == "cancelled"


class TestMCPProtocol:
    """Test the MCP server entrypoint configuration."""

    def test_main_runs_stdio_transport(self):
        with patch.object(mcp, "run") as run:
            main()
        run.assert_called_once_with(transport="stdio")


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


class TestToolParameters:
    def _ctx(self):
        ctx = MagicMock()
        ctx.request_context.lifespan_context.send_command = AsyncMock(return_value={})
        return ctx

    @pytest.mark.asyncio
    async def test_unset_parameters_are_omitted(self):
        ctx = self._ctx()
        await object_create_tool(ctx, mesh_type="cube")
        command, params = ctx.request_context.lifespan_context.send_command.await_args.args
        assert command == "object.create_mesh"
        assert params == {"type": "cube", "size": 2.0}

    @pytest.mark.asyncio
    async def test_material_set_color_params(self):
        ctx = self._ctx()
        await material_set_color_tool(ctx, name="M", color=[1, 0, 0])
        _command, params = ctx.request_context.lifespan_context.send_command.await_args.args
        assert params == {"name": "M", "color": [1, 0, 0]}

    def test_transport_schema_is_an_enum(self):
        for tool in mcp._tool_manager._tools.values():
            schema = getattr(tool, "parameters", {})
            transport = schema.get("properties", {}).get("transport")
            if transport is not None:
                assert set(transport["enum"]) == {"bridge", "headless"}, tool.name

    @pytest.mark.asyncio
    async def test_headless_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("BLENDER_MCP_HEADLESS", "0")
        with pytest.raises(PermissionError):
            await python_exec(self._ctx(), code="pass", transport="headless")

    @pytest.mark.asyncio
    async def test_async_headless_validates_before_creating_job(self):
        HEADLESS_JOB_MANAGER._jobs.clear()
        with pytest.raises(ValueError):
            await python_exec_async(self._ctx(), transport="headless")
        assert HEADLESS_JOB_MANAGER._jobs == {}


class TestHeadlessJobFailures:
    @pytest.mark.asyncio
    async def test_executor_exception_marks_job_failed(self):
        manager = HeadlessJobManager()
        job_id = await manager.create_job(HeadlessBlenderExecutor("/nonexistent/blender"), code="pass")
        await manager._jobs[job_id]["task"]
        status = manager.get_status(job_id)
        assert status["status"] == "failed"
        assert "FileNotFoundError" in status["error"]

    @pytest.mark.asyncio
    async def test_cancel_kills_process_and_propagates(self):
        executor = HeadlessBlenderExecutor("blender")
        proc = MagicMock()
        proc.returncode = None

        async def hang():
            await asyncio.sleep(10)

        proc.communicate = hang
        proc.wait = AsyncMock(return_value=-9)
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            task = asyncio.create_task(executor.execute(code="pass"))
            await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        proc.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_timeout_is_applied(self, monkeypatch):
        monkeypatch.setenv("BLENDER_MCP_HEADLESS_TIMEOUT", "0.01")
        executor = HeadlessBlenderExecutor("blender")
        proc = MagicMock()
        proc.returncode = None
        calls = {"n": 0}

        async def communicate():
            calls["n"] += 1
            if calls["n"] == 1:
                await asyncio.sleep(10)
            return b"", b""

        proc.communicate = communicate
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
            result = await executor.execute(code="pass")
        assert result["timed_out"] is True

    def test_finished_jobs_are_pruned(self):
        manager = HeadlessJobManager()
        for i in range(150):
            manager._jobs[f"headless-job-{i}"] = {"job_id": f"headless-job-{i}", "status": "succeeded", "created_at": i}
        manager._prune_finished_jobs()
        assert len(manager._jobs) < 100
        assert "headless-job-149" in manager._jobs
