# Python Script Execution — Design Document

## Overview

This document defines the contract for executing Blender Python scripts through
the MCP bridge. It covers five new bridge commands, their schemas, the safety
model, and the async job lifecycle.

## Commands

### `python.execute` — Synchronous script execution

Execute a Python snippet or script file in Blender's context and return the
result.

#### Request

```json
{
  "id": "req-001",
  "command": "python.execute",
  "params": {
    "code": "import bpy\nobj = bpy.context.active_object\n__result__ = {'name': obj.name}",
    "script_path": null,
    "args": {},
    "timeout_seconds": 30
  }
}
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `code` | string | one of `code`/`script_path` | — | Inline Python source to execute |
| `script_path` | string | one of `code`/`script_path` | — | Absolute path to a `.py` file |
| `args` | object | no | `{}` | Key/value pairs injected into the execution namespace as `args` |
| `timeout_seconds` | number | no | `30` | Maximum cooperative execution time before the script is interrupted |

If both `code` and `script_path` are provided, the request is rejected. If
neither is provided, the request is rejected.

#### Response — success

```json
{
  "id": "req-001",
  "success": true,
  "result": {
    "result": {"name": "Cube"},
    "stdout": "",
    "stderr": "",
    "duration_seconds": 0.003
  }
}
```

| Field | Type | Description |
|---|---|---|
| `result` | any (JSON-safe) | Value of `__result__` after execution, or `null` |
| `stdout` | string | Captured standard output |
| `stderr` | string | Captured standard error |
| `duration_seconds` | number | Wall-clock execution time |

#### Response — error

```json
{
  "id": "req-001",
  "success": false,
  "error": "NameError: name 'foo' is not defined\n  File \"<mcp-script>\", line 1"
}
```

Errors include the exception type, message, and a condensed traceback that
omits the bridge internals.

---

### `python.execute_async` — Asynchronous script execution

Start a long-running script and return a job ID immediately.

#### Request

Same schema as `python.execute`, plus:

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `timeout_seconds` | number | no | `300` | Longer default for async jobs |

#### Response

```json
{
  "id": "req-002",
  "success": true,
  "result": {
    "job_id": "job-a1b2c3d4"
  }
}
```

---

### `job.status` — Query job state

#### Request

```json
{
  "id": "req-003",
  "command": "job.status",
  "params": {
    "job_id": "job-a1b2c3d4"
  }
}
```

#### Response

```json
{
  "id": "req-003",
  "success": true,
  "result": {
    "job_id": "job-a1b2c3d4",
    "status": "running",
    "created_at": "2026-03-22T10:00:00Z",
    "started_at": "2026-03-22T10:00:01Z",
    "completed_at": null,
    "result": null,
    "stdout": "Baking frame 42/250...\n",
    "stderr": "",
    "error": null
  }
}
```

| Status | Description |
|---|---|
| `queued` | Job accepted, waiting to run |
| `running` | Currently executing |
| `succeeded` | Completed successfully |
| `failed` | Completed with an error |
| `cancelled` | Cancelled by the client |

---

### `job.cancel` — Cancel a running job

#### Request

```json
{
  "id": "req-004",
  "command": "job.cancel",
  "params": {
    "job_id": "job-a1b2c3d4"
  }
}
```

#### Response

```json
{
  "id": "req-004",
  "success": true,
  "result": {
    "job_id": "job-a1b2c3d4",
    "status": "cancelled"
  }
}
```

Cancellation sets a flag that scripts can check via `__cancel_event__.is_set()`.
The bridge also performs cooperative cancellation and timeout checks between
Python line executions. Long-running native Blender operators may still finish
their current call before the cancellation is observed.

---

### `job.list` — List all jobs

#### Request

```json
{
  "id": "req-005",
  "command": "job.list",
  "params": {}
}
```

#### Response

```json
{
  "id": "req-005",
  "success": true,
  "result": {
    "jobs": [
      {
        "job_id": "job-a1b2c3d4",
        "status": "running",
        "created_at": "2026-03-22T10:00:00Z"
      }
    ]
  }
}
```

---

## Execution Environment

Scripts execute inside Blender's Python interpreter via `exec()`. The execution
namespace contains:

| Name | Type | Description |
|---|---|---|
| `bpy` | module | Blender Python API |
| `mathutils` | module | Blender math utilities (Vector, Matrix, etc.) |
| `args` | dict | Caller-supplied arguments from the request |
| `__result__` | any | Set this to return a JSON-serializable value |
| `__cancel_event__` | `threading.Event` | (async only) Check `.is_set()` to detect cancellation |

Scripts set `__result__` to communicate structured data back to the caller:

```python
import bpy
domain = bpy.data.objects.get(args["domain_name"])
__result__ = {
    "name": domain.name,
    "type": domain.type,
    "modifier_count": len(domain.modifiers),
}
```

If `__result__` is not set, `null` is returned.

### JSON serialization

The bridge attempts `json.dumps()` on `__result__`. If serialization fails, the
bridge converts the value to its `repr()` string and returns that instead.

---

## Safety Model

### Trust boundary

This is **local desktop tooling**. The MCP server and Blender run on the same
machine under the same user account. The safety model prevents accidental
mistakes and constrains the execution surface — it is not designed to resist a
determined attacker who already has local code execution.

### Script file path restrictions

Script files (`script_path`) must reside under one or more **approved root
directories** configured in the addon preferences. Requests for scripts outside
these roots are rejected with a `PermissionError`.

If no roots are configured, the directory of the current `.blend` file is used
as the sole root. If there is no `.blend` file, the current working directory
is used.

Path validation resolves symlinks and relative paths via `os.path.realpath()`
before checking against the approved roots.

### Inline code control

Inline code execution (`code` field) can be disabled entirely via the
`allow_inline_code` addon preference. When disabled, only `script_path`
requests are accepted.

Default: **enabled** (inline code allowed).

### Module blocklist

A configurable list of module names is blocked from import during script
execution. The default blocklist includes:

- `subprocess`
- `shutil`
- `webbrowser`
- `ctypes`
- `multiprocessing`

This is enforced via a lightweight import hook installed during `exec()` and
removed after execution completes. It is a guardrail, not a sandbox — a
determined script can bypass it.

### Timeouts

Every execution has a wall-clock timeout:

| Mode | Default | Max |
|---|---|---|
| Synchronous | 30 seconds | 300 seconds |
| Asynchronous | 300 seconds | 3600 seconds |

When a timeout fires, the execution is flagged via `__cancel_event__` (async)
or interrupted directly (sync). The response includes a timeout error.

---

## Job Lifecycle

```
  ┌──────────┐     start     ┌──────────┐
  │  queued   │ ────────────► │  running  │
  └──────────┘               └────┬─────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼              ▼
              ┌───────────┐ ┌──────────┐ ┌────────────┐
              │ succeeded │ │  failed  │ │ cancelled  │
              └───────────┘ └──────────┘ └────────────┘
