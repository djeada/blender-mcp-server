"""Tests for Blender animation behavior."""

import math
from unittest.mock import MagicMock

import pytest

from .fakes import (
    _FakeFCurve,
    _FakeKey,
    _make_animatable_object,
)


class TestTimelineCommands:
    def test_timeline_get(self, handler):
        result = handler.handle("timeline.get", {})
        assert result == {"frame_current": 1, "frame_start": 1, "frame_end": 250}

    def test_timeline_set_frame_and_range(self, handler, mock_bpy):
        scene = mock_bpy.context.scene
        scene.frame_set.side_effect = lambda f: setattr(scene, "frame_current", f)
        result = handler.handle("timeline.set", {"frame_start": 10, "frame_end": 50, "frame_current": 20})
        assert result == {"frame_current": 20, "frame_start": 10, "frame_end": 50}
        scene.frame_set.assert_called_once_with(20)

    def test_timeline_set_partial(self, handler, mock_bpy):
        result = handler.handle("timeline.set", {"frame_end": 120})
        assert result["frame_end"] == 120
        assert result["frame_start"] == 1
        mock_bpy.context.scene.frame_set.assert_not_called()

    def test_timeline_set_rejects_inverted_range(self, handler, mock_bpy):
        with pytest.raises(ValueError, match="must not exceed"):
            handler.handle("timeline.set", {"frame_start": 100, "frame_end": 50})


