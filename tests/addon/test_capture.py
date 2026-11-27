"""Tests for inspection view framing, target selection, limits and cleanup."""

import itertools
import math
import types
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

BOXES = [
    [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)],
    [(x, y, z) for x in (-5, 5) for y in (-0.01, 0.01) for z in (-0.2, 0.2)],  # long and thin
    [(x, y, z) for x in (100, 101) for y in (7, 7) for z in (3, 9)],  # flat and off-center
    [(2, 2, 2)] * 8,  # a single point
]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


@pytest.fixture
def capture(addon_module):
    return addon_module.capture


@pytest.mark.parametrize("projection", ["orthographic", "perspective"])
@pytest.mark.parametrize("points", BOXES, ids=["cube", "thin", "flat", "point"])
def test_every_point_is_inside_every_view(capture, projection, points):
    for view in capture.VIEWS:
        framing = capture.frame_points(points, view, projection)
        right, up, forward = capture.camera_axes(view)
        reach = 0.0
        for point in points:
            relative = [point[i] - framing["location"][i] for i in range(3)]
            depth = _dot(relative, forward)
            assert framing["clip_start"] < depth < framing["clip_end"]
            if projection == "orthographic":
                half = framing["ortho_scale"] / 2
            else:
                half = depth * capture.SENSOR_WIDTH / (2 * framing["lens"])
            extent = max(abs(_dot(relative, right)), abs(_dot(relative, up))) / half
            assert extent <= 1 / capture.MARGIN + 1e-9, (view, point)
            reach = max(reach, extent)
        if projection == "orthographic" and len(set(points)) > 1:
            assert reach == pytest.approx(1 / capture.MARGIN)  # the subject fills the frame


def test_camera_axes_are_right_handed_and_match_blender_views(capture):
    for view in capture.VIEWS:
        right, up, forward = capture.camera_axes(view)
        for a, b in itertools.combinations((right, up, forward), 2):
            assert _dot(a, b) == pytest.approx(0)
        assert all(math.hypot(*axis) == pytest.approx(1) for axis in (right, up, forward))
        # A camera looks down -Z, so right x up = -forward.
        assert capture._cross(right, up) == pytest.approx(tuple(-value for value in forward))
    assert capture.camera_axes("front") == ((1, 0, 0), (0, 0, 1), (0, 1, 0))
    assert capture.camera_axes("right")[0] == (0, 1, 0)
    assert capture.camera_axes("top")[:2] == ((1, 0, 0), (0, 1, 0))


def _object(name, kind="MESH", children=(), **flags):
    values = {"hide_render": False, "hide_viewport": False, "instance_type": "NONE", **flags}
    return types.SimpleNamespace(name=name, type=kind, children=list(children), **values)


