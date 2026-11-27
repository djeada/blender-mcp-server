"""Tests for MCP tools."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from blender_mcp_server.app import HEADLESS_JOB_MANAGER
from blender_mcp_server.server import (
    main,
    mcp,
    python_exec,
    python_exec_async,
)
from blender_mcp_server.server import (
    material_set_color as material_set_color_tool,
)
from blender_mcp_server.server import (
    object_create as object_create_tool,
)


class TestToolRegistration:
    """Verify all expected tools are registered with correct metadata."""

    def _get_tool_names(self):
        return [t.name for t in mcp._tool_manager._tools.values()]

    def test_scene_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_scene_get_info" in names
        assert "blender_scene_list_objects" in names

    def test_object_read_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_object_get_transform" in names
        assert "blender_object_get_hierarchy" in names

    def test_object_mutation_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "blender_object_create",
            "blender_object_delete",
            "blender_object_translate",
            "blender_object_rotate",
            "blender_object_scale",
            "blender_object_duplicate",
        ]:
            assert tool in names

    def test_mesh_inspection_registered(self):
        assert "blender_mesh_inspect" in self._get_tool_names()

    def test_material_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "blender_material_list",
            "blender_material_create",
            "blender_material_assign",
            "blender_material_set_color",
            "blender_material_set_texture",
        ]:
            assert tool in names

    def test_camera_light_timeline_and_scene_org_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "blender_camera_create",
            "blender_camera_update",
            "blender_light_create",
            "blender_light_update",
            "blender_timeline_get",
            "blender_timeline_set",
            "blender_keyframe_add",
            "blender_keyframe_list",
            "blender_keyframe_remove",
            "blender_collection_create",
            "blender_collection_list",
            "blender_collection_rename",
            "blender_collection_add_object",
            "blender_collection_remove_object",
            "blender_object_rename",
            "blender_object_parent",
            "blender_object_unparent",
        ]:
            assert tool in names

    def test_render_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_render_still" in names
        assert "blender_render_animation" in names

    def test_export_tools_registered(self):
        names = self._get_tool_names()
        for tool in [
            "blender_export_gltf",
            "blender_export_obj",
            "blender_export_fbx",
        ]:
            assert tool in names

    def test_history_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_history_undo" in names
        assert "blender_history_redo" in names

    def test_python_exec_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_python_exec" in names
        assert "blender_python_exec_async" in names

    def test_job_tools_registered(self):
        names = self._get_tool_names()
        assert "blender_job_status" in names
        assert "blender_job_cancel" in names
        assert "blender_job_list" in names

    def test_total_tool_count(self):
        assert len(asyncio.run(mcp.list_tools())) == 74  # the default full profile

    @pytest.mark.parametrize(
        "name", ["blender_object_create_tree", "blender_object_scatter", "blender_material_create_emissive"]
    )
    def test_example_recipes_are_not_core_tools(self, name):
        assert name not in self._get_tool_names()

    def test_all_tools_have_descriptions(self):  # includes tools that only some profiles advertise
        for tool in mcp._tool_manager._tools.values():
            assert tool.description, f"Tool {tool.name} has no description"

    def test_context_parameter_not_exposed_in_tool_schema(self):
        for tool in mcp._tool_manager._tools.values():
            schema = getattr(tool, "inputSchema", None) or getattr(tool, "parameters", {})
            properties = schema.get("properties", {})
            assert "ctx" not in properties, f"Tool {tool.name} exposes ctx in schema"


class TestMCPProtocol:
    """Test the MCP server entrypoint configuration."""

    def test_main_runs_stdio_transport(self):
        with patch.object(mcp, "run") as run:
            main([])
        run.assert_called_once_with(transport="stdio")


class TestToolParameters:
    def _ctx(self):
        ctx = MagicMock()
        from blender_mcp_server.shared import policy

        ctx.request_context.lifespan_context.policy = policy.Policy.load()
        ctx.request_context.lifespan_context.send_command = AsyncMock(return_value={})
        return ctx

    @pytest.mark.asyncio
    async def test_unset_parameters_are_omitted(self):
        ctx = self._ctx()
        await object_create_tool(ctx, mesh_type="cube")
        command, params = ctx.request_context.lifespan_context.send_command.await_args.args
        assert command == "object.create_mesh"
        assert params == {"type": "cube", "size": 2.0}

    @pytest.mark.asyncio
    async def test_material_set_color_params(self):
        ctx = self._ctx()
        await material_set_color_tool(ctx, name="M", color=[1, 0, 0])
        _command, params = ctx.request_context.lifespan_context.send_command.await_args.args
        assert params == {"name": "M", "color": [1, 0, 0]}

    def test_transport_schema_is_an_enum(self):
        for tool in mcp._tool_manager._tools.values():
            schema = getattr(tool, "parameters", {})
            transport = schema.get("properties", {}).get("transport")
            if transport is not None:
                assert set(transport["enum"]) == {"bridge", "headless"}, tool.name

    @pytest.mark.asyncio
    async def test_headless_can_be_disabled(self, monkeypatch):
        monkeypatch.setenv("BLENDER_MCP_HEADLESS", "0")
        with pytest.raises(PermissionError):
            await python_exec(self._ctx(), code="pass", transport="headless")

    @pytest.mark.asyncio
    async def test_async_headless_validates_before_creating_job(self, headless_policy):
        HEADLESS_JOB_MANAGER._jobs.clear()
        with pytest.raises(ValueError):
            ctx = self._ctx()
            ctx.request_context.lifespan_context.policy = headless_policy
            await python_exec_async(ctx, transport="headless")
        assert HEADLESS_JOB_MANAGER._jobs == {}
