"""Tests for the Blender add-on command handler using mocked bpy."""

import json
import sys
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
    yield mock
    del sys.modules["bpy"]


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
