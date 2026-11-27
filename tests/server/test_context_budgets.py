"""Offline CI limits on the context a client must hold. The limits live in tests/context_budgets.json."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from blender_mcp_server import knowledge
from blender_mcp_server.capabilities import GROUPS, PROFILES
from blender_mcp_server.recipes import catalog
from blender_mcp_server.wire import OutputBudget

ROOT = Path(__file__).resolve().parents[2]
BUDGETS = json.loads((ROOT / "tests" / "context_budgets.json").read_text())


def _load_benchmark():
    spec = importlib.util.spec_from_file_location("context_benchmark", ROOT / "scripts" / "context_benchmark.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


benchmark = _load_benchmark()


@pytest.mark.asyncio
async def test_tool_lists_stay_within_budget():
    sizes = await benchmark.measure_tool_lists()
    assert set(sizes) == set(PROFILES) == set(BUDGETS["tools_list"])
    for profile, (count, size) in sizes.items():
        limit = BUDGETS["tools_list"][profile]
        assert count == limit["tools"], f"{profile} advertises {count} tools"
        assert size <= limit["bytes"], f"{profile} tools/list grew to {size} bytes (limit {limit['bytes']})"


@pytest.mark.asyncio
async def test_documented_sizes_match_the_server():
    """Published figures must be measured ones. KB here means 1,000 bytes, to one decimal."""
    sizes = await benchmark.measure_tool_lists()
    kilobytes = {profile: f"{size / 1000:.1f} KB" for profile, (_, size) in sizes.items()}
    table = (ROOT / "docs" / "profiles.md").read_text()
    for profile, (count, _) in sizes.items():
        row = next(line for line in table.splitlines() if line.startswith(f"| `{profile}`"))
        assert row.rstrip().endswith(f"| {count} | {kilobytes[profile]} |"), (profile, row, count, kilobytes[profile])
    for document in ("README.md", "CHANGELOG.md"):
        text = (ROOT / document).read_text()
        assert kilobytes["compact"] in text and kilobytes["full"] in text, (document, kilobytes)


def test_compact_stays_far_smaller_than_full():
    limits = BUDGETS["tools_list"]
    assert limits["compact"]["bytes"] * 6 < limits["full"]["bytes"]
    assert OutputBudget().max_response_bytes == 8_000  # the default compact response budget


@pytest.mark.asyncio
async def test_every_discovery_and_knowledge_response_stays_within_budget():
    limits = BUDGETS["responses"]
    over: list[str] = []
    async with benchmark.open_session("compact", benchmark.Metrics("budgets", "compact")) as session:
        await session.tools()

        async def check(kind, tool, arguments):
            ok, text = await session.call(tool, arguments)
            assert ok, text
            if len(text.encode()) > limits[kind]:
                over.append(f"{kind} {arguments}: {len(text.encode())} > {limits[kind]}")

        async def use(kind, action, arguments):
            await session.call("blender_capability_describe", {"actions": [action]})
            await check(kind, "blender_capability_invoke", {"action": action, "arguments": arguments})

        await check("capability_overview", "blender_capability_search", {})
        for group in GROUPS:
            await check("capability_search_page", "blender_capability_search", {"group": group})
            for action in GROUPS[group].tools:
                await check("capability_describe_one", "blender_capability_describe", {"actions": [action]})
        await use("guide_index", "blender_guide_search", {})
        for guide in knowledge.guides().values():
            await use("guide_card", "blender_guide_get", {"guide": guide.id})
            for section in guide.sections:
                await use("guide_section", "blender_guide_get", {"guide": guide.id, "section": section})
        for flow in knowledge.workflows()["workflows"]:
            for style in knowledge.workflows()["styles"]:
                options = {"task": flow["title"], "style": style, "target": "game"}
                for stage in knowledge.select_workflow(**options)["stages"]:
                    await use("workflow_stage", "blender_workflow", {**options, "stage": stage["id"]})
        for recipe in catalog():
            await use("recipe_card", "blender_recipe_get", {"recipe": recipe})
    assert not over, "\n".join(over)


@pytest.mark.asyncio
async def test_task_traces_stay_within_budget_and_compact_beats_full(tmp_path):
    tasks = benchmark._tasks(str(tmp_path / "parcel.glb"))
    assert set(tasks) == set(BUDGETS["compact_trace_server_bytes"])
    with benchmark.offline_bridge():
        for name, task in tasks.items():
            compact = await benchmark.run_trace(task, "compact", live=False)
            full = await benchmark.run_trace(task, "full", live=False)
            assert compact["errors"] == full["errors"] == 0
            assert compact["context_bytes"] <= BUDGETS["compact_trace_server_bytes"][name], (name, compact)
            assert compact["context_bytes"] < full["context_bytes"] / 2, name
            # The saving costs round trips; both sides are reported.
            assert compact["calls"] > full["calls"] and full["discovery_calls"] == 0
            assert compact["structured_duplicate_bytes"] == 0


@pytest.mark.parametrize("api", ["ollama", "openai"])
@pytest.mark.asyncio
async def test_model_evaluation_harness_with_a_scripted_model(api, monkeypatch):
    """The optional evaluation is exercised offline with a fake model server reply."""
    turns = [
        [("blender_object_create", {"mesh_type": "cube", "name": "Parcel"})],
        [("blender_light_create", {})],  # hidden in compact: an error the metrics must count
        [("blender_python_exec", {"code": "pass"})],
        [],
    ]
    requests = []

    probes = []

    def post(url, payload, timeout):
        # A fake server whose token count grows with the number of tools it is sent.
        prompt_tokens = 60 * len(payload["tools"])
        if payload.get("options", {}).get("num_predict") == 1:
            probes.append(payload)
            return {"message": {"role": "assistant", "content": ""}, "prompt_eval_count": prompt_tokens}
        requests.append((url, payload))
        calls = turns[len(requests) - 1]
        if api == "ollama":
            tool_calls = [{"function": {"name": name, "arguments": arguments}} for name, arguments in calls]
            message = {"role": "assistant", "content": "", "tool_calls": tool_calls}
            return {"message": message, "prompt_eval_count": prompt_tokens}
        tool_calls = [
            {"id": f"c{len(requests)}", "function": {"name": name, "arguments": json.dumps(arguments)}}
            for name, arguments in calls
        ]
        message = {"role": "assistant", "content": "DONE", "tool_calls": tool_calls}
        return {"choices": [{"message": message}], "usage": {"prompt_tokens": prompt_tokens}}

    async def no_python(code):
        return {"parcel_exists": True, "file_written": False}

    monkeypatch.setattr(benchmark, "_post", post)
    monkeypatch.setattr(benchmark, "blender_python", no_python)
    options = benchmark.parse_arguments(["model", "--model", "stub", "--api", api])
    task = benchmark._tasks("/tmp/unused.glb")["export"]
    with benchmark.offline_bridge():
        result = await benchmark.run_model(task, "compact", 2_048, options)
        sent_by_compact = len(requests)
        turns.extend(turns)  # replies for the full run, if its first request is sent
        too_small = await benchmark.run_model(task, "full", 2_048, options)
    assert result["outcome"] == "finished" and result["turns"] == 4 and result["calls"] == 3
    assert result["errors"] == 2 and result["error_codes"] == ["tool_not_enabled", "permission_denied"]
    assert result["quality"] == 0.5 and result["success"] is False
    assert result["peak_prompt_tokens"] == 60 * len(requests[0][1]["tools"]) < 2_048
    # The server's own count decides overflow: no byte-based estimate is involved.
    assert too_small["outcome"] == "context_overflow" and too_small["calls"] == 0
    assert too_small["peak_prompt_tokens"] > 2_048
    if api == "ollama":
        assert requests[0][1]["options"]["num_ctx"] == 2_048
        assert len(requests) == sent_by_compact == 4  # Ollama never receives a request it would truncate
        assert all(probe["options"]["num_ctx"] >= 65_536 for probe in probes)
    else:
        assert len(requests) == sent_by_compact + 1  # only the reported usage reveals the overflow
    offered = {tool["function"]["name"] for tool in requests[0][1]["tools"]}
    assert "blender_python_exec" not in offered


def test_model_mode_requires_a_model():
    with pytest.raises(SystemExit):
        benchmark.parse_arguments(["model"])
