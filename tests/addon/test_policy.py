"""Tests for Blender policy behavior."""

import os
import tempfile
from unittest.mock import MagicMock

import pytest


class TestPythonSandbox:
    """Tests for MCP-103 sandbox and path restrictions."""

    def test_script_outside_roots_rejected(self, handler, runtime):
        with tempfile.TemporaryDirectory() as allowed_dir, tempfile.TemporaryDirectory() as forbidden_dir:
            script = os.path.join(forbidden_dir, "evil.py")
            with open(script, "w") as f:
                f.write("pass\n")

            runtime.settings.approved_script_roots = [allowed_dir]
            try:
                with pytest.raises(PermissionError, match="outside approved"):
                    handler.handle("python.execute", {"script_path": script})
            finally:
                runtime.settings.approved_script_roots = []

    def test_script_inside_roots_accepted(self, handler, runtime):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "good.py")
            with open(script, "w") as f:
                f.write("__result__ = 'ok'\n")

            runtime.settings.approved_script_roots = [tmpdir]
            try:
                result = handler.handle("python.execute", {"script_path": script})
                assert result["result"] == "ok"
            finally:
                runtime.settings.approved_script_roots = []

    def test_inline_code_disabled_rejects(self, handler, runtime):
        runtime.settings.allow_inline_code = False
        try:
            with pytest.raises(PermissionError, match="disabled"):
                handler.handle("python.execute", {"code": "pass"})
        finally:
            runtime.settings.allow_inline_code = True

    def test_inline_code_enabled_allows(self, handler, runtime):
        runtime.settings.allow_inline_code = True
        result = handler.handle("python.execute", {"code": "__result__ = True"})
        assert result["result"] is True

    def test_runtime_preferences_are_applied(self, handler, mock_bpy, runtime):
        prefs = MagicMock()
        prefs.safe_mode = True
        prefs.port = 9988
        prefs.allow_inline_code = False
        prefs.approved_script_roots = "/tmp/a;/tmp/b"
        mock_bpy.context.preferences.addons["addon"] = MagicMock(preferences=prefs)

        with pytest.raises(PermissionError, match="disabled"):
            handler.handle("python.execute", {"code": "pass"})

        assert runtime.settings.safe_mode is True
        assert runtime.settings.port == 9988
        assert runtime.settings.allow_inline_code is False
        assert runtime.settings.approved_script_roots == ["/tmp/a", "/tmp/b"]
        assert runtime.settings.allowed_paths == ["/tmp/a", "/tmp/b"]

    def test_non_py_script_rejected(self, handler, runtime):
        with tempfile.TemporaryDirectory() as tmpdir:
            script = os.path.join(tmpdir, "script.txt")
            with open(script, "w") as f:
                f.write("pass\n")

            runtime.settings.approved_script_roots = [tmpdir]
            try:
                with pytest.raises(ValueError, match=".py"):
                    handler.handle("python.execute", {"script_path": script})
            finally:
                runtime.settings.approved_script_roots = []


class TestSafeModeAndPaths:
    def test_prefix_sibling_directory_is_not_allowed(self, handler, runtime):
        with tempfile.TemporaryDirectory() as parent:
            allowed = os.path.join(parent, "proj")
            os.makedirs(allowed)
            runtime.settings.safe_mode = True
            runtime.settings.allowed_paths = [allowed]
            handler.policy.validate_filepath(os.path.join(allowed, "out.png"))
            with pytest.raises(PermissionError):
                handler.policy.validate_filepath(os.path.join(parent, "proj-evil", "out.png"))

    def test_symlink_escape_is_blocked(self, handler, runtime):
        with tempfile.TemporaryDirectory() as allowed, tempfile.TemporaryDirectory() as outside:
            link = os.path.join(allowed, "link")
            os.symlink(outside, link)
            runtime.settings.safe_mode = True
            runtime.settings.allowed_paths = [allowed]
            with pytest.raises(PermissionError):
                handler.policy.validate_filepath(os.path.join(link, "out.png"))

    def test_safe_mode_disables_inline_code(self, handler, runtime):
        runtime.settings.safe_mode = True
        with pytest.raises(PermissionError, match="Safe Mode"):
            handler.handle("python.execute", {"code": "pass"}, sync_settings=False)

    def test_unsaved_blend_without_roots_denies_scripts(self, handler, mock_bpy, tmp_path):
        mock_bpy.data.filepath = ""
        script = tmp_path / "s.py"
        script.write_text("pass\n")
        with pytest.raises(PermissionError, match="unsaved"):
            handler.handle("python.execute", {"script_path": str(script)})

    def test_allowed_commands_preference_is_enforced(self, handler, mock_bpy):
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


class TestAsyncInlineDisabled:
    """Verify inline code toggle works for async path too."""

    def test_async_inline_disabled_rejects(self, handler, runtime):
        runtime.settings.allow_inline_code = False
        try:
            with pytest.raises(PermissionError, match="disabled"):
                handler.handle("python.execute_async", {"code": "pass"})
        finally:
            runtime.settings.allow_inline_code = True

    def test_async_script_path_outside_roots_rejected(self, handler, runtime):
        with tempfile.TemporaryDirectory() as allowed_dir, tempfile.TemporaryDirectory() as forbidden_dir:
            script = os.path.join(forbidden_dir, "bad.py")
            with open(script, "w") as f:
                f.write("pass\n")

            runtime.settings.approved_script_roots = [allowed_dir]
            try:
                with pytest.raises(PermissionError, match="outside approved"):
                    handler.handle("python.execute_async", {"script_path": script})
            finally:
                runtime.settings.approved_script_roots = []

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
