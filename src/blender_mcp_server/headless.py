"""Headless Blender execution helpers used as a fallback transport.

This path avoids executing heavy physics scripts inside the interactive
Blender add-on process. Instead, it runs a separate ``blender -b`` process,
executes the script there, and returns a structured result payload.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
from typing import Any

RESULT_PREFIX = "__BLENDER_MCP_RESULT__="
DEFAULT_TIMEOUT_SECONDS = 3600.0
MAX_FINISHED_JOBS = 100


def _default_timeout() -> float:
    """Timeout applied when a caller does not pass one (BLENDER_MCP_HEADLESS_TIMEOUT overrides)."""
    raw = os.environ.get("BLENDER_MCP_HEADLESS_TIMEOUT")
    return float(raw) if raw else DEFAULT_TIMEOUT_SECONDS


def validate_source(code: str | None, script_path: str | None) -> None:
    if code and script_path:
        raise ValueError("Provide either 'code' or 'script_path', not both")
    if not code and not script_path:
        raise ValueError("Either 'code' or 'script_path' must be provided")


def _cap_output(text: str, limit: int = 50000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... (truncated, {len(text)} total chars)"


def _safe_json(value: Any) -> Any:
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def _extract_payload(stdout: str) -> tuple[dict[str, Any] | None, str]:
    payload = None
    clean_lines: list[str] = []
    for line in stdout.splitlines():
        if line.startswith(RESULT_PREFIX):
            payload = json.loads(line[len(RESULT_PREFIX) :])
        else:
            clean_lines.append(line)
    cleaned = "\n".join(clean_lines)
    if stdout.endswith("\n"):
        cleaned += "\n"
    return payload, cleaned


def _build_wrapper_script(code_path: Path, args_path: Path) -> str:
    return textwrap.dedent(
        f"""
        import io
        import json
        import pathlib
        import traceback
        from contextlib import redirect_stdout, redirect_stderr

        import bpy
        import mathutils

        code = pathlib.Path({code_path.as_posix()!r}).read_text(encoding="utf-8")
        args = json.loads(pathlib.Path({args_path.as_posix()!r}).read_text(encoding="utf-8"))
        namespace = {{
            "bpy": bpy,
            "mathutils": mathutils,
            "args": args,
            "__result__": None,
        }}
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<mcp-headless-script>", "exec"), namespace)
            payload = {{
                "result": namespace.get("__result__"),
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
                "error": None,
                "timed_out": False,
                "cancelled": False,
            }}
        except BaseException as exc:  # SystemExit must still produce a result payload
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            payload = {{
                "result": None,
                "stdout": stdout_buf.getvalue(),
                "stderr": stderr_buf.getvalue(),
                "error": "".join(tb).strip(),
                "timed_out": False,
                "cancelled": False,
            }}

        print({RESULT_PREFIX!r} + json.dumps(payload, ensure_ascii=True, default=repr))
        """
    )


class HeadlessBlenderExecutor:
    """Run Blender scripts in a separate headless Blender process."""

    def __init__(self, blender_binary: str | None = None):
        self.blender_binary = blender_binary or os.environ.get("BLENDER_BIN", "blender")

    async def execute(
        self,
        *,
        code: str | None = None,
        script_path: str | None = None,
        args: dict[str, Any] | None = None,
        timeout_seconds: int | None = None,
        blend_file: str | None = None,
        factory_startup: bool | None = None,
        process_holder: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        validate_source(code, script_path)

        if script_path is not None:
            code = Path(script_path).read_text(encoding="utf-8")

        args = args or {}
        timeout = float(timeout_seconds) if timeout_seconds and timeout_seconds > 0 else _default_timeout()
        start = time.monotonic()

        with tempfile.TemporaryDirectory(prefix="blender-mcp-headless-") as tmpdir:
            tmp = Path(tmpdir)
            code_path = tmp / "script.py"
            args_path = tmp / "args.json"
            wrapper_path = tmp / "wrapper.py"

            code_path.write_text(code or "", encoding="utf-8")
            args_path.write_text(json.dumps(args), encoding="utf-8")
            wrapper_path.write_text(_build_wrapper_script(code_path, args_path), encoding="utf-8")

            cmd = [self.blender_binary, "-b"]
            if factory_startup is not False:
                cmd.append("--factory-startup")
            if blend_file:
                cmd.append(blend_file)
            cmd.extend(["--python", str(wrapper_path)])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if process_holder is not None:
                process_holder["process"] = proc

            try:
                stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                stdout_b, stderr_b = await proc.communicate()
                elapsed = time.monotonic() - start
                return {
                    "result": None,
                    "stdout": _cap_output(stdout_b.decode("utf-8", errors="replace")),
                    "stderr": _cap_output(stderr_b.decode("utf-8", errors="replace")),
                    "error": f"Execution exceeded timeout of {timeout:.3f}s",
                    "duration_seconds": round(elapsed, 4),
                    "timed_out": True,
                    "cancelled": False,
                }
            except asyncio.CancelledError:
                # Stop Blender, then let the cancellation propagate to the caller.
                if proc.returncode is None:
                    proc.kill()
                with contextlib.suppress(ProcessLookupError):
                    await proc.wait()
                raise

        elapsed = time.monotonic() - start
        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        payload, clean_stdout = _extract_payload(stdout)

        if payload is None:
            error = f"Headless Blender exited with code {proc.returncode} without a result payload"
            if stderr.strip():
                error = f"{error}\n{stderr.strip()}"
            return {
                "result": None,
                "stdout": _cap_output(stdout),
                "stderr": _cap_output(stderr),
                "error": error,
                "duration_seconds": round(elapsed, 4),
                "timed_out": False,
                "cancelled": False,
            }

        return {
            "result": _safe_json(payload.get("result")),
            "stdout": _cap_output(clean_stdout + payload.get("stdout", "")),
            "stderr": _cap_output(stderr + payload.get("stderr", "")),
            "error": payload.get("error"),
            "duration_seconds": round(elapsed, 4),
            "timed_out": bool(payload.get("timed_out")),
            "cancelled": bool(payload.get("cancelled")),
        }


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
        validate_source(code, script_path)
        self._prune_finished_jobs()
        job_id = f"headless-job-{uuid.uuid4().hex[:8]}"
        process_holder: dict[str, Any] = {}
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
            "process_holder": process_holder,
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
                    process_holder=process_holder,
                )
            except asyncio.CancelledError:
                job["status"] = "cancelled"
                job["cancelled"] = True
                job["error"] = "Execution cancelled"
                job["completed_at"] = time.time()
                raise
            except Exception as exc:  # e.g. missing Blender binary or unreadable script_path
                job["status"] = "failed"
                job["error"] = f"{type(exc).__name__}: {exc}"
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
            raise ValueError(f"Unknown job: {job_id}")
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
            raise ValueError(f"Unknown job: {job_id}")

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
