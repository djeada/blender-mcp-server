"""Compact output: bounded responses, source-side paging and lossless continuation."""

import contextlib
import json
from unittest.mock import AsyncMock

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from blender_mcp_server.app import mcp
from blender_mcp_server.capabilities import Exposure, parse_exposure
from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.server import main  # noqa: F401  (importing registers every tool)
from blender_mcp_server.shared import protocol
from blender_mcp_server.wire import OutputBudget, OutputStore, dumps, read_part, shape, size_of

BUDGET = OutputBudget(compact=True)


class Session:
    """A weak-referenceable stand-in for an MCP session."""


def _script_result(**overrides):
    result = {
        "result": {"vertices": [[index, index * 0.5, "é漢\x00"] for index in range(3_000)]},
        "stdout": "".join(f"step {index}\n" for index in range(5_000)),
        "stderr": "",
        "error": None,
        "duration_seconds": 1.5,
        "timed_out": False,
        "cancelled": False,
    }
    return {**result, **overrides}


def _rebuild(value, path, budget=BUDGET):
    """Read a whole part back through paged reads, checking every page against the budget."""
    pieces, offset = [], 0
    while offset is not None:
        page = read_part(value, path, offset, None, budget.max_response_bytes)
        assert size_of(page) <= budget.max_response_bytes
        if page.get("too_large"):
            keys = [entry["key"] for entry in page["keys"]]
            pieces.extend((key, _rebuild(value, f"{path}.{key}" if path else key, budget)) for key in keys)
            offset = page["next_offset"]
            if offset is None:
                return dict(pieces)
            continue
        if "value" in page:
            return page["value"]
        if "item_too_large" in page:
            pieces.append([_rebuild(value, page["item_too_large"], budget)])
        else:
            pieces.append(page.get("text", page.get("items")))
        offset = page["next_offset"]
    assert pieces, "paging made no progress"
    return "".join(pieces) if isinstance(pieces[0], str) else [item for chunk in pieces for item in chunk]


def test_small_responses_are_untouched():
    value = {"name": "Cube", "stdout": "short", "error": None}
    store = OutputStore()
    assert shape(value, BUDGET, store, Session()) is value


def test_oversized_script_output_is_bounded_and_fully_recoverable():
    store, session = OutputStore(), Session()
    original = _script_result()
    preview = shape(original, BUDGET, store, session)
    assert size_of(preview) <= BUDGET.max_response_bytes
    notice = preview["truncation"]
    assert notice["truncated"] is True and notice["total_bytes"] == size_of(original)
    assert notice["omitted_count"] >= len(notice["omitted"]) > 0
    assert preview["stdout"].endswith("step 4999\n") and "characters omitted" in preview["stdout"]
    assert preview["error"] is None and preview["timed_out"] is False
    stored = store.get(session, notice["output_id"])
    assert stored == original
    assert _rebuild(stored, "stdout") == original["stdout"]
    assert _rebuild(stored, "result.vertices") == original["result"]["vertices"]
    assert _rebuild(stored, "") == original


def test_wide_results_keep_logs_and_errors_visible():
    """Script results keyed by object name have hundreds of keys; the outcome must still be readable."""
    value = _script_result(
        result={f"Crate.{index:03}": [index, 0.0, 0.0] for index in range(500)}, error="NameError: name 'x'"
    )
    preview = shape(value, BUDGET, OutputStore(), Session())
    assert size_of(preview) <= BUDGET.max_response_bytes
    assert preview["error"] == "NameError: name 'x'"
    assert preview["stdout"].endswith("step 4999\n")
    assert preview["result"]["Crate.000"] == [0, 0.0, 0.0]
    assert any(entry.get("total_keys") == 500 for entry in preview["truncation"]["omitted"])


def test_the_last_resort_preview_still_reports_the_outcome():
    value = {f"{'k' * 200}{index}": "v" * 200 for index in range(20)} | {"error": "boom " * 400, "status": "failed"}
    budget = OutputBudget(compact=True, max_response_bytes=2_000, log_tail_chars=100_000)
    preview = shape(value, budget, OutputStore(), Session())
    assert size_of(preview) <= 2_000
    assert preview["status"] == "failed" and preview["error"].endswith("boom ")


def test_a_long_log_alone_is_tailed_and_keeps_the_error_end():
    traceback = "Traceback:\n" + "  frame\n" * 2_000 + "ValueError: the real problem"
    value = {"status": "failed", "error": traceback, "stderr": "w" * 3_000}
    preview = shape(value, BUDGET, OutputStore(), Session())
    assert preview["error"].endswith("ValueError: the real problem")
    assert [entry["path"] for entry in preview["truncation"]["omitted"]] == ["error", "stderr"]


