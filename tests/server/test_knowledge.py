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
from blender_mcp_server.recipes import catalog
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
            assert set(stage.get("recipes", [])) <= set(catalog()), (flow["id"], stage["id"])
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
        assert index["library_version"] == knowledge.workflows()["version"] == 3
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


@pytest.mark.asyncio
async def test_search_points_to_exact_sections_and_recipes(serve):
    async with serve("standard") as client:
        found = await _text(client, "blender_guide_search", {"query": "voxel remesh", "limit": 2}, 1_200)
        first = found["guides"][0]
        assert first["id"] == "sculpting-remeshing" and "pattern" in first["matched_sections"]
        assert len(first["matched_sections"]) <= 3
        scatter = await _text(client, "blender_guide_search", {"query": "scatter trees"}, 2_000)
        assert "scatter-objects" in scatter["related_recipes"] and len(scatter["related_recipes"]) <= 3


@pytest.mark.asyncio
async def test_search_filters_by_stage_style_and_target(serve):
    async with serve("standard") as client:

        async def ids(**arguments):
            found = await _text(client, "blender_guide_search", {"limit": 10, **arguments})
            return {guide["id"] for guide in found["guides"]}, found

        uvs, _ = await ids(stage="uvs")
        assert uvs == {"uv-unwrapping"}
        lowpoly, _ = await ids(query="creature", style="lowpoly")
        realistic, _ = await ids(query="creature", style="realistic")
        assert "retopology" not in lowpoly and {"sculpting-remeshing", "retopology"} & realistic
        first, found = await ids(style="stylized", limit=4)
        assert found["total"] > 4 and found["next_offset"] == 4
        second, _ = await ids(style="stylized", limit=4, offset=4)
        assert not first & second
        result = await client.call_tool("blender_guide_search", {"stage": "nope"})
        assert result.structuredContent["error"]["code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_compact_orc_blockout_comes_with_recipe_ids_and_no_other_documents(serve):
    async with serve("compact") as client:
        await client.call_tool("blender_capability_describe", {"actions": ["blender_workflow"]})
        result = await client.call_tool(
            "blender_capability_invoke",
            {"action": "blender_workflow", "arguments": {"task": "orc blockout", "stage": "blockout"}},
        )
    text = result.content[0].text
    assert len(text) < 1_000 and json.loads(text)["current"]["recipes"] == ["create-mesh"]
    for unrelated in ("anatomy-proportions", "uv-unwrapping", "rigging#", "light", "markdown"):
        assert unrelated not in text


def test_default_resources_and_prompts_are_small():
    for flow in knowledge.workflows()["workflows"]:
        from blender_mcp_server.tools.knowledge import modeling_workflow_prompt

        assert len(modeling_workflow_prompt(flow["title"], target="game")) < 1_000


TEXTURING_TOPICS = {
    "stylized-texturing",
    "procedural-materials",
    "texture-mapping",
    "material-layering",
    "organic-surfaces",
    "hard-materials",
    "texture-pipeline",
}
LIGHTING_TOPICS = {
    "lighting-fundamentals",
    "lighting-mood",
    "environment-lighting",
    "lighting-exposure",
    "lighting-composition",
    "lighting-diagnosis",
    "render-engines",
}


def test_texturing_and_lighting_topics_are_packaged():
    assert set(knowledge.guides()) >= TEXTURING_TOPICS | LIGHTING_TOPICS
    assert {knowledge.guides()[name].domain for name in LIGHTING_TOPICS} == {"lighting"}


@pytest.mark.parametrize(
    ("task", "workflow", "unrelated"),
    [
        ("texture a stylized orc", "character-surfacing", ("hard-materials", "lighting-", "anatomy-proportions")),
        ("rusty metal prop", "metal-surfacing", ("organic-surfaces", "lighting-mood", "rigging")),
        ("realistic wood", "wood-surfacing", ("organic-surfaces", "material-layering", "rigging")),
        ("light an orc portrait", "portrait-lighting", ("hard-materials", "interior", "uv-unwrapping")),
        ("light a metal prop", "product-lighting", ("organic-surfaces", "uv-unwrapping", "rigging")),
        ("light a night interior", "night-lighting", ("organic-surfaces", "uv-unwrapping", "rigging")),
    ],
)
def test_surfacing_and_lighting_tasks_get_distinct_small_stages(task, workflow, unrelated):
    plan = knowledge.select_workflow(task)
    assert plan["workflow"] == workflow and plan["matched"]
    first = json.dumps(plan["stages"][0])
    assert len(first) < 700
    assert not [name for name in unrelated if name in first]


def test_domains_keep_modeling_requests_unchanged():
    for task, workflow in [
        ("model a wooden chair", "hard-surface-prop"),
        ("wood cabin", "building"),
        ("sword", "weapon-prop"),
        ("rig a creature", "creature"),
    ]:
        assert knowledge.select_workflow(task)["workflow"] == workflow, task
    assert knowledge.select_workflow("sword", domain="surfacing")["workflow"] == "general-surfacing"
    assert knowledge.select_workflow("sword", domain="lighting")["workflow"] == "general-lighting"
    with pytest.raises(ValueError, match="Unknown domain"):
        knowledge.select_workflow("sword", domain="animation")


@pytest.mark.parametrize(
    ("symptom", "expected"),
    [
        ("flat lighting", "lighting-diagnosis"),
        ("crushed shadows", "lighting-diagnosis"),
        ("blown highlights", "lighting-diagnosis"),
        ("noisy render", "render-engines"),
        ("glare on glossy surface", "lighting-diagnosis"),
    ],
)
def test_symptoms_find_corrective_guidance(symptom, expected):
    assert expected in search_guides(symptom)[:2]


def test_every_lighting_symptom_has_a_first_change():
    table = knowledge.guides()["lighting-diagnosis"].sections["tradeoffs"].text.lower()
    for symptom in ("flat", "crushed shadows", "blown highlights", "noisy", "washed out", "glare", "scale"):
        assert symptom in table, symptom
    assert "one variable at a time" in table


def test_lighting_examples_never_hardcode_power():
    """Light power depends on distance and scale, so examples must compute it."""
    import re

    for guide in knowledge.guides().values():
        for block in guide.python_blocks():
            assert not re.search(r"\.energy\s*=\s*[0-9.]+\s*(#.*)?$", block, re.MULTILINE), guide.id
    units = knowledge.guides()["lighting-fundamentals"].sections["tradeoffs"].text
    assert "P / (4πd²)" in units and "P / (πd²)" in units and "W/m²" in units


def test_procedural_texturing_guides_state_the_gltf_limit():
    for name in sorted(TEXTURING_TOPICS | {"pbr-materials"}):
        guide = knowledge.guides()[name]
        if any("ShaderNodeTex" in block for block in guide.python_blocks()):
            assert "glTF" in guide.markdown and ("not export" in guide.markdown or "do not export" in guide.markdown), (
                name
            )


def test_knowledge_group_needs_no_bridge_commands():
    assert all(commands == () for commands in GROUPS["knowledge"].tools.values())
