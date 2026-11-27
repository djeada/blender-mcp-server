"""List, inspect and run reviewed recipes by ID."""

from typing import Annotated, Any

from mcp.server.fastmcp import Context
from pydantic import Field

from blender_mcp_server.app import Transport, bridge_result, get_connection, headless_executor, mcp
from blender_mcp_server.recipes import RECIPE_PATH, Recipe, catalog, get_recipe
from blender_mcp_server.search import rank
from blender_mcp_server.shared import protocol

MAX_RECIPE_RESULTS = 20


def search_recipes(query: str, category: str | None = None) -> list[str]:
    documents = {
        recipe.id: [
            (5, f"{recipe.id.replace('-', ' ')} {recipe.title}"),
            (4, " ".join(recipe.tags)),
            (2, recipe.description),
        ]
        for recipe in catalog().values()
        if category in (None, recipe.category)
    }
    return [recipe_id for recipe_id, _ in rank(query, documents)]


@mcp.tool(
    name="blender_recipe_search",
    description=(
        "List reviewed ready-made scripts (recipes), optionally by task words or category. Returns IDs with one-line "
        "descriptions; use blender_recipe_get for arguments."
    ),
)
async def recipe_search(
    query: str | None = None,
    category: str | None = None,
    limit: Annotated[int, Field(ge=1, le=MAX_RECIPE_RESULTS)] = 8,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    categories = sorted({recipe.category for recipe in catalog().values()})
    if category is not None and category not in categories:
        raise protocol.InvalidArgumentsError(f"Unknown category. Choose from: {', '.join(categories)}")
    if query is None:
        matches = [recipe.id for recipe in catalog().values() if category in (None, recipe.category)]
    else:
        matches = search_recipes(query, category)
    page = matches[offset : offset + limit]
    return {
        "recipes": [
            {"id": recipe_id, "category": get_recipe(recipe_id).category, "summary": get_recipe(recipe_id).description}
            for recipe_id in page
        ],
        "categories": categories,
        "total": len(matches),
        "next_offset": offset + len(page) if offset + len(page) < len(matches) else None,
    }


@mcp.tool(
    name="blender_recipe_get",
    description="Describe one recipe: argument schema with defaults, result fields, side effects and an example.",
)
async def recipe_get(ctx: Context, recipe: str) -> dict[str, Any]:
    found = get_recipe(recipe)
    policy = get_connection(ctx).policy
    card: dict[str, Any] = {
        "id": found.id,
        "version": found.version,
        "title": found.title,
        "category": found.category,
        "description": found.description,
        "input_schema": found.input_schema,
        "result_fields": list(found.output_schema["required"]),
        "blender_min": found.blender_min,
        "side_effects": list(found.side_effects),
        "prerequisites": list(found.prerequisites),
        "example": found.examples[0],
    }
    try:
        policy.require_command("python.execute")
        card["allowed_by_server_policy"] = True
    except PermissionError as exc:
        card.update(allowed_by_server_policy=False, reason=str(exc))
    if not policy.allow_inline_code:
        card["script_root_to_approve"] = str(RECIPE_PATH)
    return card


async def _run_in_bridge(ctx: Context, recipe: Recipe, arguments: dict, timeout_seconds: int | None) -> dict:
    params: dict[str, Any] = {"args": arguments, "timeout_seconds": timeout_seconds}
    outcome: dict
    if get_connection(ctx).policy.allow_inline_code:
        try:
            outcome = await bridge_result(ctx, "python.execute", code=recipe.source(), **params)
            return outcome
        except protocol.BridgeError as exc:
            # Blender preferences may forbid inline code. Nothing ran, so the approved-path route is safe to try.
            if exc.code != "permission_denied":
                raise
    outcome = await bridge_result(ctx, "python.execute", script_path=str(recipe.path), **params)
    return outcome


@mcp.tool(
    name="blender_recipe_run",
    description=(
        "Run a reviewed recipe by ID with arguments checked against its schema. Needs the same permission as Python "
        "execution. Read blender_recipe_get first for arguments and side effects."
    ),
)
async def recipe_run(
    ctx: Context,
    recipe: str,
    arguments: dict[str, Any] | None = None,
    timeout_seconds: Annotated[int | None, Field(ge=1)] = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> dict[str, Any]:
    found = get_recipe(recipe)
    values = found.arguments(arguments or {})
    if transport == "headless":
        executor = await headless_executor(ctx, "python.execute")
        inline = executor.policy.allow_inline_code
        outcome = await executor.execute(
            code=found.source() if inline else None,
            script_path=None if inline else str(found.path),
            args=values,
            timeout_seconds=timeout_seconds,
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
    else:
        outcome = await _run_in_bridge(ctx, found, values, timeout_seconds)
    if outcome.get("error"):
        raise protocol.BridgeError(
            "execution_timeout" if outcome.get("timed_out") else "command_failed",
            f"Recipe {found.id} failed: {outcome['error']}. Check its prerequisites, and inspect the scene because "
            "earlier steps of the script may have taken effect.",
            command="python.execute",
        )
    result = {"recipe": found.id, "version": found.version, "result": outcome.get("result")}
    for stream in ("stdout", "stderr"):
        if outcome.get(stream):
            result[stream] = outcome[stream]
    return result
