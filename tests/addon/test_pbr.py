"""Tests for PBR texture-set validation and image loading. Node graphs are tested in real Blender."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def pbr(addon_module):
    return addon_module.pbr


def test_orm_expands_to_the_gltf_layout(pbr):
    maps = pbr._requested_maps({"orm": "/t/orm.png"})
    assert {name: spec["channel"] for name, spec in maps.items()} == {"ao": "R", "roughness": "G", "metallic": "B"}
    assert maps["ao"]["mode"] == "gltf"
    custom = pbr._requested_maps({"orm": "/t/orm.png", "maps": {"ao": {"path": "/t/ao.png", "mode": "multiply"}}})
    assert custom["ao"]["path"] == "/t/ao.png" and custom["roughness"]["path"] == "/t/orm.png"


def test_channels_are_normalized(pbr):
    assert pbr._validate_spec("roughness", "/a.png") == {"path": "/a.png", "channel": "R"}
    assert pbr._validate_spec("opacity", {"path": "/a.png", "channel": "a", "mode": "blend"})["channel"] == "A"


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"maps": {"specular": "/a.png"}}, "Unknown map 'specular'"),
        ({"maps": {"roughness": 5}}, "must be a path or an object"),
        ({"maps": {"roughness": {}}}, "needs a 'path'"),
        ({"maps": {"base_color": {"path": "/a.png", "channel": "R"}}}, "does not accept: channel"),
        ({"maps": {"roughness": {"path": "/a.png", "channel": "X"}}}, "channel must be one of"),
        ({"maps": {"normal": "/a.png"}}, "needs 'convention': opengl or directx"),
        ({"maps": {"ao": "/a.png"}}, "needs 'mode': gltf or multiply"),
        ({"maps": {"opacity": "/a.png"}}, "needs 'mode': blend or clip"),
        ({"maps": {"height": "/a.png"}}, "needs 'mode': bump or displacement"),
        ({"maps": {"height": {"path": "/a.png", "mode": "bump", "midlevel": 0.5}}}, "midlevel"),
        ({"maps": {"normal": {"path": "/a.png", "convention": "opengl", "strength": 50}}}, "from 0 to 10"),
        ({"maps": {"emission": {"path": "/a.png", "strength": "bright"}}}, "from 0 to 1000"),
        ({"orm": "/o.png", "maps": {"roughness": "/r.png"}}, "'orm' already provides roughness"),
        ({"mapping": {"shear": [1, 1]}}, "does not accept: shear"),
        ({"mapping": {"scale": [1]}}, "two numbers"),
        ({"mapping": {"rotation": "left"}}, "number of degrees"),
        ({"remove": ["specular"]}, "'remove' lists map names"),
        ({"remove": ["roughness"], "maps": {"roughness": "/r.png"}}, "both set and remove"),
        ({}, "Provide 'maps'"),
        ({"maps": {"roughness": "/r.png"}, "on_conflict": "merge"}, "on_conflict"),
    ],
)
def test_invalid_requests_fail_before_loading(handler, mock_bpy, params, message):
    material = SimpleNamespace(name="M", library=None, use_nodes=False, node_tree=None)
    mock_bpy.data.materials.get = lambda name: material
    with pytest.raises(ValueError, match=message):
        handler.handle("material.set_texture_set", {"name": "M", **params})
    assert material.use_nodes is False
    mock_bpy.data.images.load.assert_not_called()


class _Image:
    def __init__(self, path, space="sRGB", size=(4, 4)):
        self.filepath, self.source, self.size = path, "FILE", size
        self.colorspace_settings = SimpleNamespace(name=space)


class _Images(list):
    def __init__(self, fail=(), sizes=None):
        super().__init__()
        self.fail, self.sizes, self.removed = set(fail), sizes or {}, []

    def load(self, path, check_existing=False):
        name = path.rsplit("/", 1)[-1]
        if name in self.fail:
            raise RuntimeError("cannot read")
        image = _Image(path, size=self.sizes.get(name, (4, 4)))
        self.append(image)
        return image

    def remove(self, image):
        self.removed.append(image)
        list.remove(self, image)


@pytest.fixture
def files(tmp_path):
    for name in ("a.png", "b.png"):
        (tmp_path / name).write_bytes(b"data")
    return tmp_path


def test_an_existing_image_is_reused_only_with_the_wanted_color_space(addon_module, mock_bpy, files):
    mock_bpy.data.images = images = _Images()
    path = str(files / "a.png")
    shared = _Image(path, "sRGB")
    images.append(shared)
    created: list = []
    assert addon_module.images.load_with_color_space(path, "sRGB", created) is shared and not created
    data = addon_module.images.load_with_color_space(path, "Non-Color", created)
    assert data is not shared and created == [data] and data.colorspace_settings.name == "Non-Color"
    assert shared.colorspace_settings.name == "sRGB"  # other users of the image are unaffected


@pytest.mark.parametrize(("fail", "sizes"), [(["b.png"], {}), ([], {"b.png": (0, 0)})])
def test_a_failing_second_file_unloads_the_first_and_leaves_the_material(handler, mock_bpy, files, fail, sizes):
    mock_bpy.data.images = images = _Images(fail=fail, sizes=sizes)
    material = SimpleNamespace(name="M", library=None, use_nodes=False, node_tree=None)
    mock_bpy.data.materials.get = lambda name: material
    maps = {"base_color": str(files / "a.png"), "roughness": str(files / "b.png")}
    with pytest.raises(ValueError, match="b.png"):
        handler.handle("material.set_texture_set", {"name": "M", "maps": maps})
    assert list(images) == [] and material.use_nodes is False


@pytest.mark.parametrize(
    ("path", "error"),
    [
        ("https://example.com/a.png", ValueError),
        ("/tmp/a.psd", ValueError),
        ("/nonexistent/a.png", FileNotFoundError),
    ],
)
def test_bad_paths_are_rejected_before_any_load(handler, mock_bpy, path, error):
    material = SimpleNamespace(name="M", library=None, use_nodes=False, node_tree=None)
    mock_bpy.data.materials.get = lambda name: material
    with pytest.raises(error):
        handler.handle("material.set_texture_set", {"name": "M", "maps": {"base_color": path}})
    mock_bpy.data.images.load.assert_not_called()


def test_path_policy_applies(handler, runtime, mock_bpy, files, tmp_path_factory):
    mock_bpy.data.materials.get = lambda name: SimpleNamespace(name="M", library=None, use_nodes=False, node_tree=None)
    allowed = tmp_path_factory.mktemp("allowed")
    runtime.settings.policy = replace(runtime.settings.policy, output_roots=(str(allowed),))
    with pytest.raises(PermissionError, match="outside configured output roots"):
        handler.handle("material.set_texture_set", {"name": "M", "maps": {"base_color": str(files / "a.png")}})
    mock_bpy.data.images.load.assert_not_called()


def test_missing_and_linked_materials(handler, mock_bpy):
    mock_bpy.data.materials.get = lambda name: None
    with pytest.raises(ValueError, match="Material not found"):
        handler.handle("material.set_texture_set", {"name": "M", "remove": ["normal"]})
    mock_bpy.data.materials.get = lambda name: MagicMock(library="other.blend")
    with pytest.raises(ValueError, match="linked library"):
        handler.handle("material.set_texture_set", {"name": "M", "remove": ["normal"]})


def test_texture_sets_are_undoable(handler):
    assert "material.set_texture_set" in handler.mutation_commands