def test_failures_are_never_hidden_by_list_limits():
    steps = [{"index": index, "status": "succeeded", "result": {"blob": "x" * 900}} for index in range(32)]
    steps[27] = {"index": 27, "status": "failed", "error": {"code": "not_found", "message": "Object not found"}}
    steps[28:] = [{"index": index, "status": "skipped", "reason": "previous_failure"} for index in range(28, 32)]
    preview = shape({"result": {"steps": steps}}, BUDGET, OutputStore(), Session())
    assert size_of(preview) <= BUDGET.max_response_bytes
    shown = preview["result"]["steps"]
    assert any(step["index"] == 27 and step["error"]["code"] == "not_found" for step in shown)
    listed = {entry["path"]: entry for entry in preview["truncation"]["omitted"]}
    assert listed["result.steps"]["total"] == 32 and listed["result.steps"]["shown"] == len(shown) < 32


@pytest.mark.parametrize(
    "value",
    [
        {f"key_{index}": index for index in range(5_000)},
        {"deep": [[[["y" * 500] * 30] * 30] * 5]},
        [{"name": f"Object.{index:05}"} for index in range(20_000)],
        "plain text " * 5_000,
        {"stdout": "\x00" * 60_000},
    ],
    ids=["many-keys", "deep-graph", "large-list", "text", "escapes"],
)
@pytest.mark.parametrize("limit", [2_000, 8_000])
def test_any_shape_fits_the_configured_budget(value, limit):
    budget = OutputBudget(compact=True, max_response_bytes=limit)
    store, session = OutputStore(), Session()
    preview = shape(value, budget, store, session)
    assert size_of(preview) <= limit
    notice = preview["truncation"]
    assert store.get(session, notice["output_id"]) == value
    assert size_of(read_part(value, "", 0, None, limit)) <= limit


def test_paged_reads_validate_the_path():
    value = {"items": [1, 2, 3]}
    assert read_part(value, "items", 1, 1, 2_000) == {
        "path": "items",
        "items": [2],
        "offset": 1,
        "total": 3,
        "next_offset": 2,
    }
    assert read_part(value, "items.2", 0, None, 2_000) == {"path": "items.2", "value": 3}
    for path in ("nope", "items.9", "items.-1", "items.0.deeper"):
        with pytest.raises(protocol.InvalidArgumentsError):
            read_part(value, path, 0, None, 2_000)


def test_oversized_list_items_and_dotted_blender_names_can_be_read():
    value = {
        "objects": {"Cube.001": {"log": "a" * 5_000}, "Cube": {"001": "decoy", "name": "plain"}},
        "items": ["short", "b" * 5_000, {"Sphere.002.high": list(range(2_000))}, "last"],
    }
    assert read_part(value, "objects.Cube.001.log", 4_990, None, 2_000)["text"] == "a" * 10
    assert read_part(value, "objects.Cube.name", 0, None, 2_000)["text"] == "plain"
    middle = read_part(value, "items", 1, None, 2_000)
    assert middle == {
        "path": "items",
        "items": [],
        "offset": 1,
        "total": 4,
        "next_offset": 2,
        "item_too_large": "items.1",
    }
    assert _rebuild(value, "", OutputBudget(compact=True, max_response_bytes=2_000)) == value


def test_store_is_per_session_and_keeps_only_recent_outputs():
    store, first, second = OutputStore(), Session(), Session()
    ids = [store.put(first, {"n": index}) for index in range(10)]
    assert store.get(first, ids[-1]) == {"n": 9}
    for session, output_id in [(second, ids[-1]), (first, ids[0]), (first, "out-nope")]:
        with pytest.raises(protocol.BridgeError) as error:
            store.get(session, output_id)
        assert error.value.code == "not_found"
    huge = [store.put(first, "z" * 9_000_000) for _ in range(2)]
    assert store.get(first, huge[1])
    with pytest.raises(protocol.BridgeError):
        store.get(first, huge[0])


def test_budget_configuration():
    exposure = parse_exposure(["--output", "compact"], {"BLENDER_MCP_PAGE_SIZE": "7"})
    assert exposure.profile == "full" and exposure.output == OutputBudget(compact=True, page_size=7)
    assert parse_exposure(["--profile", "compact", "--output", "full"], {}).compact_output is False
    assert parse_exposure(["--max-response-bytes", "4000"], {}).output.max_response_bytes == 4_000


