"""The packaged guides: structure, links, discovery, bounds and MCP access. No Blender needed."""

import contextlib
import json
from unittest.mock import AsyncMock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from blender_mcp_server import knowledge
from blender_mcp_server.app import mcp
from blender_mcp_server.capabilities import GROUPS, TOOL_GROUPS, Exposure
from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.server import main  # noqa: F401  (importing registers every tool)
from blender_mcp_server.tools.knowledge import search_guides

REQUIRED_TOPICS = {
    "box-modeling",
    "organic-modeling",
    "base-mesh-deformation",
    "sculpting-remeshing",
    "retopology",
    "hard-surface",
    "curves",
    "geometry-nodes",
    "modular-modeling",
    "anatomy-proportions",
    "uv-unwrapping",
    "pbr-materials",
    "rigging",
    "game-optimization",
}
SECTIONS = {"use-when", "avoid-when", "tradeoffs", "pattern", "pitfalls", "checks"}


def test_every_required_topic_has_every_part():
    guides = knowledge.guides()
    assert set(guides) >= REQUIRED_TOPICS | {"bridge-scripting"}
    for guide in guides.values():
        assert set(guide.sections) >= SECTIONS, guide.id
        assert guide.version >= 1 and guide.title and len(guide.summary) <= 160
        assert guide.python_blocks(), f"{guide.id} has no tested pattern"
        assert all(section.text for section in guide.sections.values()), guide.id
        assert set(guide.related) <= set(guides), guide.id
        for block in guide.python_blocks():
            compile(block, guide.id, "exec")


def test_guides_stay_small_enough_to_load_one_at_a_time():
    for guide in knowledge.guides().values():
        assert len(guide.markdown) <= 7_000, guide.id
        assert all(len(section.text) <= 4_000 for section in guide.sections.values()), guide.id


def test_guides_only_mention_tools_that_exist():
    import re

    # Names that look like tools but are prose or placeholders.
    for guide in knowledge.guides().values():
        for name in re.findall(r"`(blender_[a-z_]+)", guide.markdown):
            assert name in TOOL_GROUPS, f"{guide.id} mentions unknown tool {name}"


def test_workflow_links_resolve():
    data = knowledge.workflows()
    ids = [flow["id"] for flow in data["workflows"]]
    assert len(ids) == len(set(ids)) and "general" in ids
    for flow in data["workflows"]:
        assert flow["default_style"] in data["styles"]
        stage_ids = [stage["id"] for stage in flow["stages"]]
        assert len(stage_ids) == len(set(stage_ids)), flow["id"]
        for stage in flow["stages"]:
            assert stage["goal"] and stage["checkpoint"]
            assert set(stage.get("styles", data["styles"])) <= set(data["styles"])
            assert set(stage.get("targets", data["targets"])) <= set(data["targets"])
            assert set(stage["actions"]) <= set(TOOL_GROUPS), (flow["id"], stage["id"])
            for link in stage["guides"]:
                guide, section = link.split("#")
                assert section in knowledge.guides()[guide].sections, link
        for style in data["styles"]:
            for target in data["targets"]:
                assert knowledge.select_workflow(flow["title"], style, target)["stages"]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("orc", {"anatomy-proportions", "organic-modeling"}),
        ("sword", {"hard-surface", "box-modeling", "curves"}),
        ("house", {"modular-modeling", "box-modeling"}),
    ],
)
def test_a_subject_finds_its_guides_without_loading_the_library(query, expected):
    found = search_guides(query)
    assert expected <= set(found[: len(expected) + 1]), found
    assert len(found) < len(knowledge.guides()) / 2


@pytest.mark.parametrize(
    ("task", "workflow", "style", "target"),
    [
        ("Make a low poly orc for my Unity game", "creature", "lowpoly", "game"),
        ("a photorealistic dragon for a film still", "creature", "realistic", "render"),
        ("model a sword", "weapon-prop", "stylized", "render"),
        ("cartoon houses for a mobile game", "building", "stylized", "game"),
        ("a robot arm machine", "hard-surface-prop", "realistic", "render"),
        ("something abstract", "general", "stylized", "render"),
    ],
)
def test_workflow_selection_is_deterministic(task, workflow, style, target):
    plan = knowledge.select_workflow(task)
    assert (plan["workflow"], plan["style"], plan["target"]) == (workflow, style, target)
    assert plan == knowledge.select_workflow(task)
    assert plan["matched"] is (workflow != "general")


def _stages(task, **options):
    return [stage["id"] for stage in knowledge.select_workflow(task, **options)["stages"]]


