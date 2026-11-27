"""Tests for lighting validation, shared data, inspection and color management."""

import math
from dataclasses import replace
from types import SimpleNamespace

import pytest

IDENTITY = [[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]]


class _Light(SimpleNamespace):
    def copy(self):
        return _Light(**{**vars(self), "name": f"{self.name}.001"})


def _data(kind="POINT", **overrides):
    values = {
        "name": f"{kind}Data",
        "type": kind,
        "energy": 100.0,
        "color": (1.0, 1.0, 1.0),
        "shadow_soft_size": 0.25,
        "angle": math.radians(1),
        "spot_size": math.radians(45),
        "spot_blend": 0.15,
        "shape": "SQUARE",
        "size": 1.0,
        "size_y": 2.0,
        "use_shadow": True,
        "use_temperature": False,
        "temperature": 6500.0,
        "exposure": 0.0,
    }
    return _Light(**{**values, **overrides})


def _light(name, data, **overrides):
    values = {
        "name": name,
        "type": "LIGHT",
        "data": data,
        "location": (1.0, 2.0, 3.0),
        "rotation_euler": (0, 0, 0),
        "matrix_world": IDENTITY,
        "hide_viewport": False,
        "hide_render": False,
    }
    return SimpleNamespace(**{**values, **overrides})


@pytest.fixture
def lights(mock_bpy):
    """Register light objects in the data blocks and the scene."""

    def add(*objects):
        by_name = {obj.name: obj for obj in objects}
        mock_bpy.data.objects.get = by_name.get
        mock_bpy.data.objects.__iter__ = lambda self: iter(by_name.values())
        mock_bpy.context.scene.objects = list(by_name.values())

    return add


@pytest.mark.parametrize(
    "params",
    [
        {"type": "SUN", "size": 2.0},
        {"type": "SUN", "color": [2, 0, 0]},
        {"type": "AREA", "shape": "STAR"},
        {"type": "POINT", "shape": "DISK"},
        {"type": "AREA", "shape": "DISK", "size_y": 1.0},
        {"type": "POINT", "angle": 3.0},
        {"type": "SUN", "angle": 181.0},
        {"type": "SPOT", "spot_angle": 200.0},
        {"type": "SPOT", "spot_blend": -0.1},
        {"temperature": 500.0},
        {"temperature": 3000.0, "color": [1, 1, 1]},
        {"rotation": [0, 0, 0], "look_at": [1, 1, 1]},
        {"location": [1, 1, 1], "look_at": [1, 1, 1]},
        {"look_at": [0, 0, 0]},
    ],
)
def test_a_rejected_create_makes_no_datablocks(handler, mock_bpy, params):
    with pytest.raises(ValueError):
        handler.handle("light.create", params)
    mock_bpy.data.lights.new.assert_not_called()
    mock_bpy.data.objects.new.assert_not_called()


def test_a_failure_while_creating_removes_what_was_made(handler, mock_bpy):
    mock_bpy.context.scene.collection.objects.link.side_effect = RuntimeError("read-only")
    with pytest.raises(RuntimeError):
        handler.handle("light.create", {})
    mock_bpy.data.objects.remove.assert_called_once()
    mock_bpy.data.lights.remove.assert_called_once()


@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("POINT", {"type": "SUN", "size": 2.0}),
        ("AREA", {"type": "SPOT", "shape": "DISK"}),
        ("SPOT", {"type": "SUN", "spot_angle": 30.0, "energy": 5.0}),
        ("POINT", {"energy": 7.0, "look_at": [1, 2, 3]}),
        ("AREA", {"energy": 7.0, "size_y": 3.0}),
    ],
)
def test_a_rejected_update_changes_nothing(handler, lights, kind, params):
    data = _data(kind, shape="DISK")
    before = dict(vars(data))
    lights(_light("Key", data))
    with pytest.raises(ValueError):
        handler.handle("light.update", {"name": "Key", **params})
    assert vars(data) == before


def test_shape_and_temperature(handler, lights):
    data = _data("AREA", use_temperature=True)
    lights(_light("Key", data))
    result = handler.handle("light.update", {"name": "Key", "shape": "ellipse", "size_y": 3.0, "temperature": 3200})
    assert data.shape == "ELLIPSE" and data.size_y == 3.0
    assert result["shape"] == "ELLIPSE" and result["size_y"] == 3.0
    red, green, blue = result["color"]
    assert red == 1.0 > green > blue > 0
    assert data.use_temperature is False  # Blender's own temperature would otherwise apply twice


