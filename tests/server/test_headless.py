"""Tests for MCP headless."""

import asyncio
import json
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blender_mcp_server.app import HEADLESS_JOB_MANAGER
from blender_mcp_server.headless import HeadlessBlenderExecutor, HeadlessJobManager
from blender_mcp_server.headless_scripts import EXPORT_FBX, EXPORT_GLTF, EXPORT_OBJ, RENDER_ANIMATION, RENDER_STILL
from blender_mcp_server.server import (
    job_cancel,
    job_list,
    job_status,
    python_exec,
    python_exec_async,
    render_still,
)

from .helpers import _FakeRender


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
            "blender_mcp_server.headless.HeadlessBlenderExecutor.execute",
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
            "blender_mcp_server.headless.HeadlessBlenderExecutor.execute",
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
            "blender_mcp_server.headless.HeadlessBlenderExecutor.execute",
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
            "blender_mcp_server.headless.HeadlessBlenderExecutor.execute",
            new=slow_execute,
        ):
            created = json.loads(await python_exec_async(ctx, code="pass", transport="headless"))
            job_id = created["job_id"]
            cancelled = json.loads(await job_cancel(ctx, job_id))

        assert cancelled["status"] == "cancelled"


class TestHeadlessRenderScripts:
    """Run the scripts sent to ``blender -b`` against a stand-in bpy module."""

    def _run(self, monkeypatch, tmp_path, script, args, *, blend_file="", engines=("BLENDER_EEVEE_NEXT", "CYCLES")):
        bpy = MagicMock()
        bpy.data.filepath = blend_file
        bpy.path.abspath = lambda path: path
        bpy.context.scene.render = _FakeRender(engines)
        monkeypatch.setitem(sys.modules, "bpy", bpy)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        namespace = {"args": args, "__result__": None}
        exec(compile(script, "<headless-render>", "exec"), namespace)
        return bpy, namespace["__result__"]

    def test_still_resolves_default_path_and_engine_alias(self, monkeypatch, tmp_path):
        args = {"output_path": "//render.png", "resolution_x": 64, "resolution_y": None, "engine": "eevee"}
        bpy, result = self._run(monkeypatch, tmp_path, RENDER_STILL, args)
        assert result == {
            "output_path": str(tmp_path / "blender-mcp" / "render.png"),
            "engine": "BLENDER_EEVEE_NEXT",
            "resolution": [64, 1080],
        }
        assert (tmp_path / "blender-mcp").is_dir()
        bpy.ops.render.render.assert_called_once_with(write_still=True)

    def test_animation_creates_output_folder(self, monkeypatch, tmp_path):
        args = {"output_path": str(tmp_path / "frames" / "f_"), "frame_start": 1, "frame_end": 3, "engine": None}
        bpy, result = self._run(monkeypatch, tmp_path, RENDER_ANIMATION, args)
        assert result["output_path"] == str(tmp_path / "frames" / "f_")
        assert result["frame_range"] == [1, 3]
        assert (tmp_path / "frames").is_dir()
        bpy.ops.render.render.assert_called_once_with(animation=True)

    def test_unknown_engine_is_reported_before_rendering(self, monkeypatch, tmp_path):
        args = {"output_path": str(tmp_path / "r.png"), "engine": "luxrender"}
        with pytest.raises(ValueError, match="Unknown render engine 'luxrender'.*CYCLES"):
            self._run(monkeypatch, tmp_path, RENDER_STILL, args)


class TestHeadlessExportScripts:
    """Run the export scripts sent to ``blender -b`` against a stand-in bpy module."""

    def _run(self, monkeypatch, tmp_path, script, args, *, blend_file=""):
        bpy = MagicMock()
        bpy.data.filepath = blend_file
        bpy.path.abspath = lambda path: str(tmp_path / path[2:]) if path.startswith("//") else path
        monkeypatch.setitem(sys.modules, "bpy", bpy)
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        namespace = {"args": args, "__result__": None}
        exec(compile(script, "<headless-export>", "exec"), namespace)
        return bpy, namespace["__result__"]

    def test_gltf_appends_extension_and_creates_folder(self, monkeypatch, tmp_path):
        args = {"filepath": str(tmp_path / "new" / "dir" / "model")}
        bpy, result = self._run(monkeypatch, tmp_path, EXPORT_GLTF, args)
        assert result["filepath"] == f"{tmp_path}/new/dir/model.glb"
        assert (tmp_path / "new" / "dir").is_dir()
        bpy.ops.export_scene.gltf.assert_called_once_with(filepath=result["filepath"])

    def test_obj_extension_check_ignores_case(self, monkeypatch, tmp_path):
        args = {"filepath": str(tmp_path / "a.OBJ")}
        bpy, result = self._run(monkeypatch, tmp_path, EXPORT_OBJ, args)
        assert result["filepath"] == str(tmp_path / "a.OBJ")
        bpy.ops.wm.obj_export.assert_called_once_with(filepath=result["filepath"])

    def test_fbx_blend_relative_path_from_unsaved_file(self, monkeypatch, tmp_path):
        args = {"filepath": "//scene.fbx"}
        bpy, result = self._run(monkeypatch, tmp_path, EXPORT_FBX, args)
        assert result["filepath"] == str(tmp_path / "blender-mcp" / "scene.fbx")
        bpy.ops.export_scene.fbx.assert_called_once_with(filepath=result["filepath"])

    def test_fbx_blend_relative_path_from_saved_file(self, monkeypatch, tmp_path):
        args = {"filepath": "//out/model"}
        bpy, result = self._run(monkeypatch, tmp_path, EXPORT_FBX, args, blend_file=str(tmp_path / "scene.blend"))
        assert result["filepath"] == str(tmp_path / "out" / "model.fbx")


class TestHeadlessJobFailures:
    @pytest.mark.asyncio
    async def test_missing_blender_binary_names_the_fix(self):
        with pytest.raises(FileNotFoundError, match="'/nonexistent/blender' not found.*BLENDER_BIN"):
            await HeadlessBlenderExecutor("/nonexistent/blender").execute(code="pass")

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
