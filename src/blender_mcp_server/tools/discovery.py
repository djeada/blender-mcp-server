"""Find, describe and run actions whose schemas are not advertised."""

import weakref
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import Context
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field, ValidationError

from blender_mcp_server.app import get_connection, mcp
from blender_mcp_server.capabilities import GROUPS, KEYWORDS, TOOL_GROUPS
from blender_mcp_server.search import rank
from blender_mcp_server.shared import protocol
from blender_mcp_server.wire import strip_titles

MAX_SEARCH_RESULTS = 20
MAX_DESCRIBED = 3

# Actions each client session has described. Entries disappear with their session.
_discovered: "weakref.WeakKeyDictionary[Any, set[str]]" = weakref.WeakKeyDictionary()


def _tool(action: str):
    if action not in TOOL_GROUPS:
        raise protocol.BridgeError("not_found", "Unknown action; use blender_capability_search to find action IDs")
    group = TOOL_GROUPS[action]
    mcp.exposure.require_allowed_group(group, action)
    tool = mcp._tool_manager.get_tool(action)
    assert tool is not None
    return tool, group


def _summary(description: str) -> str:
    first = description.split(". ", 1)[0].rstrip(".")
    return first if len(first) <= 160 else first[:157] + "..."


@mcp.tool(
    name="blender_capability_search",
    description=(
        "Find actions beyond the advertised tools. With no arguments, lists capability groups. Pass task words in "
        "'query' (e.g. 'bevel edges', 'export for game engine') and/or a 'group' to list matching action IDs."
    ),
)
async def capability_search(
    ctx: Context,
    query: str | None = None,
    group: str | None = None,
    limit: Annotated[int, Field(ge=1, le=MAX_SEARCH_RESULTS)] = 8,
    offset: Annotated[int, Field(ge=0)] = 0,
) -> dict[str, Any]:
    exposure = mcp.exposure
    if group is not None:
        if group not in GROUPS:
            raise protocol.InvalidArgumentsError(f"Unknown group. Choose from: {', '.join(sorted(exposure.allowed))}")
        exposure.require_allowed_group(group, "That search")
    if query is None and group is None:
        return {
            "groups": [
                {
                    "group": name,
                    "summary": spec.summary,
                    "actions": len(spec.tools),
                    "advertised": name in exposure.advertised,
                }
                for name, spec in GROUPS.items()
                if name in exposure.allowed
            ]
        }
    candidates = {
        action: _tool(action)[0]
        for action, name in TOOL_GROUPS.items()
        if name in exposure.allowed and (group is None or name == group)
    }
    if query is None:
        matches = list(candidates)
    else:
        documents = {
            action: [
                (5, action.removeprefix("blender_").replace("_", " ")),
                (5, KEYWORDS.get(action, "")),
                (2, tool.description),
                (1, f"{TOOL_GROUPS[action]} {GROUPS[TOOL_GROUPS[action]].summary}"),
            ]
            for action, tool in candidates.items()
        }
        matches = [action for action, _ in rank(query, documents)]
    page = matches[offset : offset + limit]
    result: dict[str, Any] = {
        "actions": [
            {
                "action": action,
                "group": TOOL_GROUPS[action],
                "summary": _summary(candidates[action].description),
                "advertised": TOOL_GROUPS[action] in exposure.advertised,
            }
            for action in page
        ],
        "total": len(matches),
        "next_offset": offset + len(page) if offset + len(page) < len(matches) else None,
    }
    if not matches:
        result["hint"] = "No match. Try other words, or call with no arguments to list groups."
    return result


def _parameters(schema: dict) -> list[dict]:
    required = set(schema.get("required", ()))
    summaries = []
    for name, spec in schema.get("properties", {}).items():
        choices = spec.get("anyOf", [spec])
        types = []
        for choice in choices:
            if "enum" in choice:
                types.append(" | ".join(map(repr, choice["enum"])))
            elif choice.get("type") == "array" and "type" in choice.get("items", {}):
                types.append(f"array of {choice['items']['type']}")
            elif choice.get("type") != "null":
                types.append(choice.get("type", "object"))
        summary: dict[str, Any] = {"name": name, "type": " or ".join(types)}
        if name in required:
            summary["required"] = True
        elif spec.get("default") is not None:
            summary["default"] = spec["default"]
        summaries.append(summary)
    return summaries


