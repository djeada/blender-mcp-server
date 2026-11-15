"""Tests for Blender objects behavior."""

import types
from unittest.mock import MagicMock

import pytest

from .fakes import (
    _FakeObject,
)


class TestObjectCommands:
    @pytest.mark.parametrize("command", ["object.create_tree", "object.scatter", "material.create_emissive"])
    def test_example_recipes_are_not_bridge_commands(self, handler, command, runtime):
        assert command not in handler.commands
        assert command not in runtime.handler.mutation_commands
        with pytest.raises(ValueError, match="Unknown command"):
            handler.handle(command, {})

    def test_build_primitive_pydata_cube(self, addon_module):
        verts, faces = addon_module.geometry.build_primitive_pydata("cube", 2.0)
        assert len(verts) == 8
        assert len(faces) == 6

    def test_build_primitive_pydata_sphere(self, addon_module):
        verts, faces = addon_module.geometry.build_primitive_pydata("sphere", 2.0)
        assert len(verts) > 10
        assert len(faces) > 10

    def test_build_primitive_pydata_rejects_unknown_shape(self, addon_module):
        with pytest.raises(ValueError, match="Unknown mesh type"):
            addon_module.geometry.build_primitive_pydata("bad-shape", 2.0)

    def test_get_transform(self, handler):
        result = handler.handle("object.get_transform", {"name": "Cube"})
        assert result["name"] == "Cube"
        assert "location" in result
        assert "rotation_euler" in result
        assert "scale" in result

    def test_get_transform_missing_object(self, handler):
        with pytest.raises(ValueError, match="not found"):
            handler.handle("object.get_transform", {"name": "NonExistent"})

    def test_unknown_command(self, handler):
        with pytest.raises(ValueError, match="Unknown command"):
            handler.handle("nonexistent.command", {})

    def test_get_hierarchy_full_scene(self, handler):
        result = handler.handle("object.get_hierarchy", {})
        assert "roots" in result
        assert len(result["roots"]) == 2


class TestNonMeshObjects:
    def test_duplicate_object_without_data(self, handler, mock_bpy):
        empty = MagicMock()
        empty.name = "Empty"
        empty.data = None
        duplicate = empty.copy.return_value
        duplicate.data = None
        mock_bpy.data.objects.get = lambda name: empty
        result = handler.handle("object.duplicate", {"name": "Empty", "new_name": "Empty2"})
        assert result["name"] == "Empty2"
        assert duplicate.data is None
        mock_bpy.context.collection.objects.link.assert_called_once_with(duplicate)

    @pytest.mark.parametrize("data", [None, types.SimpleNamespace()], ids=["empty", "camera"])
    def test_material_assign_rejects_objects_without_material_slots(self, handler, mock_bpy, data):
        obj = types.SimpleNamespace(name="Thing", type="EMPTY" if data is None else "CAMERA", data=data)
        mock_bpy.data.objects.get = lambda name: obj
        mock_bpy.data.materials.get = MagicMock(return_value=MagicMock())
        with pytest.raises(ValueError, match=f"type {obj.type}, which cannot have materials"):
            handler.handle("material.assign", {"object": "Thing", "material": "M"})

    @pytest.mark.parametrize("existing", [[], ["old"]], ids=["no-slot", "first-slot"])
    def test_material_assign_fills_first_slot(self, handler, mock_bpy, existing):
        slots = list(existing)
        obj = types.SimpleNamespace(name="Cube", type="MESH", data=types.SimpleNamespace(materials=slots))
        material = MagicMock()
        mock_bpy.data.objects.get = lambda name: obj
        mock_bpy.data.materials.get = MagicMock(return_value=material)
        handler.handle("material.assign", {"object": "Cube", "material": "M"})
        assert slots == [material]


class TestRenameAndParentCommands:
    def test_object_rename_reports_canonical_name(self, handler, mock_bpy):
        obj = _FakeObject("Cube", taken_names={"Existing"})
        mock_bpy.data.objects.get = lambda n: obj
        result = handler.handle("object.rename", {"name": "Cube", "new_name": "Existing"})
        assert result["name"] == "Existing.001"
        assert result["requested"] == "Existing"

    def test_object_rename_missing(self, handler, mock_bpy):
        mock_bpy.data.objects.get = lambda n: None
        with pytest.raises(ValueError, match="not found"):
            handler.handle("object.rename", {"name": "Nope", "new_name": "X"})

    def test_object_parent_with_keep_transform(self, handler, mock_bpy):
        parent = MagicMock()
        parent.name = "Parent"
        parent.parent = None
        child = MagicMock()
        child.name = "Child"
        child.parent = None
        objects = {"Child": child, "Parent": parent}
        mock_bpy.data.objects.get = lambda n: objects.get(n)
        result = handler.handle("object.parent", {"name": "Child", "parent": "Parent", "keep_transform": True})
        assert result == {"name": "Child", "parent": "Parent", "keep_transform": True}
        assert child.parent is parent
        inverse = parent.matrix_world.inverted.return_value
        assert child.matrix_parent_inverse is inverse

    def test_object_parent_without_keep_transform(self, handler, mock_bpy):
        parent = MagicMock()
        parent.name = "Parent"
        parent.parent = None
        child = MagicMock()
        child.name = "Child"
        child.parent = None
        objects = {"Child": child, "Parent": parent}
        mock_bpy.data.objects.get = lambda n: objects.get(n)
        handler.handle("object.parent", {"name": "Child", "parent": "Parent"})
        assert child.parent is parent
        parent.matrix_world.inverted.assert_not_called()

    def test_object_parent_rejects_self(self, handler, mock_bpy):
        obj = MagicMock()
        obj.name = "Cube"
        mock_bpy.data.objects.get = lambda n: obj
        with pytest.raises(ValueError, match="cannot be parented to itself"):
            handler.handle("object.parent", {"name": "Cube", "parent": "Cube"})

    def test_object_parent_rejects_cycles(self, handler, mock_bpy):
        child = types.SimpleNamespace(name="Child", parent=None)
        parent = types.SimpleNamespace(name="Parent", parent=child)
        child.parent = parent
        objects = {"Child": child, "Parent": parent}
        mock_bpy.data.objects.get = lambda n: objects.get(n)
        with pytest.raises(ValueError, match="cycle"):
            handler.handle("object.parent", {"name": "Child", "parent": "Parent"})

    def test_object_parent_missing_parent(self, handler, mock_bpy):
        obj = MagicMock()
        obj.name = "Cube"
        objects = {"Cube": obj}
        mock_bpy.data.objects.get = lambda n: objects.get(n)
        with pytest.raises(ValueError, match="not found"):
            handler.handle("object.parent", {"name": "Cube", "parent": "Missing"})

    def test_object_unparent_bakes_world_transform(self, handler, mock_bpy):
        obj = MagicMock()
        obj.name = "Child"
        obj.parent = MagicMock()
        world = obj.matrix_world.copy.return_value
        mock_bpy.data.objects.get = lambda n: obj
        result = handler.handle("object.unparent", {"name": "Child", "keep_transform": True})
        assert obj.matrix_world is world
        assert obj.parent is None
        assert result == {"name": "Child", "unparented": True, "keep_transform": True}

    def test_object_unparent_without_parent(self, handler, mock_bpy):
        obj = MagicMock()
        obj.name = "Root"
        obj.parent = None
        mock_bpy.data.objects.get = lambda n: obj
        with pytest.raises(ValueError, match="has no parent"):
            handler.handle("object.unparent", {"name": "Root"})
