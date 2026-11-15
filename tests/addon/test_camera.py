"""Tests for Blender camera behavior."""

import math
from unittest.mock import MagicMock

import pytest

from .fakes import (
    _make_camera_data,
    _make_camera_object,
)


class TestCameraCommands:
    def test_camera_create_defaults(self, handler, mock_bpy):
        _make_camera_data(mock_bpy)
        obj = _make_camera_object(mock_bpy, name="Front Cam")
        result = handler.handle("camera.create", {"name": "Front Cam"})

        mock_bpy.data.cameras.new.assert_called_once_with("Front Cam")
        mock_bpy.context.scene.collection.objects.link.assert_called_once_with(obj)
        assert result["name"] == "Front Cam"
        assert result["type"] == "CAMERA"
        assert result["projection"] == "PERSP"
        assert result["lens"] == 50.0
        assert result["clip_start"] == 0.1
        assert result["clip_end"] == 100.0
        assert result["active"] is False

    def test_camera_create_with_look_at_aims_at_target(self, handler, mock_bpy, fake_mathutils):
        _make_camera_data(mock_bpy)
        obj = _make_camera_object(mock_bpy)
        result = handler.handle(
            "camera.create",
            {"name": "Cam", "location": [7.0, -6.0, 5.0], "look_at": [0.0, 0.0, 0.0]},
        )

        assert list(obj.location) == [7.0, -6.0, 5.0]
        assert obj.rotation_euler == (0.0, 0.0, math.pi)
        assert result["location"] == [7.0, -6.0, 5.0]

    def test_camera_create_with_rotation(self, handler, mock_bpy):
        _make_camera_data(mock_bpy)
        obj = _make_camera_object(mock_bpy)
        handler.handle("camera.create", {"rotation": [0, 0, 90]})
        assert obj.rotation_euler == pytest.approx([0.0, 0.0, math.pi / 2])

    def test_camera_create_rejects_rotation_and_look_at_together(self, handler, mock_bpy, fake_mathutils):
        _make_camera_data(mock_bpy)
        _make_camera_object(mock_bpy)
        with pytest.raises(ValueError, match="not both"):
            handler.handle("camera.create", {"rotation": [0, 0, 0], "look_at": [0, 0, 0]})

    def test_camera_create_set_active(self, handler, mock_bpy):
        _make_camera_data(mock_bpy)
        obj = _make_camera_object(mock_bpy)
        mock_bpy.context.scene.camera = None
        result = handler.handle("camera.create", {"set_active": True})
        assert mock_bpy.context.scene.camera is obj
        assert result["active"] is True

    def test_camera_create_ortho_with_ortho_scale(self, handler, mock_bpy):
        cam_data = _make_camera_data(mock_bpy)
        _make_camera_object(mock_bpy)
        result = handler.handle("camera.create", {"projection": "ortho", "ortho_scale": 10.0})
        assert cam_data.type == "ORTHO"
        assert result["projection"] == "ORTHO"
        assert cam_data.ortho_scale == 10.0

    def test_camera_create_rejects_lens_for_ortho(self, handler, mock_bpy):
        cam_data = _make_camera_data(mock_bpy)
        cam_data.type = "ORTHO"
        _make_camera_object(mock_bpy)
        with pytest.raises(ValueError, match="'lens' applies to PERSP"):
            handler.handle("camera.create", {"lens": 35.0})

    def test_camera_create_rejects_ortho_scale_for_persp(self, handler, mock_bpy):
        _make_camera_data(mock_bpy)
        _make_camera_object(mock_bpy)
        with pytest.raises(ValueError, match="'ortho_scale' applies to ORTHO"):
            handler.handle("camera.create", {"ortho_scale": 10.0})

    def test_camera_create_rejects_unknown_projection(self, handler, mock_bpy):
        _make_camera_data(mock_bpy)
        _make_camera_object(mock_bpy)
        with pytest.raises(ValueError, match="Unsupported camera projection"):
            handler.handle("camera.create", {"projection": "FISHEYE"})

    def test_camera_create_rejects_non_positive_lens(self, handler, mock_bpy):
        _make_camera_data(mock_bpy)
        _make_camera_object(mock_bpy)
        with pytest.raises(ValueError, match="greater than 0"):
            handler.handle("camera.create", {"lens": 0})

    def test_camera_create_rejects_inverted_clipping(self, handler, mock_bpy):
        _make_camera_data(mock_bpy)
        _make_camera_object(mock_bpy)
        with pytest.raises(ValueError, match="clip_start"):
            handler.handle("camera.create", {"clip_start": 5.0, "clip_end": 1.0})

    def test_camera_update_requires_camera_object(self, handler, mock_bpy):
        cube = MagicMock()
        cube.name = "Cube"
        cube.type = "MESH"
        mock_bpy.data.objects.get = lambda name: cube
        with pytest.raises(ValueError, match="is of type MESH, not CAMERA"):
            handler.handle("camera.update", {"name": "Cube", "lens": 35.0})

    def test_camera_update_missing_object(self, handler, mock_bpy):
        mock_bpy.data.objects.get = lambda name: None
        with pytest.raises(ValueError, match="not found"):
            handler.handle("camera.update", {"name": "Missing"})

    def test_camera_update_applies_settings(self, handler, mock_bpy):
        cam_data = _make_camera_data(mock_bpy)
        existing = MagicMock()
        existing.name = "Camera"
        existing.type = "CAMERA"
        existing.data = cam_data
        existing.location = (0.0, 0.0, 0.0)
        mock_bpy.data.objects.get = lambda name: existing
        result = handler.handle("camera.update", {"name": "Camera", "lens": 85.0, "clip_end": 500.0})
        assert cam_data.lens == 85.0
        assert cam_data.clip_end == 500.0
        assert result["lens"] == 85.0
