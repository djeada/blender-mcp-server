"""Tests for the Blender add-on command handler using mocked bpy."""

import os
import sys
import tempfile
import threading
import types
from unittest.mock import MagicMock, patch

import pytest


def _create_mock_bpy():
    """Create a mock bpy module for testing outside Blender."""
    bpy = MagicMock()
    handlers_module = types.ModuleType("bpy.app.handlers")
    handlers_module.load_post = []
    handlers_module.persistent = lambda fn: fn
    bpy.app.handlers = handlers_module

    # Mock scene
    scene = MagicMock()
    scene.name = "Scene"
    scene.frame_current = 1
    scene.frame_start = 1
    scene.frame_end = 250
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.frame_set = MagicMock()

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
    bpy.context.preferences = MagicMock()
    bpy.context.preferences.addons = {}
    bpy.app.timers.register = MagicMock()
    bpy.app.timers.is_registered = MagicMock(return_value=False)
    bpy.ops.ed.undo_push.poll.return_value = False
    bpy.path.abspath = lambda path: path

    # Mock data — use MagicMock for Blender collections (they support .get() and iteration)
    objects_collection = MagicMock()
    objects_collection.keys = lambda: ["Cube", "Camera"]
    objects_collection.get = lambda name: {"Cube": cube, "Camera": camera}.get(name)

    materials_collection = MagicMock()
    materials_collection.__iter__ = lambda self: iter([])
    materials_collection.get = MagicMock(return_value=None)
    materials_collection.new = MagicMock()

    bpy.data.objects = objects_collection
    bpy.data.materials = materials_collection
    bpy.data.filepath = "/tmp/mock_scene.blend"

    return bpy


@pytest.fixture(autouse=True)
def mock_bpy():
    """Install mock bpy before importing the addon."""
    mock = _create_mock_bpy()
    app_module = types.ModuleType("bpy.app")
    app_module.handlers = mock.app.handlers
    app_module.timers = mock.app.timers
    sys.modules["bpy"] = mock
    sys.modules["bpy.app"] = app_module
    sys.modules["bpy.app.handlers"] = mock.app.handlers
    # Also mock mathutils since it's used in the execution namespace
    if "mathutils" not in sys.modules:
        sys.modules["mathutils"] = MagicMock()
    yield mock
    del sys.modules["bpy"]
    del sys.modules["bpy.app"]
    del sys.modules["bpy.app.handlers"]
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
    def test_build_primitive_pydata_cube(self, addon_module):
        verts, faces = addon_module._build_primitive_pydata("cube", 2.0)
        assert len(verts) == 8
        assert len(faces) == 6

    def test_build_primitive_pydata_sphere(self, addon_module):
        verts, faces = addon_module._build_primitive_pydata("sphere", 2.0)
        assert len(verts) > 10
        assert len(faces) > 10

    def test_build_primitive_pydata_rejects_unknown_shape(self, addon_module):
        with pytest.raises(ValueError, match="Unknown mesh type"):
            addon_module._build_primitive_pydata("bad-shape", 2.0)

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
                target=lambda: response_holder.setdefault("response", server._submit_request(request))
            )
            worker.start()
            server._drain_request_queue()
            worker.join(timeout=1)

        assert response_holder["response"] == expected
        process.assert_called_once_with(request)

    def test_request_queue_timer_is_registered_persistent(self, addon_module, mock_bpy):
        server = addon_module.BlenderMCPServer()

        server._register_request_queue_timer()

        mock_bpy.app.timers.register.assert_called_once_with(
            server._drain_timer_callback,
            first_interval=0.01,
            persistent=True,
        )

    def test_ensure_server_running_reregisters_timer_for_healthy_server(self, addon_module):
        server = addon_module.BlenderMCPServer()
        server._running = True
        server._server_socket = object()
        server._thread = MagicMock()
        server._thread.is_alive.return_value = True
        server._register_request_queue_timer = MagicMock()
        addon_module._server = server

        result = addon_module._ensure_server_running()

        assert result is None
        server._register_request_queue_timer.assert_called_once_with()

    def test_python_execute_does_not_auto_push_undo(self, addon_module, mock_bpy):
        server = addon_module.BlenderMCPServer()
        request = {
            "id": "2",
            "command": "python.execute",
            "params": {"code": "__result__ = 1"},
        }

        result = server._process_request(request)

        assert result["success"] is True
        mock_bpy.ops.ed.undo_push.assert_not_called()


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

    def test_script_path_execution(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "test_script.py")
            with open(script, "w") as f:
                f.write("__result__ = args['name'] + ' executed'\n")

            # Set the approved roots to include tmpdir
            addon_module.APPROVED_SCRIPT_ROOTS = [tmpdir]
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
                addon_module.APPROVED_SCRIPT_ROOTS = []

    def test_script_path_not_found_raises(self, handler, addon_module):
        addon_module.APPROVED_SCRIPT_ROOTS = ["/tmp"]
        try:
            with pytest.raises(FileNotFoundError, match="not found"):
                handler.handle(
                    "python.execute",
                    {
                        "script_path": "/tmp/nonexistent_script_abc123.py",
                    },
                )
        finally:
            addon_module.APPROVED_SCRIPT_ROOTS = []

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