```

- **queued**: Job accepted, waiting for main-thread execution slot
- **running**: Actively executing on Blender's main thread
- **succeeded**: Completed normally; `result`, `stdout`, `stderr` available
- **failed**: Exception raised; `error`, `stdout`, `stderr` available
- **cancelled**: Client requested cancellation via `job.cancel`

Jobs are stored in memory for the lifetime of the Blender session. Completed
jobs are retained until Blender is restarted or the addon is disabled.

### Main-thread scheduling

Blender's `bpy` API must be called from the main thread. The job manager uses
`bpy.app.timers.register()` to schedule job execution on the main thread, the
same pattern used by the existing request queue drain loop.

---

## Example Workflows

### 1. Create a Mantaflow fluid domain

```python
# Inline code sent via python.execute
import bpy

bpy.ops.mesh.primitive_cube_add(size=4, location=(0, 0, 2))
domain = bpy.context.active_object
domain.name = args.get("domain_name", "FluidDomain")

bpy.ops.object.modifier_add(type='FLUID')
domain.modifiers["Fluid"].fluid_type = 'DOMAIN'
settings = domain.modifiers["Fluid"].domain_settings
settings.domain_type = 'LIQUID'
settings.resolution_max = args.get("resolution", 64)
settings.cache_directory = args.get("cache_dir", "//fluid_cache")

