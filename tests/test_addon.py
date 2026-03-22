"""Tests for the Blender add-on command handler using mocked bpy."""

import json
import os
import sys
import tempfile
import threading
import pytest
from unittest.mock import MagicMock, patch


def _create_mock_bpy():
    """Create a mock bpy module for testing outside Blender."""
    bpy = MagicMock()

    # Mock scene
    scene = MagicMock()
    scene.name = "Scene"
    scene.frame_current = 1
    scene.frame_start = 1
    scene.frame_end = 250
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080

    # Mock objects
    cube = MagicMock()
    cube.name = "Cube"
    cube.type = "MESH"
    cube.location = MagicMock()
    cube.location.__iter__ = lambda self: iter([0.0, 0.0, 0.0])
    cube.location.__getitem__ = lambda self, i: [0.0, 0.0, 0.0][i]
    cube.location.x = 0.0
    cube.location.y = 0.0
    cube.location.z = 0.0
    cube.rotation_euler = MagicMock()
    cube.rotation_euler.__iter__ = lambda self: iter([0.0, 0.0, 0.0])
    cube.scale = MagicMock()
    cube.scale.__iter__ = lambda self: iter([1.0, 1.0, 1.0])
    cube.visible_get.return_value = True
    cube.parent = None
    cube.children = []

    camera = MagicMock()
    camera.name = "Camera"
    camera.type = "CAMERA"
    camera.location = MagicMock()
    camera.location.__iter__ = lambda self: iter([7.0, -6.0, 5.0])
    camera.visible_get.return_value = True
    camera.parent = None
    camera.children = []

    scene.objects = [cube, camera]

    bpy.context.scene = scene
    bpy.context.collection = MagicMock()
    bpy.app.timers.register = MagicMock()
    bpy.ops.ed.undo_push.poll.return_value = False

    # Mock data — use MagicMock for Blender collections (they support .get() and iteration)
    objects_collection = MagicMock()
    objects_collection.get = lambda name: {"Cube": cube, "Camera": camera}.get(name)

    materials_collection = MagicMock()
    materials_collection.__iter__ = lambda self: iter([])
    materials_collection.get = MagicMock(return_value=None)
    materials_collection.new = MagicMock()

    bpy.data.objects = objects_collection
    bpy.data.materials = materials_collection

    return bpy


@pytest.fixture(autouse=True)
def mock_bpy():
    """Install mock bpy before importing the addon."""
    mock = _create_mock_bpy()
    sys.modules["bpy"] = mock
    # Also mock mathutils since it's used in the execution namespace
    if "mathutils" not in sys.modules:
        sys.modules["mathutils"] = MagicMock()
    yield mock
    del sys.modules["bpy"]
    if "mathutils" in sys.modules and isinstance(sys.modules["mathutils"], MagicMock):
        del sys.modules["mathutils"]


@pytest.fixture
def addon_module(mock_bpy):
    # Force reimport with mocked bpy
    if "addon" in sys.modules:
        del sys.modules["addon"]
    # We need to import the addon's __init__ as a module
    import importlib.util

    spec = importlib.util.spec_from_file_location("addon", "addon/__init__.py")
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    return addon


@pytest.fixture
def handler(addon_module):
    return addon_module.CommandHandler()


class TestSceneCommands:
    def test_scene_get_info(self, handler):
        result = handler.handle("scene.get_info", {})
        assert result["name"] == "Scene"
        assert result["frame_current"] == 1
        assert result["render_engine"] == "BLENDER_EEVEE"
        assert result["object_count"] == 2

    def test_scene_list_objects(self, handler):
        result = handler.handle("scene.list_objects", {})
        assert len(result["objects"]) == 2
        names = [o["name"] for o in result["objects"]]
        assert "Cube" in names
        assert "Camera" in names

    def test_scene_list_objects_type_filter(self, handler):
        result = handler.handle("scene.list_objects", {"type": "MESH"})
        assert len(result["objects"]) == 1
        assert result["objects"][0]["name"] == "Cube"


class TestObjectCommands:
    def test_get_transform(self, handler):
        result = handler.handle("object.get_transform", {"name": "Cube"})
        assert result["name"] == "Cube"
        assert "location" in result
        assert "rotation_euler" in result
        assert "scale" in result

    def test_get_transform_missing_object(self, handler):
        with pytest.raises(ValueError, match="not found"):
            handler.handle("object.get_transform", {"name": "NonExistent"})

    def test_unknown_command(self, handler):
        with pytest.raises(ValueError, match="Unknown command"):
            handler.handle("nonexistent.command", {})

    def test_get_hierarchy_full_scene(self, handler):
        result = handler.handle("object.get_hierarchy", {})
        assert "roots" in result
        assert len(result["roots"]) == 2