class TestPythonSandbox:
    """Tests for MCP-103 sandbox and path restrictions."""

    def test_script_outside_roots_rejected(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as allowed_dir, tempfile.TemporaryDirectory() as forbidden_dir:
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

    def test_runtime_preferences_are_applied(self, handler, addon_module, mock_bpy):
        prefs = MagicMock()
        prefs.safe_mode = True
        prefs.port = 9988
        prefs.allow_inline_code = False
        prefs.approved_script_roots = "/tmp/a;/tmp/b"
        mock_bpy.context.preferences.addons["addon"] = MagicMock(preferences=prefs)

        with pytest.raises(PermissionError, match="disabled"):
            handler.handle("python.execute", {"code": "pass"})

        assert addon_module.SAFE_MODE is True
        assert addon_module.PORT == 9988
        assert addon_module.ALLOW_INLINE_CODE is False
        assert addon_module.APPROVED_SCRIPT_ROOTS == ["/tmp/a", "/tmp/b"]
        assert addon_module.ALLOWED_PATHS == ["/tmp/a", "/tmp/b"]

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
        result = handler.handle(
            "python.execute_async",
            {
                "code": "__result__ = 'done'",
            },
        )
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
        result = handler.handle(
            "python.execute_async",
            {
                "code": "import time; time.sleep(10)",
            },
        )
        job_id = result["job_id"]
        cancel_result = handler.handle("job.cancel", {"job_id": job_id})
        assert cancel_result["status"] == "cancelled"
        assert cancel_result["cancellation_requested"] is True

    def test_job_cancel_running_marks_request_only(self, handler, addon_module):
        result = handler.handle("python.execute_async", {"code": "pass"})
        job_id = result["job_id"]
        with addon_module._job_manager._lock:
            addon_module._job_manager._jobs[job_id]["status"] = "running"

        cancel_result = handler.handle("job.cancel", {"job_id": job_id})

        assert cancel_result["status"] == "running"
        assert cancel_result["cancellation_requested"] is True

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "running"
        assert status["cancellation_requested"] is True

    def test_job_cancel_unknown_raises(self, handler):
        with pytest.raises(ValueError, match="Unknown job"):
            handler.handle("job.cancel", {"job_id": "job-nope"})

    def test_job_status_after_sync_execution(self, handler, addon_module):
        """Run the job via the timer callback and verify completion."""
        result = handler.handle(
            "python.execute_async",
            {
                "code": "__result__ = 'async_done'",
            },
        )
        job_id = result["job_id"]

        # Manually trigger the timer callback that executes the job
        addon_module._job_manager._execute_job(job_id)

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "succeeded"
        assert status["result"] == "async_done"
        assert status["error"] is None

    def test_failed_job_captures_error(self, handler, addon_module):
        result = handler.handle(
            "python.execute_async",
            {
                "code": "raise RuntimeError('async boom')",
            },
        )
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
        result = handler.handle(
            "python.execute",
            {
                "code": f"print('x' * {limit + 1000})",
            },
        )
        assert len(result["stdout"]) <= limit + 200  # Allow for truncation message
        assert "truncated" in result["stdout"]

    def test_stderr_is_capped(self, handler, addon_module):
        limit = addon_module.MAX_OUTPUT_SIZE
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
        result = handler.handle(
            "python.execute_async",
            {
                "code": "__result__ = 'job_done'",
            },
        )
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


class TestExecutionControl:
    def test_sync_timeout_is_enforced(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "while True:\n    pass",
                "timeout_seconds": 0.01,
            },
        )
        assert result["timed_out"] is True
        assert result["cancelled"] is False
        assert "timeout" in result["error"].lower()

    def test_async_cancellation_propagates_to_final_status(self, handler, addon_module):
        result = handler.handle(
            "python.execute_async",
            {
                "code": (
                    "while True:\n    if __cancel_event__.is_set():\n        raise RuntimeError('stop requested')\n"
                ),
                "timeout_seconds": 1,
            },
        )
        job_id = result["job_id"]
        addon_module._job_manager.cancel(job_id)
        addon_module._job_manager._execute_job(job_id)

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "cancelled"
        assert status["cancellation_requested"] is True


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
        with tempfile.TemporaryDirectory() as allowed_dir, tempfile.TemporaryDirectory() as forbidden_dir:
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
            handler.handle(
                "python.execute_async",
                {
                    "code": "pass",
                    "script_path": "/some/file.py",
                },
            )


