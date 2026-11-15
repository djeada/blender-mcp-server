"""Tests for Blender scene behavior."""

import types
from unittest.mock import MagicMock

import pytest

from .fakes import (
    _FakeCollection,
    _install_fake_collections,
)


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


class TestSceneListObjectsPagination:
    def _objects(self, mock_bpy):
        scene = mock_bpy.context.scene
        return scene.objects

    def test_pagination_and_total(self, handler, mock_bpy):
        cube, camera = mock_bpy.context.scene.objects
        extra = MagicMock()
        extra.name = "Ball"
        extra.type = "MESH"
        extra.location = MagicMock()
        extra.visible_get.return_value = True
        mock_bpy.context.scene.objects = [cube, camera, extra]

        result = handler.handle("scene.list_objects", {"limit": 2, "offset": 1})
        assert result["total"] == 3
        assert result["count"] == 2
        assert result["offset"] == 1
        assert [o["name"] for o in result["objects"]] == ["Camera", "Cube"]

    def test_name_filter_is_case_insensitive(self, handler, mock_bpy):
        result = handler.handle("scene.list_objects", {"name": "CUB"})
        assert [o["name"] for o in result["objects"]] == ["Cube"]

    def test_visible_filter(self, handler, mock_bpy):
        cube, camera = mock_bpy.context.scene.objects
        cube.visible_get.return_value = False
        result = handler.handle("scene.list_objects", {"visible": False})
        assert [o["name"] for o in result["objects"]] == ["Cube"]

    def test_collection_filter_missing_collection(self, handler, mock_bpy):
        _install_fake_collections(mock_bpy)
        with pytest.raises(ValueError, match="not found"):
            handler.handle("scene.list_objects", {"collection": "Props"})

    def test_collection_filter(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        props = colls.setdefault("Props", _FakeCollection("Props", {"Props"}))
        member = types.SimpleNamespace(name="Cube")
        props.objects.link(member)
        cube = MagicMock()
        cube.name = "Cube"
        cube.type = "MESH"
        mock_bpy.context.scene.objects = [cube]
        result = handler.handle("scene.list_objects", {"collection": "Props"})
        assert [o["name"] for o in result["objects"]] == ["Cube"]
        assert result["total"] == 1