def test_style_and_target_choose_the_techniques():
    lowpoly = _stages("orc", style="lowpoly", target="game")
    realistic = _stages("orc", style="realistic", target="render")
    assert {"high-detail", "retopology"}.isdisjoint(lowpoly) and "delivery" in lowpoly
    assert {"high-detail", "retopology"} <= set(realistic) and "delivery" not in realistic
    sculpt = next(s for s in knowledge.select_workflow("orc", "realistic")["stages"] if s["id"] == "high-detail")
    assert sculpt["optional"] is True  # sculpting is never mandatory
    with pytest.raises(ValueError, match="Unknown style"):
        knowledge.select_workflow("orc", style="baroque")


@pytest.fixture
def serve(monkeypatch):
    send = AsyncMock(side_effect=AssertionError("knowledge must not need Blender"))
    monkeypatch.setattr(BlenderConnection, "send_command", send)

    @contextlib.asynccontextmanager
    async def connect(profile):
        monkeypatch.setattr(mcp, "exposure", Exposure.create(profile))
        mcp._mcp_server._tool_cache.clear()
        async with create_connected_server_and_client_session(mcp) as client:
            await client.list_tools()
            yield client

    return connect


async def _text(client, tool, arguments, limit=8_000):
    result = await client.call_tool(tool, arguments)
    assert not result.isError, result.content[0].text
    assert len(result.content[0].text.encode()) <= limit, (tool, arguments)
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_guides_through_tools_with_bounded_responses(serve):
    async with serve("standard") as client:
        index = await _text(client, "blender_guide_search", {}, 2_000)
        assert sum(len(items) for items in index["domains"].values()) == len(knowledge.guides())
        found = await _text(client, "blender_guide_search", {"query": "orc", "limit": 3}, 1_000)
        assert [item["id"] for item in found["guides"]] == search_guides("orc")[:3]
        assert "markdown" not in json.dumps(found)
        paged = await _text(client, "blender_guide_search", {"domain": "modeling", "limit": 4}, 1_500)
        assert paged["next_offset"] == 4 and paged["total"] > 4
        for guide in knowledge.guides().values():
            card = await _text(client, "blender_guide_get", {"guide": guide.id}, 1_200)
            assert {section["id"] for section in card["sections"]} == set(guide.sections)
        pattern = await _text(client, "blender_guide_get", {"guide": "box-modeling", "section": "pattern"}, 3_000)
        assert "extrude_face_region" in pattern["markdown"] and "## Pitfalls" not in pattern["markdown"]
        for arguments in ({"guide": "nope"}, {"guide": "curves", "section": "nope"}):
            result = await client.call_tool("blender_guide_get", arguments)
            assert result.structuredContent["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_a_compact_client_gets_one_orc_stage_at_a_time(serve):
    async with serve("compact") as client:
        await client.call_tool("blender_capability_describe", {"actions": ["blender_workflow"]})

        async def stage(**arguments):
            return await _text(
                client,
                "blender_capability_invoke",
                {"action": "blender_workflow", "arguments": {"task": "low poly orc for a game", **arguments}},
                1_200,
            )

        first = await stage()
        assert first["current"]["id"] == "proportions" and first["next_stage"] == "blockout"
        blockout = await stage(stage="blockout")
    assert blockout["current"]["guides"] == ["organic-modeling#pattern", "organic-modeling#pitfalls"]
    assert "rigging#pattern" not in json.dumps(blockout) and "uv-unwrapping" not in json.dumps(blockout)


@pytest.mark.asyncio
async def test_resources_and_prompt(serve):
    async with serve("compact") as client:
        resources = (await client.list_resources()).resources
        assert [str(resource.uri) for resource in resources] == ["blender://guides"]
        templates = (await client.list_resource_templates()).resourceTemplates
        assert sorted(template.uriTemplate for template in templates) == [
            "blender://guides/{guide_id}",
            "blender://guides/{guide_id}/{section}",
        ]
        index = json.loads((await client.read_resource("blender://guides")).contents[0].text)
        assert index["library_version"] == 1
        whole = (await client.read_resource("blender://guides/rigging")).contents[0]
        assert whole.mimeType == "text/markdown" and whole.text == knowledge.guides()["rigging"].markdown
        section = (await client.read_resource("blender://guides/rigging/checks")).contents[0]
        assert section.text.startswith("## Checks")
        with pytest.raises(Exception, match="rror"):
            await client.read_resource("blender://guides/missing")
        prompts = (await client.list_prompts()).prompts
        assert [prompt.name for prompt in prompts] == ["blender_modeling_workflow"]
        prompt = await client.get_prompt("blender_modeling_workflow", {"task": "a sword"})
    text = prompt.messages[0].content.text
    assert "Weapon or hand-held prop" in text and len(text) < 900


def test_knowledge_group_needs_no_bridge_commands():
    assert all(commands == () for commands in GROUPS["knowledge"].tools.values())
