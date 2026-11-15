"""Tests for optional example recipes and demo runners."""

import ast
import importlib.util
import math
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
LIBRARY = EXAMPLES / "library"
DEMOS = EXAMPLES / "demos"


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLES.parent / "scripts"))
    spec = importlib.util.spec_from_file_location("run_dam_break", DEMOS / "run_dam_break.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("path", sorted(EXAMPLES.rglob("*.py")), ids=lambda path: str(path.relative_to(EXAMPLES)))
def test_example_parses(path):
    ast.parse(path.read_text(), filename=str(path))


class TestDamBreakDemo:
    def test_demo_scripts_avoid_mesh_primitive_operators(self):
        for filename in ("dam_break_scene.py", "run_dam_break.py"):
            assert "bpy.ops.mesh.primitive_" not in (DEMOS / filename).read_text()

    def test_runner_builds_correct_steps(self, runner):
        steps = runner.build_steps(str(LIBRARY))
        assert len(steps) >= 11
        labels = [step["label"].lower() for step in steps]
        for label in ("frame range", "fluid domain", "camera", "collider", "rigid"):
            assert any(label in actual for actual in labels)
        assert any("keyframe" in actual or "dolly" in actual for actual in labels)

    def test_runner_script_paths_exist(self, runner):
        for step in runner.build_steps(str(LIBRARY)):
            if step["method"] == "script":
                assert Path(step["script_path"]).is_file()

    def test_runner_stops_on_inner_script_error(self, runner):
        with patch.object(runner, "exec_inline", return_value={"success": True, "result": {"error": "boom"}}):
            assert runner.run_demo("127.0.0.1", 9876, str(LIBRARY), dry_run=False) == 1

    def test_exec_script_sends_inline_code(self, runner, tmp_path):
        script = tmp_path / "sample.py"
        script.write_text("__result__ = {'ok': True}\n")
        with patch.object(runner, "send_command", return_value={"success": True}) as send:
            runner.exec_script(str(script), {"x": 1})
        send.assert_called_once_with("python.execute", {"code": script.read_text(), "args": {"x": 1}})


@pytest.fixture
def example_bpy(monkeypatch):
    bpy = MagicMock()
    source = SimpleNamespace(name="Cube", rotation_euler=(0, 0, 0), scale=(1, 1, 1), data=object())
    source.copy = lambda: SimpleNamespace(data=source.data)
    bpy.data.objects.get.side_effect = lambda name: source if name == "Cube" else None
    monkeypatch.setitem(sys.modules, "bpy", bpy)
    return bpy


def execute_recipe(filename, args):
    return runpy.run_path(str(LIBRARY / filename), init_globals={"args": args})["__result__"]


class TestScatterExample:
    def test_scatter_stays_in_disk_and_shares_mesh(self, example_bpy):
        result = execute_recipe("scatter_objects.py", {"source": "Cube", "count": 5, "radius": 2.0, "seed": 1})
        assert result["source"] == "Cube"
        assert result["count"] == 5
        assert len(set(result["names"])) == 5
        copies = [call.args[0] for call in example_bpy.context.scene.collection.objects.link.call_args_list]
        assert len(copies) == 5
        for obj in copies:
            assert math.hypot(*obj.location[:2]) <= 2.0
            assert obj.location[2] == 0
            assert obj.data is example_bpy.data.objects.get("Cube").data

    @pytest.mark.parametrize(
        "args",
        [
            {"count": 501},
            {"count": 0},
            {"scale_min": 2.0, "scale_max": 1.0},
            {"radius": -1},
            {"radius": float("nan")},
            {"source": "Missing"},
        ],
    )
    def test_invalid_input_creates_no_copies(self, example_bpy, args):
        with pytest.raises(ValueError):
            execute_recipe("scatter_objects.py", {"source": "Cube", **args})
        example_bpy.context.scene.collection.objects.link.assert_not_called()


class TestEmissiveMaterialExample:
    def test_material_color_and_strength(self, example_bpy):
        example_bpy.data.materials.new.return_value.name = "Glow"
        result = execute_recipe("create_emissive_material.py", {"emission_color": [0, 1, 1], "emission_strength": 8})
        assert result == {"name": "Glow", "emission_color": [0, 1, 1, 1], "emission_strength": 8}
        bsdf = example_bpy.data.materials.new.return_value.node_tree.nodes.get.return_value
        assert bsdf.inputs.get.return_value.default_value == [0, 1, 1, 1]
        assert bsdf.inputs["Emission Strength"].default_value == 8
