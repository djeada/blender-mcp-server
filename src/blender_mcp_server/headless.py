"""Execute shared Blender commands in a background process with bounded output."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from blender_mcp_server.shared import ADDON_PATH, policy, protocol

MAX_FINISHED_JOBS = 100
OUTPUT_BYTES = 50_000
REQUEST_BYTES = 16 * 1024 * 1024
HEADLESS_COMMANDS = frozenset(
    {
        "python.execute",
        "python.execute_async",
        "project.get_info",
        "project.save",
        "render.still",
        "render.animation",
        "view.capture",
        "export.gltf",
        "export.obj",
        "export.fbx",
    }
)

HEADLESS_JOB_COMMANDS = frozenset({"job.status", "job.cancel", "job.list"})


def validate_source(code: str | None, script_path: str | None) -> None:
    if code and script_path:
        raise ValueError("Provide either 'code' or 'script_path', not both")
    if not code and not script_path:
        raise ValueError("Either 'code' or 'script_path' must be provided")


def _wrapper(request: Path, response: Path) -> str:
    return f"""
import importlib.util
import sys
spec = importlib.util.spec_from_file_location(
    "_mcp_blender_addon", {str(ADDON_PATH / "__init__.py")!r},
    submodule_search_locations=[{str(ADDON_PATH)!r}],
)
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
from _mcp_blender_addon.headless_runner import run
run({str(request)!r}, {str(response)!r})
"""


async def _read_output(stream: asyncio.StreamReader) -> str:
    output = bytearray()
    total = 0
    while chunk := await stream.read(65536):
        output.extend(chunk[: max(0, OUTPUT_BYTES - len(output))])
        total += len(chunk)
    text = output.decode("utf-8", errors="replace")
    if total > OUTPUT_BYTES:
        text += f"\n… (truncated, {total} total bytes)"
    return text


class HeadlessBlenderExecutor:
    """Run typed Blender operations or explicitly authorized Python in background Blender."""

    _active = 0

    def __init__(self, blender_binary: str | None = None, configured_policy: policy.Policy | None = None):
        self.blender_binary = blender_binary or os.environ.get("BLENDER_BIN", "blender")
        self.policy = configured_policy if configured_policy is not None else policy.Policy.load()

    @staticmethod
    def available_commands(config: policy.Policy) -> list[str]:
        names = []
        for name in sorted(HEADLESS_COMMANDS | HEADLESS_JOB_COMMANDS):
            try:
                config.require_command(name)
            except PermissionError:
                continue
            names.append(name)
        return names

    def prepare(self, command: str, params: dict, blend_file: str | None) -> str:
        self.policy.require_transport("headless")
        if command not in HEADLESS_COMMANDS:
            raise protocol.UnsupportedError("Command is unavailable in headless Blender")
        self.policy.require_command(command)
        source = ""
        if blend_file:
            source = policy.resolve_path(blend_file, "")
            if Path(blend_file).suffix.lower() != ".blend" or Path(source).suffix.lower() != ".blend":
                raise ValueError("Headless input must be a .blend file")
            if self.policy.output_roots is not None:
                if not self.policy.output_roots:
                    raise PermissionError("Configure explicit output_roots to load a headless .blend project")
                policy.require_within(source, self.policy.output_roots, "Project is outside configured output roots")
            if not os.path.isfile(source):
                raise FileNotFoundError("Headless input project does not exist")
        if command in {"python.execute", "python.execute_async"}:
            validate_source(params.get("code"), params.get("script_path"))
            if params.get("code") and not self.policy.allow_inline_code:
                raise PermissionError("Inline code execution is disabled by policy")
            if script_path := params.get("script_path"):
                resolved = policy.resolve_path(script_path, source)
                roots = self.policy.script_roots or (policy.project_directory(source),)
                policy.require_within(resolved, roots, "Script path is outside approved script roots")
                if Path(resolved).suffix.lower() != ".py":
                    raise ValueError("Script must be a .py file")
                if not os.path.isfile(resolved):
                    raise FileNotFoundError("Script file does not exist")
                params["script_path"] = resolved
        return source

    async def execute(
        self,
        *,
        code: str | None = None,
        script_path: str | None = None,
        args: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        blend_file: str | None = None,
        factory_startup: bool | None = None,
        command: str = "python.execute",
    ) -> dict:
        return await self.execute_command(
            command,
            {"code": code, "script_path": script_path, "args": args},
            blend_file=blend_file,
            factory_startup=factory_startup,
            timeout_seconds=timeout_seconds,
        )

    async def execute_command(
        self,
        command: str,
        params: dict,
        *,
        blend_file: str | None = None,
        factory_startup: bool | None = None,
        timeout_seconds: int | None = None,
        legacy_result: bool = False,
    ) -> dict:
        params = {k: v for k, v in params.items() if v is not None}
        source = self.prepare(command, params, blend_file)
        limit = (
            self.policy.long_timeout
            if command in protocol.LONG_COMMANDS or command == "python.execute_async"
            else self.policy.command_timeout
        )
        if command in {"python.execute", "python.execute_async"}:
            limit = min(limit, self.policy.max_script_seconds)
        if timeout_seconds is not None and (type(timeout_seconds) is not int or timeout_seconds <= 0):
            raise ValueError("Headless timeout_seconds must be a positive integer")
        default = policy.env_seconds("BLENDER_MCP_HEADLESS_TIMEOUT", limit)
        timeout = min(limit, timeout_seconds if timeout_seconds is not None else default)
        payload = json.dumps({"command": command, "params": params, "policy": asdict(self.policy)}, allow_nan=False)
        if len(payload.encode()) > REQUEST_BYTES:
            raise ValueError("Headless request exceeds the byte limit")
        if HeadlessBlenderExecutor._active >= self.policy.max_jobs:
            raise protocol.BridgeError("busy", "Headless Blender process capacity reached", retryable=True)
        HeadlessBlenderExecutor._active += 1
        try:
            return await self._run(payload, source, factory_startup, timeout, command, legacy_result)
        finally:
            HeadlessBlenderExecutor._active -= 1

    async def _run(
        self, payload: str, source: str, factory_startup: bool | None, timeout: float, command: str, legacy_result: bool
    ) -> dict:
        start = time.monotonic()
        script_command = command in {"python.execute", "python.execute_async"}
        with tempfile.TemporaryDirectory(prefix="blender-mcp-headless-") as directory:
            tmp = Path(directory)
            request, response, wrapper = tmp / "request.json", tmp / "result.json", tmp / "wrapper.py"
            request.write_text(payload, encoding="utf-8")
            wrapper.write_text(_wrapper(request, response), encoding="utf-8")
            cmd = [self.blender_binary, "-b", "--disable-autoexec"]
            if factory_startup is not False:
                cmd.append("--factory-startup")
            if source:
                cmd.append(source)
            cmd.extend(["--python-exit-code", "1", "--python", str(wrapper)])
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
                )
            except FileNotFoundError as exc:
                raise FileNotFoundError("Blender executable not found. Install Blender or set BLENDER_BIN") from exc

            async def collect():
                assert proc.stdout is not None and proc.stderr is not None
                stdout, stderr, _ = await asyncio.gather(
                    _read_output(proc.stdout), _read_output(proc.stderr), proc.wait()
                )
                return stdout, stderr

            try:
                stdout, stderr = await asyncio.wait_for(collect(), timeout=timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(proc.wait(), timeout=5)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                message = f"Headless Blender exceeded the {timeout:g}s deadline"
                if not script_command:
                    raise protocol.RequestTimeoutError("execution_timeout", message, command=command) from exc
                return {
                    "result": None,
                    "stdout": "",
                    "stderr": "",
                    "error": message,
                    "duration_seconds": round(time.monotonic() - start, 4),
                    "timed_out": True,
                    "cancelled": False,
                }

            if proc.returncode != 0 or not response.is_file():
                raise protocol.BridgeError(
                    "command_failed", "Headless Blender exited before returning a result", command=command
                )
            with response.open(encoding="utf-8") as handle:
                raw_response = handle.read(protocol.MAX_RESPONSE_BYTES + 1)
            if len(raw_response) > protocol.MAX_RESPONSE_BYTES:
                raise protocol.BridgeError(
                    "response_too_large", "Blender response exceeds the byte limit", command=command
                )
            envelope = json.loads(raw_response)
            if not envelope["success"]:
                error = envelope["error_details"]
                raise protocol.BridgeError(
                    error["code"],
                    error["message"],
                    command=command,
                    retryable=error["retryable"],
                    details=error["details"],
                )
            result: dict = envelope["result"]
            if legacy_result:
                return {
                    "result": result,
                    "stdout": stdout,
                    "stderr": stderr,
                    "error": None,
                    "duration_seconds": round(time.monotonic() - start, 4),
                    "timed_out": False,
                    "cancelled": False,
                }
            if script_command:
                result["duration_seconds"] = round(time.monotonic() - start, 4)
                for field, output in (("stdout", stdout), ("stderr", stderr)):
                    result[field] = (output + result[field])[: 2 * OUTPUT_BYTES]
            return result


class HeadlessJobManager:
    """Track async headless Blender executions inside the MCP server process."""

    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}

    async def create_job(
        self,
        executor: HeadlessBlenderExecutor,
        *,
        code: str | None = None,
        script_path: str | None = None,
        args: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        blend_file: str | None = None,
        factory_startup: bool | None = None,
    ) -> str:
        executor.prepare("python.execute_async", {"code": code, "script_path": script_path, "args": args}, blend_file)
        if sum(job["status"] in {"queued", "running"} for job in self._jobs.values()) >= executor.policy.max_jobs:
            raise protocol.BridgeError("busy", "Headless job capacity reached", retryable=True)
        self._prune_finished_jobs()
        job_id = f"headless-job-{uuid.uuid4().hex[:8]}"
        job = {
            "job_id": job_id,
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "completed_at": None,
            "result": None,
            "stdout": "",
            "stderr": "",
            "error": None,
            "cancelled": False,
            "timed_out": False,
            "task": None,
        }
        self._jobs[job_id] = job

        async def runner():
            job["status"] = "running"
            job["started_at"] = time.time()
            try:
                result = await executor.execute(
                    code=code,
                    script_path=script_path,
                    args=args,
                    timeout_seconds=timeout_seconds,
                    blend_file=blend_file,
                    factory_startup=factory_startup,
                    command="python.execute_async",
                )
            except asyncio.CancelledError:
                job["status"] = "cancelled"
                job["cancelled"] = True
                job["error"] = "Execution cancelled"
                job["completed_at"] = time.time()
                raise
            except Exception as exc:  # e.g. missing Blender binary or unreadable script_path
                job["status"] = "failed"
                error = protocol.command_error(exc, "python.execute_async", job_id)
                job["error"] = str(error)
                job["error_details"] = error.as_dict()
                job["completed_at"] = time.time()
                return
            job["result"] = result.get("result")
            job["stdout"] = result.get("stdout", "")
            job["stderr"] = result.get("stderr", "")
            job["error"] = result.get("error")
            job["cancelled"] = bool(result.get("cancelled"))
            job["timed_out"] = bool(result.get("timed_out"))
            job["completed_at"] = time.time()
            if job["cancelled"]:
                job["status"] = "cancelled"
            elif job["error"]:
                job["status"] = "failed"
            else:
                job["status"] = "succeeded"

        job["task"] = asyncio.create_task(runner())
        return job_id

    def _prune_finished_jobs(self) -> None:
        finished = [j for j in self._jobs.values() if j["status"] in {"succeeded", "failed", "cancelled"}]
        excess = len(finished) - MAX_FINISHED_JOBS + 1
        for job in sorted(finished, key=lambda j: j["created_at"])[: max(excess, 0)]:
            del self._jobs[job["job_id"]]

    def get_status(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            raise protocol.MissingResourceError("Unknown job")
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "created_at": job["created_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "result": job["result"],
            "stdout": job["stdout"],
            "stderr": job["stderr"],
            "error": job["error"],
            "error_details": job.get("error_details"),
            "cancelled": job["cancelled"],
            "timed_out": job["timed_out"],
        }

    def list_jobs(self) -> dict[str, Any]:
        jobs = [
            {
                "job_id": job["job_id"],
                "status": job["status"],
                "created_at": job["created_at"],
            }
            for job in self._jobs.values()
        ]
        return {"jobs": jobs}

    async def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._jobs.get(job_id)
        if not job:
            raise protocol.MissingResourceError("Unknown job")

        task = job.get("task")
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if job["status"] in {"queued", "running"}:
            job["status"] = "cancelled"
            job["completed_at"] = time.time()
            job["cancelled"] = True
        return {"job_id": job_id, "status": job["status"]}

    async def close(self) -> None:
        tasks = [job["task"] for job in self._jobs.values() if not job["task"].done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._jobs.clear()
