"""Lighting rig layout and camera framing math, plus validation and object handling."""

import itertools
import math

import pytest


@pytest.fixture
def rigs(addon_module):
    return addon_module.rigs


def _box(center, half):
    return [tuple(center[i] + sign[i] * half[i] for i in range(3)) for sign in itertools.product((-1, 1), repeat=3)]


@pytest.mark.parametrize("rig", ["three_point", "studio_softbox", "turntable", "portrait", "low_key"])
def test_every_rig_scales_exactly_with_the_subject(rigs, rig):
    """Distances and sizes scale with the radius and power with its square: the irradiance cannot change."""
    small = rigs.plan(rig, (0, 0, 0), 0.05, -90, {})
    large = rigs.plan(rig, (10, 20, 30), 50.0, -90, {})
    for a, b in zip(small, large, strict=True):
        assert b["distance"] / a["distance"] == pytest.approx(1000)
        assert b["size"] / a["size"] == pytest.approx(1000)
        assert b["energy"] / a["energy"] == pytest.approx(1000**2)
        assert a["energy"] / (math.pi * a["distance"] ** 2) == pytest.approx(rigs.KEY_IRRADIANCE * a["ratio"])
        offset_a = [a["location"][i] for i in range(3)]
        offset_b = [b["location"][i] - (10, 20, 30)[i] for i in range(3)]
        assert offset_b == pytest.approx([value * 1000 for value in offset_a])


def test_azimuths_are_relative_to_the_camera(rigs):
    key = next(light for light in rigs.plan("three_point", (0, 0, 0), 1, -90, {}) if light["role"] == "key")
    assert key["location"][0] > 0 > key["location"][1] and key["location"][2] > 0  # camera's right, in front
    turned = next(light for light in rigs.plan("three_point", (0, 0, 0), 1, 0, {}) if light["role"] == "key")
    assert turned["location"][0] > 0 and turned["location"][1] > 0  # the rig turned with the camera
    rotated = rigs.plan("three_point", (0, 0, 0), 1, -90, {"rotation": 90})[0]
    assert rotated["location"] == pytest.approx(turned["location"])


def test_options_change_only_what_they_say(rigs):
    base = {light["role"]: light for light in rigs.plan("three_point", (0, 0, 0), 2, -90, {})}
    changed = {
        light["role"]: light
        for light in rigs.plan(
            "three_point",
            (0, 0, 0),
            2,
            -90,
            {
                "ratios": {"fill": 0.1},
                "exposure_stops": 1,
                "size_scale": 3,
                "colors": {"rim": [1, 0, 0]},
                "temperatures": {"key": 3000},
            },
        )
    }
    assert changed["key"]["energy"] == pytest.approx(base["key"]["energy"] * 2)
    assert changed["fill"]["energy"] / changed["key"]["energy"] == pytest.approx(0.1)
    assert changed["key"]["size"] == pytest.approx(base["key"]["size"] * 3)
    assert changed["rim"]["color"] == [1, 0, 0] and changed["key"]["color"][2] < base["key"]["color"][2]
    assert changed["key"]["location"] == pytest.approx(base["key"]["location"])
    far = rigs.plan("three_point", (0, 0, 0), 2, -90, {"distance_scale": 2})[0]
    assert far["energy"] == pytest.approx(base["key"]["energy"] * 4)  # the same light at the subject


@pytest.mark.parametrize("projection", ["PERSP", "ORTHO"])
@pytest.mark.parametrize("aspect", [0.4, 1.0, 16 / 9, 3.0])
@pytest.mark.parametrize(
    "points",
    [_box((0, 0, 0), (1, 1, 1)), _box((5, -3, 2), (0.1, 4, 0.5)), _box((0, 0, 0), (3, 3, 0))],
    ids=["cube", "deep", "flat"],
)
def test_framed_points_fit_the_frame_and_touch_the_margin(rigs, addon_module, projection, aspect, points):
    toward = rigs.view_direction({"azimuth": 35, "elevation": 20})
    framing = rigs.fit_camera(points, toward, projection, 50.0, aspect, 1.2)
    capture = addon_module.capture
    forward = tuple(-value for value in toward)
    right = capture._normalize(capture._cross(forward, (0, 0, 1)))
    up = capture._cross(right, forward)
    reach = 0.0
    for point in points:
        relative = [point[i] - framing["location"][i] for i in range(3)]
        depth = capture._dot(relative, forward)
        assert framing["clip_start"] < depth < framing["clip_end"]
        if projection == "ORTHO":
            longer = framing["ortho_scale"] / 2
        else:
            longer = depth * rigs.SENSOR_WIDTH / 2 / framing["lens"]
        half_width, half_height = (longer, longer / aspect) if aspect >= 1 else (longer * aspect, longer)
        used = max(abs(capture._dot(relative, right)) / half_width, abs(capture._dot(relative, up)) / half_height)
        assert used <= 1 / 1.2 + 1e-9
        reach = max(reach, used)
    if projection == "ORTHO":
        assert reach == pytest.approx(1 / 1.2)


def test_view_directions(rigs):
    assert rigs.view_direction({"azimuth": 0, "elevation": 0}) == pytest.approx((0, -1, 0))
    assert rigs.view_direction({"azimuth": 90, "elevation": 0}) == pytest.approx((1, 0, 0))
    assert rigs.view_direction({"azimuth": 0, "elevation": 90}) == pytest.approx((0, 0, 1))


@pytest.mark.parametrize("points", [[(1, 2, 3)] * 8, [(0, 0, 0), (0, 0, 1e-9)]])
def test_degenerate_bounds_are_explicit(rigs, points):
    with pytest.raises(ValueError, match="no size"):
        rigs.extent(points)


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"rig": "disco"}, "'rig' must be one of"),
        ({"rig": "three_point", "ratios": {"top": 1}}, "unknown roles top"),
        ({"rig": "three_point", "ratios": {"fill": -1}}, "from 0 to 20"),
        ({"rig": "three_point", "ratios": {"fill": "low"}}, "from 0 to 20"),
        ({"rig": "three_point", "ratios": {"key": 0, "fill": 0, "rim": 0}}, "above 0"),
        ({"rig": "three_point", "temperatures": {"key": 100}}, "between"),
        ({"rig": "three_point", "colors": {"key": [2, 0, 0]}}, "0 to 1"),
        ({"rig": "three_point", "colors": {"key": [1, 0, 0]}, "temperatures": {"key": 5000}}, "not both"),
        ({"rig": "three_point", "exposure_stops": 20}, "at most 10"),
        ({"rig": "three_point", "distance_scale": 0.1}, "at least 0.25"),
        ({"rig": "three_point", "on_existing": "merge"}, "on_existing"),
        ({"rig": "three_point", "name": "x" * 41}, "1-40"),
    ],
)
def test_invalid_rig_requests_create_nothing(handler, mock_bpy, params, message):
    with pytest.raises(ValueError, match=message):
        handler.handle("lighting.rig_apply", {"object": "Cube", **params})
    mock_bpy.data.lights.new.assert_not_called()
    mock_bpy.data.scenes.new.assert_not_called()


def test_rig_and_framing_commands_are_undoable(handler):
    assert {"lighting.rig_apply", "lighting.rig_remove", "camera.frame"} <= handler.mutation_commands
