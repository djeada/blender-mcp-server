"""Bounded access to the packaged guides as tools, resources and a prompt."""

import json
from typing import Annotated, Any, Literal

from pydantic import Field

from blender_mcp_server import knowledge
from blender_mcp_server.app import mcp
from blender_mcp_server.search import matching_words, rank
from blender_mcp_server.shared import protocol
from blender_mcp_server.tools.recipes import search_recipes

Style = Literal["lowpoly", "stylized", "realistic"]
Target = Literal["render", "game"]
MAX_GUIDE_RESULTS = 10
MAX_MATCHED_SECTIONS = 3
MAX_RELATED_RECIPES = 3


def _guide(guide_id: str) -> knowledge.Guide:
    guide = knowledge.guides().get(guide_id)
    if guide is None:
        raise protocol.BridgeError("not_found", "Unknown guide; use blender_guide_search to find guide IDs")
    return guide


def _section(guide: knowledge.Guide, section: str) -> knowledge.Section:
    found = guide.sections.get(section)
    if found is None:
        raise protocol.BridgeError("not_found", f"Unknown section. This guide has: {', '.join(guide.sections)}")
    return found


def _index() -> dict[str, Any]:
    domains: dict[str, list[dict]] = {}
    for guide in knowledge.guides().values():
        domains.setdefault(guide.domain, []).append({"id": guide.id, "title": guide.title})
    return {"library_version": knowledge.workflows()["version"], "domains": domains}


def _staged_guides(stage: str | None, style: str | None, target: str | None) -> set[str] | None:
    """Guides that workflow stages use, after the filters. None means no filter was asked for."""
    if stage is None and style is None and target is None:
        return None
    flows = knowledge.workflows()["workflows"]
    stage_ids = sorted({item["id"] for flow in flows for item in flow["stages"]})
    if stage is not None and stage not in stage_ids:
        raise protocol.InvalidArgumentsError(f"Unknown stage. Choose from: {', '.join(stage_ids)}")
    return {
        link.split("#")[0]
        for flow in flows
        for item in flow["stages"]
        if stage in (None, item["id"])
        and (style is None or style in item.get("styles", [style]))
        and (target is None or target in item.get("targets", [target]))
        for link in item["guides"]
    }


def _matched_sections(guide: knowledge.Guide, query: str) -> list[str]:
    """Sections that mention the query's words, so a client can fetch just those."""
    counts = {section.id: len(matching_words(query, section.text)) for section in guide.sections.values()}
    best = sorted((name for name, count in counts.items() if count), key=lambda name: -counts[name])
    return best[:MAX_MATCHED_SECTIONS]


def search_guides(query: str, domain: str | None = None) -> list[str]:
    documents = {
        guide.id: [
            (5, f"{guide.id.replace('-', ' ')} {guide.title}"),
            (4, " ".join(guide.tags)),
            (2, guide.summary),
        ]
        for guide in knowledge.guides().values()
        if domain in (None, guide.domain)
    }
    return [guide_id for guide_id, _ in rank(query, documents)]


