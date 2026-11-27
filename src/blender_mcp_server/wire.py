"""Reduce what a small-context client has to hold, without changing what tools do."""

from __future__ import annotations

import json
from typing import Any

from mcp import types


def strip_titles(schema: Any) -> Any:
    """Drop generated 'title' annotations. A property that is named 'title' has a dict value and stays."""
    if isinstance(schema, dict):
        return {
            key: strip_titles(value) for key, value in schema.items() if not (key == "title" and isinstance(value, str))
        }
    if isinstance(schema, list):
        return [strip_titles(item) for item in schema]
    return schema


def compact_tool(tool: types.Tool) -> types.Tool:
    return tool.model_copy(update={"inputSchema": strip_titles(tool.inputSchema), "outputSchema": None})


def compact_result(result: Any) -> Any:
    """Return one copy of a payload as unindented JSON instead of text plus structured content."""
    content = result[0] if isinstance(result, tuple) else result
    if not isinstance(content, list):
        return content
    return [_minify(block) for block in content]


def _minify(block: Any) -> Any:
    if not isinstance(block, types.TextContent):
        return block
    try:
        value = json.loads(block.text)
    except ValueError:
        return block
    if not isinstance(value, (dict, list)):
        return block
    return block.model_copy(update={"text": json.dumps(value, separators=(",", ":"), ensure_ascii=False)})
