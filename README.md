# Blender MCP Server

Control Blender from any AI assistant using the [Model Context Protocol (MCP)](https://modelcontextprotocol.io).

27 tools across 7 namespaces — create objects, assign materials, render images, export scenes, execute Python scripts, manage async jobs, and more.

![Demo render — scene built entirely through MCP tools](docs/images/demo_render.png)

## How It Works

```
┌─────────────┐      stdio       ┌──────────────────┐    JSON/TCP     ┌─────────────────┐
│  MCP Client │ ◄──────────────► │  MCP Server      │ ◄─────────────► │  Blender Add-on │
│  (any host) │                  │  (Python)        │  localhost:9876 │  (runs in bpy)  │
└─────────────┘                  └──────────────────┘                 └─────────────────┘
```

1. The **Blender add-on** runs inside Blender and listens on `localhost:9876`.
2. The **MCP server** connects to your AI client via stdio and forwards tool calls to Blender over TCP.
   Every request carries a shared secret that the add-on writes to `~/.blender-mcp/token` (mode `0600`).
3. You ask the AI → it calls MCP tools → Blender executes commands → results flow back.

## Quick Start (macOS & Linux)

Install [Blender](https://www.blender.org/download/) 3.6+ and Python 3.10+, then:

```bash
git clone https://github.com/djeada/blender-mcp-server.git
cd blender-mcp-server
scripts/setup.sh              # venv + MCP server, installs and enables the Blender add-on
scripts/start.sh claude       # opens Blender and a Claude Code session already connected to it
```

`scripts/start.sh codex` does the same with Codex, and `scripts/start.sh none` just opens Blender
with the bridge running. Anything after the client name goes to the client, e.g.
`scripts/start.sh claude "Build a snowman and render it"`. Stop the Blender it opened with `scripts/stop.sh`.

`start.sh` hands the MCP server to the client on the command line, so it changes no client config. To
register the server permanently instead, run `scripts/setup.sh --register claude,codex,claude-desktop`.
The scripts find Blender on your `PATH`, in `/Applications/Blender.app`, or via `BLENDER_BIN`.

## Demos

Each demo is one prompt, recorded end to end against a live Blender. `scripts/record_demos.sh`
re-records them. Every demo also has a plain Blender Python script, so you can build the same kind of
scene without an AI: `scripts/run_demo.sh 1` (GUI), `--background 1` (render only), or `--bridge 1`
(send it through the MCP bridge to the Blender that `start.sh` opened).

| | Demo | Client |
|---|---|---|
| <img src="docs/demos/images/01-still-life.png" width="240"> | [Still life from a sentence](docs/demos/01-still-life.md): object, material and render tools | Claude Code |
| <img src="docs/demos/images/02-city.png" width="240"> | [Procedural city with Python](docs/demos/02-procedural-city.md): `blender_python_exec` | Codex |
| <img src="docs/demos/images/03-frame-024.png" width="240"> | [Animate live, render headless](docs/demos/03-animation-headless.md): keyframes, then `transport="headless"` | Claude Code |

## Manual Setup

### 1. Install the MCP Server

```bash
git clone https://github.com/djeada/blender-mcp-server.git
cd blender-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This creates the executable `.venv/bin/blender-mcp-server`.

### 2. Install the Blender Add-on

Download `blender_mcp_bridge.zip` from the [latest release](https://github.com/djeada/blender-mcp-server/releases/latest), or build it yourself:

```bash
./scripts/build_addon_zip.sh
```

Then in Blender:

1. Go to **Edit → Preferences → Add-ons → Install from Disk** (Blender 4.2+ installs it as an extension; older versions as a legacy add-on).
2. Select `dist/blender_mcp_bridge.zip` and enable **Blender MCP Bridge**.
3. In the 3D Viewport, press **N** → open the **MCP** tab.
4. Confirm it shows **Listening on 127.0.0.1:9876**.

### 3. Connect Your MCP Client

<details>
<summary><strong>Claude Desktop</strong></summary>

Add to your config file:

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "blender": {
      "command": "/absolute/path/to/blender-mcp-server/.venv/bin/blender-mcp-server"
    }
  }
}
```

Replace the path with the actual location of your clone.

</details>

<details>
<summary><strong>Codex CLI</strong></summary>

Register the server once:

```bash
codex mcp add blender -- /absolute/path/to/blender-mcp-server/.venv/bin/blender-mcp-server
```

Verify with `codex mcp list`. Then start Codex from any directory — it launches the server automatically.

</details>

<details>
<summary><strong>Other MCP clients</strong></summary>

Point any MCP-compatible client at the server executable:

```
/absolute/path/to/blender-mcp-server/.venv/bin/blender-mcp-server
```

The server uses **stdio** transport. No additional flags are needed.

</details>

<details>
<summary><strong>Environment variables</strong></summary>

| Variable | Default | Purpose |
|---|---|---|
| `BLENDER_MCP_HOST` | `127.0.0.1` | Bridge host |
| `BLENDER_MCP_PORT` | `9876` | Bridge port (match the add-on's **Port** preference) |
| `BLENDER_MCP_TOKEN` | — | Auth token; overrides the token file (set it for both Blender and the server) |
| `BLENDER_MCP_TOKEN_FILE` | `~/.blender-mcp/token` | Where the add-on writes and the server reads the token |
| `BLENDER_MCP_TIMEOUT` | none | Seconds to wait for a bridge response before giving up |
| `BLENDER_BIN` | `blender` | Blender binary for `transport="headless"` |
| `BLENDER_MCP_HEADLESS` | `1` | Set to `0` to disable the headless transport |
| `BLENDER_MCP_HEADLESS_TIMEOUT` | `3600` | Default timeout (seconds) for headless runs |

</details>

<details>
<summary><strong>Docker</strong></summary>

The image contains only the MCP server. For the bridge transport, share the host network and mount the token:

```bash
docker build -t blender-mcp-server .
docker run -i --rm --network host \
  -v ~/.blender-mcp/token:/home/mcp/.blender-mcp/token:ro blender-mcp-server
```

For the headless transport, mount a Blender install and set `BLENDER_BIN`.

</details>

### 4. Start Using It

Make sure Blender is open with the add-on listening, then ask your AI assistant:

- *"What objects are in my Blender scene?"*
- *"Create a cube named TestCube at [0, 0, 1]"*
- *"Render the scene to /tmp/render.png"*

The AI calls MCP tools like `blender_scene_list_objects` and `blender_object_create`, which the server forwards to Blender.

## Example Prompts

<details>
<summary><strong>🔍 Inspecting your scene</strong></summary>

- *"What objects are in my scene?"*
- *"Show me the transform of the Camera object"*
- *"List all materials in the file"*

</details>

<details>
<summary><strong>🔨 Creating objects</strong></summary>

- *"Create a sphere named 'Earth' at position [0, 0, 2] with size 3"*
- *"Add a cylinder at the origin, then scale it to [0.5, 0.5, 4] to make a tall pillar"*
- *"Create 5 cubes in a row spaced 3 units apart"*

</details>

<details>
<summary><strong>🎨 Materials & colors</strong></summary>

- *"Create a red material and assign it to the Cube"*
- *"Make a material called 'Ocean' with color [0.0, 0.3, 0.8] and assign it to the Sphere"*
- *"Change the color of 'RedMaterial' to orange"*

</details>

<details>
<summary><strong>📐 Transforming objects</strong></summary>

- *"Move the Cube up 2 units on the Z axis"*
- *"Rotate the Cylinder 45 degrees on the Z axis"*
- *"Scale the Sphere to [2, 2, 2]"*

</details>

<details>
<summary><strong>📸 Rendering & exporting</strong></summary>

- *"Render the scene at 1920×1080 and save it to /tmp/render.png"*
- *"Export the scene as a GLB file to /tmp/scene.glb"*

</details>

<details>
<summary><strong>🐍 Python execution</strong></summary>

- *"Run this Blender Python: `bpy.ops.mesh.primitive_monkey_add(location=(0,0,2))`"*
- *"Execute the fluid_domain.py script from the library with resolution 128"*
- *"Start an async bake job for the fluid simulation and tell me the job ID"*

</details>

<details>
<summary><strong>⏪ Undo / Redo</strong></summary>

- *"Undo the last change"*
- *"Redo what was just undone"*

</details>

## Tool Reference

### Scene Inspection

| Tool | Description |
|---|---|
| `blender_scene_get_info` | Scene metadata — name, frame range, render engine, resolution, object count |
| `blender_scene_list_objects` | List all objects, optionally filter by type (`MESH`, `CAMERA`, `LIGHT`, …) |
| `blender_object_get_transform` | Get position, rotation, and scale of an object by name |
| `blender_object_get_hierarchy` | Parent/child hierarchy tree (full scene or subtree) |

### Object Manipulation

| Tool | Description |
|---|---|
| `blender_object_create` | Create primitives: `cube`, `sphere`, `cylinder`, `plane`, `cone`, `torus` |
| `blender_object_delete` | Delete an object by name |
| `blender_object_translate` | Move — absolute `location` or relative `offset` |
| `blender_object_rotate` | Set rotation `[x, y, z]` in degrees (default) or radians |
| `blender_object_scale` | Set scale `[x, y, z]` |
| `blender_object_duplicate` | Duplicate with optional new name |

### Materials

| Tool | Description |
|---|---|
| `blender_material_list` | List all materials in the file |
| `blender_material_create` | Create a material with optional base color `[r, g, b]` (0–1) |
| `blender_material_assign` | Assign a material to an object |
| `blender_material_set_color` | Set the Principled BSDF base color |
| `blender_material_set_texture` | Set an image texture as base color |

### Rendering & Export

| Tool | Description |
|---|---|
| `blender_render_still` | Render still image — output path, resolution, engine |
| `blender_render_animation` | Render animation — frame range, output path, engine |
| `blender_export_gltf` | Export as glTF/GLB |
| `blender_export_obj` | Export as OBJ |
| `blender_export_fbx` | Export as FBX |

### History

| Tool | Description |
|---|---|
| `blender_history_undo` | Undo the last operation |
| `blender_history_redo` | Redo the last undone operation |

### Python Execution

| Tool | Description |
|---|---|
| `blender_python_exec` | Run a Python script synchronously. Accepts `code` or `script_path`, optional `args`, `timeout_seconds`, and `transport` (`bridge` or `headless`). |
| `blender_python_exec_async` | Start a long-running script asynchronously. Returns a `job_id`. |
| `blender_job_status` | Poll an async job's status, result, stdout, stderr, and error. |
| `blender_job_cancel` | Cancel a running or queued async job. |
| `blender_job_list` | List known async jobs with IDs, status, and creation time. |

## Script Library

Pre-built scripts in `scripts/library/` for use with `blender_python_exec` via `script_path`:

| Script | Description |
|---|---|
| `create_mesh.py` | Create primitive meshes through the data API (no `bpy.ops`) |
| `fluid_domain.py` | Create a Mantaflow fluid domain |
| `fluid_inflow.py` | Create an inflow source |
| `effector.py` | Set objects as collision effectors |
| `rigid_body.py` | Add rigid body physics |
| `frame_range.py` | Set scene frame range |
| `camera.py` | Create and configure a camera |
| `keyframes.py` | Insert transform keyframes |
| `collections.py` | Organize objects into collections |
| `apply_transforms.py` | Apply transforms to objects |
| `save_blend.py` | Save the `.blend` file |

See [`scripts/library/README.md`](scripts/library/README.md) for full argument docs and a dam-break walkthrough.

> **Tips for physics workflows:**
> - Prefer `create_mesh.py` (data API) over `bpy.ops.mesh.primitive_*_add` in live sessions — the operator path can destabilize view-layer updates around fluid setup.
> - Keep Mantaflow liquid modifiers hidden in the viewport to avoid crashes in Blender 4.x.
> - Use `transport="headless"` for heavy physics bakes — this runs scripts in a separate `blender -b` process.

## Safety & Security

`blender_python_exec` runs arbitrary Python inside Blender, so anything that can talk to the bridge can run code as you.
The bridge is therefore locked to clients that can read your token file.

| Feature | Description |
|---|---|
| **Token authentication** | Every bridge request must carry the secret from `~/.blender-mcp/token` (created `0600`). Unauthenticated connections are dropped. |
| **Strict framing** | The first malformed line closes the connection, so a web page cannot smuggle a command inside an HTTP request to `localhost`. |
| **Automatic undo push** | Mutation tools push an undo step before executing (Python exec excluded for stability). |
| **Safe Mode** | Restricts render/export/texture paths to the approved roots (or the saved `.blend` file's folder) and disables inline code. |
| **Allowed Commands** | Optional allowlist of bridge commands (e.g. read-only tools only). |
| **Script path restrictions** | `script_path` must be under the approved roots; symlinks are resolved. With no roots and an unsaved file, scripts are refused. |
| **Inline code toggle** | Disable inline code execution via add-on preferences. |
| **Module blocklist** | Imports of `subprocess`, `socket`, `webbrowser`, `ctypes`, `multiprocessing` fail by default. This is a speed bump, **not a sandbox**: `os`, `importlib`, and file access remain available. |

The headless transport runs in a separate `blender -b` process under the MCP server's user and is not subject to the
add-on's preferences. Set `BLENDER_MCP_HEADLESS=0` to turn it off.

## Add-on Preferences

In Blender → **Edit → Preferences → Add-ons → Blender MCP Bridge**:

| Setting | Default | Description |
|---|---|---|
| Safe Mode | Off | Restrict file paths to the approved roots and disable inline code |
| Port | 9876 | TCP port for the MCP bridge (the bridge rebinds on change; set `BLENDER_MCP_PORT` for the server) |
| Allowed Commands | *(empty = all)* | Comma-separated bridge commands to accept, e.g. `scene.get_info,scene.list_objects` |
| Allow Inline Code | On | Allow `python.execute` to run inline code strings |
| Approved Script Roots | *(saved blend file dir)* | Semicolon-separated directories for script file access |

The preferences panel also shows where the auth token file lives.

## Advanced Usage

<details>
<summary><strong>Direct bridge testing (no MCP client)</strong></summary>

The helper scripts in `scripts/` connect directly to the Blender add-on on `127.0.0.1:9876`, bypassing the MCP server entirely. Useful for verifying the add-on works:

```bash
python3 scripts/blender_scene_info.py
python3 scripts/blender_create_test_cube.py --name TestCube --x 0 --y 0 --z 1 --size 2
python3 scripts/blender_bridge_request.py scene.get_info
python3 scripts/blender_bridge_request.py object.translate --params '{"name":"TestCube","offset":[0,0,2]}'
```

All scripts accept `--host`, `--port`, and `--timeout` flags, and read the auth token the same way the server does.

</details>

<details>
<summary><strong>Headless / background mode</strong></summary>

For one-off scripts and renders you don't need the add-on at all: pass `transport="headless"` to
`blender_python_exec`, `blender_python_exec_async`, or the render tools and the server runs a separate
`blender -b` process.

To serve the bridge from background Blender, note that `bpy.app.timers` does not fire after the startup
script returns, so the script has to drain the request queue itself. See
[`tests/integration/blender_bridge_harness.py`](tests/integration/blender_bridge_harness.py):

```bash
BLENDER_MCP_PORT=9876 blender -b --factory-startup --python tests/integration/blender_bridge_harness.py
```

</details>

<details>
<summary><strong>Programmatic tool call examples</strong></summary>

**Inline code — create a fluid domain:**

```json
{
  "tool": "blender_python_exec",
  "args": {
    "code": "import bpy\nbpy.ops.mesh.primitive_cube_add(size=4, location=(0,0,2))\ndomain = bpy.context.active_object\ndomain.name = 'FluidDomain'\nbpy.ops.object.modifier_add(type='FLUID')\ndomain.modifiers['Fluid'].fluid_type = 'DOMAIN'\nsettings = domain.modifiers['Fluid'].domain_settings\nsettings.domain_type = 'LIQUID'\nsettings.resolution_max = 64\n__result__ = {'domain': domain.name, 'resolution': 64}",
    "args": {"resolution": 64}
  }
}
```

**Script file — set up colliders:**

```json
{
  "tool": "blender_python_exec",
  "args": {
    "script_path": "scripts/library/effector.py",
    "args": {
      "objects": ["Ground", "Building_01", "Building_02"],
      "effector_type": "COLLISION"
    }
  }
}
```

**Async bake and poll:**

```json
{"tool": "blender_python_exec_async", "args": {"code": "import bpy\nbpy.ops.fluid.bake_all()\n__result__ = {'baked': True}", "timeout_seconds": 1800}}
```

→ `{"job_id": "job-f8e2a1b3"}`

```json
{"tool": "blender_job_status", "args": {"job_id": "job-f8e2a1b3"}}
```

</details>

## Development

```bash
git clone https://github.com/djeada/blender-mcp-server.git
cd blender-mcp-server
pip install -e ".[dev]"

pytest -v                                                    # unit tests, no Blender needed
BLENDER_MCP_INTEGRATION=1 pytest tests/integration --no-cov  # end-to-end against real Blender
```

### Project Structure

```
blender-mcp-server/
├── addon/                        # Blender add-on (TCP server + command handlers + job manager)
├── src/blender_mcp_server/       # MCP server (stdio transport + tool definitions)
├── scripts/
│   ├── setup.sh / start.sh / stop.sh  # One-command install and launch (macOS & Linux)
│   ├── run_demo.sh               # Run a demo scene script yourself (no AI)
│   ├── record_demos.sh           # Re-record docs/demos with a real AI client
│   ├── library/                  # Reusable Blender scripts for common tasks
│   ├── demos/                    # Bridge-driven dam-break demo scenes
│   └── blender_bridge_request.py # Direct bridge test helpers
├── tests/                        # Unit tests (mocked bpy) + integration tests (real Blender)
├── docs/                         # Architecture & design docs, recorded demos
├── pyproject.toml
└── README.md
```

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Add tests for your changes.
4. Run `pytest tests/ -v` to verify all tests pass.
5. Submit a pull request.

## License

MIT
