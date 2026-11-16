# Setup and client configuration

Install Python 3.10+ and Blender 3.6+. Clone the repository before using the scripts. Blender 3.6–4.1 use the legacy add-on. Blender 4.2+ use the extension from the same archive.

## macOS and Linux

Run `./scripts/setup.sh` to create the virtual environment and enable the add-on. Set `BLENDER_BIN` or pass `--blender /absolute/path/to/blender` when Blender is outside the normal install locations. Start with `./scripts/start.sh codex`, `./scripts/start.sh claude`, or `./scripts/start.sh none`. For permanent MCP client registration, run `./scripts/setup.sh --register claude,codex,claude-desktop`.

## Windows

From the repository root in PowerShell, run the setup, start, and status commands.

```powershell
.\scripts\windows.ps1 Setup
.\scripts\windows.ps1 Start
.\scripts\windows.ps1 Status
```

Setup discovers `blender.exe` on PATH or under Program Files, installs the Python server in `.venv`, enables the add-on in Blender's user profile, and creates a private token at `%LOCALAPPDATA%\BlenderMCP\token`. It reports the generated client config at `.venv\blender-mcp.json`. Close Blender before running Setup. If Blender is installed elsewhere or needs a different port, pass the settings to Setup once.

```powershell
.\scripts\windows.ps1 Setup -Blender 'D:\Apps\Blender\blender.exe' -Port 19876
```

Use `-Python 'C:\path\to\python.exe'` to select a different Python. For a custom `-TokenFile`, create a private local NTFS directory first. Setup checks file ownership and applies a user-only ACL to the token. If setup reports that the token is empty, remove that file and rerun setup. Keep credentials in the token file. The generated client config contains its path.

Open the MCP panel in Blender through **3D Viewport → N → MCP**. Once the panel shows **Listening**, the `Status` command should print `"success": true` and the scene name. Run `.\scripts\windows.ps1 Stop` to request shutdown of the instance launched by the script. Respond to Blender's save dialog if it appears.

For Claude Desktop, merge the generated `mcpServers.blender` entry into `%APPDATA%\Claude\claude_desktop_config.json` and restart Claude Desktop. For Claude Code, pass the generated file to `claude --mcp-config .venv/blender-mcp.json`. For Codex, use the same port and token file shown in `.venv\blender-mcp.json`.

```powershell
$entry = (Get-Content .venv/blender-mcp.json -Raw | ConvertFrom-Json).mcpServers.blender
codex mcp add blender --env "BLENDER_MCP_PORT=$($entry.env.BLENDER_MCP_PORT)" --env "BLENDER_MCP_TOKEN_FILE=$($entry.env.BLENDER_MCP_TOKEN_FILE)" -- $entry.command
codex mcp list
```

With a shared policy, also pass `BLENDER_MCP_POLICY_FILE` to Codex and the Blender launcher. If you set it during Setup, Claude's generated entry already carries it. Set `BLENDER_BIN` for a client using headless Blender when the executable is outside PATH.

## Manual install

1. Create a venv with `python -m venv .venv` and install the repo with the venv's Python using `python -m pip install -e .`.
2. Download `blender_mcp_bridge.zip` from the [releases](https://github.com/djeada/blender-mcp-server/releases), or run `python scripts/build_addon_zip.py` to build it.
3. In Blender Preferences, install the archive from disk and enable **Blender MCP Bridge**. Look for the listener in **3D Viewport → N → MCP**.
4. Point the client at the venv's `blender-mcp-server` executable. Use `.venv/bin/blender-mcp-server` on POSIX and `.venv\Scripts\blender-mcp-server.exe` on Windows. The client launches it over stdio.

On Linux, the Docker image can reach a local Blender bridge over host networking. Run it as the user who can read the mounted private token.

```sh
docker build -t blender-mcp-server .
docker run -i --rm --network host --user "$(id -u):$(id -g)" \
  -v "$HOME/.blender-mcp/token:/home/mcp/.blender-mcp/token:ro" blender-mcp-server
```

For headless Docker, mount a Blender installation and the approved project directories. Set `BLENDER_BIN` and use the policy in [Policy and recovery](policy.md).