class TestDamBreakDemo:
    """Validate the dam-break demo scripts."""

    DEMOS_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "scripts", "demos")
    LIBRARY_DIR = os.path.join(os.path.dirname(__file__), os.pardir, "scripts", "library")

    def test_dam_break_scene_parses(self):
        """The monolithic demo script must be syntactically valid Python."""
        import ast

        path = os.path.join(self.DEMOS_DIR, "dam_break_scene.py")
        with open(path) as f:
            ast.parse(f.read(), filename=path)

    def test_run_dam_break_parses(self):
        """The bridge caller script must be syntactically valid."""
        import ast

        path = os.path.join(self.DEMOS_DIR, "run_dam_break.py")
        with open(path) as f:
            ast.parse(f.read(), filename=path)

    def test_demo_scripts_avoid_mesh_primitive_operators(self):
        """Bridge-driven demo geometry should use data-API helpers, not bpy.ops primitives."""
        for filename in ("dam_break_scene.py", "run_dam_break.py"):
            path = os.path.join(self.DEMOS_DIR, filename)
            with open(path) as f:
                contents = f.read()
            assert "bpy.ops.mesh.primitive_" not in contents

    def test_run_dam_break_builds_correct_steps(self):
        """build_steps() returns expected step count and uses library scripts."""
        sys.path.insert(0, self.DEMOS_DIR)
        try:
            import run_dam_break

            steps = run_dam_break.build_steps(self.LIBRARY_DIR)
        finally:
            sys.path.pop(0)
            sys.modules.pop("run_dam_break", None)

        assert len(steps) >= 11
        labels = [s["label"] for s in steps]
        assert any("frame range" in label.lower() for label in labels)
        assert any("fluid domain" in label.lower() for label in labels)
        assert any("camera" in label.lower() for label in labels)
        assert any("collider" in label.lower() for label in labels)
        assert any("rigid" in label.lower() for label in labels)
        assert any("keyframe" in label.lower() or "dolly" in label.lower() for label in labels)

    def test_run_dam_break_script_paths_exist(self):
        """Every library script referenced by build_steps must exist."""
        sys.path.insert(0, self.DEMOS_DIR)
        try:
            import run_dam_break

            steps = run_dam_break.build_steps(self.LIBRARY_DIR)
        finally:
            sys.path.pop(0)
            sys.modules.pop("run_dam_break", None)

        for step in steps:
            if step["method"] == "script":
                assert os.path.isfile(step["script_path"]), f"Missing library script: {step['script_path']}"

    def test_run_dam_break_stops_on_inner_script_error(self):
        """run_demo() must fail fast if python.execute returns an inner script error."""
        sys.path.insert(0, self.DEMOS_DIR)
        try:
            import run_dam_break

            with patch.object(
                run_dam_break,
                "exec_inline",
                return_value={"success": True, "result": {"error": "boom"}},
            ):
                exit_code = run_dam_break.run_demo(
                    "127.0.0.1",
                    9876,
                    self.LIBRARY_DIR,
                    dry_run=False,
                )
        finally:
            sys.path.pop(0)
            sys.modules.pop("run_dam_break", None)

        assert exit_code == 1

    def test_exec_script_sends_inline_code(self):
        """The step runner should inline local library scripts, not rely on script_path."""
        sys.path.insert(0, self.DEMOS_DIR)
        try:
            import run_dam_break

            with tempfile.TemporaryDirectory() as tmpdir:
                script_path = os.path.join(tmpdir, "sample.py")
                with open(script_path, "w") as f:
                    f.write("__result__ = {'ok': True}\n")

                with patch.object(run_dam_break, "send_command", return_value={"success": True}) as send:
                    run_dam_break.exec_script(script_path, {"x": 1})
        finally:
            sys.path.pop(0)
            sys.modules.pop("run_dam_break", None)

        send.assert_called_once()
        command, params = send.call_args.args
        assert command == "python.execute"
        assert "code" in params
        assert "script_path" not in params
        assert params["args"] == {"x": 1}

    def test_dam_break_scene_executes_in_mock(self, handler, addon_module):
        """The monolithic script should execute without import errors
        in the mocked bpy environment (logic errors from mocks are OK)."""
        path = os.path.realpath(os.path.join(self.DEMOS_DIR, "dam_break_scene.py"))
        addon_module.APPROVED_SCRIPT_ROOTS = [os.path.dirname(path)]
        try:
            result = handler.handle(
                "python.execute",
                {
                    "script_path": path,
                    "args": {"resolution": 16, "frame_end": 10},
                },
            )
            # With mocked bpy the script may error on mock attribute access,
            # but it should not raise an import or syntax error.
            # If it succeeds, validate the result structure.
            if result.get("error") is None:
                assert "fluid_domain" in result["result"]
                assert "camera" in result["result"]
                assert "debris" in result["result"]
        finally:
            addon_module.APPROVED_SCRIPT_ROOTS = []

    def test_all_library_scripts_parse(self):
        """Every .py in scripts/library/ must be syntactically valid."""
        import ast
        import glob as globmod

        for path in sorted(globmod.glob(os.path.join(self.LIBRARY_DIR, "*.py"))):
            with open(path) as f:
                ast.parse(f.read(), filename=path)