def _permissions(ctx: Context, action: str, group: str) -> dict[str, Any]:
    commands = list(GROUPS[group].tools[action])
    result: dict[str, Any] = {"bridge_commands": commands, "allowed_by_server_policy": True}
    try:
        for command in commands:
            get_connection(ctx).policy.require_command(command)
    except PermissionError as exc:
        result.update(allowed_by_server_policy=False, reason=str(exc))
    return result


@mcp.tool(
    name="blender_capability_describe",
    description=(
        "Get what you need to run up to 3 actions: description, parameters, prerequisites and permissions. "
        "detail='schema' returns full JSON schemas. Describing an action makes it invocable in this session."
    ),
)
async def capability_describe(
    ctx: Context,
    actions: Annotated[list[str], Field(min_length=1, max_length=MAX_DESCRIBED)],
    detail: Literal["summary", "schema"] = "summary",
) -> dict[str, Any]:
    found = [(action, *_tool(action)) for action in actions]  # all must be valid before any is recorded
    described = []
    for action, tool, group in found:
        entry: dict[str, Any] = {
            "action": action,
            "group": group,
            "description": tool.description,
            "prerequisites": GROUPS[group].prerequisites,
            "permissions": _permissions(ctx, action, group),
        }
        if detail == "schema":
            entry["input_schema"] = strip_titles(tool.parameters)
        else:
            entry["parameters"] = _parameters(tool.parameters)
        described.append(entry)
    _discovered.setdefault(ctx.session, set()).update(actions)
    return {"actions": described}


@mcp.tool(
    name="blender_capability_invoke",
    description=(
        "Run an action by ID with its arguments object. The result matches calling that tool directly. "
        "Describe an unadvertised action first. Policy and permissions apply as usual."
    ),
    structured_output=False,
)
async def capability_invoke(ctx: Context, action: str, arguments: dict[str, Any] | None = None):
    tool, group = _tool(action)
    if group not in mcp.exposure.advertised and action not in _discovered.get(ctx.session, ()):
        raise protocol.BridgeError(
            "discovery_required",
            f"Call blender_capability_describe with actions=['{action}'] before invoking it",
            details={"action": action},
        )
    arguments = arguments or {}
    if unknown := sorted(set(arguments) - set(tool.parameters.get("properties", {}))):
        # Direct calls ignore extra arguments; here a misspelled name would silently run with defaults.
        raise protocol.BridgeError(
            "invalid_arguments",
            f"{action} has no parameter named {', '.join(map(repr, unknown[:5]))}",
            details={"action": action},
        )
    mcp.exposure.require_arguments(action, arguments)
    try:
        result = await tool.run(arguments, context=ctx, convert_result=True)
    except ToolError as exc:
        if isinstance(exc.__cause__, ValidationError):
            # Name the failing fields without echoing the submitted values.
            problems = "; ".join(
                f"{'.'.join(map(str, error['loc']))}: {error['msg']}" for error in exc.__cause__.errors()[:5]
            )
            raise protocol.BridgeError(
                "invalid_arguments", f"Invalid arguments for {action}. {problems}", details={"action": action}
            ) from None
        raise
    return result[0] if isinstance(result, tuple) else result


@mcp.tool(
    name="blender_capability_reset",
    description="Forget the actions described in this session, for one group or all. Blender is not changed.",
)
async def capability_reset(ctx: Context, group: str | None = None) -> dict[str, Any]:
    if group is not None and group not in GROUPS:
        raise protocol.InvalidArgumentsError("Unknown group")
    known = _discovered.get(ctx.session, set())
    removed = {action for action in known if group is None or TOOL_GROUPS[action] == group}
    known -= removed
    return {"forgotten": sorted(removed), "still_described": sorted(known)}