class TestMaterialCommands:
    def test_material_list_empty(self, handler, mock_bpy):
        mock_bpy.data.materials = []
        result = handler.handle("material.list", {})
        assert result["materials"] == []


class TestServerExecution:
    def test_mutation_request_skips_undo_when_poll_fails(self, addon_module, mock_bpy):
        server = addon_module.BlenderMCPServer()
        request = {
            "id": "1",
            "command": "object.translate",
            "params": {"name": "Cube", "offset": [1, 2, 3]},
        }

        result = server._process_request(request)

        assert result["success"] is True
        mock_bpy.ops.ed.undo_push.assert_not_called()

    def test_submit_request_runs_through_queue(self, addon_module):
        server = addon_module.BlenderMCPServer()
        request = {"id": "abc", "command": "scene.get_info", "params": {}}
        expected = {"id": "abc", "success": True, "result": {"ok": True}}
        response_holder = {}

        with patch.object(server, "_process_request", return_value=expected) as process:
            worker = threading.Thread(
                target=lambda: response_holder.setdefault(
                    "response", server._submit_request(request)
                )
            )
            worker.start()
            server._drain_request_queue()
            worker.join(timeout=1)

        assert response_holder["response"] == expected
        process.assert_called_once_with(request)


class TestPythonExecute:
    """Tests for the python.execute command handler."""

    def test_inline_code_returns_result(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = {'answer': 42}",
        })
        assert result["result"] == {"answer": 42}
        assert result["error"] is None
        assert "duration_seconds" in result

    def test_inline_code_captures_stdout(self, handler):
        result = handler.handle("python.execute", {
            "code": "print('hello world')",
        })
        assert "hello world" in result["stdout"]
        assert result["error"] is None

    def test_inline_code_captures_stderr(self, handler):
        result = handler.handle("python.execute", {
            "code": "import sys; sys.stderr.write('warn\\n')",
        })
        assert "warn" in result["stderr"]

    def test_inline_code_exception_returns_error(self, handler):
        result = handler.handle("python.execute", {
            "code": "raise ValueError('boom')",
        })
        assert result["error"] is not None
        assert "ValueError" in result["error"]
        assert "boom" in result["error"]
        assert result["result"] is None

    def test_args_passed_to_namespace(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = args['x'] + args['y']",
            "args": {"x": 10, "y": 20},
        })
        assert result["result"] == 30

    def test_bpy_available_in_namespace(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = bpy.context.scene.name",
        })
        assert result["result"] == "Scene"

    def test_no_result_set_returns_null(self, handler):
        result = handler.handle("python.execute", {
            "code": "x = 1 + 1",
        })
        assert result["result"] is None
        assert result["error"] is None

    def test_non_json_result_falls_back_to_repr(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = {1, 2, 3}",
        })
        # Sets aren't JSON-serializable, should get repr
        assert result["result"] is not None
        assert result["error"] is None

    def test_missing_code_and_script_raises(self, handler):
        with pytest.raises(ValueError, match="Either"):
            handler.handle("python.execute", {})

    def test_both_code_and_script_raises(self, handler):
        with pytest.raises(ValueError, match="not both"):
            handler.handle("python.execute", {
                "code": "pass",
                "script_path": "/some/file.py",
            })

    def test_script_path_execution(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "test_script.py")
            with open(script, "w") as f:
                f.write("__result__ = args['name'] + ' executed'\n")

            # Set the approved roots to include tmpdir
            addon_module.APPROVED_SCRIPT_ROOTS = [tmpdir]
            try:
                result = handler.handle("python.execute", {
                    "script_path": script,
                    "args": {"name": "test"},
                })
                assert result["result"] == "test executed"
                assert result["error"] is None
            finally:
                addon_module.APPROVED_SCRIPT_ROOTS = []

    def test_script_path_not_found_raises(self, handler, addon_module):
        addon_module.APPROVED_SCRIPT_ROOTS = ["/tmp"]
        try:
            with pytest.raises(FileNotFoundError, match="not found"):
                handler.handle("python.execute", {
                    "script_path": "/tmp/nonexistent_script_abc123.py",
                })
        finally:
            addon_module.APPROVED_SCRIPT_ROOTS = []

    def test_blocked_module_import(self, handler):
        result = handler.handle("python.execute", {
            "code": "import subprocess",
        })
        assert result["error"] is not None
        assert "blocked" in result["error"].lower() or "ImportError" in result["error"]

    def test_allowed_module_import(self, handler):
        result = handler.handle("python.execute", {
            "code": "import json; __result__ = json.dumps({'ok': True})",
        })
        assert result["error"] is None
        assert result["result"] == '{"ok": true}'