@pytest.mark.parametrize(
    ("kelvin", "expected"),
    # Linear sRGB reference values for black bodies on the Planckian locus.
    [(2000, (1.0, 0.2516, 0.0063)), (6500, (1.0, 0.9396, 0.9759)), (15000, (0.4693, 0.5880, 1.0))],
)
def test_temperature_conversion(addon_module, kelvin, expected):
    assert addon_module.lighting.temperature_to_color(kelvin) == pytest.approx(expected, abs=0.02)


@pytest.mark.parametrize("kelvin", [1000, 30000])
def test_temperature_range(addon_module, kelvin):
    with pytest.raises(ValueError, match="between"):
        addon_module.lighting.temperature_to_color(kelvin)


def test_shared_light_data_needs_an_explicit_choice(handler, lights):
    data = _data("POINT")
    first, second = _light("A", data), _light("B", data)
    lights(first, second)
    with pytest.raises(ValueError, match=r"shared by 2 objects \(A, B\)"):
        handler.handle("light.update", {"name": "A", "energy": 5.0})
    assert data.energy == 100.0
    handler.handle("light.update", {"name": "A", "location": [4, 4, 4]})  # a transform is per object
    assert first.location == [4, 4, 4]
    handler.handle("light.update", {"name": "A", "energy": 5.0, "shared_data": "update_all"})
    assert data.energy == 5.0 and second.data is data
    handler.handle("light.update", {"name": "A", "energy": 9.0, "shared_data": "make_single_user"})
    assert first.data is not data and first.data.energy == 9.0 and data.energy == 5.0
    with pytest.raises(ValueError, match="shared_data"):
        handler.handle("light.update", {"name": "B", "energy": 1.0, "shared_data": "yes"})


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        ("POINT", {"size": 0.25}),
        ("SUN", {"angle": 1.0}),
        ("SPOT", {"size": 0.25, "spot_angle": 45.0, "spot_blend": 0.15}),
        ("AREA", {"shape": "SQUARE", "size": 1.0}),
    ],
)
def test_inspection_reports_each_light_type(handler, lights, mock_bpy, kind, expected):
    lights(_light("Lamp", _data(kind, exposure=1.5), hide_render=True))
    mock_bpy.context.scene.camera = None
    mock_bpy.context.scene.world = None
    mock_bpy.context.scene.view_settings.exposure = 0.0
    mock_bpy.context.scene.view_settings.gamma = 1.0
    report = handler.handle("lighting.inspect", {})
    (entry,) = report["lights"]
    assert {key: entry[key] for key in expected} == expected
    assert entry["world_location"] == [1, 2, 3] and entry["hide_render"] is True
    assert entry["light_exposure"] == 1.5
    assert entry["energy_unit"] == ("W/m²" if kind == "SUN" else "W")
    assert ("world_direction" in entry) is (kind != "POINT")
    if kind != "POINT":
        assert entry["world_direction"] == [0, 0, -1]
    assert report["total"] == 1 and report["camera"] is None and report["world"] is None
    assert "lighting.inspect" not in handler.mutation_commands


def test_inspection_pages_lights_in_name_order(handler, lights, mock_bpy):
    lights(*[_light(f"L{index}", _data()) for index in (3, 1, 2, 0)])
    mock_bpy.context.scene.camera = None
    mock_bpy.context.scene.world = None
    mock_bpy.context.scene.view_settings.exposure = 0.0
    mock_bpy.context.scene.view_settings.gamma = 1.0
    page = handler.handle("lighting.inspect", {"limit": 3})
    assert [light["name"] for light in page["lights"]] == ["L0", "L1", "L2"]
    assert (page["total"], page["next_offset"]) == (4, 3)


class _Enums:
    """Settings that reject unknown values the way Blender does, with dependent look lists."""

    LOOKS = {"AgX": ["None", "AgX - Punchy"], "Standard": ["None", "High Contrast"]}

    def __init__(self):
        self.__dict__.update(
            view_transform="AgX", look="AgX - Punchy", exposure=0.0, gamma=1.0, use_curve_mapping=False
        )

    def __setattr__(self, name, value):
        allowed = None
        if name == "view_transform":
            allowed = list(self.LOOKS)
        elif name == "look":
            allowed = self.LOOKS[self.view_transform]
        if allowed is not None and value not in allowed:
            listed = ", ".join(f"'{item}'" for item in allowed)
            raise TypeError(f'bpy_struct: item.attr = val: enum "{value}" not found in ({listed})')
        self.__dict__[name] = value
        if name == "view_transform" and self.look not in self.LOOKS[value]:
            self.__dict__["look"] = "None"


