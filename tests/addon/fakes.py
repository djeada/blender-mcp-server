"""Small Blender data stand-ins shared by feature tests."""

import math
import types
from unittest.mock import MagicMock


class _FakeVector:
    """Minimal mathutils.Vector stand-in for look-at tests."""

    def __init__(self, xyz):
        self.xyz = [float(v) for v in xyz]

    def __sub__(self, other):
        return _FakeVector([a - b for a, b in zip(self.xyz, other.xyz, strict=False)])

    @property
    def length(self):
        return sum(v * v for v in self.xyz) ** 0.5

    def to_track_quat(self, track, up):
        return _FakeQuaternion()


class _FakeQuaternion:
    def to_euler(self):
        return (0.0, 0.0, math.pi)


def _make_camera_data(mock_bpy):
    cam_data = MagicMock()
    cam_data.type = "PERSP"
    cam_data.lens = 50.0
    cam_data.ortho_scale = 1.0
    cam_data.clip_start = 0.1
    cam_data.clip_end = 100.0
    mock_bpy.data.cameras.new.return_value = cam_data
    return cam_data


def _make_camera_object(mock_bpy, name="Camera"):
    obj = MagicMock()
    obj.name = name
    obj.type = "CAMERA"
    obj.location = (0.0, 0.0, 0.0)
    mock_bpy.data.objects.new.return_value = obj
    return obj


def _make_light_data(mock_bpy, light_type="POINT"):
    light_data = MagicMock()
    light_data.type = light_type
    light_data.energy = 1000.0
    light_data.color = (1.0, 1.0, 1.0)
    mock_bpy.data.lights.new.return_value = light_data
    return light_data


def _make_light_object(mock_bpy, name="Light"):
    obj = MagicMock()
    obj.name = name
    obj.type = "LIGHT"
    obj.location = (0.0, 0.0, 0.0)
    mock_bpy.data.objects.new.return_value = obj
    return obj


class _FakeKey:
    def __init__(self, frame, value=0.0):
        self.co = (frame, value)
        self.interpolation = None


class _FakeFCurve:
    def __init__(self, data_path, array_index, keys=None):
        self.data_path = data_path
        self.array_index = array_index
        self.keyframe_points = list(keys or [])


def _make_animatable_object(mock_bpy, fcurves=None, name="Cube"):
    obj = MagicMock()
    obj.name = name
    anim = MagicMock()
    obj.animation_data = anim
    obj.animation_data_create.return_value = anim
    if fcurves is not None:
        anim.action = MagicMock(name="CubeAction")
        anim.action.name = "CubeAction"
        anim.action.fcurves = list(fcurves)
    mock_bpy.data.objects.get = lambda n: obj if n == name else None
    return obj, anim


class _FakeCollection:
    """Standalone collection with bpy-like name collision handling."""

    def __init__(self, name, taken_names):
        self.taken_names = taken_names
        self._name = name
        self.objects = _FakeBpyList()
        self.children = _FakeBpyList()

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if value in self.taken_names and value != self._name:
            self._name = f"{value}.001"
        else:
            self._name = value


class _FakeBpyList:
    def __init__(self):
        self.items = []

    def get(self, name):
        return next((item for item in self.items if getattr(item, "name", None) == name), None)

    def link(self, item):
        self.items.append(item)

    def unlink(self, item):
        if item in self.items:
            self.items.remove(item)

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)


def _install_fake_collections(mock_bpy):
    colls: dict[str, _FakeCollection] = {}
    taken: set[str] = set()

    def get(name):
        return colls.get(name)

    def new(name):
        taken.add(name)
        coll = _FakeCollection(name, taken)
        colls[name] = coll
        return coll

    mock_bpy.data.collections.get = get
    mock_bpy.data.collections.new = new
    mock_bpy.data.collections.__iter__ = lambda self: iter(colls.values())
    mock_bpy.context.scene.collection = types.SimpleNamespace(
        name="Scene Collection", children=_FakeBpyList(), objects=_FakeBpyList()
    )
    return colls


class _FakeObject:
    """Object stub with bpy-like name collision handling and dynamic collection membership."""

    def __init__(self, name, taken_names=None, colls=None):
        self.taken_names = taken_names or set()
        self.colls = colls or []
        self._name = name

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, value):
        if value in self.taken_names and value != self._name:
            self._name = f"{value}.001"
        else:
            self._name = value

    @property
    def users_collection(self):
        return [coll for coll in self.colls if self in coll.objects.items]
