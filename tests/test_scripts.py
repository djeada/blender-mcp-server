"""Tests for the helpers behind scripts/setup.sh, start.sh and record_demos.sh."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, LIB / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


client_config = _load("client_config")
demo_record = _load("demo_record")


class TestClientConfig:
    def test_claude_mcp_config(self, tmp_path):
        out = tmp_path / "mcp.json"
        client_config.main(["claude-json", str(out), "/venv/bin/server", "BLENDER_MCP_PORT=9877", "A=b=c"])
        server = json.loads(out.read_text())["mcpServers"]["blender"]
        assert server["command"] == "/venv/bin/server"
        assert server["env"] == {"BLENDER_MCP_PORT": "9877", "A": "b=c"}

    def test_codex_env_is_inline_toml(self, capsys):
        client_config.main(["codex-env", "BLENDER_MCP_PORT=9877", 'P=/a "b"'])
        assert capsys.readouterr().out.strip() == '{BLENDER_MCP_PORT = "9877", P = "/a \\"b\\""}'

    def test_claude_desktop_merge_keeps_other_servers_and_backs_up(self, tmp_path):
        config = tmp_path / "claude_desktop_config.json"
        config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
        client_config.main(["claude-desktop", str(config), "/venv/bin/server", "K=V"])
        data = json.loads(config.read_text())
        assert data["theme"] == "dark"
        assert data["mcpServers"]["other"] == {"command": "x"}
        assert data["mcpServers"]["blender"] == {"command": "/venv/bin/server", "env": {"K": "V"}}
        assert (tmp_path / "claude_desktop_config.json.bak").exists()


DEMO = """# Demo

<!-- prompt:start -->
```text
Build a cube
and render it.
```
<!-- prompt:end -->

<!-- record:start -->
old
<!-- record:end -->
"""


class TestDemoRecord:
    def test_prompt_is_extracted_as_one_line(self, tmp_path):
        demo = tmp_path / "demo.md"
        demo.write_text(DEMO)
        assert demo_record.read_prompt(demo) == "Build a cube and render it."

    def test_claude_transcript_keeps_only_blender_calls(self, tmp_path):
        events = [
            {"type": "system", "subtype": "init", "model": "m1"},
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "1", "name": "Read", "input": {}},
                        {
                            "type": "tool_use",
                            "id": "2",
                            "name": "mcp__blender__blender_python_exec",
                            "input": {"code": "a\nb"},
                        },
                    ]
                },
            },
            {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "1", "is_error": True}]}},
            {"type": "result", "result": "Done, see [render](</tmp/x.png>).", "duration_ms": 4000},
        ]
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("\n".join(json.dumps(e) for e in events))
        demo = tmp_path / "demo.md"
        demo.write_text(DEMO)
        demo_record.update(demo, transcript, "claude", "1.0")
        text = demo.read_text()
        assert "1 Blender tool calls" in text
        assert "returned an error" not in text  # the failing call was Read, not Blender
        assert "`blender_python_exec` — Python, 2 lines" in text
        assert "Done, see render." in text
        assert "old" not in text

    def test_codex_transcript(self):
        events = [
            {
                "type": "item.completed",
                "item": {
                    "type": "mcp_tool_call",
                    "server": "blender",
                    "tool": "blender_render_still",
                    "arguments": '{"output_path": "/tmp/a.png"}',
                },
            },
            {
                "type": "item.completed",
                "item": {"type": "mcp_tool_call", "server": "other", "tool": "x", "arguments": {}},
            },
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Rendered."}},
        ]
        parsed = demo_record.parse_codex(events)
        assert parsed["calls"] == [("blender_render_still", {"output_path": "/tmp/a.png"})]
        assert parsed["answer"] == "Rendered."

    def test_update_refuses_transcript_without_blender_calls(self, tmp_path):
        transcript = tmp_path / "t.jsonl"
        transcript.write_text("")
        demo = tmp_path / "demo.md"
        demo.write_text(DEMO)
        with pytest.raises(SystemExit):
            demo_record.update(demo, transcript, "claude", "1.0")
        assert demo.read_text() == DEMO