class TestPythonSandbox:
    """Tests for MCP-103 sandbox and path restrictions."""

    def test_script_outside_roots_rejected(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as allowed_dir:
            with tempfile.TemporaryDirectory() as forbidden_dir:
                script = os.path.join(forbidden_dir, "evil.py")
                with open(script, "w") as f:
                    f.write("pass\n")

                addon_module.APPROVED_SCRIPT_ROOTS = [allowed_dir]
                try:
                    with pytest.raises(PermissionError, match="outside approved"):
                        handler.handle("python.execute", {"script_path": script})
                finally:
                    addon_module.APPROVED_SCRIPT_ROOTS = []

    def test_script_inside_roots_accepted(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "good.py")
            with open(script, "w") as f:
                f.write("__result__ = 'ok'\n")

            addon_module.APPROVED_SCRIPT_ROOTS = [tmpdir]
            try:
                result = handler.handle("python.execute", {"script_path": script})
                assert result["result"] == "ok"
            finally:
                addon_module.APPROVED_SCRIPT_ROOTS = []

    def test_inline_code_disabled_rejects(self, handler, addon_module):
        addon_module.ALLOW_INLINE_CODE = False
        try:
            with pytest.raises(PermissionError, match="disabled"):
                handler.handle("python.execute", {"code": "pass"})
        finally:
            addon_module.ALLOW_INLINE_CODE = True

    def test_inline_code_enabled_allows(self, handler, addon_module):
        addon_module.ALLOW_INLINE_CODE = True
        result = handler.handle("python.execute", {"code": "__result__ = True"})
        assert result["result"] is True

    def test_non_py_script_rejected(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "script.txt")
            with open(script, "w") as f:
                f.write("pass\n")

            addon_module.APPROVED_SCRIPT_ROOTS = [tmpdir]
            try:
                with pytest.raises(ValueError, match=".py"):
                    handler.handle("python.execute", {"script_path": script})
            finally:
                addon_module.APPROVED_SCRIPT_ROOTS = []


class TestJobLifecycle:
    """Tests for MCP-104 async job support."""

    def test_execute_async_returns_job_id(self, handler):
        result = handler.handle("python.execute_async", {
            "code": "__result__ = 'done'",
        })
        assert "job_id" in result
        assert result["job_id"].startswith("job-")

    def test_job_status_for_unknown_job(self, handler):
        with pytest.raises(ValueError, match="Unknown job"):
            handler.handle("job.status", {"job_id": "job-nonexistent"})

    def test_job_list_returns_jobs(self, handler):
        result1 = handler.handle("python.execute_async", {"code": "pass"})
        listing = handler.handle("job.list", {})
        job_ids = [j["job_id"] for j in listing["jobs"]]
        assert result1["job_id"] in job_ids

    def test_job_cancel_sets_cancelled(self, handler, addon_module):
        result = handler.handle("python.execute_async", {
            "code": "import time; time.sleep(10)",
        })
        job_id = result["job_id"]
        cancel_result = handler.handle("job.cancel", {"job_id": job_id})
        assert cancel_result["status"] == "cancelled"

    def test_job_cancel_unknown_raises(self, handler):
        with pytest.raises(ValueError, match="Unknown job"):
            handler.handle("job.cancel", {"job_id": "job-nope"})

    def test_job_status_after_sync_execution(self, handler, addon_module):
        """Run the job via the timer callback and verify completion."""
        result = handler.handle("python.execute_async", {
            "code": "__result__ = 'async_done'",
        })
        job_id = result["job_id"]

        # Manually trigger the timer callback that executes the job
        addon_module._job_manager._execute_job(job_id)

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "succeeded"
        assert status["result"] == "async_done"
        assert status["error"] is None

    def test_failed_job_captures_error(self, handler, addon_module):
        result = handler.handle("python.execute_async", {
            "code": "raise RuntimeError('async boom')",
        })
        job_id = result["job_id"]

        addon_module._job_manager._execute_job(job_id)

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "failed"
        assert "RuntimeError" in status["error"]
        assert "async boom" in status["error"]

    def test_job_status_missing_id_raises(self, handler):
        with pytest.raises(ValueError, match="job_id"):
            handler.handle("job.status", {})


class TestOutputBounding:
    """Tests for MCP-106 output size limits and diagnostics."""

    def test_stdout_is_capped(self, handler, addon_module):
        limit = addon_module.MAX_OUTPUT_SIZE
        result = handler.handle("python.execute", {
            "code": f"print('x' * {limit + 1000})",
        })
        assert len(result["stdout"]) <= limit + 200  # Allow for truncation message
        assert "truncated" in result["stdout"]

    def test_stderr_is_capped(self, handler, addon_module):
        limit = addon_module.MAX_OUTPUT_SIZE
        result = handler.handle("python.execute", {
            "code": f"import sys; sys.stderr.write('e' * {limit + 500})",
        })
        assert len(result["stderr"]) <= limit + 200
        assert "truncated" in result["stderr"]

    def test_short_output_not_capped(self, handler):
        result = handler.handle("python.execute", {
            "code": "print('short')",
        })
        assert "truncated" not in result["stdout"]
        assert "short" in result["stdout"]

    def test_last_execution_updated_on_success(self, handler, addon_module):
        handler.handle("python.execute", {"code": "__result__ = 1"})
        last = addon_module._last_execution
        assert last["status"] == "ok"
        assert last["request_id"] is not None
        assert last["request_id"].startswith("exec-")
        assert last["error_summary"] is None

    def test_last_execution_updated_on_error(self, handler, addon_module):
        handler.handle("python.execute", {"code": "raise RuntimeError('oops')"})
        last = addon_module._last_execution
        assert last["status"] == "error"
        assert "oops" in last["error_summary"]

    def test_last_execution_updated_by_job(self, handler, addon_module):
        result = handler.handle("python.execute_async", {
            "code": "__result__ = 'job_done'",
        })
        addon_module._job_manager._execute_job(result["job_id"])
        last = addon_module._last_execution
        assert last["status"] == "succeeded"
        assert last["request_id"] == result["job_id"]

    def test_truncate_helper(self, addon_module):
        assert addon_module._truncate("short", 100) == "short"
        assert addon_module._truncate("a" * 200, 10) == "a" * 10 + "…"

    def test_request_id_in_execution_result(self, handler, addon_module):
        """Every execution should track a request_id."""
        handler.handle("python.execute", {"code": "pass"})
        last = addon_module._last_execution
        assert last["request_id"] is not None
        assert last["duration_seconds"] is not None


class TestResultSerialization:
    """Additional tests for JSON-safe result handling."""

    def test_nested_dict_result(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = {'a': {'b': [1, 2, 3]}}",
        })
        assert result["result"] == {"a": {"b": [1, 2, 3]}}

    def test_list_result(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = [1, 'two', 3.0, None, True]",
        })
        assert result["result"] == [1, "two", 3.0, None, True]

    def test_string_result(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = 'hello'",
        })
        assert result["result"] == "hello"

    def test_numeric_result(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = 3.14159",
        })
        assert result["result"] == 3.14159

    def test_bool_result(self, handler):
        result = handler.handle("python.execute", {
            "code": "__result__ = False",
        })
        assert result["result"] is False

    def test_object_result_uses_repr(self, handler):
        result = handler.handle("python.execute", {
            "code": "class Foo: pass\n__result__ = Foo()",
        })
        # Custom objects can't be JSON serialized, should get repr
        assert result["result"] is not None
        assert isinstance(result["result"], str)


