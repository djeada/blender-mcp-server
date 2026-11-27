"""Reduce what a small-context client has to hold, without changing what tools do.

A compact response that exceeds the byte budget becomes a preview. The complete payload
stays on the server so it can be read in pieces without running the command again.
"""

from __future__ import annotations

import json
import uuid
import weakref
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from mcp import types

from blender_mcp_server.shared import protocol

MAX_STORED_OUTPUTS = 8
MAX_STORED_BYTES = 16 * 1024 * 1024
MAX_REPORTED_OMISSIONS = 6
_LOG_KEYS = frozenset({"stdout", "stderr"})
# Dictionaries wider than this are data, such as results keyed by object name, rather than records.
_MAX_RECORD_KEYS = 32
# Outcome fields that every preview keeps.
_ESSENTIAL_KEYS = frozenset(
    {"error", "errors", "status", "summary", "stdout", "stderr", "timed_out", "cancelled", "total", "next_offset"}
)
# (list items, string characters) for successively tighter previews.
_PREVIEW_STEPS = ((20, 600), (10, 300), (5, 160), (3, 80), (1, 60))


@dataclass(frozen=True)
class OutputBudget:
    """Context budgets for compact output. These are separate from wire, security and execution limits."""

    compact: bool = False
    max_response_bytes: int = 8_000
    page_size: int = 25
    log_tail_chars: int = 2_000

    LIMITS = {
        "max_response_bytes": (2_000, 8 * 1024 * 1024),
        "page_size": (1, 1_000),
        "log_tail_chars": (0, 100_000),
    }

    def __post_init__(self):
        for name, (low, high) in self.LIMITS.items():
            if not low <= getattr(self, name) <= high:
                raise ValueError(f"{name} must be between {low} and {high}")


def dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def size_of(value: Any) -> int:
    return len(dumps(value).encode("utf-8", errors="replace"))


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


class OutputStore:
    """Recent oversized payloads for each client session, newest kept."""

    def __init__(self):
        self._sessions: weakref.WeakKeyDictionary[Any, OrderedDict[str, tuple[Any, int]]] = weakref.WeakKeyDictionary()

    def put(self, session: Any, value: Any) -> str:
        outputs = self._sessions.setdefault(session, OrderedDict())
        output_id = f"out-{uuid.uuid4().hex[:8]}"
        outputs[output_id] = (value, size_of(value))
        while len(outputs) > 1 and (
            len(outputs) > MAX_STORED_OUTPUTS or sum(size for _, size in outputs.values()) > MAX_STORED_BYTES
        ):
            outputs.popitem(last=False)
        return output_id

    def get(self, session: Any, output_id: str) -> Any:
        try:
            return self._sessions[session][output_id][0]
        except KeyError:
            raise protocol.BridgeError(
                "not_found",
                "Unknown or expired output_id. Only this session's most recent oversized outputs are kept",
            ) from None


def _tail(text: str, limit: int) -> str:
    return f"…[{len(text) - limit} earlier characters omitted]\n{text[-limit:] if limit else ''}"


