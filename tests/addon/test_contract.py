"""Tests for Blender contract behavior."""

from unittest.mock import MagicMock

import pytest


class TestServerAddonContract:
    """Every MCP tool must send parameters the add-on's validator accepts."""

    CALLS = [
        ("scene_execute_batch", {"commands": [{"command": "scene.get_info"}]}),
        ("project_save", {"filepath": "/tmp/file.blend", "overwrite": True}),
        ("project_open", {"filepath": "/tmp/file.blend", "discard_changes": True}),
        ("project_revert", {"confirm": True}),
        ("object_list_modifiers", {"name": "Cube"}),
        ("object_add_modifier", {"name": "Cube", "modifier_type": "BEVEL", "properties": {"segments": 2}}),
        ("object_update_modifier", {"name": "Cube", "modifier_name": "Edge", "properties": {"width": 0.1}}),
        ("object_remove_modifier", {"name": "Cube", "modifier_name": "Edge"}),
        ("scene_list_objects", {"type": "MESH", "limit": 5, "offset": 5}),
        ("material_list", {"limit": 5, "offset": 5}),
        ("collection_list", {"limit": 5, "offset": 5}),
        ("object_get_transform", {"name": "Cube"}),
        ("object_get_hierarchy", {"name": "Cube", "max_nodes": 5, "max_depth": 2, "offset": 1}),
        ("object_create", {"mesh_type": "sphere", "name": "S", "location": [1, 2, 3], "size": 1.0}),
        ("object_delete", {"name": "Cube"}),
        ("object_translate", {"name": "Cube", "offset": [1, 0, 0]}),
        ("object_rotate", {"name": "Cube", "rotation": [0, 0, 90]}),
        ("object_scale", {"name": "Cube", "scale": [2, 2, 2]}),
        ("object_duplicate", {"name": "Cube", "new_name": "Copy"}),
        ("object_rename", {"name": "Cube", "new_name": "Renamed"}),
        ("object_parent", {"name": "Cube", "parent": "Parent", "keep_transform": True}),
        ("object_unparent", {"name": "Cube", "keep_transform": True}),
        ("camera_create", {"name": "Camera", "location": [3, -4, 5], "look_at": [0, 0, 0], "lens": 50}),
        ("camera_update", {"name": "Camera", "projection": "ORTHO", "ortho_scale": 4}),
        ("light_create", {"name": "Key", "light_type": "AREA", "energy": 100, "size": 2}),
        ("light_update", {"name": "Key", "color": [1, 0.5, 0.25], "shared_data": "update_all"}),
        ("light_create", {"light_type": "AREA", "shape": "DISK", "temperature": 3200}),
        ("lighting_inspect", {"include_options": True, "limit": 5, "offset": 1}),
        (
            "world_set",
            {
                "mode": "sky",
                "color": [0, 0, 0],
                "strength": 1,
                "filepath": "/tmp/a.hdr",
                "rotation": 1,
                "sky_type": "PREETHAM",
                "sun_elevation": 1,
                "sun_rotation": 1,
                "sun_intensity": 1,
                "sun_disc": True,
                "turbidity": 2,
                "camera_background": [0, 0, 0],
                "clear_camera_background": True,
                "on_conflict": "replace",
            },
        ),
        ("color_management_set", {"view_transform": "Standard", "look": "None", "exposure": 1, "gamma": 1}),
        ("timeline_set", {"frame_current": 1, "frame_start": 1, "frame_end": 120}),
        ("keyframe_add", {"name": "Cube", "property": "location", "frame": 1, "value": [0, 0, 0]}),
        ("keyframe_list", {"name": "Cube", "property": "location", "limit": 5, "offset": 5}),
        ("keyframe_remove", {"name": "Cube", "property": "location", "frame": 1}),
        ("collection_create", {"name": "Props", "parent": "Scene"}),
        ("collection_rename", {"name": "Props", "new_name": "Assets"}),
        ("collection_add_object", {"collection": "Props", "object": "Cube"}),
        ("collection_remove_object", {"collection": "Props", "object": "Cube"}),
        ("material_create", {"name": "M", "color": [1, 0, 0]}),
        ("material_slots", {"object": "Cube", "limit": 2, "offset": 1}),
        (
            "lighting_rig_apply",
            {
                "rig": "portrait",
                "object": "Cube",
                "name": "R",
                "camera": "C",
                "rotation": 5,
                "exposure_stops": 1,
                "distance_scale": 2,
                "size_scale": 2,
                "ratios": {"fill": 0.2},
                "temperatures": {"key": 4000},
                "colors": {"rim": [1, 0, 0]},
                "on_existing": "replace",
            },
        ),
        ("lighting_rig_remove", {"name": "R"}),
        (
            "camera_frame",
            {
                "camera": "C",
                "collection": "Parts",
                "azimuth": 10,
                "elevation": 5,
                "projection": "ORTHO",
                "lens": 50,
                "margin": 1.2,
                "aspect": 1.5,
                "set_active": True,
            },
        ),
        (
            "material_diagnose",
            {
                "object": "Cube",
                "profile": "mobile",
                "max_texture_size": 512,
                "max_texture_memory_mb": 8,
                "allow": ["unused_nodes"],
                "limit": 4,
                "offset": 1,
            },
        ),
        ("material_preview", {"material": "M", "shape": "plane", "views": ["front"], "resolution": 64}),
        (
            "shader_graph_inspect",
            {"material": "M", "group_path": ["G"], "nodes": ["a"], "sockets": True, "limit": 3, "offset": 1},
        ),
        (
            "shader_graph_edit",
            {"world": True, "operations": [{"op": "remove_node", "node": "a"}], "shared_data": "update_all"},
        ),
        (
            "material_set_texture_set",
            {
                "name": "M",
                "maps": {"base_color": "/tmp/a.png"},
                "orm": "/tmp/o.png",
                "uv_map": "UVMap",
                "mapping": {"scale": [2, 2]},
                "remove": ["height"],
                "on_conflict": "replace",
            },
        ),
        ("material_slot_append", {"object": "Cube", "material": "M", "link": "OBJECT", "shared_data": "update_all"}),
        ("material_slot_replace", {"object": "Cube", "index": 0, "material": "M", "link": "DATA"}),
        ("material_slot_remove", {"object": "Cube", "index": 1, "remap_to": 0}),
        (
            "material_assign_faces",
            {"object": "Cube", "slot": 0, "face_indices": [0, 1], "match": "any", "min_weight": 0.5},
        ),
        ("material_assign", {"object": "Cube", "material": "M"}),
        ("material_set_color", {"name": "M", "color": [1, 0, 0]}),
        ("material_set_texture", {"name": "M", "filepath": "/tmp/t.png"}),
        (
            "mesh_inspect",
            {"name": "Cube", "source": "evaluated", "check_duplicates": True, "include_regions": True},
        ),
        ("render_still", {"output_path": "/tmp/r.png", "resolution_x": 64, "resolution_y": 64, "engine": "CYCLES"}),
        ("render_animation", {"output_path": "/tmp/r_", "frame_start": 1, "frame_end": 2}),
        ("export_gltf", {"filepath": "/tmp/x.glb"}),
        ("export_obj", {"filepath": "/tmp/x.obj"}),
        ("export_fbx", {"filepath": "/tmp/x.fbx"}),
        ("python_exec", {"code": "pass", "args": {"a": 1}, "timeout_seconds": 5}),
        ("python_exec_async", {"code": "pass", "timeout_seconds": 5}),
        ("job_status", {"job_id": "job-1"}),
        ("job_cancel", {"job_id": "job-1"}),
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("tool_name", "kwargs"), CALLS)
    async def test_tool_params_pass_addon_validation(self, tool_name, kwargs, runtime):
        from unittest.mock import AsyncMock

        from blender_mcp_server import server

        ctx = MagicMock()
        ctx.request_context.lifespan_context.send_command = AsyncMock(return_value={})
        await getattr(server, tool_name)(ctx, **kwargs)
        command, params = ctx.request_context.lifespan_context.send_command.await_args.args

        validator = runtime.handler.commands[command].validator
        assert validator is not None, f"{command} has no add-on validator"
        validated = validator.model_validate(params).model_dump(exclude_none=True)
        for key in params:
            assert key in validated, f"{tool_name} sends '{key}', which the add-on drops"

    def test_every_bridge_command_is_handled(self, runtime):
        import inspect
        import re

        from blender_mcp_server import server

        commands = set()
        for tool in server.mcp._tool_manager._tools.values():
            source = inspect.getsource(tool.fn)
            commands.update(re.findall(r'bridge(?:_result)?\(\s*ctx,\s*"([a-z_.]+)"', source))
            commands.update(re.findall(r'send_command\("([a-z_.]+)"', source))
        assert commands == set(runtime.handler.commands)


def test_capability_registry_covers_every_bridge_command(runtime):
    from blender_mcp_server.capabilities import GROUPS

    registered = {command for group in GROUPS.values() for commands in group.tools.values() for command in commands}
    assert registered == set(runtime.handler.commands)


class TestVersionConsistency:
    def test_addon_version_matches_package(self, addon_module):
        import re

        with open("pyproject.toml") as f:
            pyproject = f.read()
        version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
        assert ".".join(map(str, addon_module.bl_info["version"])) == version
        with open("addon/blender_manifest.toml") as f:
            manifest = f.read()
        assert f'version = "{version}"' in manifest


def test_port_environment_variable_overrides_preference(handler, mock_bpy, monkeypatch, runtime):
    prefs = MagicMock()
    prefs.safe_mode = False
    prefs.port = 9876
    prefs.allow_inline_code = True
    prefs.approved_script_roots = ""
    prefs.allowed_commands = ""
    mock_bpy.context.preferences.addons["addon"] = MagicMock(preferences=prefs)
    monkeypatch.setenv("BLENDER_MCP_PORT", "9911")
    runtime.settings.sync_preferences()
    assert runtime.settings.port == 9911
