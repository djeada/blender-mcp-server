"""Write MCP client configuration for scripts/setup.sh and scripts/start.sh.

client_config.py claude-json OUT SERVER [KEY=VALUE ...]        # file for `claude --mcp-config`
client_config.py server-json SERVER [KEY=VALUE ...]            # one server, for `claude mcp add-json`
client_config.py codex-env [KEY=VALUE ...]                     # inline TOML table for `codex -c`
client_config.py claude-desktop CONFIG SERVER [KEY=VALUE ...]  # merge into Claude Desktop config
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _env(pairs: list[str]) -> dict[str, str]:
    return dict(pair.split("=", 1) for pair in pairs if "=" in pair)


def _stdio_server(command: str, env: dict[str, str]) -> dict:
    return {"type": "stdio", "command": command, "args": [], "env": env}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    action, rest = argv[0], argv[1:]
    if action == "claude-json":
        out, server, env = Path(rest[0]), rest[1], _env(rest[2:])
        config = {"mcpServers": {"blender": _stdio_server(server, env)}}
        out.write_text(json.dumps(config, indent=2) + "\n")
    elif action == "server-json":
        print(json.dumps(_stdio_server(rest[0], _env(rest[1:]))))
    elif action == "codex-env":
        env = _env(rest)
        print("{" + ", ".join(f"{key} = {json.dumps(value)}" for key, value in env.items()) + "}")
    elif action == "claude-desktop":
        path, server, env = Path(rest[0]), rest[1], _env(rest[2:])
        data = json.loads(path.read_text()) if path.exists() and path.read_text().strip() else {}
        if path.exists():
            shutil.copy2(path, path.with_name(path.name + ".bak"))
        data.setdefault("mcpServers", {})["blender"] = {"command": server, "env": env}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
