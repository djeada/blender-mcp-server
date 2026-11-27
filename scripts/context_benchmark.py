"""Measure what an MCP client has to hold in context, and optionally evaluate a local model.

    python scripts/context_benchmark.py sizes
        Bytes of each profile's tool list. No Blender needed.

    python scripts/context_benchmark.py trace [--live] [--json out.json]
        Replay fixed tool sequences for representative tasks in the compact and full profiles.
        With --live, calls go to a running Blender (BLENDER_MCP_PORT / BLENDER_MCP_TOKEN_FILE) and results
        are scored from the scene. Without it, Blender replies are small stand-ins, so only the schema,
        discovery and knowledge bytes are meaningful.

    python scripts/context_benchmark.py model --model NAME --url http://127.0.0.1:11434 --budgets 8192,32768
        Let a local model attempt the tasks. Uses Ollama's native API (which honours the context window) or,
        with --api openai, an OpenAI-compatible server whose context window you configure yourself.
        THE MODEL CHANGES THE CONNECTED BLENDER and can write render and export files. Use a throwaway session.
        Model-written Python is refused unless you add --allow-python, which runs it with your user's rights;
        without it, tasks that need a script cannot fully succeed.

Byte counts are exact for this transport. Token figures marked "approx" are bytes/4 and can be far off (for
qwen2.5 on these schemas they overstate the count by about half); real counts depend on the tokenizer, and
image tokens vary by client. The model mode uses only the model server's own token counts.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import os
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass, field

from mcp.shared.memory import create_connected_server_and_client_session

from blender_mcp_server.capabilities import GROUPS, PROFILES, Exposure
from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.server import mcp

DISCOVERY = ("blender_capability_search", "blender_capability_describe", "blender_capability_reset")
MAX_TURNS = 24
REPLY_RESERVE_TOKENS = 256  # room the model needs for its next tool call
PROBE_WINDOW = 65_536
SYSTEM_PROMPT = (
    "You operate Blender through tools. Complete the user's task, then reply with the single word DONE. "
    "If an action you need is not among your tools, find it with blender_capability_search, read it with "
    "blender_capability_describe, then run it with blender_capability_invoke."
)

# Groups that execute Python. A model may use them only with --allow-python.
PYTHON_GROUPS = frozenset({"scripting", "recipes"})

# A scene reset that keeps the bridge running.
RESET_SCENE = """
for block in list(bpy.data.objects):
    bpy.data.objects.remove(block)
for kind in ('meshes', 'materials', 'lights', 'cameras', 'curves'):
    for block in list(getattr(bpy.data, kind)):
        getattr(bpy.data, kind).remove(block)
for collection in list(bpy.data.collections):
    bpy.data.collections.remove(collection)
__result__ = True
"""


@dataclass(frozen=True)
class Task:
    id: str
    prompt: str
    # ("search", words) or ("call", tool, arguments): the shortest sensible solution.
    steps: tuple
    # Python run in Blender after the task; sets __result__ to {check name: bool}.
    checks: str


def _tasks(export_path: str) -> dict[str, Task]:
    blockout = (
        "import bmesh\n"
        "from mathutils import Vector\n"
        "for name, z, size in (('Legs', 0.55, (0.7, 0.35, 1.1)), ('Torso', 1.45, (1.1, 0.5, 0.7)), "
        "('Head', 2.05, (0.45, 0.45, 0.45)), ('Jaw', 1.9, (0.4, 0.5, 0.2))):\n"
        "    mesh = bpy.data.meshes.new(name); bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1)\n"
        "    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts); bm.to_mesh(mesh); bm.free()\n"
        "    obj = bpy.data.objects.new(name, mesh); obj.location.z = z\n"
        "    bpy.context.scene.collection.objects.link(obj)\n"
    )
    tasks = (
        Task(
            "basic-prop",
            "Create a cube named Crate, give it a bevel modifier, then create a brown material and assign it to Crate.",
            (
                ("call", "blender_object_create", {"mesh_type": "cube", "name": "Crate"}),
                ("search", "bevel edges"),
                ("call", "blender_object_add_modifier", {"name": "Crate", "modifier_type": "BEVEL"}),
                ("search", "create and assign material"),
                ("call", "blender_material_create", {"name": "Brown", "color": [0.25, 0.12, 0.05]}),
                ("call", "blender_material_assign", {"object": "Crate", "material": "Brown"}),
                ("search", "check mesh topology"),
                ("call", "blender_mesh_inspect", {"name": "Crate", "source": "evaluated"}),
            ),
            """
