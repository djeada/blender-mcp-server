"""Tests for Blender lighting behavior."""

import math
from unittest.mock import MagicMock

import pytest

from .fakes import (
    _make_light_data,
    _make_light_object,
)


class TestLightCommands:
    @pytest.mark.parametrize("light_type", ["POINT", "SUN", "SPOT", "AREA"])
    def test_light_create_supported_types(self, handler, mock_bpy, light_type):
        _make_light_data(mock_bpy, light_type)
        _make_light_object(mock_bpy)
        result = handler.handle("light.create", {"type": light_type.lower()})

        mock_bpy.data.lights.new.assert_called_once_with(f"{light_type.capitalize()}Light", type=light_type)
        assert result["light_type"] == light_type
        assert result["type"] == "LIGHT"

    def test_light_create_unsupported_type(self, handler, mock_bpy):
        with pytest.raises(ValueError, match="Unsupported light type"):
            handler.handle("light.create", {"type": "VOLUMETRIC"})

    def test_light_create_defaults_to_point(self, handler, mock_bpy):
        _make_light_data(mock_bpy)
        _make_light_object(mock_bpy)
        result = handler.handle("light.create", {})
        assert result["light_type"] == "POINT"
        assert result["energy"] == 1000.0

    def test_light_create_rejects_out_of_range_color(self, handler, mock_bpy):
        _make_light_data(mock_bpy)
        _make_light_object(mock_bpy)
        with pytest.raises(ValueError, match="between 0 and 1"):
            handler.handle("light.create", {"color": [0.5, 1.5, 0.5]})

    def test_light_create_rejects_non_positive_energy(self, handler, mock_bpy):
        _make_light_data(mock_bpy)
        _make_light_object(mock_bpy)
        with pytest.raises(ValueError, match="greater than 0"):
            handler.handle("light.create", {"energy": 0})

    def test_light_create_point_size_sets_radius(self, handler, mock_bpy):
        light_data = _make_light_data(mock_bpy)
        _make_light_object(mock_bpy)
        handler.handle("light.create", {"type": "POINT", "size": 0.5})
        assert light_data.shadow_soft_size == 0.5

    def test_light_create_size_on_sun_is_rejected(self, handler, mock_bpy):
        _make_light_data(mock_bpy, "SUN")
        _make_light_object(mock_bpy)
        with pytest.raises(ValueError, match="'size' does not apply to SUN"):
            handler.handle("light.create", {"type": "SUN", "size": 1.0})

    def test_light_create_sun_angle(self, handler, mock_bpy):

        light_data = _make_light_data(mock_bpy, "SUN")
        _make_light_object(mock_bpy)
        handler.handle("light.create", {"type": "SUN", "angle": 5.0})
        assert light_data.angle == pytest.approx(math.radians(5.0))

    def test_light_create_angle_on_point_is_rejected(self, handler, mock_bpy):
        _make_light_data(mock_bpy)
        _make_light_object(mock_bpy)
        with pytest.raises(ValueError, match="'angle' applies to SUN"):
            handler.handle("light.create", {"angle": 5.0})

    def test_light_create_spot_full_configuration(self, handler, mock_bpy):

        light_data = _make_light_data(mock_bpy, "SPOT")
        _make_light_object(mock_bpy)
        handler.handle(
            "light.create",
            {"type": "SPOT", "size": 0.2, "spot_angle": 45.0, "spot_blend": 0.3},
        )
        assert light_data.shadow_soft_size == 0.2
        assert light_data.spot_size == pytest.approx(math.radians(45.0))
        assert light_data.spot_blend == 0.3

    def test_light_create_spot_blend_out_of_range(self, handler, mock_bpy):
        _make_light_data(mock_bpy, "SPOT")
        _make_light_object(mock_bpy)
        with pytest.raises(ValueError, match="spot_blend"):
            handler.handle("light.create", {"type": "SPOT", "spot_blend": 1.5})

    def test_light_create_spot_angle_on_area_is_rejected(self, handler, mock_bpy):
        _make_light_data(mock_bpy, "AREA")
        _make_light_object(mock_bpy)
        with pytest.raises(ValueError, match="'spot_angle' applies to SPOT"):
            handler.handle("light.create", {"type": "AREA", "spot_angle": 30.0})

    def test_light_create_area_rectangle(self, handler, mock_bpy):
        light_data = _make_light_data(mock_bpy, "AREA")
        _make_light_object(mock_bpy)
        handler.handle("light.create", {"type": "AREA", "size": 2.0, "size_y": 4.0})
        assert light_data.size == 2.0
        assert light_data.shape == "RECTANGLE"
        assert light_data.size_y == 4.0

    def test_light_create_size_y_on_spot_is_rejected(self, handler, mock_bpy):
        _make_light_data(mock_bpy, "SPOT")
        _make_light_object(mock_bpy)
        with pytest.raises(ValueError, match="'size_y' applies to AREA"):
            handler.handle("light.create", {"type": "SPOT", "size_y": 2.0})

    def test_light_create_with_look_at(self, handler, mock_bpy, fake_mathutils):
        _make_light_data(mock_bpy)
        obj = _make_light_object(mock_bpy)
        handler.handle("light.create", {"location": [3.0, 0.0, 5.0], "look_at": [0.0, 0.0, 0.0]})
        assert obj.rotation_euler == (0.0, 0.0, math.pi)

    def test_light_update_missing_object(self, handler, mock_bpy):
        mock_bpy.data.objects.get = lambda name: None
        with pytest.raises(ValueError, match="not found"):
            handler.handle("light.update", {"name": "Missing"})

    def test_light_update_requires_light_object(self, handler, mock_bpy):
        cube = MagicMock()
        cube.name = "Cube"
        cube.type = "MESH"
        mock_bpy.data.objects.get = lambda name: cube
        with pytest.raises(ValueError, match="is of type MESH, not LIGHT"):
            handler.handle("light.update", {"name": "Cube", "energy": 5.0})

    def test_light_update_energy_and_color(self, handler, mock_bpy):
        light_data = _make_light_data(mock_bpy)
        existing = MagicMock()
        existing.name = "KeyLight"
        existing.type = "LIGHT"
        existing.data = light_data
        existing.location = (0.0, 0.0, 0.0)
        mock_bpy.data.objects.get = lambda name: existing
        result = handler.handle("light.update", {"name": "KeyLight", "energy": 42.0, "color": [1.0, 0.5, 0.25]})
        assert light_data.energy == 42.0
        assert light_data.color == [1.0, 0.5, 0.25]
        assert result["energy"] == 42.0

    def test_light_update_type_change(self, handler, mock_bpy):
        light_data = _make_light_data(mock_bpy)
        existing = MagicMock()
        existing.name = "KeyLight"
        existing.type = "LIGHT"
        existing.data = light_data
        existing.location = (0.0, 0.0, 0.0)
        mock_bpy.data.objects.get = lambda name: existing
        result = handler.handle("light.update", {"name": "KeyLight", "type": "spot"})
        assert light_data.type == "SPOT"
        assert result["light_type"] == "SPOT"

    def test_camera_and_light_commands_push_undo(self, runtime):
        assert {
            "camera.create",
            "camera.update",
            "light.create",
            "light.update",
        } <= runtime.handler.mutation_commands