@pytest.fixture
def scene_with(mock_bpy, handler):
    """Register objects and one rendered instance with a unit bounding box."""

    def build(*objects):
        by_name = {}

        def add(item):
            by_name[item.name] = item
            for child in item.children:
                add(child)

        for item in objects:
            add(item)
        mock_bpy.data.objects.get = by_name.get
        mock_bpy.data.collections.get = lambda name: (
            types.SimpleNamespace(name="Parts", all_objects=list(by_name.values())) if name == "Parts" else None
        )
        temp_scene = MagicMock()
        instance = MagicMock()
        instance.object = types.SimpleNamespace(type="MESH", bound_box=BOXES[0])
        instance.matrix_world = [[1, 0, 0, 4], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        layer = temp_scene.view_layers.__getitem__.return_value
        layer.depsgraph.object_instances = [instance]
        mock_bpy.data.scenes.new.return_value = temp_scene
        return temp_scene

    return build


def test_targets_walk_children_and_explain_exclusions(scene_with, handler):
    scene_with(
        _object(
            "Root",
            "EMPTY",
            [
                _object("Body"),
                _object("Hidden", hide_render=True),
                _object("Off", hide_viewport=True),
                _object("Lamp", "LIGHT"),
                _object("Instances", "EMPTY", instance_type="COLLECTION"),
            ],
        )
    )
    result = handler.handle("view.capture", {"object": "Root", "include_images": False})
    assert result["objects_shown"] == 2
    reasons = {item["object"]: item["reason"] for item in result["excluded"]["items"]}
    assert set(reasons) == {"Root", "Hidden", "Off", "Lamp"}
    assert reasons["Hidden"] == "hidden from render"
    assert result["bounds_world"] == {"min": [3, -1, -1], "max": [5, 1, 1], "size": [2, 2, 2]}
    with pytest.raises(ValueError, match="nothing that can be rendered"):
        handler.handle("view.capture", {"object": "Root", "include_children": False})


@pytest.mark.parametrize(
    ("modifier", "noted"),
    [
        ({"show_viewport": True, "show_render": True}, False),
        ({"show_viewport": False, "show_render": True}, True),
        ({"show_viewport": True, "show_render": True, "levels": 1, "render_levels": 3}, True),
        ({"show_viewport": True, "show_render": True, "levels": 2, "render_levels": 2}, False),
    ],
)
def test_render_only_modifier_settings_are_reported(scene_with, handler, modifier, noted):
    scene_with(_object("Body", modifiers=[types.SimpleNamespace(**modifier)]))
    notes = handler.handle("view.capture", {"object": "Body", "include_images": False})["notes"]
    assert bool(notes) is noted
    assert not noted or "Body" in notes[0]


def test_wireframe_shows_only_meshes(scene_with, handler):
    scene_with(_object("Mesh"), _object("Path", "CURVE"))
    result = handler.handle("view.capture", {"collection": "Parts", "mode": "wireframe", "include_images": False})
    assert result["objects_shown"] == 1
    assert result["excluded"]["items"] == [{"object": "Path", "reason": "wireframe views support mesh objects only"}]


def test_metadata_only_renders_nothing_and_removes_the_temporary_scene(scene_with, handler, mock_bpy):
    temp_scene = scene_with(_object("Body"))
    result = handler.handle("view.capture", {"object": "Body", "views": ["front", "top"], "include_images": False})
    assert [view["view"] for view in result["views"]] == ["front", "top"]
    assert result["engine"] is None and "png_base64" not in result["views"][0]
    mock_bpy.ops.render.render.assert_not_called()
    mock_bpy.data.scenes.remove.assert_called_once_with(temp_scene)
    mock_bpy.data.cameras.new.assert_not_called()


@pytest.fixture
def fake_render(mock_bpy, fake_mathutils, scene_with):
    """Write a file of the requested size wherever the temporary scene points."""
    fake_mathutils.Matrix = lambda rows: rows
    temp_scene = scene_with(_object("Body"))
    background = types.SimpleNamespace(type="BACKGROUND", inputs=MagicMock())
    mock_bpy.data.worlds.new.return_value.node_tree.nodes = [background]
    mock_bpy.app.background = True

    def configure(size=1_000):
        def render(**kwargs):
            with open(temp_scene.render.filepath, "wb") as handle:
                handle.write(b"p" * size)
            return {"FINISHED"}

        mock_bpy.ops.render.render.side_effect = render
        return temp_scene

    return configure


def _removed(mock_bpy):
    kinds = ("scenes", "objects", "meshes", "materials", "cameras", "lights", "worlds")
    return {kind: getattr(mock_bpy.data, kind).remove.call_count for kind in kinds}


# One camera and three suns, the temporary scene and world, and the clay material used in solid mode.
EXPECTED_REMOVALS = {"scenes": 1, "objects": 4, "meshes": 0, "materials": 1, "cameras": 1, "lights": 3, "worlds": 1}


def test_successful_capture_encodes_each_view_and_cleans_up(fake_render, handler, mock_bpy, tmp_path):
    import base64
    import os

    temp_scene = fake_render()
    result = handler.handle(
        "view.capture", {"object": "Body", "views": ["front", "back"], "save_directory": str(tmp_path / "out")}
    )
    assert [base64.b64decode(view["png_base64"]) for view in result["views"]] == [b"p" * 1_000] * 2
    assert [view["bytes"] for view in result["views"]] == [1_000, 1_000]
    assert sorted(os.listdir(tmp_path / "out")) == ["capture_back.png", "capture_front.png"]
    assert not os.path.exists(os.path.dirname(temp_scene.render.filepath))
    assert result["engine"] == "CYCLES" and result["notes"] == []
    assert _removed(mock_bpy) == EXPECTED_REMOVALS
    assert mock_bpy.ops.render.render.call_args.kwargs["scene"] == temp_scene.name


@pytest.mark.parametrize("failure", ["raises", "cancelled", "no_file", "too_large"])
def test_render_failures_clean_up_everything(fake_render, handler, mock_bpy, addon_module, failure):
    import os

    temp_scene = fake_render(size=6_000)
    if failure == "raises":
        mock_bpy.ops.render.render.side_effect = RuntimeError("out of memory")
    elif failure == "cancelled":
        mock_bpy.ops.render.render.side_effect = lambda **kwargs: {"CANCELLED"}
    elif failure == "no_file":
        mock_bpy.ops.render.render.side_effect = lambda **kwargs: {"FINISHED"}
    with pytest.raises(RuntimeError) as error:
        handler.handle("view.capture", {"object": "Body", "views": ["front", "back"], "max_bytes": 10_000})
    if failure == "too_large":
        assert isinstance(error.value, addon_module.protocol.BridgeError)
        assert error.value.code == "budget_exceeded"
        assert error.value.details == {"bytes_so_far": 12_000, "views_rendered": 2}
    assert _removed(mock_bpy) == EXPECTED_REMOVALS
    if isinstance(temp_scene.render.filepath, str):
        assert not os.path.exists(os.path.dirname(temp_scene.render.filepath))


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"object": "A", "collection": "Parts"},
        {"object": "A", "views": []},
        {"object": "A", "views": ["front"] * 2},
        {"object": "A", "views": ["isometric"]},
        {"object": "A", "views": [["front"]]},
        {"object": "A", "views": ["front", "back", "left", "right", "top", "bottom", "three_quarter"]},
        {"object": "A", "mode": "xray"},
        {"object": "A", "projection": "fisheye"},
        {"object": "A", "resolution": 63},
        {"object": "A", "resolution": 1025},
        {"object": "A", "max_bytes": 5_000_001},
    ],
)
def test_invalid_or_oversized_requests(scene_with, handler, mock_bpy, params):
    scene_with(_object("A"))
    with pytest.raises(ValueError):
        handler.handle("view.capture", params)
    mock_bpy.ops.render.render.assert_not_called()


