"""Tests for Blender execution behavior."""

import os
import tempfile

import pytest


class TestPythonExecute:
    """Tests for the python.execute command handler."""

    def test_execution_namespace_exposes_safe_mesh_helper(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = callable(mcp_create_mesh) and math.pi > 3",
            },
        )
        assert result["result"] is True

    def test_inline_code_returns_result(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = {'answer': 42}",
            },
        )
        assert result["result"] == {"answer": 42}
        assert result["error"] is None
        assert "duration_seconds" in result

    def test_inline_code_captures_stdout(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "print('hello world')",
            },
        )
        assert "hello world" in result["stdout"]
        assert result["error"] is None

    def test_inline_code_captures_stderr(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "import sys; sys.stderr.write('warn\\n')",
            },
        )
        assert "warn" in result["stderr"]

    def test_inline_code_exception_returns_error(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "raise ValueError('boom')",
            },
        )
        assert result["error"] is not None
        assert "ValueError" in result["error"]
        assert "boom" in result["error"]
        assert result["result"] is None

    def test_args_passed_to_namespace(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = args['x'] + args['y']",
                "args": {"x": 10, "y": 20},
            },
        )
        assert result["result"] == 30

    def test_bpy_available_in_namespace(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = bpy.context.scene.name",
            },
        )
        assert result["result"] == "Scene"

    def test_no_result_set_returns_null(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "x = 1 + 1",
            },
        )
        assert result["result"] is None
        assert result["error"] is None

    def test_non_json_result_falls_back_to_repr(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = {1, 2, 3}",
            },
        )
        # Sets aren't JSON-serializable, should get repr
        assert result["result"] is not None
        assert result["error"] is None

    def test_missing_code_and_script_raises(self, handler):
        with pytest.raises(ValueError, match="Either"):
            handler.handle("python.execute", {})

    def test_both_code_and_script_raises(self, handler):
        with pytest.raises(ValueError, match="not both"):
            handler.handle(
                "python.execute",
                {
                    "code": "pass",
                    "script_path": "/some/file.py",
                },
            )

    def test_script_path_execution(self, handler, runtime):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "test_script.py")
            with open(script, "w") as f:
                f.write("__result__ = args['name'] + ' executed'\n")

            # Set the approved roots to include tmpdir
            runtime.settings.approved_script_roots = [tmpdir]
            try:
                result = handler.handle(
                    "python.execute",
                    {
                        "script_path": script,
                        "args": {"name": "test"},
                    },
                )
                assert result["result"] == "test executed"
                assert result["error"] is None
            finally:
                runtime.settings.approved_script_roots = []

    def test_script_path_not_found_raises(self, handler, runtime):
        runtime.settings.approved_script_roots = ["/tmp"]
        try:
            with pytest.raises(FileNotFoundError, match="not found"):
                handler.handle(
                    "python.execute",
                    {
                        "script_path": "/tmp/nonexistent_script_abc123.py",
                    },
                )
        finally:
            runtime.settings.approved_script_roots = []

    def test_blocked_module_import(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "import subprocess",
            },
        )
        assert result["error"] is not None
        assert "blocked" in result["error"].lower() or "ImportError" in result["error"]

    def test_shutil_import_is_allowed(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "import shutil\n__result__ = hasattr(shutil, 'rmtree')",
            },
        )
        assert result["error"] is None
        assert result["result"] is True

    def test_blocked_import_hook_does_not_mutate_global_builtins(self, handler):
        import builtins as pybuiltins

        original_import = pybuiltins.__import__
        handler.handle("python.execute", {"code": "import subprocess"})
        assert pybuiltins.__import__ is original_import

    def test_allowed_module_import(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "import json; __result__ = json.dumps({'ok': True})",
            },
        )
        assert result["error"] is None
        assert result["result"] == '{"ok": true}'


class TestResultSerialization:
    """Additional tests for JSON-safe result handling."""

    def test_nested_dict_result(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = {'a': {'b': [1, 2, 3]}}",
            },
        )
        assert result["result"] == {"a": {"b": [1, 2, 3]}}

    def test_list_result(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = [1, 'two', 3.0, None, True]",
            },
        )
        assert result["result"] == [1, "two", 3.0, None, True]

    def test_string_result(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = 'hello'",
            },
        )
        assert result["result"] == "hello"

    def test_numeric_result(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = 3.14159",
            },
        )
        assert result["result"] == 3.14159

    def test_bool_result(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "__result__ = False",
            },
        )
        assert result["result"] is False

    def test_object_result_uses_repr(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "class Foo: pass\n__result__ = Foo()",
            },
        )
        # Custom objects can't be JSON serialized, should get repr
        assert result["result"] is not None
        assert isinstance(result["result"], str)


class TestOutputBounding:
    """Tests for MCP-106 output size limits and diagnostics."""

    def test_stdout_is_capped(self, handler, addon_module):
        limit = addon_module.execution.MAX_OUTPUT_SIZE
        result = handler.handle(
            "python.execute",
            {
                "code": f"print('x' * {limit + 1000})",
            },
        )
        assert len(result["stdout"]) <= limit + 200  # Allow for truncation message
        assert "truncated" in result["stdout"]

    def test_stderr_is_capped(self, handler, addon_module):
        limit = addon_module.execution.MAX_OUTPUT_SIZE
        result = handler.handle(
            "python.execute",
            {
                "code": f"import sys; sys.stderr.write('e' * {limit + 500})",
            },
        )
        assert len(result["stderr"]) <= limit + 200
        assert "truncated" in result["stderr"]

    def test_short_output_not_capped(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "print('short')",
            },
        )
        assert "truncated" not in result["stdout"]
        assert "short" in result["stdout"]

    def test_last_execution_updated_on_success(self, handler, runtime):
        handler.handle("python.execute", {"code": "__result__ = 1"})
        last = runtime.handler.executor.last_execution
        assert last["status"] == "ok"
        assert last["request_id"] is not None
        assert last["request_id"].startswith("exec-")
        assert last["error_summary"] is None

    def test_last_execution_updated_on_error(self, handler, runtime):
        handler.handle("python.execute", {"code": "raise RuntimeError('oops')"})
        last = runtime.handler.executor.last_execution
        assert last["status"] == "error"
        assert "oops" in last["error_summary"]

    def test_last_execution_updated_by_job(self, handler, runtime):
        result = handler.handle(
            "python.execute_async",
            {
                "code": "__result__ = 'job_done'",
            },
        )
        runtime.handler.jobs._execute_job(result["job_id"])
        last = runtime.handler.executor.last_execution
        assert last["status"] == "succeeded"
        assert last["request_id"] == result["job_id"]

    def test_truncate_helper(self, addon_module):
        assert addon_module.execution.truncate("short", 100) == "short"
        assert addon_module.execution.truncate("a" * 200, 10) == "a" * 10 + "…"

    def test_request_id_in_execution_result(self, handler, runtime):
        """Every execution should track a request_id."""
        handler.handle("python.execute", {"code": "pass"})
        last = runtime.handler.executor.last_execution
        assert last["request_id"] is not None
        assert last["duration_seconds"] is not None
