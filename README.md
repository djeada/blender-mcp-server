# Blender MCP Server

Control Blender from AI assistants like Claude Desktop using the [Model Context Protocol (MCP)](https://modelcontextprotocol.io).

**27 tools** across 7 namespaces — create objects, assign materials, render images, export scenes, execute Python scripts, manage async jobs, and more, all through natural language.

![Demo render — scene built entirely through MCP tools](docs/images/demo_render.png)

*Scene above was created entirely through MCP commands: orange cube, blue sphere, stretched cylinder, and cone — with materials, transforms, and lighting.*

## How It Works

```
┌─────────────────┐      stdio       ┌──────────────────────┐    JSON/TCP     ┌────────────────────┐
│  Claude Desktop │ ◄──────────────► │  MCP Server (Python) │ ◄─────────────► │  Blender Add-on    │
│  (MCP Client)   │                  │  src/server.py       │  localhost:9876 │  (runs in Blender) │
└─────────────────┘                  └──────────────────────┘                 └────────────────────┘
```

1. The **Blender add-on** runs inside Blender, opening a TCP socket on `localhost:9876`
2. The **MCP server** connects to Claude Desktop via stdio and forwards tool calls to Blender over TCP
3. You talk to Claude → Claude calls MCP tools → Blender executes commands → results flow back

There are two ways to talk to Blender:

1. **Via an MCP client** such as Claude Desktop or Codex:
   `MCP client → blender-mcp-server (stdio) → Blender add-on (TCP) → bpy`
2. **Via the direct test scripts** in `scripts/`:
   `script → Blender add-on (TCP) → bpy`

The helper scripts in `scripts/` do **not** use MCP. They connect directly to the Blender add-on on `127.0.0.1:9876` for local testing.

## Quick Start

This is the recommended local setup for Codex:

1. Create a local virtualenv in this repo
2. Install the MCP server into that virtualenv
3. Install the Blender add-on from this repo
4. Register Codex to launch `/home/adam/my-repos/blender-mcp-server/.venv/bin/blender-mcp-server`
5. Keep Blender open with the add-on listening on `127.0.0.1:9876`
6. Start Codex and ask it to use Blender

### Step 1: Create the Local Virtualenv

```bash
cd /home/adam/my-repos/blender-mcp-server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

This creates the local server executable at:

```bash
/home/adam/my-repos/blender-mcp-server/.venv/bin/blender-mcp-server
```

### Step 2: Install the Blender Add-on

Create an installable zip:

```bash
cd /home/adam/my-repos/blender-mcp-server
./scripts/build_addon_zip.sh
```

Then in Blender:

1. Open Blender
2. Go to **Edit -> Preferences -> Add-ons -> Install**
3. Select `dist/blender_mcp_bridge.zip`
4. Enable **Blender MCP Bridge**
5. In the 3D Viewport, press `N` and open the `MCP` tab
6. Confirm it shows `Listening on 127.0.0.1:9876`

The Blender add-on is the bridge endpoint inside Blender. It listens for JSON/TCP requests and executes them through `bpy`.

### Step 3: Register the MCP Server in Codex

Register the local server once:

```bash
codex mcp add blender -- /home/adam/my-repos/blender-mcp-server/.venv/bin/blender-mcp-server
```

Verify it:

```bash
codex mcp list
codex mcp get blender
```

You should see the command path:

```bash
/home/adam/my-repos/blender-mcp-server/.venv/bin/blender-mcp-server
```

### Step 4: Start Blender and Codex

1. Start Blender and make sure the add-on is enabled
2. Confirm the `MCP` panel shows `Listening on 127.0.0.1:9876`
3. Start Codex from this repo:

```bash
cd /home/adam/my-repos/blender-mcp-server
codex
```

Do not manually start `python -m blender_mcp_server.server` for Codex. Codex launches the MCP server itself using the registered command.

### Step 5: Ask Codex Normally

Inside Codex, ask naturally:

- `What objects are in my Blender scene?`
- `Create a cube named TestCube at [0, 0, 1]`
- `Render the scene to /tmp/test.png`

Codex will call MCP tools such as `blender_scene_list_objects` and `blender_object_create`. Those tool calls go to `blender-mcp-server`, which forwards them to the Blender add-on on `127.0.0.1:9876`.

### Optional: Claude Desktop

If you want to use Claude Desktop instead of Codex, point it at the same virtualenv executable.

Config file locations:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- Linux: `~/.config/Claude/claude_desktop_config.json`

Example config:

```json
{
  "mcpServers": {
    "blender": {
      "command": "/home/adam/my-repos/blender-mcp-server/.venv/bin/blender-mcp-server"
    }
  }
}
```

### Direct Bridge Test Scripts

If you want to test the Blender add-on without an MCP client, use the helper scripts in `scripts/`:

```bash
python3 scripts/blender_scene_info.py
python3 scripts/blender_create_test_cube.py --name TestCube --x 0 --y 0 --z 1 --size 2
python3 scripts/blender_bridge_request.py scene.get_info
python3 scripts/blender_bridge_request.py object.translate --params '{"name":"TestCube","offset":[0,0,2]}'
```

All scripts connect to `127.0.0.1:9876` by default and accept `--host`, `--port`, and `--timeout`.

These scripts bypass `blender-mcp-server` entirely. They are useful for checking whether the Blender add-on works before involving an MCP client.

## Example Prompts

Here's what you can ask Claude to do once everything is connected:

### 🔍 Inspecting Your Scene
> "What objects are in my scene?"
>
> "Show me the transform of the Camera object"
>
> "List all materials in the file"

### 🔨 Creating Objects
> "Create a sphere named 'Earth' at position [0, 0, 2] with size 3"
>
> "Add a cylinder at the origin, then scale it to [0.5, 0.5, 4] to make a tall pillar"
>
> "Create 5 cubes in a row spaced 3 units apart"

### 🎨 Materials & Colors
> "Create a red material and assign it to the Cube"
>
> "Make a material called 'Ocean' with color [0.0, 0.3, 0.8] and assign it to the Sphere"
>
> "Change the color of 'RedMaterial' to orange"

### 📐 Transforming Objects
> "Move the Cube up 2 units on the Z axis"
>
> "Rotate the Cylinder 45 degrees on the Z axis"
>
> "Scale the Sphere to [2, 2, 2]"

### 📸 Rendering & Exporting
> "Render the scene at 1920x1080 and save it to /tmp/render.png"
>
> "Export the scene as a GLB file to /tmp/scene.glb"

### ⏪ Safety
> "Undo the last change"
>
> "Redo what was just undone"

### 🐍 Python Script Execution
> "Run this Blender Python: `bpy.ops.mesh.primitive_monkey_add(location=(0,0,2))`"
>
> "Execute the fluid_domain.py script from the library with resolution 128"
>
> "Start an async bake job for the fluid simulation and tell me the job ID"
>
> "Check the status of job job-a1b2c3d4"

### 🐍 Python Execution — Programmatic Examples

#### Inline code — create a fluid domain

```json
{
  "tool": "blender_python_exec",
  "args": {
    "code": "import bpy\nbpy.ops.mesh.primitive_cube_add(size=4, location=(0,0,2))\ndomain = bpy.context.active_object\ndomain.name = 'FluidDomain'\nbpy.ops.object.modifier_add(type='FLUID')\ndomain.modifiers['Fluid'].fluid_type = 'DOMAIN'\nsettings = domain.modifiers['Fluid'].domain_settings\nsettings.domain_type = 'LIQUID'\nsettings.resolution_max = 64\n__result__ = {'domain': domain.name, 'resolution': 64}",
    "args": {"resolution": 64}
  }
}
```

#### Script file — set up colliders

```json
{
  "tool": "blender_python_exec",
  "args": {
    "script_path": "/path/to/scripts/library/effector.py",
    "args": {
      "objects": ["Ground", "Building_01", "Building_02"],
      "effector_type": "COLLISION"
    }
  }
}
```

#### Animate a camera with keyframes

```json
{
  "tool": "blender_python_exec",
  "args": {
    "script_path": "/path/to/scripts/library/keyframes.py",
    "args": {
      "keyframes": [
        {"object": "Camera", "frame": 1, "location": [20, -20, 10]},
        {"object": "Camera", "frame": 120, "location": [5, -10, 6]},
        {"object": "Camera", "frame": 250, "location": [0, -5, 3]}
      ]
    }
  }
}
```

#### Start a bake and poll for completion

```json
{"tool": "blender_python_exec_async", "args": {"code": "import bpy\nbpy.ops.fluid.bake_all()\n__result__ = {'baked': True}", "timeout_seconds": 1800}}
```

Response: `{"job_id": "job-f8e2a1b3"}`

Then poll:
```json
{"tool": "blender_job_status", "args": {"job_id": "job-f8e2a1b3"}}
```

### Script Library

Pre-built scripts in `scripts/library/` for common Blender tasks. Use with `blender_python_exec` via `script_path`:

| Script | Description |
|---|---|
| `create_mesh.py` | Create primitive meshes through the data API without `bpy.ops` |
| `fluid_domain.py` | Create a Mantaflow fluid domain |
| `fluid_inflow.py` | Create an inflow source |
| `effector.py` | Set objects as collision effectors |
| `rigid_body.py` | Add rigid body physics |
| `frame_range.py` | Set scene frame range |
| `camera.py` | Create and configure a camera |
| `keyframes.py` | Insert transform keyframes |
| `collections.py` | Organize objects into collections |
| `apply_transforms.py` | Apply transforms to objects |
| `save_blend.py` | Save the .blend file |

See `scripts/library/README.md` for full argument docs and an end-to-end dam-break setup walkthrough.
For live bridge sessions, prefer the data-API helper `mcp_create_mesh(...)` inside `blender_python_exec` scripts, or `scripts/library/create_mesh.py`, over `bpy.ops.mesh.primitive_*_add`. The operator path can destabilize view-layer updates around fluid setup.
Also keep Mantaflow liquid modifiers hidden in the viewport for live bridge sessions. Visible liquid domain/flow updates in Blender 4.0.x can still crash even when geometry creation avoids `bpy.ops`.
For heavy physics workflows, prefer `transport="headless"` on `blender_python_exec` / `blender_python_exec_async`. That runs the script in a separate `blender -b` process instead of the live add-on session.

## Example Session

Here's a real session transcript showing every category of tool in action.
All output below was produced by a live Blender 4.0.2 instance controlled through the MCP bridge:

```
📋 STEP 1: Get Scene Info
─────────────────────────
{
  "name": "Scene",
  "frame_current": 1,
  "frame_start": 1,
  "frame_end": 250,
  "render_engine": "BLENDER_EEVEE",
  "resolution_x": 1920,
  "resolution_y": 1080,
  "object_count": 3
}

📦 STEP 2: List Default Scene Objects
──────────────────────────────────────
  • Cube            (MESH    ) at [0.0, 0.0, 0.0]
  • Light           (LIGHT   ) at [4.1, 1.0, 5.9]
  • Camera          (CAMERA  ) at [7.4, -6.9, 5.0]

🔨 STEP 3: Create Mesh Objects
───────────────────────────────
  ✅ Created MyCube          at [0.0, 0.0, 0.0]
  ✅ Created MySphere        at [3.0, 0.0, 0.0]
  ✅ Created MyCylinder      at [-3.0, 0.0, 0.0]
  ✅ Created MyCone          at [0.0, 3.0, 0.0]

🔄 STEP 4: Transform Objects
─────────────────────────────
  ✅ Moved MyCube to [0.0, 0.0, 2.0]
  ✅ Rotated MySphere Z=45°
  ✅ Scaled MyCylinder to [1.0, 1.0, 3.0]

📑 STEP 5: Duplicate Object
────────────────────────────
  ✅ Duplicated 'MyCube' → 'MyCube.Copy'

📐 STEP 6: Inspect Object Transform
────────────────────────────────────
{
  "name": "MyCube",
  "location": [0.0, 0.0, 2.0],
  "rotation_euler": [0.0, 0.0, 0.0],
  "scale": [1.0, 1.0, 1.0]
}

🎨 STEP 7: Create & Assign Materials
─────────────────────────────────────
  ✅ Created 'RedMaterial'
  ✅ Assigned 'RedMaterial' → 'MyCube'
  ✅ Created 'BlueMaterial'
  ✅ Assigned 'BlueMaterial' → 'MySphere'
  ✅ Changed RedMaterial color → orange

🎨 STEP 8: List Materials
─────────────────────────
  • BlueMaterial          (nodes: True, users: 1)
  • Material              (nodes: True, users: 1)
  • RedMaterial           (nodes: True, users: 1)

🌳 STEP 9: Scene Hierarchy
───────────────────────────
  • Cube (MESH)       • MyCube (MESH)
  • Light (LIGHT)     • MySphere (MESH)
  • Camera (CAMERA)   • MyCylinder (MESH)
                      • MyCone (MESH)

🗑️  STEP 10: Delete Object
──────────────────────────
  ✅ Deleted 'MyCube.Copy'

📸 STEP 12: Render Still Image
───────────────────────────────
  ✅ Rendered: /tmp/blender_mcp_render.png
     Engine: BLENDER_EEVEE, Resolution: [640, 480]

⏪ STEP 13: Undo & Redo
───────────────────────
  ✅ undo
  ✅ redo

📦 FINAL: Scene Summary — 7 objects, 3 materials
```

## Tool Reference

### Scene Inspection

| Tool | Description |
|---|---|
| `blender_scene_get_info` | Scene metadata — name, frame range, render engine, resolution, object count |
| `blender_scene_list_objects` | List all objects, optionally filter by type (`MESH`, `CAMERA`, `LIGHT`, etc.) |
| `blender_object_get_transform` | Get position, rotation, and scale of an object by name |
| `blender_object_get_hierarchy` | Parent/child hierarchy tree (full scene or subtree) |

### Materials

| Tool | Description |
|---|---|
| `blender_material_list` | List all materials in the file |
| `blender_material_create` | Create a new material with optional base color `[r, g, b]` (0–1) |
| `blender_material_assign` | Assign a material to an object |
| `blender_material_set_color` | Set the Principled BSDF base color |
| `blender_material_set_texture` | Set an image texture as base color |

### Object Manipulation

| Tool | Description |
|---|---|
| `blender_object_create` | Create primitives: `cube`, `sphere`, `cylinder`, `plane`, `cone`, `torus` |
| `blender_object_delete` | Delete an object by name |
| `blender_object_translate` | Move — absolute `location` or relative `offset` |
| `blender_object_rotate` | Set rotation `[x, y, z]` in degrees (default) or radians |
| `blender_object_scale` | Set scale `[x, y, z]` |
| `blender_object_duplicate` | Duplicate with optional new name |

### Rendering & Export

| Tool | Description |
|---|---|
| `blender_render_still` | Render still image — set output path, resolution, engine |
| `blender_render_animation` | Render animation — set frame range, output path, engine |
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
| `blender_python_exec` | Execute a Python script synchronously in Blender. Provide `code` or `script_path`, optional `args`, `timeout_seconds`, and `transport` (`bridge` or `headless`). Returns result, stdout, stderr, and timeout/cancel metadata. |
| `blender_python_exec_async` | Start a long-running script asynchronously. Returns a `job_id`. Supports `transport="headless"` for separate background Blender processes. |
| `blender_job_status` | Poll an async job's status, result, stdout, stderr, and error. |
| `blender_job_cancel` | Cancel a running or queued async job. |
| `blender_job_list` | List known async jobs with IDs, status, and creation time. |

## Safety Features

- **Automatic undo push** — object/material mutation tools push an undo step first; `python.execute` is excluded because multi-step physics scripts were unstable with per-request undo snapshots
- **Safe Mode** — enable in add-on preferences to restrict file access to the project directory only
- **Tool whitelist** — limit which commands the bridge will accept
- **Script path restrictions** — `script_path` must be under configured approved roots
- **Inline code toggle** — disable inline code execution via add-on preferences
- **Module blocklist** — `subprocess`, `shutil`, `socket`, `webbrowser`, `ctypes`, `multiprocessing` are blocked by default during script execution

## Add-on Preferences

In Blender → Edit → Preferences → Add-ons → Blender MCP Bridge:

| Setting | Description | Default |
|---|---|---|
| **Safe Mode** | Restrict file I/O to project directory | Off |
| **Port** | TCP port for the MCP bridge | 9876 |
| **Allow Inline Code** | Allow `python.execute` to run inline code strings | On |
| **Approved Script Roots** | Semicolon-separated directories for script file access | (blend file dir) |

## Headless / Background Mode

You can also run Blender in background mode (no GUI) for automation:

```bash
blender -b --python your_script.py
```

Where `your_script.py` starts the MCP bridge:

```python
import sys
sys.path.insert(0, "/path/to/blender-mcp-server")
from addon import CommandHandler, BlenderMCPServer

server = BlenderMCPServer()
server.start()

# Keep Blender alive (use your preferred method)
import socket
s = socket.socket()
s.bind(("127.0.0.1", 9877))
s.listen(1)
s.accept()  # Blocks until shutdown signal
```

## Development

```bash
# Clone and install with dev dependencies
git clone https://github.com/your-org/blender-mcp-server
cd blender-mcp-server
pip install -e ".[dev]"

# Run tests (no Blender required)
pytest tests/ -v
```

### Project Structure

```
blender-mcp-server/
├── addon/
│   └── __init__.py          # Blender add-on — TCP server + command handlers + job manager
├── src/blender_mcp_server/
│   ├── __init__.py
│   └── server.py            # MCP server — stdio transport + 27 tool definitions
├── scripts/
│   ├── library/             # Reusable Blender scripts for common tasks
│   │   ├── fluid_domain.py, fluid_inflow.py, effector.py, ...
│   │   └── README.md
│   ├── demos/               # End-to-end demo scenes
│   │   ├── dam_break_scene.py   # Monolithic dam-break scene builder
│   │   ├── run_dam_break.py     # Step-by-step bridge caller
│   │   └── README.md            # Demo docs + follow-up tickets
│   └── blender_bridge_request.py, ...  # Direct bridge test helpers
├── tests/
│   ├── test_addon.py        # Add-on tests (mocked bpy)
│   └── test_server.py       # MCP server tests
├── docs/
│   ├── architecture.md      # Architecture documentation
│   ├── python-execute-design.md  # Python execution design doc
│   └── images/
│       └── demo_render.png  # Render from demo session
├── pyproject.toml
└── README.md
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run `pytest tests/ -v` to verify all 83 tests pass
5. Submit a pull request

## License

MIT