def test_missing_targets(scene_with, handler):
    scene_with()
    for params in ({"object": "Nope"}, {"collection": "Nope"}):
        with pytest.raises(ValueError, match="not found"):
            handler.handle("view.capture", params)


def test_policy_limits_apply(scene_with, handler, runtime, mock_bpy, tmp_path):
    scene_with(_object("Body"))
    policy = runtime.settings.policy
    runtime.settings.policy = replace(policy, max_render_pixels=100 * 100)
    with pytest.raises(ValueError, match="render limits"):
        handler.handle("view.capture", {"object": "Body", "resolution": 128})
    runtime.settings.policy = replace(policy, output_roots=(str(tmp_path / "allowed"),))
    with pytest.raises(PermissionError, match="outside configured output roots"):
        handler.handle("view.capture", {"object": "Body", "save_directory": str(tmp_path / "elsewhere")})
    runtime.settings.policy = replace(policy, allowed_commands=("render.still",))
    with pytest.raises(PermissionError, match="allowlist"):
        handler.handle("view.capture", {"object": "Body"})
    mock_bpy.data.scenes.new.assert_not_called()


def test_a_scene_without_a_world_previews_with_a_black_one(fake_render, handler, mock_bpy):
    temp_scene = fake_render()
    mock_bpy.context.scene.world = None
    mock_bpy.context.scene.objects = []
    result = handler.handle("view.capture", {"object": "Body", "mode": "material", "lighting": "world"})
    background = mock_bpy.data.worlds.new.return_value.node_tree.nodes[0]
    # The last values written are those of the black preview world: no color and no strength.
    assert background.inputs.__getitem__.return_value.default_value == 0.0
    assert temp_scene.world is mock_bpy.data.worlds.new.return_value
    assert "no environment light" in result["notes"][0]


def test_capture_adds_no_undo_checkpoint(handler):
    assert "view.capture" not in handler.mutation_commands
