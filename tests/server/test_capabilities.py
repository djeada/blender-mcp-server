"""Protocol-level tests for capability profiles, discovery and on-demand execution."""

import contextlib
import inspect
import json
import re
from unittest.mock import AsyncMock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from blender_mcp_server.app import mcp
from blender_mcp_server.capabilities import (
    DISCOVERY_TOOLS,
    GROUPS,
    KEYWORDS,
    OUTPUT_TOOL,
    SUPPORT_TOOLS,
    TOOL_GROUPS,
    Exposure,
    parse_exposure,
)
from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.server import main  # noqa: F401  (importing registers every tool)

# The compact startup surface. Growing it, or these limits, is a deliberate change: update the docs with it.
COMPACT_TOOLS = sorted([*GROUPS["core"].tools, *SUPPORT_TOOLS])
COMPACT_SCHEMA_BYTE_BUDGET = 6_200

# Names that existing full-profile clients depend on.
LEGACY_TOOLS = [
    "camera_create",
    "camera_update",
    "collection_add_object",
    "collection_create",
    "collection_list",
    "collection_remove_object",
    "collection_rename",
    "export_fbx",
    "export_gltf",
    "export_obj",
    "history_redo",
    "history_undo",
    "job_cancel",
    "job_list",
    "job_status",
    "keyframe_add",
    "keyframe_list",
    "keyframe_remove",
    "light_create",
    "light_update",
    "material_assign",
    "material_create",
    "material_list",
    "material_set_color",
    "material_set_texture",
    "mesh_inspect",
    "object_add_modifier",
    "object_create",
    "object_delete",
    "object_duplicate",
    "object_get_hierarchy",
    "object_get_transform",
    "object_list_modifiers",
    "object_parent",
    "object_remove_modifier",
    "object_rename",
    "object_rotate",
    "object_scale",
    "object_translate",
    "object_unparent",
    "object_update_modifier",
    "project_get_info",
    "project_open",
    "project_revert",
    "project_save",
    "python_exec",
    "python_exec_async",
    "render_animation",
    "render_still",
    "view_capture",
    "guide_get",
    "guide_search",
    "workflow",
    "scene_execute_batch",
    "scene_get_info",
    "scene_list_objects",
    "status",
    "timeline_get",
    "timeline_set",
]


@pytest.fixture
def sent(monkeypatch):
    """Replace the socket with a recorder. Policy checks before it still run."""
    send = AsyncMock(return_value={"name": "Scene", "value": [1, 2]})

    async def send_command(connection, command, params=None, **kwargs):
        connection.policy.require_command(command)
        return await send(command, params)

    monkeypatch.setattr(BlenderConnection, "send_command", send_command)
    return send


@pytest.fixture
def serve(monkeypatch, sent):
    """Connect a real MCP client to the server with a chosen exposure."""

    @contextlib.asynccontextmanager
    async def connect(profile="compact", **options):
        monkeypatch.setattr(mcp, "exposure", Exposure.create(profile, **options))
        mcp._mcp_server._tool_cache.clear()  # one server object, many exposures: only happens in tests
        async with create_connected_server_and_client_session(mcp) as client:
            await client.list_tools()
            yield client

    return connect


async def _json(client, tool, /, **arguments):
    result = await client.call_tool(tool, arguments)
    assert not result.isError, result.content[0].text
    return json.loads(result.content[0].text)


async def _error(client, tool, /, **arguments):
    result = await client.call_tool(tool, arguments)
    assert result.isError, result.content[0].text
    return result.structuredContent["error"]


async def _describe_and_invoke(client, action, arguments):
    await _json(client, "blender_capability_describe", actions=[action])
    return await client.call_tool("blender_capability_invoke", {"action": action, "arguments": arguments})


def test_every_tool_has_exactly_one_group():
    grouped = [tool for group in GROUPS.values() for tool in group.tools]
    assert len(grouped) == len(set(grouped))
    assert set(mcp._tool_manager._tools) == set(grouped) | SUPPORT_TOOLS
    assert set(KEYWORDS) <= set(grouped)


def test_registry_lists_the_commands_each_tool_sends():
    for tool, group in TOOL_GROUPS.items():
        source = inspect.getsource(mcp._tool_manager._tools[tool].fn)
        literal = set(re.findall(r'bridge(?:_result)?\(\s*ctx,\s*"([a-z_.]+)"', source))
        assert literal <= set(GROUPS[group].tools[tool]), tool


