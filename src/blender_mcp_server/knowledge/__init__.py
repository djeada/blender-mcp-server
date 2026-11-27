"""The packaged modeling guides and workflows, readable offline.

Guides are Markdown files with a JSON header. Each '##' heading is a section that can be
retrieved on its own. Nothing here needs Blender, a network or a language model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

from blender_mcp_server.search import words

_HEADER = re.compile(r"\A<!--\s*(\{.*?\})\s*-->\s*", re.DOTALL)


@dataclass(frozen=True)
class Section:
    id: str
    heading: str
    text: str


@dataclass(frozen=True)
class Guide:
    id: str
    version: int
    domain: str
    title: str
    summary: str
    tags: tuple[str, ...]
    related: tuple[str, ...]
    sections: dict[str, Section]
    markdown: str

    def python_blocks(self) -> list[str]:
        return re.findall(r"^```python\n(.*?)^```$", self.markdown, re.DOTALL | re.MULTILINE)


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def parse_guide(guide_id: str, source: str) -> Guide:
    header = _HEADER.match(source)
    if header is None:
        raise ValueError(f"Guide {guide_id} has no JSON header")
    metadata = json.loads(header.group(1))
    markdown = source[header.end() :]
    sections: dict[str, Section] = {}
    heading: str | None = None
    lines: list[str] = []
    fenced = False

    def close():
        if heading is not None:
            slug = _slug(heading)
            if slug in sections:
                raise ValueError(f"Guide {guide_id} repeats the section {slug}")
            sections[slug] = Section(slug, heading, "\n".join(lines).strip())

    for line in markdown.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        if line.startswith("## ") and not fenced:
            close()
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    close()
    return Guide(
        guide_id,
        metadata["version"],
        metadata["domain"],
        metadata["title"],
        metadata["summary"],
        tuple(metadata["tags"]),
        tuple(metadata["related"]),
        sections,
        markdown,
    )


@cache
def guides() -> dict[str, Guide]:
    directory = files(__name__) / "guides"
    names = sorted(entry.name for entry in directory.iterdir() if entry.name.endswith(".md"))
    return {name[:-3]: parse_guide(name[:-3], (directory / name).read_text(encoding="utf-8")) for name in names}


@cache
def workflows() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((files(__name__) / "workflows.json").read_text(encoding="utf-8"))
    return data


def _detect(task: str, table: dict[str, list[str]]) -> str | None:
    text = f" {re.sub(r'[^a-z0-9]+', ' ', task.lower())} "
    for name, phrases in table.items():
        if any(f" {re.sub(r'[^a-z0-9]+', ' ', phrase)} " in text for phrase in phrases):
            return name
    return None


# The workflow used when nothing in a domain matches the task.
FALLBACKS = {"modeling": "general", "surfacing": "general-surfacing", "lighting": "general-lighting"}


def _mentions(task: str, phrases: list[str]) -> bool:
    return _detect(task, {"found": phrases}) is not None


def _best(domain: str, terms: set[str]) -> tuple[int, dict]:
    flows = [flow for flow in workflows()["workflows"] if flow["domain"] == domain]
    scored = [
        (sum(1 for keyword in flow["keywords"] if words(keyword) and words(keyword) <= terms), -index, flow)
        for index, flow in enumerate(flows)
    ]
    score, _, flow = max(scored, key=lambda item: item[:2])
    return score, flow


def _choose_domain(task: str, terms: set[str]) -> str:
    """Modeling verbs win; otherwise lighting or surfacing words; a bare material is surfacing."""
    table = workflows()["domain_words"]
    if _mentions(task, table["modeling_verbs"]):
        return "modeling"
    if _mentions(task, table["lighting"]):
        return "lighting"
    if _mentions(task, table["surfacing"]):
        return "surfacing"
    # 'realistic wood' is about a surface, while 'wood cabin' names something to model.
    if _mentions(task, table["material_nouns"]) and _best("modeling", terms)[0] == 0:
        return "surfacing"
    return "modeling"


def select_workflow(
    task: str, style: str | None = None, target: str | None = None, domain: str | None = None
) -> dict[str, Any]:
    """Choose a workflow by keyword and filter its stages for the style and target. Deterministic."""
    data = workflows()
    for value, key in ((style, "styles"), (target, "targets"), (domain, "domains")):
        if value is not None and value not in data[key]:
            raise ValueError(f"Unknown {key[:-1]} '{value}'. Choose from: {', '.join(data[key])}")
    terms = words(task)
    domain = domain or _choose_domain(task, terms)
    score, flow = _best(domain, terms)
    if score == 0:
        flow = next(item for item in data["workflows"] if item["id"] == FALLBACKS[domain])
    style = style or _detect(task, data["style_words"]) or flow["default_style"]
    target = target or _detect(task, data["target_words"]) or "render"
    return {
        "domain": domain,
        "workflow": flow["id"],
        "title": flow["title"],
        "summary": flow["summary"],
        "matched": score > 0,
        "style": style,
        "target": target,
        "stages": [
            stage
            for stage in flow["stages"]
            if style in stage.get("styles", [style]) and target in stage.get("targets", [target])
        ],
    }
