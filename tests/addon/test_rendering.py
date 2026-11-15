"""Tests for Blender rendering behavior."""

import os
import tempfile

import pytest


class _FakeRender:
    """Render settings whose engine enum rejects unknown names the way bpy does."""

    resolution_x = 1920
    resolution_y = 1080
    filepath = ""
    resolution_percentage = 100
    use_compositing = True
    use_file_extension = True
    file_extension = ".png"

    def frame_path(self):
        return self.filepath

    def __init__(self, engines):
        self._engines = engines
        self._engine = engines[0]

    @property
    def engine(self):
        return self._engine

    @engine.setter
    def engine(self, value):
        if value not in self._engines:
            raise TypeError(f'enum "{value}" not found in {self._engines}')
        self._engine = value


class TestOutputPaths:
    def test_export_creates_folder_adds_extension_and_returns_absolute_path(self, handler, mock_bpy, tmp_path):
        target = tmp_path / "new" / "dir" / "model"
        result = handler.handle("export.gltf", {"filepath": str(target)})
        assert result["filepath"] == f"{target}.glb"
        assert target.parent.is_dir()
        mock_bpy.ops.export_scene.gltf.assert_called_once_with(filepath=f"{target}.glb", export_format="GLB")

    def test_export_extension_check_ignores_case(self, handler, tmp_path):
        result = handler.handle("export.obj", {"filepath": str(tmp_path / "a.OBJ")})
        assert result["filepath"] == str(tmp_path / "a.OBJ")

    def test_blend_relative_path_uses_temp_folder_while_unsaved(self, handler, mock_bpy, monkeypatch, tmp_path):
        mock_bpy.data.filepath = ""
        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
        result = handler.handle("render.still", {})
        expected = str(tmp_path / "blender-mcp" / "render.png")
        assert result["output_path"] == expected
        assert mock_bpy.context.scene.render.filepath == expected
        assert (tmp_path / "blender-mcp").is_dir()

    def test_blend_relative_path_is_left_to_blender_when_saved(self, handler, mock_bpy, tmp_path):
        mock_bpy.data.filepath = str(tmp_path / "scene.blend")
        mock_bpy.path.abspath = lambda path: str(tmp_path / path[2:])
        result = handler.handle("export.fbx", {"filepath": "//out/model.fbx"})
        assert result["filepath"] == str(tmp_path / "out" / "model.fbx")

    def test_directory_style_render_path_keeps_trailing_separator(self, handler, tmp_path):
        frames = str(tmp_path / "frames") + os.sep
        result = handler.handle("render.animation", {"output_path": frames})
        assert result["output_path"] == frames
        assert (tmp_path / "frames").is_dir()

    def test_safe_mode_is_enforced_on_the_resolved_path(self, handler, tmp_path, runtime):
        allowed = tmp_path / "ok"
        allowed.mkdir()
        runtime.settings.safe_mode = True
        runtime.settings.allowed_paths = [str(allowed)]
        with pytest.raises(PermissionError):
            handler.handle("export.fbx", {"filepath": str(tmp_path / "outside" / "x.fbx")})
        assert not (tmp_path / "outside").exists(), "a denied export must not create folders"
        assert handler.handle("export.fbx", {"filepath": str(allowed / "x")})["filepath"] == str(allowed / "x.fbx")


class TestRenderEngineNames:
    @pytest.mark.parametrize(
        ("available", "requested", "expected"),
        [
            (("BLENDER_EEVEE_NEXT", "CYCLES"), "BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"),  # Blender 4.2-4.5
            (("BLENDER_EEVEE_NEXT", "CYCLES"), "eevee", "BLENDER_EEVEE_NEXT"),
            (("BLENDER_EEVEE", "CYCLES"), "BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"),  # Blender 5.x
            (("BLENDER_EEVEE", "CYCLES"), "Eevee", "BLENDER_EEVEE"),
            (("BLENDER_EEVEE", "BLENDER_WORKBENCH"), "workbench", "BLENDER_WORKBENCH"),
            (("BLENDER_EEVEE", "CYCLES"), "cycles", "CYCLES"),
        ],
    )
    def test_engine_name_is_resolved_for_the_running_blender(
        self, handler, mock_bpy, tmp_path, available, requested, expected
    ):
        mock_bpy.context.scene.render = _FakeRender(available)
        result = handler.handle("render.still", {"output_path": str(tmp_path / "r.png"), "engine": requested})
        assert result["engine"] == expected

    def test_unknown_engine_reports_version_error(self, handler, mock_bpy, tmp_path):
        mock_bpy.context.scene.render = _FakeRender(("BLENDER_EEVEE", "CYCLES"))
        with pytest.raises(ValueError, match="Unknown render engine on this Blender version"):
            handler.handle("render.animation", {"output_path": str(tmp_path / "r_"), "engine": "luxrender"})
        mock_bpy.ops.render.render.assert_not_called()
