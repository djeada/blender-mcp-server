"""Blender script execution, source policy, output capture, and last-run status."""

from __future__ import annotations

import builtins
import io
import json
import logging
import math
import sys
import time
import traceback
import uuid
from contextlib import redirect_stderr, redirect_stdout
from typing import TYPE_CHECKING, Any

import bpy

from .objects import create_primitive_mesh_object

if TYPE_CHECKING:
    import threading

    from .paths import PathPolicy
    from .settings import RuntimeSettings

logger = logging.getLogger(__name__)


DEFAULT_SYNC_TIMEOUT = 30
DEFAULT_ASYNC_TIMEOUT = 300
MAX_SYNC_TIMEOUT = 300
MAX_ASYNC_TIMEOUT = 3600
MAX_OUTPUT_SIZE = 50000  # Cap stdout/stderr returned to client
LOG_CODE_PREVIEW_LEN = 120  # Max chars of code shown in log messages


def truncate(text: str, limit: int) -> str:
    """Truncate text with an ellipsis indicator."""
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def cap_output(text: str) -> str:
    """Cap output string to MAX_OUTPUT_SIZE."""
    if len(text) <= MAX_OUTPUT_SIZE:
        return text
    return text[:MAX_OUTPUT_SIZE] + f"\n… (truncated, {len(text)} total chars)"


def make_exec_builtins(blocked_modules: set[str]) -> dict[str, Any]:
    """Create a per-execution builtins dict with a guarded __import__."""
    exec_builtins = dict(builtins.__dict__)
    original_import = exec_builtins["__import__"]

    def guarded_import(name, *a, **kw):
        top_level = name.split(".")[0]
        if top_level in blocked_modules:
            raise ImportError(f"Import of '{name}' is blocked by MCP safety policy")
        return original_import(name, *a, **kw)

    exec_builtins["__import__"] = guarded_import
    return exec_builtins


class ScriptExecutionTimeout(BaseException):
    """Raised when script execution exceeds the configured timeout."""


class ScriptExecutionCancelled(BaseException):
    """Raised when script execution is cancelled cooperatively."""


def safe_json(value: Any) -> Any:
    """Ensure a value is JSON-serializable, falling back to repr()."""
    if value is None:
        return None
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


class ScriptExecutor:
    """Run scripts on Blender's main thread with capture and cooperative cancellation."""

    def __init__(self, settings: RuntimeSettings, policy: PathPolicy):
        self.settings = settings
        self.policy = policy
        self.last_execution: dict[str, Any] = {
            "request_id": None,
            "source": None,
            "status": None,
            "duration_seconds": None,
            "error_summary": None,
        }

    def prepare_source(self, params: dict) -> tuple[str, str]:
        """Resolve and authorize the same script source for sync and async execution."""
        code = params.get("code")
        script_path = params.get("script_path")
        if code and script_path:
            raise ValueError("Provide either 'code' or 'script_path', not both")
        if not code and not script_path:
            raise ValueError("Either 'code' or 'script_path' must be provided")
        if code is not None:
            if not self.settings.allow_inline_code or self.settings.safe_mode:
                raise PermissionError(
                    "Inline code execution is disabled (Allow Inline Code is off or Safe Mode is on). "
                    "Use script_path instead."
                )
            return code, f"inline ({truncate(code, LOG_CODE_PREVIEW_LEN)})"
        validated = self.policy.validate_script_path(str(script_path))
        with open(validated, encoding="utf-8") as handle:
            return handle.read(), f"file ({script_path})"

    def make_namespace(self, args: dict, cancel_event: threading.Event | None = None) -> dict:
        """Build the execution namespace for exec()."""
        import mathutils

        ns: dict[str, Any] = {
            "bpy": bpy,
            "math": math,
            "mathutils": mathutils,
            "mcp_create_mesh": create_primitive_mesh_object,
            "args": args or {},
            "__result__": None,
            "__builtins__": make_exec_builtins(self.settings.blocked_modules),
        }
        if cancel_event is not None:
            ns["__cancel_event__"] = cancel_event
        return ns

    def run_code(
        self,
        code: str,
        namespace: dict,
        timeout_seconds: float,
        request_id: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict:
        """Execute code with stdout/stderr capture and cooperative timeout checks."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        start = time.monotonic()
        previous_trace = sys.gettrace()

        def trace_calls(frame, event, arg):
            if event == "line":
                if cancel_event is not None and cancel_event.is_set():
                    raise ScriptExecutionCancelled("Execution cancelled")
                if timeout_seconds > 0 and (time.monotonic() - start) > timeout_seconds:
                    raise ScriptExecutionTimeout(f"Execution exceeded timeout of {timeout_seconds:.3f}s")
            return trace_calls

        sys.settrace(trace_calls)
        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(compile(code, "<mcp-script>", "exec"), namespace)
        except BaseException as exc:  # Includes SystemExit/KeyboardInterrupt, which must not reach Blender
            elapsed = time.monotonic() - start
            tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
            # Filter out internal bridge frames
            filtered = [line for line in tb_lines if __file__ not in line]
            error_str = "".join(filtered).strip()
            logger.warning(
                "Script execution failed [%s] after %.3fs: %s",
                request_id or "?",
                elapsed,
                truncate(str(exc), 200),
            )
            return {
                "result": None,
                "stdout": cap_output(stdout_buf.getvalue()),
                "stderr": cap_output(stderr_buf.getvalue()),
                "error": error_str,
                "duration_seconds": round(elapsed, 4),
                "timed_out": isinstance(exc, ScriptExecutionTimeout),
                "cancelled": isinstance(exc, ScriptExecutionCancelled),
            }
        finally:
            sys.settrace(previous_trace)

        elapsed = time.monotonic() - start
        logger.info(
            "Script execution succeeded [%s] in %.3fs",
            request_id or "?",
            elapsed,
        )
        return {
            "result": safe_json(namespace.get("__result__")),
            "stdout": cap_output(stdout_buf.getvalue()),
            "stderr": cap_output(stderr_buf.getvalue()),
            "error": None,
            "duration_seconds": round(elapsed, 4),
            "timed_out": False,
            "cancelled": False,
        }

    def execute(self, params: dict) -> dict:
        args = params.get("args", {})
        timeout_seconds = min(params.get("timeout_seconds", DEFAULT_SYNC_TIMEOUT), MAX_SYNC_TIMEOUT)

        request_id = f"exec-{uuid.uuid4().hex[:8]}"

        code, source_label = self.prepare_source(params)

        logger.info("python.execute [%s] starting: %s", request_id, source_label)

        namespace = self.make_namespace(args)
        result = self.run_code(code, namespace, timeout_seconds, request_id, cancel_event=None)

        self.last_execution = {
            "request_id": request_id,
            "source": source_label,
            "status": "error" if result.get("error") else "ok",
            "duration_seconds": result.get("duration_seconds"),
            "error_summary": (truncate(result["error"], 200) if result.get("error") else None),
        }
        return result