class TestAsyncInlineDisabled:
    """Verify inline code toggle works for async path too."""

    def test_async_inline_disabled_rejects(self, handler, addon_module):
        addon_module.ALLOW_INLINE_CODE = False
        try:
            with pytest.raises(PermissionError, match="disabled"):
                handler.handle("python.execute_async", {"code": "pass"})
        finally:
            addon_module.ALLOW_INLINE_CODE = True

    def test_async_script_path_outside_roots_rejected(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as allowed_dir:
            with tempfile.TemporaryDirectory() as forbidden_dir:
                script = os.path.join(forbidden_dir, "bad.py")
                with open(script, "w") as f:
                    f.write("pass\n")

                addon_module.APPROVED_SCRIPT_ROOTS = [allowed_dir]
                try:
                    with pytest.raises(PermissionError, match="outside approved"):
                        handler.handle("python.execute_async", {"script_path": script})
                finally:
                    addon_module.APPROVED_SCRIPT_ROOTS = []

    def test_async_missing_code_and_script_raises(self, handler):
        with pytest.raises(ValueError, match="Either"):
            handler.handle("python.execute_async", {})

    def test_async_both_code_and_script_raises(self, handler):
        with pytest.raises(ValueError, match="not both"):
            handler.handle("python.execute_async", {
                "code": "pass",
                "script_path": "/some/file.py",
            })