def _tail_logs(value: Any, limit: int, path: str, omitted: list[dict]) -> Any:
    """Keep the end of logs and error traces, which is where the failure is."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            allowed = limit if key in _LOG_KEYS else 2 * limit if key == "error" else None
            if allowed is not None and isinstance(item, str) and len(item) > allowed:
                omitted.append({"path": child, "total_chars": len(item), "kept": "end"})
                result[key] = _tail(item, allowed)
            else:
                result[key] = _tail_logs(item, limit, child, omitted)
        return result
    if isinstance(value, list):
        return [_tail_logs(item, limit, f"{path}.{index}", omitted) for index, item in enumerate(value)]
    return value


def _is_failure(item: Any) -> bool:
    return isinstance(item, dict) and (
        item.get("status") in {"failed", "error"} or item.get("severity") == "error" or bool(item.get("error"))
    )


def _shrink(value: Any, items: int, chars: int, path: str, omitted: list[dict], key: str = "") -> Any:
    if isinstance(value, dict):
        names = list(value)
        if len(names) > _MAX_RECORD_KEYS:
            first = set(names[:items])
            names = [name for name in names if name in first or name in _ESSENTIAL_KEYS or _is_failure(value[name])]
            omitted.append({"path": path, "shown_keys": len(names), "total_keys": len(value)})
        return {
            name: _shrink(value[name], items, chars, f"{path}.{name}" if path else str(name), omitted, str(name))
            for name in names
        }
    if isinstance(value, list):
        # Never hide a failure behind the item limit.
        kept = [(index, item) for index, item in enumerate(value) if index < items or _is_failure(item)]
        if len(kept) < len(value):
            omitted.append({"path": path, "shown": len(kept), "total": len(value)})
        return [_shrink(item, items, chars, f"{path}.{index}", omitted) for index, item in kept]
    if isinstance(value, str):
        # Log tails were already chosen, so only tighten them if the preview is still too large.
        keeps_end = key in _LOG_KEYS or key == "error"
        limit = chars * 3 if keeps_end else chars
        if len(value) > limit:
            omitted.append({"path": path, "total_chars": len(value), "kept": "end" if keeps_end else "start"})
            return _tail(value, limit) if keeps_end else value[:limit] + "…"
    return value


def shape(value: Any, budget: OutputBudget, store: OutputStore, session: Any) -> Any:
    """Return `value` if it fits the budget, otherwise a labelled preview with a way to read the rest."""
    tailed: list[dict] = []
    preview = _tail_logs(value, budget.log_tail_chars, "", tailed)
    total = size_of(value)
    if not tailed and total <= budget.max_response_bytes:
        return value
    output_id = store.put(session, value)

    def envelope(body: Any, omitted: list[dict]) -> Any:
        notice = {
            "truncated": True,
            "output_id": output_id,
            "total_bytes": total,
            "omitted": [{**entry, "path": entry["path"][-120:]} for entry in omitted[:MAX_REPORTED_OMISSIONS]],
            "omitted_count": len(omitted),
            "read_more": "blender_output_read(output_id, path) returns any omitted part without rerunning the command",
        }
        if isinstance(body, dict):
            return {"truncation": notice, **{k: v for k, v in body.items() if k != "truncation"}}
        return {"truncation": notice, "preview": body}

    candidate = envelope(preview, tailed)
    for items, chars in _PREVIEW_STEPS:
        if size_of(candidate) <= budget.max_response_bytes:
            return candidate
        omitted = list(tailed)
        candidate = envelope(_shrink(preview, items, chars, "", omitted), omitted)
    if size_of(candidate) <= budget.max_response_bytes:
        return candidate
    # Still too large: keep the outcome fields and name the top level so the client can drill in.
    keys = list(value)[:30] if isinstance(value, dict) else []
    fallback: dict[str, Any] = {"preview_keys": [str(key)[:60] for key in keys]}
    if isinstance(value, dict):
        for key in ("status", "error", "timed_out", "cancelled"):
            if key in value:
                item = value[key]
                text = item if isinstance(item, str) else dumps(item)
                fallback[key] = _tail(text, 300) if len(text) > 300 else item
    candidate = envelope(fallback, tailed[:2])
    if size_of(candidate) <= budget.max_response_bytes:
        return candidate
    return envelope({}, [])


def compact_result(result: Any, budget: OutputBudget, store: OutputStore | None = None, session: Any = None) -> Any:
    """Return one copy of a payload as unindented JSON, within the budget when a store is given."""
    content = result[0] if isinstance(result, tuple) else result
    if not isinstance(content, list):
        return content
    return [_compact_block(block, budget, store, session) for block in content]


def _compact_block(block: Any, budget: OutputBudget, store: OutputStore | None, session: Any) -> Any:
    if not isinstance(block, types.TextContent):
        return block
    try:
        value = json.loads(block.text)
    except ValueError:
        value = block.text
    if store is not None:
        value = shape(value, budget, store, session)
    return block.model_copy(update={"text": value if isinstance(value, str) else dumps(value)})


_MISSING = object()


def select(value: Any, path: str) -> Any:
    """Follow a dotted path such as 'result.findings.0.ids'.

    Keys may contain dots themselves, as Blender names like 'Cube.001' do.
    """
    found = _follow(value, path.split(".") if path else [])
    if found is _MISSING:
        raise protocol.InvalidArgumentsError("The path does not exist in this output")
    return found


def _follow(value: Any, parts: list[str]) -> Any:
    if not parts:
        return value
    if isinstance(value, list):
        index = parts[0]
        if index.isdecimal() and int(index) < len(value):
            return _follow(value[int(index)], parts[1:])
    elif isinstance(value, dict):
        for end in range(len(parts), 0, -1):
            key = ".".join(parts[:end])
            if key in value and (found := _follow(value[key], parts[end:])) is not _MISSING:
                return found
    return _MISSING


def _largest_fitting(count: int, build, max_bytes: int) -> int:
    """Return the largest n in [0, count] whose page fits. Page size grows with n."""
    low, high = 0, count
    while low < high:
        middle = (low + high + 1) // 2
        if size_of(build(middle)) <= max_bytes:
            low = middle
        else:
            high = middle - 1
    return low


def read_part(value: Any, path: str, offset: int, limit: int | None, max_bytes: int) -> dict:
    """Page through one part of a stored payload so that every response fits the budget."""
    selected = select(value, path)
    if isinstance(selected, str):
        available = max(0, len(selected) - offset)
        wanted = available if limit is None else min(available, limit)

        def text_page(n: int) -> dict:
            end = offset + n
            return {
                "path": path,
                "text": selected[offset:end],
                "offset": offset,
                "total_chars": len(selected),
                "next_offset": end if end < len(selected) else None,
            }

        return text_page(_largest_fitting(wanted, text_page, max_bytes))
    if isinstance(selected, list):
        rest = selected[offset:] if limit is None else selected[offset : offset + limit]

        def list_page(n: int) -> dict:
            end = offset + n
            return {
                "path": path,
                "items": rest[:n],
                "offset": offset,
                "total": len(selected),
                "next_offset": end if end < len(selected) else None,
            }

        count = _largest_fitting(len(rest), list_page, max_bytes)
        if rest and not count:
            # Point at the oversized item and let paging continue past it.
            item_path = f"{path}.{offset}" if path else str(offset)
            return {
                **list_page(0),
                "item_too_large": item_path,
                "next_offset": offset + 1 if offset + 1 < len(selected) else None,
            }
        return list_page(count)
    whole = {"path": path, "value": selected}
    if size_of(whole) <= max_bytes:
        return whole
    return _outline(selected, path, offset, limit, max_bytes)


def _outline(value: Any, path: str, offset: int, limit: int | None, max_bytes: int) -> dict:
    """Describe a part that is too large to return, so the client can request something inside it."""
    if isinstance(value, str):
        return {"path": path, "too_large": True, "type": "string", "total_chars": len(value)}
    if isinstance(value, list):
        return {"path": path, "too_large": True, "type": "array", "total": len(value)}
    names = list(value)
    rest = names[offset:] if limit is None else names[offset : offset + limit]

    def key_page(n: int) -> dict:
        end = offset + n
        return {
            "path": path,
            "too_large": True,
            "keys": [
                {"key": name, "type": type(value[name]).__name__, "bytes": size_of(value[name])} for name in rest[:n]
            ],
            "offset": offset,
            "total": len(names),
            "next_offset": end if end < len(names) else None,
        }

    return key_page(_largest_fitting(len(rest), key_page, max_bytes))