__result__ = {
    "domain": domain.name,
    "resolution": settings.resolution_max,
    "cache_dir": settings.cache_directory,
}
```

Request:
```json
{
  "command": "python.execute",
  "params": {
    "code": "...(above)...",
    "args": {
      "domain_name": "WaterDomain",
      "resolution": 128,
      "cache_dir": "//dam_break_cache"
    }
  }
}
```

### 2. Assign rigid body settings to objects

```python
import bpy

for obj_name in args["objects"]:
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        continue
    bpy.context.view_layer.objects.active = obj
    bpy.ops.rigidbody.object_add()
    obj.rigid_body.type = args.get("rb_type", "ACTIVE")
    obj.rigid_body.mass = args.get("mass", 1.0)
    obj.rigid_body.friction = args.get("friction", 0.5)
    obj.rigid_body.restitution = args.get("restitution", 0.3)

__result__ = {
    "configured": args["objects"],
    "type": args.get("rb_type", "ACTIVE"),
}
```

Request:
```json
{
  "command": "python.execute",
  "params": {
    "code": "...(above)...",
    "args": {
      "objects": ["Building_01", "Building_02", "Debris_01"],
      "rb_type": "ACTIVE",
      "mass": 500.0,
      "friction": 0.8
    }
  }
}
```

### 3. Set up camera and keyframes

```python
import bpy
from mathutils import Vector

scene = bpy.context.scene
cam_data = bpy.data.cameras.new("DamBreakCam")
cam_obj = bpy.data.objects.new("DamBreakCam", cam_data)
bpy.context.collection.objects.link(cam_obj)
scene.camera = cam_obj

keyframes = args.get("keyframes", [])
for kf in keyframes:
    frame = kf["frame"]
    loc = kf.get("location")
    rot = kf.get("rotation")
    scene.frame_set(frame)
    if loc:
        cam_obj.location = Vector(loc)
        cam_obj.keyframe_insert(data_path="location", frame=frame)
    if rot:
        cam_obj.rotation_euler = rot
        cam_obj.keyframe_insert(data_path="rotation_euler", frame=frame)

scene.frame_start = args.get("frame_start", 1)
scene.frame_end = args.get("frame_end", 250)

__result__ = {
    "camera": cam_obj.name,
    "frame_range": [scene.frame_start, scene.frame_end],
    "keyframe_count": len(keyframes),
}
```

Request:
```json
{
  "command": "python.execute",
  "params": {
    "code": "...(above)...",
    "args": {
      "keyframes": [
        {"frame": 1, "location": [20, -20, 10], "rotation": [1.1, 0, 0.8]},
        {"frame": 120, "location": [5, -10, 6], "rotation": [1.2, 0, 0.3]},
        {"frame": 250, "location": [0, -5, 3], "rotation": [1.4, 0, 0.0]}
      ],
      "frame_start": 1,
      "frame_end": 250
    }
  }
}
```

### 4. Bake fluid simulation (async)

```python
import bpy

domain = bpy.data.objects[args["domain_name"]]
bpy.context.view_layer.objects.active = domain

override = bpy.context.copy()
override["active_object"] = domain

print("Starting fluid bake...")
bpy.ops.fluid.bake_all()
print("Fluid bake complete.")

__result__ = {"baked": True, "domain": domain.name}
```

Request (async — baking can take minutes):
```json
{
  "command": "python.execute_async",
  "params": {
    "code": "...(above)...",
    "args": {"domain_name": "WaterDomain"},
    "timeout_seconds": 1800
  }
}
```

Response:
```json
{
  "success": true,
  "result": {"job_id": "job-f8e2a1b3"}
}
```

Then poll with `job.status`:
```json
{
  "command": "job.status",
  "params": {"job_id": "job-f8e2a1b3"}
}
```