@pytest.mark.asyncio
async def test_compact_advertises_a_small_surface_without_advanced_schemas(serve):
    async with serve("compact") as client:
        listed = await client.list_tools()
    assert sorted(tool.name for tool in listed.tools) == COMPACT_TOOLS
    wire = listed.model_dump_json(exclude_none=True, by_alias=True)
    assert len(wire) <= COMPACT_SCHEMA_BYTE_BUDGET, len(wire)
    for advanced in ("blender_python_exec", "blender_light_create", "check_duplicates", "spot_angle", "outputSchema"):
        assert advanced not in wire
    assert '"title"' not in wire


@pytest.mark.asyncio
async def test_full_profile_keeps_the_original_names_and_schemas(serve):
    async with serve("full") as client:
        listed = await client.list_tools()
    assert sorted(tool.name for tool in listed.tools) == sorted(f"blender_{name}" for name in LEGACY_TOOLS)
    for tool in listed.tools:
        registered = mcp._tool_manager.get_tool(tool.name)
        assert tool.inputSchema == registered.parameters
        assert tool.outputSchema == registered.output_schema


@pytest.mark.asyncio
async def test_standard_profile_and_enabled_groups(serve):
    async with serve("standard") as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
    assert "blender_mesh_inspect" in names and names >= DISCOVERY_TOOLS
    assert not {"blender_python_exec", "blender_keyframe_add"} & names
    assert OUTPUT_TOOL not in names  # standard output is not truncated
    async with serve("compact", enable=["lighting"]) as client:
        names = {tool.name for tool in (await client.list_tools()).tools}
        assert names == set(COMPACT_TOOLS) | set(GROUPS["lighting"].tools)
        assert not (await client.call_tool("blender_light_create", {})).isError


@pytest.mark.parametrize(
    ("argv", "environ", "profile", "advertised"),
    [
        ([], {}, "full", set(GROUPS)),
        ([], {"BLENDER_MCP_PROFILE": "compact", "BLENDER_MCP_ENABLE_GROUPS": "materials, "}, "compact", None),
        (["--profile", "standard"], {"BLENDER_MCP_PROFILE": "compact"}, "standard", None),
        (["--allow-groups", "scene"], {}, "full", {"core", "scene"}),
        ([], {"BLENDER_MCP_ALLOWED_GROUPS": ""}, "full", {"core"}),
    ],
)
def test_startup_configuration(argv, environ, profile, advertised):
    exposure = parse_exposure(argv, environ)
    assert exposure.profile == profile
    if advertised is not None:
        assert exposure.advertised == advertised
    elif profile == "compact":
        assert exposure.advertised == {"core", "materials"}


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (["--profile", "tiny"], "Unknown profile: tiny"),
        (["--enable-groups", "sculpting"], "Unknown capability group: sculpting"),
        (["--allow-groups", "scene,nope"], "Unknown capability group: nope"),
        (["--enable-groups", "scripting", "--allow-groups", "scene"], "not in the allowed groups: scripting"),
    ],
)
def test_invalid_startup_configuration_stops_the_server(argv, message, capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse_exposure(argv, {})
    assert exit_info.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.asyncio
async def test_direct_call_to_hidden_tool_is_refused_before_blender(serve, sent):
    async with serve("compact") as client:
        error = await _error(client, "blender_light_create")
    assert error["code"] == "tool_not_enabled"
    assert error["details"] == {"tool": "blender_light_create", "group": "lighting", "profile": "compact"}
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_discovery_tools_are_absent_from_a_full_server(serve):
    async with serve("full") as client:
        assert (await _error(client, "blender_capability_search"))["code"] == "tool_not_enabled"


@pytest.mark.asyncio
async def test_unknown_tool_is_reported(serve):
    async with serve("compact") as client:
        assert (await client.call_tool("blender_nope", {})).isError


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("bevel the edges of my sword", "blender_object_add_modifier"),
        ("check mesh topology for holes", "blender_mesh_inspect"),
        ("apply a pbr texture", "blender_material_set_texture"),
        ("add three point lighting", "blender_light_create"),
        ("export for unity", "blender_export_fbx"),
        ("animate a bouncing ball", "blender_keyframe_add"),
        ("save my project", "blender_project_save"),
        ("run a python script", "blender_python_exec"),
    ],
)
@pytest.mark.asyncio
async def test_search_ranks_the_relevant_action_first(serve, query, expected):
    async with serve("compact") as client:
        found = await _json(client, "blender_capability_search", query=query, limit=3)
    assert expected in [item["action"] for item in found["actions"]][:2]


