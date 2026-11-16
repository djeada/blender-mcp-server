"""Headless execution, subprocess deadlines and shared-policy enforcement."""

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blender_mcp_server.app import HEADLESS_JOB_MANAGER
from blender_mcp_server.headless import HeadlessBlenderExecutor, HeadlessJobManager
from blender_mcp_server.server import job_status, python_exec, python_exec_async, render_still
from blender_mcp_server.shared import policy, protocol


def _context(config, send=None):
    ctx = MagicMock()
    conn = ctx.request_context.lifespan_context
    conn.policy = config
    conn.send_command = AsyncMock(return_value=send)
    return ctx


def _stream(data):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    return reader


@pytest.mark.asyncio
async def test_executor_uses_json_result_file_and_disables_autoexec(headless_policy, tmp_path):
    source = tmp_path / "model.blend"
    source.touch()
    proc = MagicMock(returncode=0, stderr=_stream(b""), stdout=_stream(b"native output\n"))
    proc.wait = AsyncMock(return_value=0)

    async def spawn(*cmd, **kwargs):
        assert cmd[:4] == ("blender", "-b", "--disable-autoexec", "--factory-startup")
        assert cmd[4] == str(source)
        tmp = Path(cmd[-1]).parent
        request = json.loads((tmp / "request.json").read_text())
        assert request["command"] == "python.execute"
        result = {"result": {"ok": True}, "stdout": "script output", "stderr": "", "error": None}
        (tmp / "result.json").write_text(json.dumps({"success": True, "result": result}))
        return proc

    executor = HeadlessBlenderExecutor(configured_policy=headless_policy)
    with patch("asyncio.create_subprocess_exec", side_effect=spawn):
        result = await executor.execute(code="pass", blend_file=str(source))
    assert result["result"] == {"ok": True}
    assert result["stdout"] == "native output\nscript output"


@pytest.mark.asyncio
async def test_headless_status_and_cancel_lifecycle(headless_policy):
    await HEADLESS_JOB_MANAGER.close()
    ctx = _context(headless_policy)
    with patch.object(HeadlessBlenderExecutor, "execute", new=AsyncMock(return_value={"result": "ok"})):
        job_id = json.loads(await python_exec_async(ctx, code="pass", transport="headless"))["job_id"]
        await HEADLESS_JOB_MANAGER._jobs[job_id]["task"]
    assert json.loads(await job_status(ctx, job_id))["status"] == "succeeded"
    await HEADLESS_JOB_MANAGER.close()


@pytest.mark.asyncio
async def test_typed_render_uses_its_own_command(headless_policy):
    configured = replace(headless_policy, allow_python=False, allow_inline_code=False)
    with patch.object(HeadlessBlenderExecutor, "execute_command", new=AsyncMock(return_value={})) as execute:
        await render_still(_context(configured), output_path="/tmp/image", transport="headless")
    assert execute.await_args.args[0] == "render.still"


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed_commands", [None, ("render.still",)])
async def test_headless_does_not_bypass_live_preferences(headless_policy, allowed_commands):
    config = replace(
        headless_policy, transports=("bridge", "headless"), output_roots=(), allowed_commands=allowed_commands
    )
    ctx = _context(config, {"policy": {"local_restrictions": True}})
    with patch("asyncio.create_subprocess_exec") as spawn:
        if allowed_commands is None:
            with pytest.raises(protocol.BridgeError, match="local Blender") as error:
                await python_exec(ctx, code="pass", transport="headless")
            assert error.value.code == "policy_mismatch"
        else:
            with pytest.raises(PermissionError, match="allowlist"):
                await python_exec(ctx, code="pass", transport="headless")
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_managed_script_and_project_paths_are_checked_before_spawn(headless_policy, tmp_path):
    approved = tmp_path / "works"
    approved.mkdir()
    (tmp_path / "outside.py").write_text("pass")
    (tmp_path / "outside.blend").touch()
    config = replace(headless_policy, script_roots=(str(approved),), output_roots=(str(approved),))
    executor = HeadlessBlenderExecutor(configured_policy=config)
    with patch("asyncio.create_subprocess_exec") as spawn:
        with pytest.raises(PermissionError, match="approved script"):
            await executor.execute(script_path=str(approved / ".." / "outside.py"))
        with pytest.raises(PermissionError, match="output roots"):
            await executor.execute_command("project.get_info", {}, blend_file=str(tmp_path / "outside.blend"))
    spawn.assert_not_called()


def test_policy_file_is_explicit_and_rejects_unknown_settings(monkeypatch, tmp_path):
    monkeypatch.delenv("BLENDER_MCP_POLICY_FILE", raising=False)
    assert policy.Policy.load().transports == ("bridge",)
    config = tmp_path / "policy.json"
    monkeypatch.setenv("BLENDER_MCP_POLICY_FILE", str(config))
    config.write_text('{"transports": ["headless"], "allowed_commands": []}')
    value = policy.Policy.load()
    assert value.policy_id and not value.allow_python
    with pytest.raises(PermissionError):
        value.require_command("scene.get_info")
    config.write_text('{"allow_pythn": true}')
    with pytest.raises(ValueError, match="Unknown policy"):
        policy.Policy.load()


@pytest.mark.asyncio
async def test_missing_blender_marks_job_failed(headless_policy):
    executor = HeadlessBlenderExecutor("/nonexistent/blender", headless_policy)
    manager = HeadlessJobManager()
    job_id = await manager.create_job(executor, code="pass")
    await manager._jobs[job_id]["task"]
    status = manager.get_status(job_id)
    assert status["status"] == "failed"
    assert status["error_details"]["code"] == "not_found"
    assert "BLENDER_BIN" in status["error"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [True, False])
async def test_subprocess_is_killed_on_timeout_or_cancellation(headless_policy, monkeypatch, cancel):
    spawned = asyncio.Event()
    proc = MagicMock(returncode=None, stdout=asyncio.StreamReader(), stderr=asyncio.StreamReader())
    proc.wait = AsyncMock(return_value=-9)

    async def spawn(*args, **kwargs):
        spawned.set()
        return proc

    monkeypatch.setenv("BLENDER_MCP_HEADLESS_TIMEOUT", "1" if cancel else "0.02")
    executor = HeadlessBlenderExecutor(configured_policy=headless_policy)
    with patch("asyncio.create_subprocess_exec", side_effect=spawn):
        task = asyncio.create_task(executor.execute(code="pass"))
        await spawned.wait()
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert (await task)["timed_out"]
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_headless_job_queries_obey_command_policy(headless_policy):
    from blender_mcp_server.server import job_cancel, job_list

    ctx = _context(replace(headless_policy, allowed_commands=("python.execute_async",)))
    for tool in (job_status, job_cancel, job_list):
        params = {} if tool is job_list else {"job_id": "headless-job-private"}
        with pytest.raises(PermissionError, match="allowlist"):
            await tool(ctx, **params)
