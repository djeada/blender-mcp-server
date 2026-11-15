# Tool Reference

### Scene Inspection

| Tool | Description |
|---|---|
| `blender_scene_get_info` | Scene metadata — name, frame range, render engine, resolution, object count |
| `blender_scene_list_objects` | List objects with stable name sorting, optional filters (`type`, `name` substring, `collection`, `visibility`) and pagination (`limit`, `offset`); returns total matches |
| `blender_object_get_transform` | Get position, rotation, and scale of an object by name |
| `blender_object_get_hierarchy` | Parent/child hierarchy tree (full scene or subtree) |

### Scene Organization

| Tool | Description |
|---|---|
| `blender_collection_create` | Create a collection, optionally under a `parent` collection |
| `blender_collection_list` | List collections with object counts |
| `blender_collection_rename` | Rename a collection (returns the canonical name — Blender appends `.001` on collision) |
| `blender_collection_add_object` | Move an object into a collection, leaving its previous collection(s) |
| `blender_collection_remove_object` | Remove an object from a collection; orphans are re-linked to the scene root |
| `blender_object_rename` | Rename an object (returns the canonical name after collision handling) |
| `blender_object_parent` | Parent an object; `keep_transform=true` preserves the world transform. Self/descendant parenting is refused |
| `blender_object_unparent` | Clear an object's parent; `keep_transform=true` bakes the world transform first |

### Timeline & Animation

| Tool | Description |
|---|---|
| `blender_timeline_get` | Get current frame and scene frame range |
| `blender_timeline_set` | Set current frame and/or frame range |
| `blender_keyframe_add` | Insert a keyframe on `location`, `rotation` (degrees) or `scale`, optionally setting its value and interpolation (`BEZIER`, `LINEAR`, `CONSTANT`); reports inserted vs. overwritten |
| `blender_keyframe_list` | List keys per channel (index, frame, value — rotation stored as radians) |
| `blender_keyframe_remove` | Remove key(s) at a frame; reports how many were removed |

Keyframe tools cover a small allowlist of object transforms; full rigging, constraints and fcurve editing remain
available through `blender_python_exec` and the script library (e.g. `examples/library/keyframes.py`).

### Object Manipulation

| Tool | Description |
|---|---|
| `blender_object_create` | Create primitives: `cube`, `sphere`, `cylinder`, `plane`, `cone`, `torus` |
| `blender_object_delete` | Delete an object by name |
| `blender_object_translate` | Move — absolute `location` or relative `offset` |
| `blender_object_rotate` | Set rotation `[x, y, z]` in degrees (default) or radians |
| `blender_object_scale` | Set scale `[x, y, z]` |
| `blender_object_duplicate` | Duplicate with optional new name |

### Camera & Lighting

| Tool | Description |
|---|---|
| `blender_camera_create` | Create a camera — `name`, `location`, orientation via `rotation` (degrees) or `look_at` `[x, y, z]` target, `projection` (`PERSP`/`ORTHO`), `lens` (mm, PERSP), `ortho_scale` (ORTHO), `clip_start`/`clip_end`, `set_active` |
| `blender_camera_update` | Update an existing camera by `name` with any of the camera settings above |
| `blender_light_create` | Create a light — `light_type` (`POINT`, `SUN`, `SPOT`, `AREA`), `color` `[r, g, b]` (0–1), `energy`, `size`, `size_y` (AREA), `angle` (SUN, degrees), `spot_angle`/`spot_blend` (SPOT), `look_at` |
| `blender_light_update` | Update an existing light by `name` with any of the light settings above |

Parameters that do not apply to the chosen type (e.g. `spot_angle` on a `POINT` light) return an explicit error
instead of being silently ignored. For advanced camera rigging, see [`examples/library/camera.py`](../examples/library/camera.py).

Example — frame and light a product shot:

```
blender_camera_create(name="ProductCam", location=[3, -3, 2], look_at=[0, 0, 0.5],
                      lens=85, clip_start=0.1, clip_end=100, set_active=true)
blender_light_create(light_type="AREA", name="KeyLight", location=[2, -2, 3],
                     look_at=[0, 0, 0.5], energy=400, color=[1.0, 0.97, 0.92],
                     size=2, size_y=3)
```

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
| `blender_render_still` | Render still image — output path, resolution, engine (`EEVEE`, `CYCLES`, `WORKBENCH`); `transport="headless"` renders a `.blend` file without opening Blender |
| `blender_render_animation` | Render animation — frame range, output path, engine; also works headless |
| `blender_export_gltf` | Export as glTF/GLB; `transport="headless"` exports a `.blend` file without opening Blender |
| `blender_export_obj` | Export as OBJ; also works headless |
| `blender_export_fbx` | Export as FBX; also works headless |

Render and export tools return the absolute path they wrote. A path starting with `//` is relative to the
`.blend` file; while the file is unsaved it goes to `blender-mcp/` in the system temp directory. Missing
folders are created.

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


### Ordered batches

`blender_scene_execute_batch` accepts 1–32 commands. Each step has a bridge command name and optional parameter object. This batch relies on the first step to create the object used by later steps.

```json
{
  "commands": [
    {"command": "object.create_mesh", "params": {"type": "cube", "name": "Copper block"}},
    {"command": "object.translate", "params": {"name": "Copper block", "location": [0, 0, 1]}},
    {"command": "material.create", "params": {"name": "Copper", "color": [0.63, 0.25, 0.11]}},
    {"command": "material.assign", "params": {"object": "Copper block", "material": "Copper"}}
  ],
  "stop_on_error": true
}
```

Allowlist and parameter-shape checks run before any step starts. State-dependent checks run in order. Each result has a zero-based `index` and a `status` of `succeeded`, `failed`, or `skipped`. Earlier changes persist after a failure. Each mutation gets the same undo behavior as its standalone tool, where Blender's context supports undo. A timeout after execution begins can leave completed edits in the scene. The batch stops starting new steps at its command deadline.

The batch supports ordinary scene, object, modifier, material, camera, light, timeline, keyframe, and collection operations. Use standalone tools for project files, textures, renders, exports, Python, jobs, and history. The entire input is capped at 64 KiB. Results larger than 16 KiB per step are marked with `result_omitted: "size_limit"`.

### Modifier stack

Use `blender_object_list_modifiers` to read names, types, settings, and stack order. Use `blender_object_add_modifier`, `blender_object_update_modifier`, and `blender_object_remove_modifier` to edit local meshes. A supplied modifier name must be unique on the object. The result reports the effective name and settings. Other modifier types can be listed by name and type.

| Type | Editable settings |
|---|---|
| `BEVEL` | `width`, `segments` (1–32), `profile` (0–1) |
| `SUBSURF` | `levels` (0–4), `render_levels` (0–6), `show_only_control_edges` |
| `MIRROR` | `use_axis` (three booleans for X/Y/Z), `use_clip`, `use_mirror_merge`, `merge_threshold` (0–1) |
| `SOLIDIFY` | `thickness`, `offset` (−1 to 1), `use_even_offset`, `use_rim` |

Width is limited to 0–1,000 and thickness to −1,000 to 1,000 in Blender units. The running Blender version may restrict a property further.

### Project lifecycle

`blender_project_get_info` returns the current absolute path, save state, Blender version, and dirty state. The dirty value can be `null` on builds where Blender cannot report it reliably.

`blender_project_save` saves the current file when called without arguments. Provide a `.blend` path to save a new file. Provide `overwrite: true` to replace a different existing file. Blender uses its configured Save Versions setting for backups such as `.blend1`.

`blender_project_open` loads an existing `.blend`. Use `discard_changes: true` only when you intend to discard changes in the current project. Opening a file changes the bridge generation and fails queued requests from the previous project. An acknowledged open returns the loaded path. If the connection drops, reconnect using `blender_status` and verify the path with `blender_project_get_info`. `blender_project_revert` reloads the current file when given `confirm: true`.

For a headless save, supply the output filepath and, when cloning a saved scene, the input `blend_file`. The output must be distinct from the input.

See [Policy and recovery](policy.md) for status, structured error codes, and command budgets.