@pytest.mark.parametrize(
    ("argv", "environ"),
    [
        (["--output", "tiny"], {}),
        (["--max-response-bytes", "10"], {}),
        (["--page-size", "0"], {}),
        ([], {"BLENDER_MCP_LOG_TAIL_CHARS": "lots"}),
    ],
)
def test_invalid_budgets_stop_the_server(argv, environ):
    with pytest.raises(SystemExit):
        parse_exposure(argv, environ)


@pytest.fixture
def serve(monkeypatch):
    @contextlib.asynccontextmanager
    async def connect(profile, respond, **options):
        send = AsyncMock(side_effect=lambda command, params=None, **kwargs: respond(command, params or {}))

        async def send_command(connection, command, params=None, **kwargs):
            return await send(command, params)

        monkeypatch.setattr(BlenderConnection, "send_command", send_command)
        monkeypatch.setattr(mcp, "exposure", Exposure.create(profile, **options))
        mcp._mcp_server._tool_cache.clear()
        async with create_connected_server_and_client_session(mcp) as client:
            await client.list_tools()
            yield client, send

    return connect


@pytest.mark.parametrize(
    ("tool", "arguments", "parameter"),
    [
        ("blender_scene_list_objects", {}, "limit"),
        ("blender_material_list", {}, "limit"),
        ("blender_collection_list", {}, "limit"),
        ("blender_keyframe_list", {"name": "Cube", "property": "location"}, "limit"),
        ("blender_object_get_hierarchy", {}, "max_nodes"),
    ],
)
@pytest.mark.asyncio
async def test_compact_listings_are_paged_at_the_source_and_full_ones_are_not(serve, tool, arguments, parameter):
    async def call(profile, extra):
        async with serve(
            profile, lambda command, params: {}, allow=None, enable=["scene", "materials", "animation"]
        ) as (
            client,
            send,
        ):
            result = await client.call_tool(tool, {**arguments, **extra})
            assert not result.isError, result.content[0].text
            return send.await_args.args[1]

    assert (await call("compact", {}))[parameter] == 25
    assert (await call("compact", {parameter: 300}))[parameter] == 300
    assert parameter not in await call("full", {})


@pytest.mark.asyncio
async def test_job_list_pages_newest_first(serve):
    jobs = [{"job_id": f"job-{index:03}", "status": "succeeded", "created_at": index} for index in range(60)]
    async with serve("compact", lambda command, params: {"jobs": jobs}, enable=["scripting"]) as (client, _):
        seen, offset = [], 0
        while offset is not None:
            result = await client.call_tool("blender_job_list", {"offset": offset})
            page = json.loads(result.content[0].text)
            seen += [job["job_id"] for job in page["jobs"]]
            offset = page["next_offset"]
    assert seen == [job["job_id"] for job in reversed(jobs)] and page["total"] == 60
    async with serve("full", lambda command, params: {"jobs": jobs}) as (client, _):
        full = json.loads((await client.call_tool("blender_job_list", {})).content[0].text)
    assert full == {"jobs": jobs}


@pytest.mark.asyncio
async def test_truncated_response_is_read_back_without_rerunning(serve):
    original = _script_result()
    async with serve("compact", lambda command, params: original, enable=["scripting"]) as (client, send):
        result = await client.call_tool("blender_python_exec", {"code": "build()"})
        text = result.content[0].text
        assert result.structuredContent is None and len(text.encode()) <= 8_000
        output_id = json.loads(text)["truncation"]["output_id"]
        chunks, offset = [], 0
        while offset is not None:
            read = await client.call_tool(
                "blender_output_read", {"output_id": output_id, "path": "stdout", "offset": offset}
            )
            assert len(read.content[0].text.encode()) <= 8_000 and read.structuredContent is None
            page = json.loads(read.content[0].text)
            assert "truncation" not in page
            chunks.append(page["text"])
            offset = page["next_offset"]
        assert "".join(chunks) == original["stdout"]
        async with create_connected_server_and_client_session(mcp) as other:
            denied = await other.call_tool("blender_output_read", {"output_id": output_id})
        assert denied.structuredContent["error"]["code"] == "not_found"
    send.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_output_is_complete_and_has_no_continuation_tool(serve):
    original = _script_result()
    async with serve("full", lambda command, params: original) as (client, _):
        result = await client.call_tool("blender_python_exec", {"code": "build()"})
        assert json.loads(result.content[0].text) == original
        hidden = await client.call_tool("blender_output_read", {"output_id": "out-1"})
    assert hidden.structuredContent["error"]["code"] == "tool_not_enabled"


def test_dumps_keeps_non_ascii_compact():
    assert dumps({"name": "Épée"}) == '{"name":"Épée"}'