class TestKeyframeCommands:
    def _location_fcurves(self):
        return [_FakeFCurve("location", i) for i in range(3)]

    def test_keyframe_insert_new_keys(self, handler, mock_bpy):
        fcurves = self._location_fcurves()
        obj, anim = _make_animatable_object(mock_bpy, fcurves)

        def insert_side_effect(data_path, frame):
            for fc in fcurves:
                fc.keyframe_points.append(_FakeKey(frame, 0.0))
            return True

        obj.keyframe_insert.side_effect = insert_side_effect
        result = handler.handle("keyframe.insert", {"name": "Cube", "property": "location", "frame": 10})
        assert result["result"] == "inserted"
        assert result["keyframe_count"] == 3
        assert result["action"] == "CubeAction"
        assert result["frame"] == 10

    def test_keyframe_insert_overwrites_existing_key(self, handler, mock_bpy):
        fcurves = [_FakeFCurve("location", i, [_FakeKey(10, 0.0)]) for i in range(3)]
        obj, anim = _make_animatable_object(mock_bpy, fcurves)
        obj.keyframe_insert.return_value = True
        result = handler.handle("keyframe.insert", {"name": "Cube", "property": "location", "frame": 10})
        assert result["result"] == "overwritten"
        assert result["keyframe_count"] == 3

    def test_keyframe_insert_sets_value_before_insert(self, handler, mock_bpy):
        fcurves = self._location_fcurves()
        obj, anim = _make_animatable_object(mock_bpy, fcurves)
        obj.keyframe_insert.return_value = True
        handler.handle(
            "keyframe.insert",
            {"name": "Cube", "property": "location", "frame": 5, "value": [1.0, 2.0, 3.0]},
        )
        assert list(obj.location) == [1.0, 2.0, 3.0]

    def test_keyframe_insert_rotation_converts_degrees(self, handler, mock_bpy):
        fcurves = [_FakeFCurve("rotation_euler", i) for i in range(3)]
        obj, anim = _make_animatable_object(mock_bpy, fcurves)
        obj.keyframe_insert.return_value = True
        handler.handle(
            "keyframe.insert",
            {"name": "Cube", "property": "rotation", "frame": 5, "value": [0.0, 0.0, 90.0]},
        )
        assert obj.rotation_euler == pytest.approx([0.0, 0.0, math.pi / 2])

    def test_keyframe_insert_applies_interpolation(self, handler, mock_bpy):
        fcurves = self._location_fcurves()
        obj, anim = _make_animatable_object(mock_bpy, fcurves)

        def insert_side_effect(data_path, frame):
            for fc in fcurves:
                fc.keyframe_points.append(_FakeKey(frame, 0.0))
            return True

        obj.keyframe_insert.side_effect = insert_side_effect
        handler.handle(
            "keyframe.insert",
            {"name": "Cube", "property": "location", "frame": 10, "interpolation": "linear"},
        )
        assert all(key.interpolation == "LINEAR" for fc in fcurves for key in fc.keyframe_points)

    def test_keyframe_insert_rejects_unknown_property(self, handler, mock_bpy):
        obj, anim = _make_animatable_object(mock_bpy, [])
        with pytest.raises(ValueError, match="Unsupported animatable property"):
            handler.handle("keyframe.insert", {"name": "Cube", "property": "visibility", "frame": 1})

    def test_keyframe_insert_rejects_unknown_interpolation(self, handler, mock_bpy):
        fcurves = self._location_fcurves()
        obj, anim = _make_animatable_object(mock_bpy, fcurves)
        obj.keyframe_insert.return_value = True
        with pytest.raises(ValueError, match="Unsupported interpolation"):
            handler.handle(
                "keyframe.insert",
                {"name": "Cube", "property": "location", "frame": 1, "interpolation": "WARP"},
            )

    def test_keyframe_insert_failed_insert(self, handler, mock_bpy):
        fcurves = self._location_fcurves()
        obj, anim = _make_animatable_object(mock_bpy, fcurves)
        obj.keyframe_insert.return_value = False
        with pytest.raises(ValueError, match="Keyframe insertion failed"):
            handler.handle("keyframe.insert", {"name": "Cube", "property": "location", "frame": 1})

    def test_keyframe_insert_missing_object(self, handler, mock_bpy):
        mock_bpy.data.objects.get = lambda n: None
        with pytest.raises(ValueError, match="not found"):
            handler.handle("keyframe.insert", {"name": "Missing", "property": "location", "frame": 1})

    def test_keyframe_list(self, handler, mock_bpy):
        fcurves = [
            _FakeFCurve("location", 0, [_FakeKey(1, 0.0), _FakeKey(10, 2.0)]),
            _FakeFCurve("location", 1, [_FakeKey(1, 1.0)]),
        ]
        obj, anim = _make_animatable_object(mock_bpy, fcurves)
        result = handler.handle("keyframe.list", {"name": "Cube", "property": "location"})
        assert result["keyframe_count"] == 3
        assert result["keys"][0] == {"channel": 0, "frame": 1, "value": 0.0}
        assert result["keys"][-1] == {"channel": 1, "frame": 1, "value": 1.0}

    def test_keyframe_list_requires_animation_data(self, handler, mock_bpy):
        obj = MagicMock()
        obj.name = "Cube"
        obj.animation_data = None
        mock_bpy.data.objects.get = lambda n: obj
        with pytest.raises(ValueError, match="no animation data"):
            handler.handle("keyframe.list", {"name": "Cube", "property": "location"})

    def test_keyframe_remove(self, handler, mock_bpy):
        fcurves = [_FakeFCurve("location", i, [_FakeKey(1), _FakeKey(10)]) for i in range(3)]
        obj, anim = _make_animatable_object(mock_bpy, fcurves)

        def delete_side_effect(data_path, frame):
            for fc in fcurves:
                fc.keyframe_points = [k for k in fc.keyframe_points if k.co[0] != frame]
            return True

        obj.keyframe_delete.side_effect = delete_side_effect
        result = handler.handle("keyframe.remove", {"name": "Cube", "property": "location", "frame": 10})
        assert result["removed"] == 3
        assert result["keyframe_count"] == 3

    def test_keyframe_remove_no_key_at_frame(self, handler, mock_bpy):
        fcurves = [_FakeFCurve("location", i, [_FakeKey(1)]) for i in range(3)]
        obj, anim = _make_animatable_object(mock_bpy, fcurves)
        obj.keyframe_delete.return_value = False
        with pytest.raises(ValueError, match="No keyframe"):
            handler.handle("keyframe.remove", {"name": "Cube", "property": "location", "frame": 99})

    def test_keyframe_remove_requires_animation_data(self, handler, mock_bpy):
        obj = MagicMock()
        obj.name = "Cube"
        obj.animation_data = None
        mock_bpy.data.objects.get = lambda n: obj
        with pytest.raises(ValueError, match="no animation data"):
            handler.handle("keyframe.remove", {"name": "Cube", "property": "scale", "frame": 1})
