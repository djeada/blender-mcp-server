# Modeling knowledge and workflows

The server ships short modeling, surfacing and rigging guides so that a model can choose a technique instead of guessing. They are part of the installed package and work offline, without Blender and without calling any language model.

## Get only what the task needs

1. `blender_workflow(task="low poly orc for a game")` picks a workflow and returns its stage IDs plus the **first stage only**: a goal, the guide sections to read, the tools to use and a checkpoint. Pass `stage` to get another.
2. `blender_guide_get(guide="organic-modeling", section="pattern")` reads one section.
3. `blender_guide_search(query="sword blade")` finds guides by task words. With no query it returns the index.

`blender_guide_get(guide)` without a section returns a card with the section IDs. Every guide has `use-when`, `avoid-when`, `tradeoffs`, `pattern`, `pitfalls` and `checks`. `section="all"` returns the whole guide, which is under 7,000 characters.

These tools form the `knowledge` group. `standard` and `full` advertise them. In the `compact` profile, reach them through [discovery](profiles.md#use-actions-that-are-not-advertised).

## Resources and prompt

| MCP item | Content |
|---|---|
| Resource `blender://guides` | JSON index by domain |
| Template `blender://guides/{guide_id}` | One guide as Markdown |
| Template `blender://guides/{guide_id}/{section}` | One section |
| Prompt `blender_modeling_workflow` | A short start for a task: the chosen workflow and its first stage |

Nothing is loaded automatically. Clients that ignore resources can use the tools.

## How a workflow is chosen

Selection is keyword matching with fixed rules, so the same words give the same plan. The task picks `creature`, `weapon-prop`, `building` or `hard-surface-prop`; anything else gets `general`, and `matched` is `false`. Style (`lowpoly`, `stylized`, `realistic`) and target (`render`, `game`) come from the arguments, then from words in the task, then from defaults. They decide which stages apply. For example, only a realistic creature gets the high-detail and retopology stages, high detail is marked optional, and only game targets get a delivery stage. Treat a plan as a suggestion.

## Writing guides

Guides live in `src/blender_mcp_server/knowledge/guides/`. Each is Markdown with a JSON header (`version`, `domain`, `title`, `summary`, `tags`, `related`), and `##` headings become section IDs. Increase `version` when the advice changes. Workflows live in `workflows.json`.

Tests check the headers, sections, links, tool names and sizes. Every `python` block runs through the real bridge in the integration suite, and any mesh it creates must pass `blender_mesh_inspect` without errors or warnings. Examples must work on every [supported Blender version](compatibility.md), so test for attributes where APIs differ.
