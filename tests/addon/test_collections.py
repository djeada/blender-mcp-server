"""Tests for Blender collections behavior."""

import types
from unittest.mock import MagicMock

import pytest

from .fakes import (
    _FakeCollection,
    _FakeObject,
    _install_fake_collections,
)


class TestCollectionCommands:
    def test_collection_create_at_scene_root(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        result = handler.handle("collection.create", {"name": "Props"})
        assert result == {"name": "Props", "parent": "Scene Collection"}
        assert colls["Props"] in mock_bpy.context.scene.collection.children.items

    def test_collection_create_under_parent(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        parent = colls.setdefault("Sets", _FakeCollection("Sets", {"Sets"}))
        result = handler.handle("collection.create", {"name": "Props", "parent": "Sets"})
        assert result["parent"] == "Sets"
        assert colls["Props"] in parent.children.items

    def test_collection_create_missing_parent(self, handler, mock_bpy):
        _install_fake_collections(mock_bpy)
        with pytest.raises(ValueError, match="Parent collection 'Nope' not found"):
            handler.handle("collection.create", {"name": "Props", "parent": "Nope"})

    def test_collection_create_rejects_duplicate(self, handler, mock_bpy):
        _install_fake_collections(mock_bpy)
        handler.handle("collection.create", {"name": "Props"})
        with pytest.raises(ValueError, match="already exists"):
            handler.handle("collection.create", {"name": "Props"})

    def test_collection_create_rejects_empty_name(self, handler, mock_bpy):
        _install_fake_collections(mock_bpy)
        with pytest.raises(ValueError, match="must not be empty"):
            handler.handle("collection.create", {"name": "  "})

    def test_collection_list(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        props = colls.setdefault("Props", _FakeCollection("Props", {"Props"}))
        props.objects.link(types.SimpleNamespace(name="Cube"))
        result = handler.handle("collection.list", {})
        assert {"name": "Props", "object_count": 1} in result["collections"]

    def test_collection_rename_reports_canonical_name(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        colls.setdefault("Existing", _FakeCollection("Existing", {"Existing"}))
        colls.setdefault("Props", _FakeCollection("Props", {"Existing"}))
        result = handler.handle("collection.rename", {"name": "Props", "new_name": "Existing"})
        assert result["name"] == "Existing.001"
        assert result["requested"] == "Existing"

    def test_collection_rename_missing(self, handler, mock_bpy):
        _install_fake_collections(mock_bpy)
        with pytest.raises(ValueError, match="not found"):
            handler.handle("collection.rename", {"name": "Nope", "new_name": "X"})

    def test_collection_add_object_moves_and_reports_previous(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        old = colls.setdefault("Old", _FakeCollection("Old", {"Old"}))
        target = colls.setdefault("New", _FakeCollection("New", {"New"}))
        obj = MagicMock()
        obj.name = "Cube"
        obj.users_collection = [old]
        mock_bpy.data.objects.get = lambda n: obj
        result = handler.handle("collection.add_object", {"collection": "New", "object": "Cube"})
        assert result["moved"] is True
        assert result["previous_collections"] == ["Old"]
        assert obj not in old.objects.items
        assert obj in target.objects.items

    def test_collection_add_object_already_member(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        target = colls.setdefault("New", _FakeCollection("New", {"New"}))
        obj = MagicMock()
        obj.name = "Cube"
        obj.users_collection = [target]
        mock_bpy.data.objects.get = lambda n: obj
        result = handler.handle("collection.add_object", {"collection": "New", "object": "Cube"})
        assert result["moved"] is False

    def test_collection_remove_object_relinks_orphans_to_scene(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        props = colls.setdefault("Props", _FakeCollection("Props", {"Props"}))
        obj = _FakeObject("Cube", colls=[props])
        props.objects.link(obj)
        mock_bpy.data.objects.get = lambda n: obj
        result = handler.handle("collection.remove_object", {"collection": "Props", "object": "Cube"})
        assert result["relinked_to_scene"] is True
        assert obj not in props.objects.items

    def test_collection_remove_object_not_member(self, handler, mock_bpy):
        colls = _install_fake_collections(mock_bpy)
        colls.setdefault("Props", _FakeCollection("Props", {"Props"}))
        obj = MagicMock()
        obj.name = "Cube"
        obj.users_collection = []
        mock_bpy.data.objects.get = lambda n: obj
        with pytest.raises(ValueError, match="is not in collection"):
            handler.handle("collection.remove_object", {"collection": "Props", "object": "Cube"})