crate = bpy.data.objects.get('Crate')
materials = [s.material for s in crate.material_slots if s.material] if crate else []
color = None
if materials:
    node = next((n for n in materials[0].node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if materials[0].use_nodes else None
    color = list(node.inputs['Base Color'].default_value) if node else list(materials[0].diffuse_color)
__result__ = {
    'crate_is_mesh': bool(crate and crate.type == 'MESH'),
    'has_bevel': bool(crate and any(m.type == 'BEVEL' for m in crate.modifiers)),
    'has_material': bool(materials),
    'material_is_brownish': bool(color and color[0] > color[2] and color[0] < 0.8 and color[0] >= color[1]),
}
""",
        ),
        Task(
            "orc-blockout",
            "Block out a standing orc about 2 meters tall from separate simple mesh parts (legs, torso, head, jaw).",
            (
                ("search", "plan how to start an orc"),
                ("call", "blender_workflow", {"task": "stylized orc", "stage": "blockout"}),
                ("search", "read modeling guide"),
                ("call", "blender_guide_get", {"guide": "organic-modeling", "section": "pitfalls"}),
                ("search", "run python script"),
                ("call", "blender_python_exec", {"code": blockout}),
                ("search", "see object picture"),
                ("call", "blender_view_capture", {"object": "Torso", "views": ["front"], "resolution": 128}),
            ),
            """
meshes = [o for o in bpy.context.scene.objects if o.type == 'MESH']
bpy.context.view_layer.update()
corners = [(o.matrix_world @ __import__('mathutils').Vector(c)).z for o in meshes for c in o.bound_box]
__result__ = {
    'at_least_four_parts': len(meshes) >= 4,
    'about_two_meters': bool(corners) and 1.5 <= max(corners) - min(corners) <= 3.0,
}
""",
        ),
        Task(
            "pbr-material",
            "Create a sphere named Orb and give it a metal material named Steel with metallic 1.0 and roughness 0.3.",
            (
                ("call", "blender_object_create", {"mesh_type": "sphere", "name": "Orb"}),
                ("search", "pbr metal material guide"),
                ("call", "blender_guide_get", {"guide": "pbr-materials", "section": "values"}),
                ("search", "run python script"),
                (
                    "call",
                    "blender_python_exec",
                    {
                        "code": "m = bpy.data.materials.new('Steel'); m.use_nodes = True\n"
                        "s = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')\n"
                        "s.inputs['Metallic'].default_value = 1.0; s.inputs['Roughness'].default_value = 0.3"
                    },
                ),
                ("search", "assign material to object"),
                ("call", "blender_material_assign", {"object": "Orb", "material": "Steel"}),
            ),
            """
orb, steel = bpy.data.objects.get('Orb'), bpy.data.materials.get('Steel')
node = next((n for n in steel.node_tree.nodes if n.type == 'BSDF_PRINCIPLED'), None) if steel and steel.use_nodes else None
__result__ = {
    'orb_exists': bool(orb),
    'steel_assigned': bool(orb and steel and any(s.material == steel for s in orb.material_slots)),
    'metallic': bool(node and node.inputs['Metallic'].default_value > 0.95),
    'roughness': bool(node and abs(node.inputs['Roughness'].default_value - 0.3) < 0.05),
}
""",
        ),
        Task(
            "three-point-lighting",
            "Set up three-point lighting around the origin with area lights named Key, Fill and Rim, where Key is the "
            "strongest.",
            (
                ("search", "add lights"),
                (
                    "call",
                    "blender_light_create",
                    {"light_type": "AREA", "name": "Key", "location": [3, -3, 3], "look_at": [0, 0, 0], "energy": 500},
                ),
                (
                    "call",
                    "blender_light_create",
                    {
                        "light_type": "AREA",
                        "name": "Fill",
                        "location": [-3, -2, 1],
                        "look_at": [0, 0, 0],
                        "energy": 150,
                    },
                ),
                (
                    "call",
                    "blender_light_create",
                    {"light_type": "AREA", "name": "Rim", "location": [0, 3, 3], "look_at": [0, 0, 0], "energy": 300},
                ),
                ("call", "blender_scene_list_objects", {"type": "LIGHT"}),
            ),
            """
lights = {name: bpy.data.objects.get(name) for name in ('Key', 'Fill', 'Rim')}
ok = all(o and o.type == 'LIGHT' for o in lights.values())
__result__ = {
    'three_named_lights': ok,
    'all_area': ok and all(o.data.type == 'AREA' for o in lights.values()),
    'key_is_strongest': ok and lights['Key'].data.energy > max(lights['Fill'].data.energy, lights['Rim'].data.energy),
    'distinct_positions': ok and len({tuple(round(v, 1) for v in o.location) for o in lights.values()}) == 3,
}
""",
        ),
        Task(
            "export",
            f"Create a cube named Parcel and export the scene as a GLB file to {export_path}",
            (
                ("call", "blender_object_create", {"mesh_type": "cube", "name": "Parcel"}),
                ("search", "export for game engine"),
                ("call", "blender_export_gltf", {"filepath": export_path}),
            ),
            f"""
import os
__result__ = {{
    'parcel_exists': 'Parcel' in bpy.data.objects,
    'file_written': os.path.isfile({export_path!r}) and os.path.getsize({export_path!r}) > 200,
}}
""",
        ),
    )
    return {task.id: task for task in tasks}


@dataclass
class Metrics:
    task: str
    profile: str
    tools: int = 0
    instructions_bytes: int = 0
    schema_bytes: int = 0
    calls: int = 0
    discovery_calls: int = 0
    request_bytes: int = 0
    response_bytes: int = 0
    structured_duplicate_bytes: int = 0
    images: int = 0
    image_bytes: int = 0
    errors: int = 0
    invalid_argument_errors: int = 0
    repeated_failures: int = 0
    runtime_seconds: float = 0.0
    error_codes: list = field(default_factory=list)

    @property
    def context_bytes(self) -> int:
        """Text a client holds if it keeps everything: instructions, schemas, arguments and results."""
        return self.instructions_bytes + self.schema_bytes + self.request_bytes + self.response_bytes

    def report(self) -> dict:
        data = asdict(self)
        data["context_bytes"] = self.context_bytes
        data["approx_context_tokens"] = math.ceil(self.context_bytes / 4)
        return data


class Session:
    """An MCP client session that counts everything it sends and receives."""

    def __init__(self, client, metrics: Metrics):
        self.client = client
        self.metrics = metrics
        self._failed: str | None = None

    async def tools(self) -> list:
        listed = await self.client.list_tools()
        self.metrics.tools = len(listed.tools)
        self.metrics.schema_bytes = len(listed.model_dump_json(exclude_none=True, by_alias=True).encode())
        return listed.tools

    async def call(self, name: str, arguments: dict) -> tuple[bool, str]:
        metrics = self.metrics
        result = await self.client.call_tool(name, arguments)
        text = "\n".join(block.text for block in result.content if block.type == "text")
        metrics.calls += 1
        target = arguments.get("action", name) if name == "blender_capability_invoke" else name
        metrics.discovery_calls += name in DISCOVERY
        metrics.request_bytes += len(json.dumps({"name": name, "arguments": arguments}).encode())
        metrics.response_bytes += len(text.encode())
        for block in result.content:
            if block.type == "image":
                metrics.images += 1
                metrics.image_bytes += len(block.data)
        if result.structuredContent is not None and not result.isError:
            metrics.structured_duplicate_bytes += len(json.dumps(result.structuredContent).encode())
        failed = result.isError or '"error": "' in text or ('"error":"' in text and "python_exec" in target)
        if failed:
            metrics.errors += 1
            code = ((result.structuredContent or {}).get("error") or {}).get("code", "script_error")
            metrics.error_codes.append(code)
            metrics.invalid_argument_errors += code == "invalid_arguments"
            metrics.repeated_failures += self._failed == target
        self._failed = target if failed else None
        return not failed, text


@contextlib.asynccontextmanager
async def open_session(profile: str, metrics: Metrics, *, allow_python: bool = True):
    previous = mcp.exposure
    allowed = None if allow_python else set(GROUPS) - PYTHON_GROUPS
    mcp.exposure = Exposure.create(profile, allow=allowed)
    mcp._mcp_server._tool_cache.clear()
    try:
        async with create_connected_server_and_client_session(mcp) as client:
            yield Session(client, metrics)
    finally:
        mcp.exposure = previous
        mcp._mcp_server._tool_cache.clear()


async def blender_python(code: str):
    """Run harness code in Blender outside the measured session."""
    connection = BlenderConnection()
    try:
        outcome = await connection.send_command("python.execute", {"code": code})
    finally:
        await connection.disconnect()
    if outcome["error"]:
        raise RuntimeError(f"Harness script failed: {outcome['error']}")
    return outcome["result"]


async def score(task: Task) -> dict:
    checks = await blender_python(task.checks)
    return {"checks": checks, "quality": sum(checks.values()) / len(checks), "success": all(checks.values())}


@contextlib.contextmanager
def offline_bridge():
    """Answer bridge commands with tiny stand-ins, so server-side bytes can be measured without Blender."""
    original = BlenderConnection.send_command

    async def send_command(self, command, params=None, **kwargs):
        self.policy.require_command(command)
        if command == "view.capture":
            return {"views": [{"view": "front"}]}
        if command == "python.execute":
            return {"result": None, "stdout": "", "stderr": "", "error": None}
        return {"offline": command}

    BlenderConnection.send_command = send_command
    try:
        yield
    finally:
        BlenderConnection.send_command = original


async def run_trace(task: Task, profile: str, *, live: bool) -> dict:
    if live:
        await blender_python(RESET_SCENE)
    metrics = Metrics(task.id, profile)
    started = time.monotonic()
    async with open_session(profile, metrics) as session:
        advertised = {tool.name for tool in await session.tools()}
        described: set[str] = set()
        for step in task.steps:
            if step[0] == "search":
                if profile != "full":  # a full client already has every schema
                    await session.call("blender_capability_search", {"query": step[1], "limit": 5})
                continue
            _, tool, arguments = step
            if tool in advertised:
                ok, text = await session.call(tool, arguments)
            else:
                if tool not in described:
                    await session.call("blender_capability_describe", {"actions": [tool]})
                    described.add(tool)
                ok, text = await session.call("blender_capability_invoke", {"action": tool, "arguments": arguments})
            if not ok:
                raise RuntimeError(f"{task.id}/{profile}: {tool} failed: {text[:300]}")
    metrics.runtime_seconds = round(time.monotonic() - started, 2)
    report = metrics.report()
    if live:
        report.update(await score(task))
    return report


def _post(url: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def count_prompt_tokens(url: str, model: str, messages: list, tools: list, budget: int, timeout: float) -> int:
    """The exact prompt size, measured by Ollama in a window too large to truncate it.

    Ollama truncates silently when a prompt exceeds num_ctx, and estimates from byte counts can be
    wrong by half, so neither the real request nor an estimate can detect an overflow reliably.
    """
    reply = _post(
        f"{url.rstrip('/')}/api/chat",
        {
            "model": model,
            "messages": messages,
            "tools": tools,
            "stream": False,
            "options": {"num_ctx": max(budget, PROBE_WINDOW), "num_predict": 1},
        },
        timeout,
    )
    return int(reply["prompt_eval_count"])


def chat(api: str, url: str, model: str, messages: list, tools: list, budget: int, seed: int, timeout: float):
    """One model turn. Returns (assistant message, tool calls, prompt tokens reported by the server)."""
    base = url.rstrip("/")
    if api == "ollama":
        reply = _post(
            f"{base}/api/chat",
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "stream": False,
                "options": {"num_ctx": budget, "temperature": 0, "seed": seed},
            },
            timeout,
        )
        message = reply["message"]
        calls = [(None, c["function"]["name"], c["function"]["arguments"]) for c in message.get("tool_calls") or []]
        return message, calls, reply.get("prompt_eval_count")
    reply = _post(
        f"{base}/chat/completions",
        {"model": model, "messages": messages, "tools": tools, "temperature": 0, "seed": seed},
        timeout,
    )
    message = reply["choices"][0]["message"]
    calls = []
    for call in message.get("tool_calls") or []:
        try:
            arguments = json.loads(call["function"]["arguments"] or "{}")
        except ValueError:
            arguments = {"__unparsable__": True}
        calls.append((call.get("id"), call["function"]["name"], arguments))
    return message, calls, (reply.get("usage") or {}).get("prompt_tokens")


async def run_model(task: Task, profile: str, budget: int, options) -> dict:
    await blender_python(RESET_SCENE)
    metrics = Metrics(task.id, profile)
    started = time.monotonic()
    outcome, peak_tokens, turns = "turn_limit", 0, 0
    transcript: list[dict] = []  # what the model chose, to diagnose tool-selection errors
    async with open_session(profile, metrics, allow_python=options.allow_python) as session:
        tools = [
            {
                "type": "function",
                "function": {"name": tool.name, "description": tool.description, "parameters": tool.inputSchema},
            }
            for tool in await session.tools()
        ]
        messages: list = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": task.prompt}]
        for turns in range(1, options.max_turns + 1):  # noqa: B007 - reported below
            try:
                if options.api == "ollama":
                    needed = await asyncio.to_thread(
                        count_prompt_tokens, options.url, options.model, messages, tools, budget, options.timeout
                    )
                    peak_tokens = max(peak_tokens, needed)
                    if needed > budget - REPLY_RESERVE_TOKENS:
                        outcome = "context_overflow"
                        break
                message, calls, prompt_tokens = await asyncio.to_thread(
                    chat,
                    options.api,
                    options.url,
                    options.model,
                    messages,
                    tools,
                    budget,
                    options.seed,
                    options.timeout,
                )
            except (OSError, ValueError, KeyError) as exc:
                outcome = f"model_server_error: {type(exc).__name__}"
                break
            peak_tokens = max(peak_tokens, prompt_tokens or 0)
            # An OpenAI-compatible server's window is configured outside this script; check what it reports.
            if prompt_tokens and prompt_tokens > budget - REPLY_RESERVE_TOKENS:
                outcome = "context_overflow"
                break
            messages.append(message)
            if not calls:
                outcome = "finished"
                break
            for call_id, name, arguments in calls:
                if not isinstance(arguments, dict):
                    arguments = {"__unparsable__": True}
                try:
                    ok, text = await session.call(name, arguments)
                except Exception as exc:  # a malformed call must not end the evaluation
                    ok, text = False, f"Tool call failed: {type(exc).__name__}"
                    metrics.errors += 1
                transcript.append({"tool": name, "arguments": arguments, "ok": ok, "reply": text[:240]})
                reply = {"role": "tool", "content": text}
                reply.update({"tool_call_id": call_id} if call_id else {"tool_name": name})
                messages.append(reply)
    metrics.runtime_seconds = round(time.monotonic() - started, 1)
    return {
        **metrics.report(),
        "model": options.model,
        "python_allowed": options.allow_python,
        "context_budget_tokens": budget,
        "outcome": outcome,
        "turns": turns,
        "peak_prompt_tokens": peak_tokens,
        "transcript": transcript,
        **await score(task),
    }


async def measure_tool_lists() -> dict[str, tuple[int, int]]:
    """Return {profile: (tool count, bytes of the serialized tools/list result)}."""
    sizes = {}
    for profile in PROFILES:
        metrics = Metrics("sizes", profile)
        async with open_session(profile, metrics) as session:
            await session.tools()
        sizes[profile] = (metrics.tools, metrics.schema_bytes)
    return sizes


def _table(rows: list[dict], columns: list[str]) -> str:
    widths = {c: max(len(c), *(len(str(row.get(c, ""))) for row in rows)) for c in columns}
    lines = ["  ".join(c.ljust(widths[c]) for c in columns)]
    lines += ["  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns) for row in rows]
    return "\n".join(lines)


async def _main(options) -> dict:
    if options.mode == "sizes":
        rows = [
            {"profile": profile, "tools": count, "tools_list_bytes": size, "approx_tokens": math.ceil(size / 4)}
            for profile, (count, size) in (await measure_tool_lists()).items()
        ]
        print(_table(rows, ["profile", "tools", "tools_list_bytes", "approx_tokens"]))
        return {"sizes": rows}

    with tempfile.TemporaryDirectory(prefix="blender-mcp-benchmark-") as directory:
        tasks = _tasks(os.path.join(directory, "parcel.glb"))
        chosen = options.tasks.split(",") if options.tasks else list(tasks)
        if unknown := set(chosen) - set(tasks):
            raise SystemExit(f"Unknown tasks: {', '.join(sorted(unknown))}. Choose from: {', '.join(tasks)}")
        profiles = options.profiles.split(",")
        results = []
        if options.mode == "trace":
            live = options.live
            with contextlib.nullcontext() if live else offline_bridge():
                for name in chosen:
                    for profile in profiles:
                        results.append(await run_trace(tasks[name], profile, live=live))
            columns = ["task", "profile", "schema_bytes", "calls", "discovery_calls", "response_bytes", "context_bytes"]
            columns += ["approx_context_tokens", "images", "quality"] if live else ["approx_context_tokens"]
        else:
            for budget in [int(value) for value in options.budgets.split(",")]:
                for name in chosen:
                    for profile in profiles:
                        result = await run_model(tasks[name], profile, budget, options)
                        results.append(result)
                        print(
                            f"{name} {profile} budget={budget}: {result['outcome']} quality={result['quality']:.2f} "
                            f"calls={result['calls']} errors={result['errors']}",
                            file=sys.stderr,
                            flush=True,
                        )
            columns = ["task", "profile", "context_budget_tokens", "outcome", "quality", "success", "turns", "calls"]
            columns += ["errors", "invalid_argument_errors", "peak_prompt_tokens", "context_bytes", "runtime_seconds"]
    print(_table(results, columns))
    return {"mode": options.mode, "live": getattr(options, "live", True), "results": results}


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["sizes", "trace", "model"])
    parser.add_argument("--tasks", help="Comma-separated task IDs (default: all)")
    parser.add_argument("--profiles", default="compact,full")
    parser.add_argument("--live", action="store_true", help="trace: use a running Blender and score the scene")
    parser.add_argument("--model", help="model: model name on the local server")
    parser.add_argument("--api", choices=["ollama", "openai"], default="ollama")
    parser.add_argument("--url", default="http://127.0.0.1:11434", help="Model server (OpenAI: include /v1)")
    parser.add_argument("--budgets", default="8192,32768", help="Context windows in tokens")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument("--allow-python", action="store_true", help="model: let the model run Python in Blender")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=600, help="Seconds to wait for one model reply")
    parser.add_argument("--json", help="Also write the full results to this file")
    options = parser.parse_args(argv)
    if options.mode == "model" and not options.model:
        parser.error("model mode needs --model")
    return options


def main(argv: list[str] | None = None) -> None:
    options = parse_arguments(argv)
    logging.disable(logging.INFO)
    report = asyncio.run(_main(options))
    if options.json:
        with open(options.json, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2)


if __name__ == "__main__":
    main()
