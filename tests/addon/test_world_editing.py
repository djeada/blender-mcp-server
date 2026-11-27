"""Tests for typed world editing: conflicts, preservation and validation before mutation."""

import math
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


class _Socket:
    def __init__(self, node, default=None):
        self.node, self.default_value, self.links = node, default, []


class _Sockets(dict):
    """Sockets looked up by name or position, and iterated as sockets, like Blender's."""

    def __iter__(self):
        return iter(self.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            while len(self) <= key:
                self[f"socket {len(self)}"]
            return list(self.values())[key]
        return self.setdefault(key, _Socket(self.node))


SHAPES = {
    "ShaderNodeOutputWorld": ("OUTPUT_WORLD", {"Surface": None}),
    "ShaderNodeBackground": ("BACKGROUND", {"Color": (0.05, 0.05, 0.05, 1), "Strength": 1.0}),
    "ShaderNodeTexEnvironment": ("TEX_ENVIRONMENT", {"Vector": None}),
    "ShaderNodeTexSky": ("TEX_SKY", {}),
    "ShaderNodeMapping": ("MAPPING", {"Vector": None, "Rotation": (0.0, 0.0, 0.0)}),
    "ShaderNodeTexNoise": ("TEX_NOISE", {}),
    "ShaderNodeMixShader": ("MIX_SHADER", {"Fac": 0.5, "Shader": None, "Shader_001": None}),
}


class _Node:
    def __init__(self, kind):
        self.bl_idname = kind
        self.type, defaults = SHAPES.get(kind, (kind.upper(), {}))
        self.name, self.location, self.properties = kind, (0.0, 0.0), {}
        self.inputs, self.outputs = _Sockets(), _Sockets()
        self.inputs.node = self.outputs.node = self
        for name, value in defaults.items():
            self.inputs[name].default_value = value
        self.is_active_output = True
        self.image = None

    def __setitem__(self, key, value):
        self.properties[key] = value

    def __getitem__(self, key):
        return self.properties[key]

    def get(self, key, default=None):
        return self.properties.get(key, default)


class _Tree:
    def __init__(self):
        outer = self

        class Nodes(list):
            def new(self, kind):
                node = _Node(kind)
                self.append(node)
                return node

            def remove(self, node):
                list.remove(self, node)
                for other in self:
                    for socket in other.inputs.values():
                        socket.links = [link for link in socket.links if link.from_node is not node]

        class Links:
            def new(self, source, target):
                target.links = [SimpleNamespace(from_node=source.node)]

        self.nodes, self.links = Nodes(), Links()
        del outer


class _World:
    def __init__(self, name="World", *, plain=True):
        self.name, self.users, self.library, self.use_nodes, self.use_fake_user = name, 1, None, True, False
        self.node_tree = _Tree()
        output = self.node_tree.nodes.new("ShaderNodeOutputWorld")
        if plain:
            background = self.node_tree.nodes.new("ShaderNodeBackground")
            self.node_tree.links.new(background.outputs["Background"], output.inputs["Surface"])


def _custom_world(name="Studio"):
    world = _World(name)
    noise = world.node_tree.nodes.new("ShaderNodeTexNoise")
    background = next(node for node in world.node_tree.nodes if node.type == "BACKGROUND")
    world.node_tree.links.new(noise.outputs["Color"], background.inputs["Color"])
    return world


@pytest.fixture
def scene(mock_bpy):
    current = mock_bpy.context.scene
    current.world = _World()
    mock_bpy.data.scenes = [current]
    mock_bpy.data.worlds.new.side_effect = lambda name: _World(name, plain=True)
    sky = MagicMock()
    sky.bl_rna.properties = {
        "sky_type": SimpleNamespace(
            enum_items=[SimpleNamespace(identifier=name) for name in ("MULTIPLE_SCATTERING", "PREETHAM")]
        )
    }
    mock_bpy.types.ShaderNodeTexSky = sky
    return current


def _snapshot(world):
    return [
        (node.bl_idname, sorted((name, len(socket.links)) for name, socket in node.inputs.items()))
        for node in world.node_tree.nodes
    ]


def _roles(world):
    return sorted(node.get("mcp_world_role") for node in world.node_tree.nodes if node.get("mcp_world_role"))


def test_color_and_strength_are_edited_in_place_and_kept(handler, scene):
    world = scene.world
    first = handler.handle("world.set", {"mode": "color", "color": [0.2, 0.3, 0.4], "strength": 2})
    assert first["created_world"] is False and scene.world is world
    assert first["settings"] == {"mode": "color", "color": [0.2, 0.3, 0.4], "strength": 2.0}
    second = handler.handle("world.set", {"strength": 0.5})
    assert second["settings"] == {"mode": "color", "color": [0.2, 0.3, 0.4], "strength": 0.5}
    assert _roles(world) == ["lighting"]
    assert "world.set" in handler.mutation_commands and "world.get" not in handler.mutation_commands


def test_unrelated_nodes_survive_editing(handler, scene):
    spare = scene.world.node_tree.nodes.new("ShaderNodeTexNoise")  # not connected to the output
    handler.handle("world.set", {"mode": "color", "color": [1, 1, 1]})
    handler.handle("world.set", {"camera_background": [0, 0, 0]})
    handler.handle("world.set", {"clear_camera_background": True})
    assert spare in scene.world.node_tree.nodes
    assert _roles(scene.world) == ["lighting"]


def test_a_scene_without_a_world_gets_one(handler, scene):
    scene.world = None
    result = handler.handle("world.set", {"mode": "color", "color": [0.5, 0.5, 0.5]})
    assert result["created_world"] is True and scene.world.name == "MCP World" and "kept_world" not in result


@pytest.mark.parametrize("kind", ["custom", "shared", "linked"])
def test_conflicts_change_nothing_unless_resolved(handler, scene, mock_bpy, kind, addon_module):
    if kind == "custom":
        scene.world = _custom_world()
    elif kind == "shared":
        mock_bpy.data.scenes = [scene, SimpleNamespace(name="Other", world=scene.world)]
    else:
        scene.world.library = object()
    original, before = scene.world, _snapshot(scene.world)
    report = handler.handle("world.get", {})
    assert report["editable_in_place"] is False and report["conflict"]
    with pytest.raises(addon_module.protocol.BridgeError) as error:
        handler.handle("world.set", {"mode": "color", "color": [1, 0, 0]})
    assert error.value.code == "conflict" and "new_world" in str(error.value)
    assert scene.world is original and _snapshot(original) == before
    mock_bpy.data.worlds.new.assert_not_called()

    result = handler.handle("world.set", {"mode": "color", "color": [1, 0, 0], "on_conflict": "new_world"})
    assert result["created_world"] is True and result["kept_world"] == original.name
    assert scene.world is not original and original.use_fake_user is True and _snapshot(original) == before


def test_replace_overwrites_only_when_asked(handler, scene, addon_module):
    scene.world = world = _custom_world()
    result = handler.handle("world.set", {"mode": "color", "color": [1, 0, 0], "on_conflict": "replace"})
    assert scene.world is world and result["created_world"] is False and "Replaced" in result["notes"][0]
    assert _roles(world) == ["lighting"]
    scene.world = _World()
    scene.world.library = object()
    with pytest.raises(addon_module.protocol.UnsupportedError, match="linked world"):
        handler.handle("world.set", {"mode": "color", "on_conflict": "replace"})


@pytest.mark.parametrize(
    "params",
    [
        {"mode": "rainbow"},
        {"mode": "color", "filepath": "/tmp/a.hdr"},
        {"mode": "color", "sun_elevation": 10},
        {"mode": "environment"},
        {"mode": "environment", "filepath": "https://example.com/sky.hdr"},
        {"mode": "environment", "filepath": "/tmp/sky.gif"},
        {"mode": "environment", "filepath": "/nonexistent/sky.hdr"},
        {"mode": "color", "color": [-1, 0, 0]},
        {"mode": "color", "camera_background": [0, 0, 0], "clear_camera_background": True},
        {"mode": "sky", "sky_type": "HOSEK_WILKIE"},
        {"mode": "sky", "turbidity": 3},
        {"mode": "sky", "sky_type": "PREETHAM", "sun_disc": True},
        {"mode": "sky", "sky_type": "PREETHAM", "turbidity": 20},
        {"mode": "sky", "sun_elevation": 120},
        {"mode": "sky", "sun_intensity": -1},
        {"mode": "color", "on_conflict": "overwrite"},
        {"strength": -1},
    ],
)
def test_invalid_requests_leave_the_world_untouched(handler, scene, mock_bpy, params):
    before = _snapshot(scene.world)
    with pytest.raises((ValueError, FileNotFoundError)):
        handler.handle("world.set", params)
    assert _snapshot(scene.world) == before
    mock_bpy.data.worlds.new.assert_not_called()
    mock_bpy.data.images.load.assert_not_called()


def test_forbidden_image_paths_do_not_mutate(handler, scene, runtime, mock_bpy, tmp_path):
    image = tmp_path / "outside.hdr"
    image.write_bytes(b"data")
    runtime.settings.policy = replace(runtime.settings.policy, output_roots=(str(tmp_path / "allowed"),))
    before = _snapshot(scene.world)
    with pytest.raises(PermissionError, match="outside configured output roots"):
        handler.handle("world.set", {"mode": "environment", "filepath": str(image)})
    assert _snapshot(scene.world) == before
    mock_bpy.data.images.load.assert_not_called()


class _Images(list):
    def __init__(self, image):
        super().__init__()
        self.image, self.removed = image, []

    def load(self, path, check_existing=True):
        self.append(self.image)
        return self.image

    def remove(self, image):
        self.removed.append(image)


@pytest.mark.parametrize(("size", "message"), [((0, 0), "decode"), ((20000, 10000), "limit")])
def test_unreadable_or_huge_images_are_discarded(handler, scene, mock_bpy, tmp_path, size, message):
    path = tmp_path / "sky.hdr"
    path.write_bytes(b"data")
    mock_bpy.data.images = images = _Images(SimpleNamespace(size=size))
    before = _snapshot(scene.world)
    with pytest.raises(ValueError, match=message):
        handler.handle("world.set", {"mode": "environment", "filepath": str(path)})
    assert images.removed == [images.image] and _snapshot(scene.world) == before


def test_environment_keeps_its_image_across_partial_updates(handler, scene, mock_bpy, tmp_path):
    path = tmp_path / "sky.hdr"
    path.write_bytes(b"data")
    image = SimpleNamespace(name="sky.hdr", size=(8, 4), colorspace_settings=SimpleNamespace(name="Linear Rec.709"))
    mock_bpy.data.images = _Images(image)
    handler.handle("world.set", {"mode": "environment", "filepath": str(path), "rotation": 45})
    result = handler.handle("world.set", {"strength": 3})
    assert result["settings"] == {
        "mode": "environment",
        "rotation": 45.0,
        "strength": 3.0,
        "image": {"name": "sky.hdr", "size": [8, 4], "color_space": "Linear Rec.709"},
    }
    mapping = next(node for node in scene.world.node_tree.nodes if node.get("mcp_world_role") == "mapping")
    assert mapping.vector_type == "TEXTURE"
    assert mapping.inputs["Rotation"].default_value[2] == pytest.approx(math.radians(45))
    assert image.colorspace_settings.name == "Linear Rec.709"  # shared image settings are never changed


def test_sky_choice_depends_on_the_build(handler, scene, addon_module):
    with pytest.raises(addon_module.protocol.UnsupportedError, match="Available: MULTIPLE_SCATTERING, PREETHAM"):
        handler.handle("world.set", {"mode": "sky", "sky_type": "NISHITA"})
    assert handler.handle("world.get", {})["sky_types"] == ["MULTIPLE_SCATTERING", "PREETHAM"]
    assert addon_module.world._choose_sky(None) == "MULTIPLE_SCATTERING"
    assert addon_module.world._choose_sky("preetham") == "PREETHAM"
