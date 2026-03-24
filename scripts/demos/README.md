# Dam-Break Demo

End-to-end validation that the MCP python execution path can build a complete
flood-through-town scene without manual Blender UI steps (beyond enabling the
add-on). The repo now ships two variants:

- `procedural_dam_break_scene.py`: stable visible flood animation for Blender 4.0.x.
- `dam_break_scene.py`: experimental Mantaflow setup path.

## Recommended Mode

For Blender 4.0.x use the procedural scene. It produces visible water in the
viewport and avoids the Mantaflow viewport crash.

```bash
python3 scripts/demos/run_dam_break.py
```

To force the older Mantaflow path:

```bash
python3 scripts/demos/run_dam_break.py --simulation mantaflow --bake
```

## What the Procedural Demo Builds

| Element | Details |
|---|---|
| Ground plane | Street + sidewalks + barrier |
| 6 buildings | Blockout town section around an intersection |
| Flood animation | Procedural water mesh sequence over 120 frames |
| Debris objects | 4 props advected by the flood field |
| Camera | Animated cinematic overview over 120 frames |
| Frame range | 1–120 at 24 fps |
| Render settings | EEVEE, 1280×720 preview |

## Two Ways to Run

### Option A — Single script (all-in-one)

Send the monolithic scene script through MCP:

```json
{
  "tool": "blender_python_exec",
  "args": {
    "script_path": "/path/to/scripts/demos/procedural_dam_break_scene.py",
    "args": {"frame_end": 120}
  }
}
```

Or via the bridge test helper:

```bash
python3 scripts/blender_bridge_request.py python.execute \
  --params '{"script_path":"/path/to/scripts/demos/procedural_dam_break_scene.py","args":{"frame_end":120}}'
```

### Option B — Step-by-step bridge caller

The `run_dam_break.py` script sends individual MCP commands, mixing inline
code (for geometry) with local library scripts (sent as inline code for
portability, so it does not depend on approved script roots inside Blender):

```bash
# Dry run — see what would be sent:
python3 scripts/demos/run_dam_break.py --dry-run

# Run against live Blender (stable procedural mode):
python3 scripts/demos/run_dam_break.py

# Run Mantaflow mode instead:
python3 scripts/demos/run_dam_break.py --simulation mantaflow --bake --render
```

## Mantaflow Notes

The Mantaflow path remains in the repo for experimentation, but Blender 4.0.x
can crash when a visible liquid domain updates in the viewport. Use the
procedural scene when you need a stable visible result in the live app.

## After Scene Setup

### Bake the fluid simulation

```json
{
  "tool": "blender_python_exec_async",
  "args": {
    "code": "import bpy\nbpy.ops.fluid.bake_all()\n__result__ = {'baked': True}",
    "timeout_seconds": 1800
  }
}
```

Then poll:

```json
{"tool": "blender_job_status", "args": {"job_id": "<returned job_id>"}}
```

### Render a preview still

```json
{
  "tool": "blender_render_still",
  "args": {"output_path": "/tmp/dam_break_preview.png"}
}
```

## What This Validates

- [x] Inline code creates geometry (ground, buildings, debris)
- [x] Library script `frame_range.py` sets frame range
- [x] Library script `fluid_domain.py` creates Mantaflow domain
- [x] Library script `fluid_inflow.py` creates inflow source
- [x] Library script `effector.py` marks objects as collision effectors
- [x] Library script `rigid_body.py` adds active rigid bodies
- [x] Library script `camera.py` creates and positions camera
- [x] Library script `keyframes.py` inserts dolly animation keyframes
- [x] Library script `collections.py` organizes scene hierarchy
- [x] Render settings are configurable via inline code
- [x] Async job path works for baking
- [x] Job polling and completion work
- [x] Render still produces output

## Gaps & Follow-Up Tickets

Issues discovered while building this demo that should be addressed in future
work:

### GAP-1: Live bridge scripts should avoid `bpy.ops.mesh.primitive_*`

**Status:** mitigated

The repo now includes `scripts/library/create_mesh.py`, and the bridge injects
an `mcp_create_mesh(...)` helper into `python.execute` scripts. Use those
instead of `bpy.ops.mesh.primitive_*_add` for bridge-driven blockouts,
especially near Mantaflow setup.

### GAP-2: No library script for render settings

**Problem:** There is no library script for configuring render engine, samples,
resolution, color management, or output format. The demo uses inline code.

**Impact:** Render configuration is a common task that would benefit from a
reusable, validated script.

**Recommendation:** Add `scripts/library/render_settings.py` supporting engine
selection, resolution, samples, output format, and color management.

### GAP-3: No fluid bake library script

**Problem:** Triggering `bpy.ops.fluid.bake_all()` requires inline code through
the async path. There is no library wrapper.

**Impact:** Minor — the inline call is simple. But a library script could add
validation (check domain exists, check cache dir).

**Recommendation:** Add `scripts/library/fluid_bake.py` that validates the
domain setup before calling bake.

### GAP-4: No viewport/OpenGL render for quick preview

**Problem:** The existing render tools only support full engine renders (EEVEE
or Cycles). There is no viewport render or OpenGL render option for sub-second
preview captures.

**Impact:** Getting visual feedback during iterative scene building requires a
full render, which is slow even with EEVEE at low resolution.

**Recommendation:** Add a `render.viewport` bridge command using
`bpy.ops.render.opengl()` for instant viewport captures.

### GAP-5: No progress callback for async jobs

**Problem:** The async job system supports polling via `job.status`, but there
is no way for the running script to report intermediate progress (e.g., "baking
frame 45/120").

**Impact:** Long bakes appear as opaque "running" status with no visibility
into progress.

**Recommendation:** Add a `__progress__` callback or namespace variable that
scripts can update, surfaced through `job.status`.
