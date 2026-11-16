"""Contracts for project files, bounded batches and modifier edits."""

from dataclasses import replace
from unittest.mock import MagicMock

import pytest


def test_project_validates_extension_overwrite_and_dirty_state(handler, mock_bpy, tmp_path):
    path = tmp_path / "scene.blend"
    path.touch()
    mock_bpy.data.filepath = ""
    mock_bpy.data.is_dirty = True
    assert handler.handle("project.get_info", {})["dirty"] is True
    with pytest.raises(ValueError, match=r"\.blend"):
        handler.handle("project.save", {"filepath": str(path.with_suffix(".png"))})
    with pytest.raises(PermissionError, match="overwrite=true"):
        handler.handle("project.save", {"filepath": str(path)})
    with pytest.raises(PermissionError, match="discard_changes=true"):
        handler.handle("project.open", {"filepath": str(path)})
    with pytest.raises(PermissionError, match="confirm=true"):
        handler.handle("project.revert", {"confirm": False})
    with pytest.raises(FileNotFoundError):
        handler.handle("project.open", {"filepath": str(path.with_name("missing.blend")), "discard_changes": True})
    mock_bpy.ops.wm.save_as_mainfile.assert_not_called()
    mock_bpy.ops.wm.open_mainfile.assert_not_called()


@pytest.mark.parametrize(
    "step",
    [
        {"command": "python.execute", "params": {"code": "pass"}},
        {"command": "scene.execute_batch", "params": {"commands": []}},
        {"command": "object.scale", "params": {"name": "Cube", "scale": [2]}},
        {"command": "material.set_texture", "params": {"name": "A", "filepath": "/tmp/image.png"}},
    ],
)
def test_batch_preflight_rejects_invalid_steps_before_mutation(handler, mock_bpy, step):
    commands = [{"command": "object.translate", "params": {"name": "Cube", "offset": [2, 0, 0]}}, step]
    with pytest.raises(RuntimeError, match="Batch step 1"):
        handler.handle("scene.execute_batch", {"commands": commands})
    assert not mock_bpy.ops.ed.undo_push.called


def test_batch_honors_command_whitelist_and_budget(handler, runtime):
    runtime.settings.tool_whitelist = {"scene.execute_batch", "scene.get_info"}
    with pytest.raises(RuntimeError, match="whitelist"):
        handler.handle("scene.execute_batch", {"commands": [{"command": "object.delete", "params": {"name": "Cube"}}]})
    with pytest.raises(RuntimeError, match="32"):
        handler.handle("scene.execute_batch", {"commands": [{"command": "scene.get_info"}] * 33})
    with pytest.raises(RuntimeError, match="64 KiB"):
        handler.handle(
            "scene.execute_batch", {"commands": [{"command": "object.delete", "params": {"name": "x" * 65536}}]}
        )


@pytest.mark.parametrize("stop", [True, False])
def test_batch_reports_each_step_and_undo_pushes(handler, mock_bpy, stop):
    mock_bpy.ops.ed.undo_push.poll.return_value = True
    params = {"name": "Cube", "offset": [1, 0, 0]}
    result = handler.handle(
        "scene.execute_batch",
        {
            "commands": [
                {"command": "object.translate", "params": params},
                {"command": "object.get_transform", "params": {"name": "Missing"}},
                {"command": "object.translate", "params": params},
            ],
            "stop_on_error": stop,
        },
    )
    assert [row["status"] for row in result["steps"]] == ["succeeded", "failed", "skipped" if stop else "succeeded"]
    assert result["steps"][1]["error"]["code"] == "not_found"
    assert mock_bpy.ops.ed.undo_push.call_count == (1 if stop else 2)


def test_bridge_rejects_mismatched_policy_and_sanitizes_ids(runtime):
    runtime.settings.policy = replace(runtime.settings.policy, allowed_commands=("scene.get_info",), output_roots=())
    bridge = runtime.create_server()
    result = bridge._submit_request({"id": "request1", "command": "scene.get_info"})
    assert result["error_details"]["code"] == "policy_mismatch"
    assert result["error_details"]["request_id"] == "request1"


def test_invalid_modifier_property_does_not_add_modifier(handler, mock_bpy):
    obj = mock_bpy.data.objects.get("Cube")
    obj.library = None
    obj.modifiers.get.return_value = None
    mock_bpy.types.BevelModifier.bl_rna.properties = {
        "segments": MagicMock(is_readonly=False, hard_min=1, hard_max=100)
    }
    with pytest.raises(ValueError, match="Invalid value"):
        handler.handle(
            "object.add_modifier", {"name": "Cube", "modifier_type": "BEVEL", "properties": {"segments": 100}}
        )
    obj.modifiers.new.assert_not_called()


def test_batch_undo_checkpoints_record_each_completed_mutation(handler, mock_bpy):
    cube = mock_bpy.data.objects.get("Cube")
    checkpoints = []
    mock_bpy.ops.ed.undo_push.poll.return_value = True
    mock_bpy.ops.ed.undo_push.side_effect = lambda **_: checkpoints.append(list(cube.location))

    handler.dispatch(
        "scene.execute_batch",
        {
            "commands": [
                {"command": "object.translate", "params": {"name": "Cube", "location": [1, 0, 0]}},
                {"command": "object.translate", "params": {"name": "Cube", "location": [2, 0, 0]}},
            ]
        },
    )
    assert checkpoints == [[1, 0, 0], [2, 0, 0]]