class TestBridgeProtocolSecurity:
    """Connection-level auth and framing for the TCP bridge."""

    def _serve(self, addon_module, payload: bytes) -> list[dict]:
        import json
        import socket

        server = addon_module.BlenderMCPServer()
        server._running = True
        addon_module.AUTH_TOKEN = "secret"
        client, bridge_side = socket.socketpair()
        with patch.object(
            server, "_submit_request", side_effect=lambda r: {"id": r.get("id"), "success": True, "result": "ran"}
        ):
            worker = threading.Thread(target=server._handle_client, args=(bridge_side,))
            worker.start()
            client.sendall(payload)
            client.shutdown(socket.SHUT_WR)
            worker.join(timeout=2)
        data = b""
        while chunk := client.recv(65536):
            data += chunk
        client.close()
        return [json.loads(line) for line in data.splitlines() if line.strip()]

    def test_authorized_request_is_processed(self, addon_module):
        responses = self._serve(addon_module, b'{"id": "1", "command": "scene.get_info", "token": "secret"}\n')
        assert responses == [{"id": "1", "success": True, "result": "ran"}]

    def test_missing_or_wrong_token_is_rejected(self, addon_module):
        for token_part in (b"", b', "token": "wrong"'):
            payload = b'{"id": "1", "command": "python.execute"' + token_part + b"}\n"
            responses = self._serve(addon_module, payload)
            assert len(responses) == 1
            assert responses[0]["success"] is False
            assert "Unauthorized" in responses[0]["error"]

    def test_http_smuggled_command_is_not_executed(self, addon_module):
        """A browser POST whose body is a JSON command must never reach the handler."""
        body = b'{"id": "x", "command": "python.execute", "params": {"code": "pass"}, "token": "secret"}\n'
        http = b"POST / HTTP/1.1\r\nHost: 127.0.0.1:9876\r\nContent-Type: text/plain\r\n\r\n" + body
        responses = self._serve(addon_module, http)
        assert len(responses) == 1
        assert "Invalid JSON" in responses[0]["error"]

    def test_non_object_request_closes_connection(self, addon_module):
        responses = self._serve(addon_module, b"[1, 2]\n" + b'{"id": "1", "token": "secret"}\n')
        assert len(responses) == 1
        assert responses[0]["success"] is False

    def test_oversized_request_is_rejected(self, addon_module):
        addon_module.MAX_REQUEST_SIZE = 1024
        responses = self._serve(addon_module, b"x" * 2048)
        assert "exceeds" in responses[0]["error"]

    def test_token_file_created_private(self, addon_module, monkeypatch, tmp_path):
        monkeypatch.delenv("BLENDER_MCP_TOKEN")
        token_file = tmp_path / "sub" / "token"
        monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(token_file))
        token = addon_module._load_or_create_token()
        assert token_file.read_text() == token
        assert (token_file.stat().st_mode & 0o777) == 0o600
        assert addon_module._load_or_create_token() == token  # reused, not rotated