class _Display:
    display_device = "sRGB"

    def __setattr__(self, name, value):
        if value != "sRGB":
            raise TypeError(f"enum \"{value}\" not found in ('sRGB')")


@pytest.fixture
def color_scene(mock_bpy):
    mock_bpy.context.scene.view_settings = _Enums()
    mock_bpy.context.scene.display_settings = _Display()
    return mock_bpy.context.scene


def test_color_management_updates_only_what_is_given(handler, color_scene):
    result = handler.handle("render.set_color_management", {"exposure": 1.5})
    assert result["changed"] == ["exposure"]
    assert result["color_management"] == {
        "display_device": "sRGB",
        "view_transform": "AgX",
        "look": "AgX - Punchy",
        "exposure": 1.5,
        "gamma": 1.0,
        "use_curve_mapping": False,
    }
    assert "render.set_color_management" in handler.mutation_commands


def test_blender_adjustments_are_reported(handler, color_scene):
    result = handler.handle("render.set_color_management", {"view_transform": "Standard"})
    assert result["adjusted_by_blender"] == {"look": {"was": "AgX - Punchy", "now": "None"}}


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"view_transform": "Technicolor"}, "Choose from: AgX, Standard"),
        # The view transform is valid but the look is not valid for it: both are rolled back.
        ({"view_transform": "Standard", "look": "AgX - Punchy", "exposure": 2}, "Choose from: None, High Contrast"),
        ({"display_device": "CRT"}, "Choose from: sRGB"),
    ],
)
def test_invalid_color_settings_leave_everything_unchanged(handler, color_scene, params, message):
    with pytest.raises(ValueError, match=message):
        handler.handle("render.set_color_management", params)
    settings = color_scene.view_settings
    assert (settings.view_transform, settings.look, settings.exposure) == ("AgX", "AgX - Punchy", 0.0)


def test_options_are_read_without_changing_them(addon_module, color_scene):
    options = addon_module.color_management.options(color_scene)
    assert options == {
        "display_devices": ["sRGB"],
        "view_transforms": ["AgX", "Standard"],
        "looks": ["None", "AgX - Punchy"],
    }
    assert color_scene.view_settings.look == "AgX - Punchy"


@pytest.mark.parametrize("params", [{}, {"exposure": 40}, {"gamma": -1}])
def test_invalid_color_requests(handler, color_scene, params):
    with pytest.raises(ValueError):
        handler.handle("render.set_color_management", params)


def _node(kind, **attributes):
    return SimpleNamespace(type=kind, bl_idname=f"ShaderNode{kind}", **attributes)


def _socket(value=None, source=None):
    return SimpleNamespace(default_value=value, links=[SimpleNamespace(from_node=source)] if source else [])


def _world(color_source=None, surface=True, shader_type="BACKGROUND"):
    shader = _node(shader_type, inputs={"Color": _socket((0.1, 0.2, 0.3, 1), color_source), "Strength": _socket(2.0)})
    output = _node(
        "OUTPUT_WORLD", is_active_output=True, inputs={"Surface": _socket(source=shader if surface else None)}
    )
    return SimpleNamespace(name="World", users=1, use_nodes=True, node_tree=SimpleNamespace(nodes=[shader, output]))


@pytest.mark.parametrize(
    ("world", "expected"),
    [
        (_world(), {"kind": "color", "color": [0.1, 0.2, 0.3], "strength": 2.0}),
        (_world(_node("TEX_ENVIRONMENT", image=SimpleNamespace(name="sky.hdr"))), {"kind": "environment"}),
        (_world(_node("TEX_SKY", sky_type="PREETHAM")), {"kind": "sky", "sky_type": "PREETHAM"}),
        (_world(_node("TEX_NOISE")), {"kind": "custom", "color_node": "ShaderNodeTEX_NOISE"}),
        (_world(surface=False), {"kind": "none"}),
        (_world(shader_type="MIX_SHADER"), {"kind": "custom", "surface_node": "ShaderNodeMIX_SHADER"}),
        (
            SimpleNamespace(name="Flat", users=1, use_nodes=False, node_tree=None, color=(0.5, 0.5, 0.5)),
            {"kind": "color", "color": [0.5, 0.5, 0.5]},
        ),
    ],
)
def test_world_summary(addon_module, world, expected):
    summary = addon_module.world.summary(world)
    assert {key: summary[key] for key in expected} == expected


def test_policy_applies_to_new_commands(handler, runtime):
    runtime.settings.policy = replace(runtime.settings.policy, allowed_commands=("scene.get_info",))
    for command in ("lighting.inspect", "render.set_color_management"):
        with pytest.raises(PermissionError):
            handler.handle(command, {})
