# Reusable Script Library for Blender MCP

Pre-built Blender Python scripts for common tasks. Call them via
`blender_python_exec` with `script_path` pointing to the script and
structured `args`.

## Scripts

| Script | Description |
|---|---|
| `fluid_domain.py` | Create a Mantaflow fluid domain with configurable resolution and cache |
| `fluid_inflow.py` | Create or configure an inflow/flow source for fluid simulation |
| `effector.py` | Set up collision/effector objects for fluid or rigid body sims |
| `rigid_body.py` | Add rigid body physics to one or more objects |
| `frame_range.py` | Set scene frame range and optionally jump to a frame |
| `camera.py` | Create a camera, set it as active, and optionally set its transform |
| `keyframes.py` | Insert transform keyframes on objects at specified frames |
| `collections.py` | Create collections and move objects into them |
| `apply_transforms.py` | Apply location/rotation/scale transforms to objects |
| `save_blend.py` | Save the current .blend file to a specified path |

## Usage

```json
{
  "command": "python.execute",
  "params": {
    "script_path": "/path/to/scripts/library/rigid_body.py",
    "args": {
      "objects": ["Building_01", "Debris_01"],
      "rb_type": "ACTIVE",
      "mass": 500.0
    }
  }
}
```

Each script documents its accepted `args` and returned `__result__` in a
docstring at the top of the file.

## End-to-End Example: Dam Break Setup

Call these scripts in sequence to set up a dam-break scene:

1. **frame_range.py** — set frame range to 1–250
2. **fluid_domain.py** — create the fluid domain
3. **fluid_inflow.py** — create the water source
4. **effector.py** — set ground plane and buildings as colliders
5. **rigid_body.py** — make debris objects active rigid bodies
6. **camera.py** — create and position the camera
7. **keyframes.py** — animate the camera
8. **collections.py** — organize into Fluid, Buildings, Camera collections
9. **save_blend.py** — save the project
