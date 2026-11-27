"""Unit tests for material diagnostic rules and file policy. Graph checks run in real Blender."""

from dataclasses import replace
from types import SimpleNamespace

import pytest


@pytest.fixture
def diagnostics(addon_module):
    return addon_module.material_diagnostics


@pytest.mark.parametrize(
    ("space", "linear"),
    [("Non-Color", True), ("Linear Rec.709", True), ("Raw", True), ("sRGB", False), ("AgX Base sRGB", False)],
)
def test_linear_color_spaces(diagnostics, space, linear):
    assert diagnostics._is_linear(space) is linear


@pytest.mark.parametrize(
    ("name", "kinds"),
    [
        ("crate_normal", {"normal"}),
        ("crate_nrm_2k", {"normal"}),
        ("wood rough", {"roughness"}),
        ("albedo", {"base_color"}),
        ("metalness.v2", {"metallic"}),
        ("normandy_beach", set()),
        ("abnormal", set()),
        ("trough", set()),
    ],
)
def test_name_hints_match_whole_words_only(diagnostics, name, kinds):
    assert {kind for kind, pattern in diagnostics._NAME_HINTS.items() if pattern.search(name)} == kinds


def test_exceptions_can_excuse_a_check_a_subject_or_a_material(diagnostics):
    report = diagnostics._Report(["unused_nodes", "color_space:mask", "texture_size:Hero"])
    report.add("unused_nodes", "warning", "A", "x")
    report.add("color_space", "error", "A", "x", "mask")
    report.add("color_space", "error", "A", "x", "other")
    report.add("texture_size", "error", "Hero", "x", "big")
    report.add("texture_size", "error", "Prop", "x", "big")
    assert [(f["check"], f["material"], f.get("subject")) for f in report.findings] == [
        ("color_space", "A", "other"),
        ("texture_size", "Prop", "big"),
    ]
    assert len(report.allowed) == 3
    report.add("color_space", "error", "A", "x", "other")
    assert len(report.findings) == 2  # the same finding is not repeated


def _image(path, **overrides):
    values = {
        "name": "tex",
        "source": "FILE",
        "packed_file": None,
        "filepath": path,
        "library": None,
        "size": (16, 8),
        "is_float": False,
        "colorspace_settings": SimpleNamespace(name="sRGB"),
    }
    return SimpleNamespace(**{**values, **overrides})


def test_image_description_and_memory_estimate(diagnostics, handler, tmp_path):
    present = tmp_path / "a.png"
    present.write_bytes(b"x")
    info = diagnostics._image_info(_image(str(present)), handler.policy)
    assert info == {
        "name": "tex",
        "color_space": "sRGB",
        "storage": "external",
        "file": "a.png",
        "size": [16, 8],
        "estimated_bytes": int(16 * 8 * 4 * 4 / 3),
    }
    assert str(tmp_path) not in str(info)  # full paths are never reported
    assert diagnostics._image_info(_image(str(tmp_path / "gone.png")), handler.policy)["status"] == "missing"
    assert diagnostics._image_info(_image(str(present), size=(0, 0)), handler.policy)["status"] == "unreadable"
    floating = diagnostics._image_info(_image("", source="GENERATED", is_float=True), handler.policy)
    assert floating["storage"] == "generated" and floating["estimated_bytes"] == int(16 * 8 * 16 * 4 / 3)
    packed = diagnostics._image_info(_image("/gone.png", packed_file=object()), handler.policy)
    assert packed["storage"] == "packed" and "status" not in packed


def test_files_outside_approved_roots_are_not_touched(diagnostics, handler, runtime, tmp_path):
    runtime.settings.policy = replace(runtime.settings.policy, output_roots=(str(tmp_path / "allowed"),))

    class Unreadable(SimpleNamespace):
        @property
        def size(self):
            raise AssertionError("the file must not be opened")

    values = vars(_image(str(tmp_path / "secret.png")))
    values.pop("size")
    info = diagnostics._image_info(Unreadable(**values), handler.policy)
    assert info["status"] == "outside_approved_roots" and "size" not in info


@pytest.mark.parametrize(
    "params",
    [
        {"profile": "console"},
        {"material": "M", "object": "O"},
        {"material": "Nope"},
        {"object": "Nope"},
        {"allow": [1]},
        {"max_texture_size": 0},
        {"alpha_modes": []},
        {"alpha_modes": ["GLASS"]},
    ],
)
def test_invalid_requests(handler, mock_bpy, params):
    mock_bpy.data.materials.get = lambda name: None
    mock_bpy.data.objects.get = lambda name: None
    with pytest.raises(ValueError):
        handler.handle("material.diagnose", params)


@pytest.mark.parametrize(
    ("value", "source", "expected"),
    [
        (1.0, None, "OPAQUE"),
        (0.5, None, "BLEND"),
        (1.0, ("ShaderNodeTexImage", None), "BLEND"),
        (1.0, ("ShaderNodeMath", "GREATER_THAN"), "MASK"),
        (1.0, ("ShaderNodeMath", "ROUND"), "MASK"),
        (1.0, ("ShaderNodeMath", "MULTIPLY"), "BLEND"),
    ],
)
def test_alpha_modes_follow_the_exporters_patterns(diagnostics, value, source, expected):
    links = []
    if source:
        links = [SimpleNamespace(from_node=SimpleNamespace(bl_idname=source[0], operation=source[1]))]
    shader = SimpleNamespace(inputs={"Alpha": SimpleNamespace(default_value=value, links=links)})
    assert diagnostics._alpha_mode(shader) == expected


@pytest.mark.parametrize(
    ("roughness", "metallic", "check"),
    [
        (("orm", "G"), ("orm", "B"), None),
        (("rough", "R"), ("metal", "R"), "channel_packing"),
        (("orm", "R"), ("orm", "B"), "channel_layout"),
        (("orm", "G"), None, None),
    ],
)
def test_metallic_and_roughness_packing(diagnostics, roughness, metallic, check):
    bindings = [
        {"semantic": semantic, "image": spec[0], "channel": spec[1]}
        for semantic, spec in (("roughness", roughness), ("metallic", metallic))
        if spec
    ]
    report = diagnostics._Report([])
    diagnostics._check_packing("M", bindings, "heuristic", report)
    assert [finding["check"] for finding in report.findings] == ([check] if check else [])


def test_diagnostics_and_previews_add_no_undo_step(handler):
    assert not {"material.diagnose", "material.preview"} & handler.mutation_commands


def test_preview_cleans_up_when_the_capture_fails(handler, mock_bpy, addon_module, monkeypatch):
    material = SimpleNamespace(name="M")
    mock_bpy.data.materials.get = lambda name: material

    def fail(*args, **kwargs):
        raise RuntimeError("render failed")

    monkeypatch.setattr(addon_module.capture, "capture", fail)
    with pytest.raises(RuntimeError, match="render failed"):
        handler.handle("material.preview", {"material": "M", "shape": "plane"})
    mock_bpy.data.objects.remove.assert_called_once()
    mock_bpy.data.meshes.remove.assert_called_once()
    with pytest.raises(ValueError, match="shape"):
        handler.handle("material.preview", {"material": "M", "shape": "torus"})
