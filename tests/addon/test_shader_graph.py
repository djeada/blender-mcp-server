"""Tests for shader patch validation. Graph behaviour is tested in real Blender."""

import pytest


@pytest.fixture
def graph(addon_module):
    return addon_module.shader_graph


def _add(node_id, kind="ShaderNodeMath", **extra):
    return {"op": "add_node", "id": node_id, "type": kind, **extra}


@pytest.mark.parametrize(
    ("operations", "message"),
    [
        ([], "1-64 operations"),
        ([_add(f"n{i}") for i in range(65)], "1-64 operations"),
        (["add"], "'op' must be one of"),
        ([{"op": "run_python", "code": "x"}], "'op' must be one of"),
        ([{"op": "add_node", "id": "a"}], "needs: type"),
        ([{"op": "remove_node", "node": "a", "force": True}], "does not accept: force"),
        ([{"op": "remove_node", "node": ""}], "'node' must be a nonempty string"),
        ([{"op": "connect", "from": "a", "from_socket": 0, "to": "b", "to_socket": "x"}], "'from_socket' must be"),
        ([_add("a"), _add("a")], "duplicate node id 'a'"),
        ([_add("x" * 64)], "at most 63 bytes"),
        ([_add("line\nbreak")], "printable"),
        ([_add("a", "ShaderNodeScript")], "'ShaderNodeScript' is not supported"),
        ([_add("a", "ShaderNodeOutputMaterial")], "not supported"),
        ([_add("a", "ShaderNodeGroup")], "not supported"),
        ([_add("a", properties=[1])], "'properties' must be an object"),
    ],
)
def test_malformed_patches_are_rejected_before_blender(graph, operations, message):
    with pytest.raises(ValueError, match=message):
        graph.check_operations(operations)


def test_no_listed_node_or_setting_can_run_code(graph):
    assert "ShaderNodeScript" not in graph.NODE_TYPES
    settings = {name for names in graph.NODE_TYPES.values() for name in names}
    assert not settings & {"script", "filepath", "bytecode", "mode_script", "node_tree", "name"}


@pytest.mark.parametrize(
    ("source", "target", "allowed"),
    [
        ("SHADER", "SHADER", True),
        ("SHADER", "VALUE", False),
        ("VALUE", "SHADER", False),
        ("VALUE", "RGBA", True),
        ("RGBA", "VECTOR", True),
        ("VECTOR", "VALUE", True),
        ("ROTATION", "ROTATION", True),
        ("ROTATION", "VALUE", False),
    ],
)
def test_socket_compatibility(graph, source, target, allowed):
    assert graph._compatible(source, target) is allowed


@pytest.mark.parametrize(
    "params",
    [
        {"operations": [_add("a")]},
        {"material": "M", "world": True, "operations": [_add("a")]},
        {"material": "M", "operations": [_add("a")], "shared_data": "sometimes"},
        {"material": "M", "operations": "add"},
    ],
)
def test_invalid_edit_requests(handler, params):
    with pytest.raises(ValueError):
        handler.handle("shader.edit_graph", params)


def test_missing_material_and_flags(handler, mock_bpy):
    mock_bpy.data.materials.get = lambda name: None
    with pytest.raises(ValueError, match="Material not found"):
        handler.handle("shader.inspect_graph", {"material": "M"})
    assert "shader.edit_graph" in handler.mutation_commands
    assert "shader.inspect_graph" not in handler.mutation_commands
