"""Tests for Blender materials behavior."""

from unittest.mock import MagicMock

import pytest


class TestMaterialCommands:
    def test_material_list_empty(self, handler, mock_bpy):
        mock_bpy.data.materials = []
        result = handler.handle("material.list", {})
        assert result["materials"] == []


class TestMaterialTexture:
    def _material(self, mock_bpy):
        material = MagicMock()
        material.name = "M"
        mock_bpy.data.materials.get = MagicMock(return_value=material)
        return material

    def test_failed_image_load_adds_no_node(self, handler, mock_bpy):
        material = self._material(mock_bpy)
        mock_bpy.data.images.load.side_effect = RuntimeError("Cannot read '/missing.png'")
        with pytest.raises(FileNotFoundError, match="Cannot read"):
            handler.handle("material.set_texture", {"name": "M", "filepath": "/missing.png"})
        material.node_tree.nodes.new.assert_not_called()

    def test_first_texture_creates_and_links_a_node(self, handler, mock_bpy):
        material = self._material(mock_bpy)
        handler.handle("material.set_texture", {"name": "M", "filepath": "/a.png"})
        node = material.node_tree.nodes.new.return_value
        material.node_tree.nodes.new.assert_called_once_with("ShaderNodeTexImage")
        material.node_tree.links.new.assert_called_once()
        assert node.image is mock_bpy.data.images.load.return_value

    def test_replacing_a_texture_reuses_the_linked_node(self, handler, mock_bpy):
        material = self._material(mock_bpy)
        existing = MagicMock()
        existing.bl_idname = "ShaderNodeTexImage"
        link = MagicMock()
        link.from_node = existing
        material.node_tree.nodes.get.return_value.inputs.__getitem__.return_value.links = [link]
        handler.handle("material.set_texture", {"name": "M", "filepath": "/b.png"})
        material.node_tree.nodes.new.assert_not_called()
        assert existing.image is mock_bpy.data.images.load.return_value
