"""Helpers for scripts/record_demos.sh.

demo_record.py prompt DEMO.md                            # print the demo's prompt
demo_record.py update DEMO.md TRANSCRIPT CLIENT VERSION  # rewrite the "What the agent did" section
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

PROMPT_RE = re.compile(r"<!-- prompt:start -->\s*```text\n(.*?)\n```\s*<!-- prompt:end -->", re.S)
RECORD_RE = re.compile(r"(<!-- record:start -->\n).*?(\n<!-- record:end -->)", re.S)


def read_prompt(demo: Path) -> str:
    match = PROMPT_RE.search(demo.read_text())
    if not match:
        raise SystemExit(f"{demo}: no <!-- prompt:start --> ```text block found")
    return " ".join(match.group(1).split())


def _events(transcript: Path) -> list[dict]:
    events = []
    for line in transcript.read_text(errors="replace").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def parse_claude(events: list[dict]) -> dict:
    """Blender MCP calls only; the client's own tools (Read, ToolSearch, ...) are left out."""
    calls, errors, answer, meta = [], 0, "", {}
    blender_ids: set[str] = set()
    for event in events:
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            meta["model"] = event.get("model")
        elif kind == "assistant":
            for block in event.get("message", {}).get("content", []):
                if block.get("type") == "tool_use" and block.get("name", "").startswith("mcp__blender__"):
                    blender_ids.add(block.get("id"))
                    calls.append((block["name"].split("__")[-1], block.get("input", {})))
        elif kind == "user":
            content = event.get("message", {}).get("content", [])
            if isinstance(content, list):
                errors += sum(
                    1
                    for block in content
                    if block.get("type") == "tool_result"
                    and block.get("is_error")
                    and block.get("tool_use_id") in blender_ids
                )
        elif kind == "result":
            answer = event.get("result", "")
            meta["turns"] = event.get("num_turns")
            meta["seconds"] = round(event.get("duration_ms", 0) / 1000)
            meta["ok"] = not event.get("is_error")
    return {"calls": calls, "errors": errors, "answer": answer, "meta": meta}


def parse_codex(events: list[dict]) -> dict:
    calls, errors, answer, meta = [], 0, "", {"ok": True}
    for event in events:
        item = event.get("item") or {}
        if event.get("type") != "item.completed":
            continue
        if item.get("type") == "mcp_tool_call" and item.get("server", "blender") == "blender":
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": arguments}
            calls.append((item.get("tool", ""), arguments or {}))
            errors += 1 if item.get("status") == "failed" or item.get("error") else 0
        elif item.get("type") == "agent_message":
            answer = item.get("text", answer)
    return {"calls": calls, "errors": errors, "answer": answer, "meta": meta}


def _describe(tool: str, args: dict) -> str:
    code = args.get("code")
    shown = {key: value for key, value in args.items() if key != "code"}
    text = f"`{tool}`"
    if shown:
        compact = json.dumps(shown, separators=(", ", ": "))
        text += f" `{compact[:150] + ('…' if len(compact) > 150 else '')}`"
    if code:
        lines = code.strip().splitlines()
        text += f" — Python, {len(lines)} lines"
    return text


def render_record(parsed: dict, client: str, version: str) -> str:
    calls = parsed["calls"]
    meta = parsed["meta"]
    head = f"Recorded {date.today().isoformat()} with **{client}** `{version}`"
    if meta.get("model"):
        head += f" (model `{meta['model']}`)"
    stats = f"{len(calls)} Blender tool calls"
    if parsed["errors"]:
        stats += f", {parsed['errors']} returned an error the agent then worked around"
    if meta.get("seconds"):
        stats += f", {meta['seconds']} s end to end"
    out = [head + ". " + stats + ".", "", "### Tool calls", ""]
    for index, (tool, args) in enumerate(calls, 1):
        out.append(f"{index}. {_describe(tool, args)}")
    scripts = [(tool, args["code"]) for tool, args in calls if args.get("code")]
    if scripts:
        tool, code = max(scripts, key=lambda item: len(item[1]))
        out += [
            "",
            "<details><summary>Largest Python script the agent ran</summary>",
            "",
            "```python",
            code.strip(),
            "```",
            "",
            "</details>",
        ]
    # Links to local files (e.g. the render in /tmp) are dead on GitHub; keep only their text.
    answer = re.sub(r"\[([^\]]+)\]\(<?/[^)>]*>?\)", r"\1", parsed["answer"]).strip()
    if answer:
        out += ["", "### Agent's reply", ""] + [f"> {line}" if line else ">" for line in answer.splitlines()]
    return "\n".join(out)


def update(demo: Path, transcript: Path, client: str, version: str) -> None:
    events = _events(transcript)
    parsed = parse_codex(events) if client == "codex" else parse_claude(events)
    if not parsed["calls"]:
        raise SystemExit(f"{transcript}: no Blender tool calls found; not updating {demo}")
    body = render_record(parsed, client, version)
    text = demo.read_text()
    demo.write_text(RECORD_RE.sub(lambda m: m.group(1) + body + m.group(2), text))
    print(f"{demo}: {len(parsed['calls'])} tool calls recorded")


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "prompt":
        print(read_prompt(Path(argv[1])))
        return 0
    if len(argv) == 5 and argv[0] == "update":
        update(Path(argv[1]), Path(argv[2]), argv[3], argv[4])
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