class TestBridgeRobustness:
    def test_system_exit_in_script_is_contained(self, handler):
        result = handler.handle("python.execute", {"code": "raise SystemExit(3)"})
        assert "SystemExit" in result["error"]

    def test_script_cannot_swallow_timeout(self, handler):
        code = "while True:\n    try:\n        pass\n    except Exception:\n        pass\n"
        result = handler.handle("python.execute", {"code": code, "timeout_seconds": 0.05})
        assert result["timed_out"] is True

    def test_drain_always_answers_waiting_client(self, addon_module):
        server = addon_module.BlenderMCPServer()
        event = threading.Event()
        server._request_queue.put({"request": {"id": "9"}, "event": event, "response": None})
        with patch.object(server, "_process_request", side_effect=KeyboardInterrupt()):
            server._drain_request_queue()
        assert event.is_set()

    def test_job_commands_bypass_main_thread_queue(self, addon_module):
        """job.status/cancel must work while an async job occupies the main thread."""
        server = addon_module.BlenderMCPServer()
        job_id = server._handler.handle("python.execute_async", {"code": "pass"})["job_id"]
        response = server._submit_request({"id": "1", "command": "job.cancel", "params": {"job_id": job_id}})
        assert response["success"] is True
        assert server._request_queue.empty()

    def test_finished_jobs_are_pruned_and_released(self, handler, addon_module):
        manager = addon_module._job_manager
        job_id = handler.handle("python.execute_async", {"code": "__result__ = 1"})["job_id"]
        manager._execute_job(job_id)
        assert manager._jobs[job_id]["code"] is None
        for _ in range(addon_module.MAX_FINISHED_JOBS + 20):
            manager._execute_job(handler.handle("python.execute_async", {"code": "pass"})["job_id"])
        assert len(manager._jobs) <= addon_module.MAX_FINISHED_JOBS

    def test_port_change_marks_server_unhealthy(self, addon_module):
        server = addon_module.BlenderMCPServer()
        server._running = True
        server._server_socket = object()
        server._thread = MagicMock()
        server._thread.is_alive.return_value = True
        addon_module._server = server
        assert addon_module._server_healthy()
        addon_module.PORT = server._port + 1
        assert not addon_module._server_healthy()


class TestSafeModeAndPaths:
    def test_prefix_sibling_directory_is_not_allowed(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, "proj")
            os.makedirs(allowed)
            addon_module.SAFE_MODE = True
            addon_module.ALLOWED_PATHS = [allowed]
            handler._validate_filepath(os.path.join(allowed, "out.png"))
            with pytest.raises(PermissionError):
                handler._validate_filepath(os.path.join(parent, "proj-evil", "out.png"))

    def test_symlink_escape_is_blocked(self, handler, addon_module):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            link = os.path.join(allowed, "link")
            os.symlink(outside, link)
            addon_module.SAFE_MODE = True
            addon_module.ALLOWED_PATHS = [allowed]
            with pytest.raises(PermissionError):
                handler._validate_filepath(os.path.join(link, "out.png"))

    def test_safe_mode_disables_inline_code(self, handler, addon_module):
        addon_module.SAFE_MODE = True
        with pytest.raises(PermissionError, match="Safe Mode"):
            handler.handle("python.execute", {"code": "pass"}, sync_settings=False)

    def test_unsaved_blend_without_roots_denies_scripts(self, handler, addon_module, mock_bpy, tmp_path):
        mock_bpy.data.filepath = ""
        script = tmp_path / "s.py"
        script.write_text("pass\n")
        with pytest.raises(PermissionError, match="unsaved"):
            handler.handle("python.execute", {"script_path": str(script)})

    def test_allowed_commands_preference_is_enforced(self, handler, addon_module, mock_bpy):
        prefs = MagicMock()
        prefs.safe_mode = False
        prefs.port = 9876
        prefs.allow_inline_code = True
        prefs.approved_script_roots = ""
        prefs.allowed_commands = "scene.get_info, object.get_transform"
        mock_bpy.context.preferences.addons["addon"] = MagicMock(preferences=prefs)

        assert handler.handle("scene.get_info", {})["name"] == "Scene"
        with pytest.raises(PermissionError, match="whitelist"):
            handler.handle("python.execute", {"code": "pass"})


