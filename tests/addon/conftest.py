import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from .fakes import _FakeVector


def _create_mock_bpy():
    """Create a mock bpy module for testing outside Blender."""
    bpy = MagicMock()
    for name in ("AddonPreferences", "Panel", "Operator"):
        setattr(bpy.types, name, type(name, (), {}))
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
def mock_bpy(monkeypatch):
    """Install mock bpy before importing the addon."""
    mock = _create_mock_bpy()
    app_module = types.ModuleType("bpy.app")
    app_module.handlers = mock.app.handlers
    app_module.timers = mock.app.timers
    monkeypatch.setitem(sys.modules, "bpy", mock)
    monkeypatch.setitem(sys.modules, "bpy.app", app_module)
    monkeypatch.setitem(sys.modules, "bpy.app.handlers", mock.app.handlers)
    monkeypatch.setitem(sys.modules, "mathutils", MagicMock())
    return mock


@pytest.fixture
def addon_module(mock_bpy, monkeypatch):
    """Load a fresh add-on package so feature modules share this test's bpy mock."""
    import importlib.util

    for name in tuple(sys.modules):
        if name == "addon" or name.startswith("addon."):
            monkeypatch.delitem(sys.modules, name)
    path = Path(__file__).resolve().parents[2] / "addon" / "__init__.py"
    spec = importlib.util.spec_from_file_location("addon", path)
    addon = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "addon", addon)
    spec.loader.exec_module(addon)
    yield addon
    for name in tuple(sys.modules):
        if name.startswith("addon."):
            sys.modules.pop(name, None)


@pytest.fixture
def runtime(addon_module):
    return addon_module.runtime.runtime


@pytest.fixture
def handler(runtime):
    return runtime.handler


@pytest.fixture
def fake_mathutils(monkeypatch):
    module = types.ModuleType("mathutils")
    module.Vector = _FakeVector
    monkeypatch.setitem(sys.modules, "mathutils", module)
    return module