@mcp.tool(
    name="blender_guide_search",
    description=(
        "Find modeling, surfacing and rigging guides. With no arguments, returns the index by domain. With task words "
        "such as 'orc', 'sword blade' or 'house walls', returns guide IDs, summaries, matching section IDs and related "
        "recipe IDs. Filter by domain, workflow stage, style or target."
    ),
)
async def guide_search(
    query: str | None = None,
    domain: str | None = None,
    stage: str | None = None,
    style: Style | None = None,
    target: Target | None = None,
    limit: Annotated[int, Field(ge=1, le=MAX_GUIDE_RESULTS)] = 5,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    known = sorted({guide.domain for guide in knowledge.guides().values()})
    if domain is not None and domain not in known:
        raise protocol.InvalidArgumentsError(f"Unknown domain. Choose from: {', '.join(known)}")
    staged = _staged_guides(stage, style, target)
    if query is None and domain is None and staged is None:
        return _index()
    candidates = (
        search_guides(query, domain)
        if query is not None
        else [guide.id for guide in knowledge.guides().values() if domain in (None, guide.domain)]
    )
    matches = [guide_id for guide_id in candidates if staged is None or guide_id in staged]
    page = matches[offset : offset + limit]
    cards = []
    for guide_id in page:
        guide = _guide(guide_id)
        card: dict[str, Any] = {"id": guide.id, "title": guide.title, "summary": guide.summary}
        if query is not None and (sections := _matched_sections(guide, query)):
            card["matched_sections"] = sections
        cards.append(card)
    result: dict[str, Any] = {
        "guides": cards,
        "total": len(matches),
        "next_offset": offset + len(page) if offset + len(page) < len(matches) else None,
    }
    if query is not None and offset == 0 and (recipes := search_recipes(query)):
        result["related_recipes"] = recipes[:MAX_RELATED_RECIPES]
    return result


@mcp.tool(
    name="blender_guide_get",
    description=(
        "Read a guide. Without 'section', returns its card with the section IDs. Pass a section ID such as "
        "'pattern', 'pitfalls' or 'checks' for that part only, or 'all' for the whole guide."
    ),
)
async def guide_get(guide: str, section: str | None = None) -> dict[str, Any]:
    found = _guide(guide)
    base = {"guide": found.id, "version": found.version}
    if section == "all":
        return {**base, "markdown": found.markdown}
    if section is not None:
        part = _section(found, section)
        return {**base, "section": part.id, "heading": part.heading, "markdown": part.text}
    return {
        **base,
        "title": found.title,
        "summary": found.summary,
        "domain": found.domain,
        "sections": [{"id": part.id, "chars": len(part.text)} for part in found.sections.values()],
        "related": list(found.related),
    }


@mcp.tool(
    name="blender_workflow",
    description=(
        "Get a stage-by-stage plan for a task such as 'low poly orc for a game'. Returns the stage list and only the "
        "current stage in detail: goal, guide sections, actions and checkpoint. Pass 'stage' to move on."
    ),
)
async def workflow(
    task: Annotated[str, Field(min_length=1, max_length=500)],
    style: Style | None = None,
    target: Target | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    plan = knowledge.select_workflow(task, style, target)
    stages = plan.pop("stages")
    ids = [item["id"] for item in stages]
    if stage is not None and stage not in ids:
        raise protocol.InvalidArgumentsError(f"This plan has no stage '{stage}'. Stages: {', '.join(ids)}")
    position = ids.index(stage) if stage is not None else 0
    current = {key: value for key, value in stages[position].items() if key not in {"styles", "targets"}}
    return {
        **plan,
        "stage_ids": ids,
        "current": current,
        "next_stage": ids[position + 1] if position + 1 < len(ids) else None,
    }


@mcp.resource("blender://guides", name="guide-index", mime_type="application/json", description="Modeling guide index")
def guide_index_resource() -> str:
    return json.dumps(_index(), separators=(",", ":"))


@mcp.resource(
    "blender://guides/{guide_id}", name="guide", mime_type="text/markdown", description="One complete modeling guide"
)
def guide_resource(guide_id: str) -> str:
    return _guide(guide_id).markdown


@mcp.resource(
    "blender://guides/{guide_id}/{section}",
    name="guide-section",
    mime_type="text/markdown",
    description="One section of a modeling guide",
)
def guide_section_resource(guide_id: str, section: str) -> str:
    part = _section(_guide(guide_id), section)
    return f"## {part.heading}\n\n{part.text}"


@mcp.prompt(name="blender_modeling_workflow", description="Start a modeling task with a suitable staged workflow.")
def modeling_workflow_prompt(task: str, style: str = "", target: str = "") -> str:
    plan = knowledge.select_workflow(task, style or None, target or None)
    first = plan["stages"][0]
    outline = " -> ".join(stage["id"] for stage in plan["stages"])
    return (
        f"Task: {task}\n"
        f"Suggested workflow: {plan['title']} ({plan['style']}, for {plan['target']}): {outline}.\n"
        f"Start with '{first['id']}': {first['goal']} Done when: {first['checkpoint']}\n"
        f"Guide sections: {', '.join(first['guides'])} (read with blender_guide_get).\n"
        "Work one stage at a time, check each checkpoint with blender_mesh_inspect or blender_view_capture, and get "
        "the next stage from blender_workflow. Adapt the plan when the task calls for it."
    )