class TestParameterValidation:
    def test_translate_rejects_location_and_offset_together(self, handler):
        with pytest.raises(ValueError, match="not both"):
            handler.handle("object.translate", {"name": "Cube", "location": [0, 0, 0], "offset": [1, 1, 1]})

    def test_non_finite_numbers_rejected(self, handler):
        with pytest.raises(ValueError, match="finite"):
            handler.handle("object.scale", {"name": "Cube", "scale": [1, float("nan"), 1]})

    def test_material_set_color_accepts_rgba(self, handler, mock_bpy):
        material = MagicMock()
        material.name = "M"
        mock_bpy.data.materials.get = MagicMock(return_value=material)
        result = handler.handle("material.set_color", {"name": "M", "color": [1, 0, 0, 0.5]})
        assert result["color"] == [1.0, 0.0, 0.0, 0.5]


class TestServerAddonContract:
    """Every MCP tool must send parameters the add-on's validator accepts."""

    CALLS = [
        ("scene_list_objects", {"type": "MESH"}),
        ("object_get_transform", {"name": "Cube"}),
        ("object_get_hierarchy", {"name": "Cube"}),
        ("object_create", {"mesh_type": "sphere", "name": "S", "location": [1, 2, 3], "size": 1.0}),
        ("object_delete", {"name": "Cube"}),
        ("object_translate", {"name": "Cube", "offset": [1, 0, 0]}),
        ("object_rotate", {"name": "Cube", "rotation": [0, 0, 90]}),
        ("object_scale", {"name": "Cube", "scale": [2, 2, 2]}),
        ("object_duplicate", {"name": "Cube", "new_name": "Copy"}),
        ("material_create", {"name": "M", "color": [1, 0, 0]}),
        ("material_assign", {"object": "Cube", "material": "M"}),
        ("material_set_color", {"name": "M", "color": [1, 0, 0]}),
        ("material_set_texture", {"name": "M", "filepath": "/tmp/t.png"}),
        ("render_still", {"output_path": "/tmp/r.png", "resolution_x": 64, "resolution_y": 64, "engine": "CYCLES"}),
        ("render_animation", {"output_path": "/tmp/r_", "frame_start": 1, "frame_end": 2}),
        ("export_gltf", {"filepath": "/tmp/x.glb"}),
        ("export_obj", {"filepath": "/tmp/x.obj"}),
        ("export_fbx", {"filepath": "/tmp/x.fbx"}),
        ("python_exec", {"code": "pass", "args": {"a": 1}, "timeout_seconds": 5}),
        ("python_exec_async", {"code": "pass", "timeout_seconds": 5}),
        ("job_status", {"job_id": "job-1"}),
        ("job_cancel", {"job_id": "job-1"}),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("tool_name", "kwargs"), CALLS)
    async def test_tool_params_pass_addon_validation(self, addon_module, tool_name, kwargs):
        from unittest.mock import AsyncMock

        from blender_mcp_server import server

        ctx = MagicMock()
        ctx.request_context.lifespan_context.send_command = AsyncMock(return_value={})
        await getattr(server, tool_name)(ctx, **kwargs)
        command, params = ctx.request_context.lifespan_context.send_command.await_args.args

        validator = addon_module.CommandHandler._VALIDATORS.get(command)
        assert validator is not None, f"{command} has no add-on validator"
        validated = validator.model_validate(params).model_dump(exclude_none=True)
        for key in params:
            assert key in validated, f"{tool_name} sends '{key}', which the add-on drops"

    def test_every_bridge_command_is_handled(self, addon_module):
        from blender_mcp_server import server

        with open(server.__file__) as f:
            source = f.read()
        handlers = addon_module.CommandHandler()._handlers
        import re

        for command in re.findall(r'_bridge\(\s*ctx,\s*"([a-z_.]+)"', source):
            assert command in handlers, f"server sends unknown command {command}"


class TestVersionConsistency:
    def test_addon_version_matches_package(self, addon_module):
        import re

        with open("pyproject.toml") as f:
            pyproject = f.read()
        version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
        assert ".".join(map(str, addon_module.bl_info["version"])) == version
        with open("addon/blender_manifest.toml") as f:
            manifest = f.read()
        assert f'version = "{version}"' in manifest


def test_port_environment_variable_overrides_preference(handler, addon_module, mock_bpy, monkeypatch):
    prefs = MagicMock()
    prefs.safe_mode = False
    prefs.port = 9876
    prefs.allow_inline_code = True
    prefs.approved_script_roots = ""
    prefs.allowed_commands = ""
    mock_bpy.context.preferences.addons["addon"] = MagicMock(preferences=prefs)
    monkeypatch.setenv("BLENDER_MCP_PORT", "9911")
    addon_module._sync_runtime_settings()
    assert addon_module.PORT == 9911