@pytest.mark.asyncio
async def test_search_is_bounded_paginated_and_deterministic(serve):
    async with serve("compact") as client:
        overview = await _json(client, "blender_capability_search")
        assert [group["group"] for group in overview["groups"]] == list(GROUPS)
        pages, offset = [], 0
        while offset is not None:
            page = await _json(client, "blender_capability_search", group="scene", limit=5, offset=offset)
            assert len(page["actions"]) <= 5 and page["total"] == len(GROUPS["scene"].tools)
            pages.extend(item["action"] for item in page["actions"])
            offset = page["next_offset"]
        assert pages == list(GROUPS["scene"].tools)
        nothing = await _json(client, "blender_capability_search", query="quantum teapot")
        assert nothing["actions"] == [] and nothing["hint"]
        assert (await client.call_tool("blender_capability_search", {"limit": 500})).isError
        assert (await _error(client, "blender_capability_search", group="nope"))["code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_describe_returns_only_what_was_asked(serve, sent):
    async with serve("compact") as client:
        result = await client.call_tool("blender_capability_describe", {"actions": ["blender_mesh_inspect"]})
        entry = json.loads(result.content[0].text)["actions"][0]
        schema = await _json(client, "blender_capability_describe", actions=["blender_mesh_inspect"], detail="schema")
        too_many = await client.call_tool(
            "blender_capability_describe", {"actions": list(GROUPS["materials"].tools)[:4]}
        )
        missing = await _error(client, "blender_capability_describe", actions=["blender_nope"])
    assert entry["permissions"] == {"bridge_commands": ["mesh.inspect"], "allowed_by_server_policy": True}
    assert {"name": "name", "type": "string", "required": True} in entry["parameters"]
    assert {"name": "source", "type": "'raw' | 'evaluated'", "default": "raw"} in entry["parameters"]
    assert "light" not in result.content[0].text and len(result.content[0].text) < 1_500
    assert schema["actions"][0]["input_schema"]["required"] == ["name"]
    assert too_many.isError and missing["code"] == "not_found"
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_invocation_matches_a_direct_call(serve, sent):
    arguments = {"name": "Sword", "check_duplicates": True}
    async with serve("compact") as client:
        invoked = await _describe_and_invoke(client, "blender_mesh_inspect", arguments)
    invoked_call = sent.await_args.args
    async with serve("full") as client:
        direct = await client.call_tool("blender_mesh_inspect", arguments)
    assert sent.await_args.args == invoked_call
    assert json.loads(invoked.content[0].text) == json.loads(direct.content[0].text)
    assert invoked.structuredContent is None


@pytest.mark.asyncio
async def test_advertised_actions_can_be_invoked_without_describing(serve, sent):
    async with serve("compact") as client:
        await _json(client, "blender_capability_invoke", action="blender_scene_get_info")
    sent.assert_awaited_once_with("scene.get_info", {})


@pytest.mark.asyncio
async def test_discovery_is_required_per_session_and_can_be_reset(serve, sent):
    call = {"action": "blender_material_create", "arguments": {"name": "Steel"}}
    async with serve("compact") as first, create_connected_server_and_client_session(mcp) as second:
        assert (await _error(first, "blender_capability_invoke", **call))["code"] == "discovery_required"
        await _json(first, "blender_capability_describe", actions=["blender_material_create", "blender_light_create"])
        await _json(first, "blender_capability_invoke", **call)
        # Another session has discovered nothing.
        assert (await _error(second, "blender_capability_invoke", **call))["code"] == "discovery_required"
        reset = await _json(first, "blender_capability_reset", group="materials")
        assert reset == {"forgotten": ["blender_material_create"], "still_described": ["blender_light_create"]}
        assert (await _error(first, "blender_capability_invoke", **call))["code"] == "discovery_required"
        assert (await _json(first, "blender_capability_reset"))["still_described"] == []
    # Discovery and reset never reach Blender: only the one authorized invocation did.
    sent.assert_awaited_once_with("material.create", {"name": "Steel"})


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({}, "name: Field required"),
        ({"name": "Cube", "max_ids": "lots"}, "max_ids:"),
        ({"name": "Cube", "check_duplicate": True}, "no parameter named 'check_duplicate'"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_invocation_arguments_are_explained(serve, sent, arguments, message):
    async with serve("compact") as client:
        result = await _describe_and_invoke(client, "blender_mesh_inspect", arguments)
    assert result.isError and result.structuredContent["error"]["code"] == "invalid_arguments"
    assert message in result.content[0].text and "lots" not in result.content[0].text
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatcher_cannot_call_itself(serve):
    async with serve("compact") as client:
        error = await _error(client, "blender_capability_invoke", action="blender_capability_invoke")
    assert error["code"] == "not_found"


@pytest.mark.asyncio
async def test_disallowed_groups_cannot_be_discovered_invoked_or_batched(serve, sent):
    async with serve("compact", allow=["scene", "modeling"]) as client:
        overview = await _json(client, "blender_capability_search")
        assert [group["group"] for group in overview["groups"]] == ["core", "scene", "modeling"]
        assert (await _json(client, "blender_capability_search", query="run python script"))["actions"] == []
        for tool, arguments in [
            ("blender_capability_search", {"group": "scripting"}),
            ("blender_capability_describe", {"actions": ["blender_python_exec"]}),
            ("blender_capability_invoke", {"action": "blender_python_exec", "arguments": {"code": "pass"}}),
            ("blender_python_exec", {"code": "pass"}),
        ]:
            assert (await _error(client, tool, **arguments))["code"] == "permission_denied", tool
        batch = {"commands": [{"command": "scene.get_info"}, {"command": "light.create", "params": {}}]}
        invoked = await _describe_and_invoke(client, "blender_scene_execute_batch", batch)
        assert invoked.structuredContent["error"]["code"] == "permission_denied"
    sent.assert_not_awaited()
    async with serve("full", allow=["scene"]) as client:
        assert (await _error(client, "blender_scene_execute_batch", **batch))["code"] == "permission_denied"
    sent.assert_not_awaited()


@pytest.mark.parametrize("profile", ["compact", "full"])
@pytest.mark.asyncio
async def test_no_profile_bypasses_policy(serve, sent, monkeypatch, tmp_path, profile):
    policy_file = tmp_path / "policy.json"
    policy_file.write_text(json.dumps({"allow_python": False, "allowed_commands": ["scene.get_info"]}))
    monkeypatch.setenv("BLENDER_MCP_POLICY_FILE", str(policy_file))
    async with serve(profile) as client:
        for action, arguments in [
            ("blender_python_exec", {"code": "pass"}),
            ("blender_material_create", {"name": "M"}),
        ]:
            if profile == "compact":
                described = await _json(client, "blender_capability_describe", actions=[action])
                assert described["actions"][0]["permissions"]["allowed_by_server_policy"] is False
                result = await client.call_tool("blender_capability_invoke", {"action": action, "arguments": arguments})
            else:
                result = await client.call_tool(action, arguments)
            assert result.structuredContent["error"]["code"] == "permission_denied"
    sent.assert_not_awaited()


@pytest.mark.asyncio
async def test_compact_results_are_one_copy_of_unindented_json(serve):
    async with serve("compact") as client:
        compact = await client.call_tool("blender_scene_get_info", {})
    async with serve("full") as client:
        full = await client.call_tool("blender_scene_get_info", {})
    assert compact.structuredContent is None
    assert compact.content[0].text == '{"name":"Scene","value":[1,2]}'
    assert full.structuredContent == {"result": full.content[0].text}
    assert "\n" in full.content[0].text


@pytest.fixture
def live_status(sent):
    commands = [f"area.command_{index}" for index in range(60)]
    sent.return_value = {
        "blender_version": "5.1.1",
        "bridge_version": "0.2.0",
        "generation": "abc",
        "main_thread_progress": True,
        "queue_depth": 0,
        "oldest_queue_age_seconds": None,
        "active_request": None,
        "commands": commands,
        "policy": {"local_restrictions": False},
    }


@pytest.mark.asyncio
async def test_status_is_summarized_only_in_compact_unless_asked(serve, live_status):
    async with serve("compact") as client:
        summary = await client.call_tool("blender_status", {})
        detailed = await _json(client, "blender_status", detail="full")
    body = json.loads(summary.content[0].text)
    assert body["capabilities"] == {
        "profile": "compact",
        "advertised_groups": ["core"],
        "on_demand_groups": sorted(set(GROUPS) - {"core"}),
        "advertised_tool_count": len(COMPACT_TOOLS),
    }
    assert body["bridge"]["command_count"] == 60 and body["bridge"]["local_restrictions"] is False
    assert "area.command_1" not in summary.content[0].text and len(summary.content[0].text) < 900
    assert detailed["mcp_tools"] == COMPACT_TOOLS and len(detailed["bridge"]["commands"]) == 60
    async with serve("full") as client:
        legacy = await _json(client, "blender_status")
    assert legacy["profile"] == "full" and len(legacy["mcp_tools"]) == len(LEGACY_TOOLS)
