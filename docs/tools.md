# Tool Reference

The server advertises all of these by default. [Tool profiles](profiles.md) explains how to advertise fewer and discover the rest on demand.

Object, material, collection, keyframe and job listings accept `limit` and `offset`, and then report `total` and `next_offset`. Without them they return everything, except in [compact output](profiles.md#compact-output).

### Scene Inspection

| Tool | Description |
|---|---|
| `blender_scene_get_info` | Scene metadata — name, frame range, render engine, resolution, object count |
| `blender_scene_list_objects` | List objects with stable name sorting, optional filters (`type`, `name` substring, `collection`, `visibility`) and pagination (`limit`, `offset`); returns total matches |
| `blender_object_get_transform` | Get position, rotation, and scale of an object by name |
| `blender_object_get_hierarchy` | Parent/child hierarchy tree (full scene or subtree), optionally limited by `max_nodes` and `max_depth`, with `offset` paging the top level |

### Mesh Diagnostics

`blender_mesh_inspect` checks one mesh object by `name` without changing the scene, selection, mode or geometry. It works through the live bridge and in ordered batches (as `mesh.inspect`).

| Parameter | Default | Meaning |
|---|---|---|
| `source` | `raw` | Mesh described by bounds, vertex groups, components, material face counts, findings and element IDs: `raw` (the object's mesh data) or `evaluated` (after modifiers and shape keys) |
| `check_duplicates` | `false` | Also look for vertices within `tolerance` of each other |
| `include_regions` | `false` | Add local bounds for each vertex group and each used material index |
| `tolerance` | `1e-5` | Distance in local units (0–1,000) for duplicate vertices and zero-area faces |
| `max_ids` | `10` | Sample element IDs per finding, and the number of components listed (0–100) |
| `element_budget` | `500000` | Largest mesh to analyze, counted as vertices + edges + face corners (up to 2,000,000) |

`counts.raw` and `counts.evaluated` are always reported. `evaluated` uses **viewport** settings, so a modifier hidden in the viewport is left out and Subdivision uses its viewport level, not its render level. Blender does not evaluate objects that are disabled in viewports or excluded from the view layer. For those, `counts.evaluated` is `null`, `world_transform_current` is `false` (world bounds may be out of date), and `source="evaluated"` fails. Element IDs from an evaluated mesh do not index the raw mesh.

Coordinates are Blender's right-handed, Z-up system. `bounds.local` is in object space, before the object's transform. `bounds.world` is the axis-aligned box around the transformed vertices. Both use Blender units, as `[x, y, z]` rounded to six decimals. Component and region bounds are local. `tolerance` ignores object scale.

| Check | Severity | Reports |
|---|---|---|
| `non_finite_vertices` | error | NaN or infinite coordinates (left out of bounds) |
| `non_manifold_edges` | error | Edges with more than two faces |
| `zero_area_faces` | error | Faces whose width (twice the area over the longest side) is within `tolerance` |
| `inconsistent_winding` | error | Two adjacent faces whose normals disagree |
| `loose_vertices`, `loose_edges` | warning | Geometry that is not part of an edge or a face |
| `duplicate_vertices` | warning | Opt-in. Vertices within `tolerance` of an earlier one; chains are not merged transitively |
| `boundary_edges` | info | Edges with one face: a hole, or an intentionally open surface |

`summary.status` is `errors`, `warnings` or `ok`. It only covers `checks_run`; `checks_skipped` lists the rest. Boundary edges and separate components are often intentional and do not change the status. `summary.closed_edge_manifold` means every edge has exactly two faces. Faces that meet only at a vertex, self-intersections and inward-facing normals on a consistently wound mesh are not detected.

Lists of material slots, vertex groups, modifiers and regions stop at 64 entries and set `truncated`. A mesh over `element_budget` fails with `budget_exceeded`, and the error details include the element counts. Meshes in Edit Mode are rejected because their stored data is stale.

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

### Visual Inspection

`blender_view_capture` lets the model see its work. It returns one metadata text block, then a `view: <name>` text block and a PNG image for each requested view. The client and model must accept MCP image content.

| Parameter | Default | Meaning |
|---|---|---|
| `object` or `collection` | | The subject. Give exactly one. An object includes its children unless `include_children=false` |
| `views` | `["three_quarter"]` | Up to six of `front`, `back`, `right`, `left`, `top`, `bottom`, `three_quarter`. `front` looks along +Y, as in Blender |
| `mode` | `solid` | `solid` (neutral shading for shape), `material`, or `wireframe` (edges of the evaluated mesh over a shaded surface; meshes only) |
| `projection` | `orthographic` | Or `perspective` (70 mm lens) |
| `resolution` | 512, or 384 in compact output | Square image size, 64–1024 pixels |
| `include_images` | `true` | `false` returns framing metadata only |
| `save_directory` | | Also write `capture_<view>.png` files there and report their paths. Existing files are replaced. With `include_images=false`, this is the fallback for text-only clients |
| `max_bytes` | 4,000,000 | Limit on the PNG bytes returned (10,000–5,000,000). Over it, the call fails with `budget_exceeded` and returns no images |

The metadata lists the engine, world bounds, each camera's direction and position, `ortho_scale` or `lens`, and any objects left out with the reason: hidden from render, disabled in viewports, without a renderable surface, or not a mesh in wireframe mode. Framing uses the bounding boxes of evaluated geometry and instances, so every subject is in the picture; a rotated view of a round shape can have extra space around it.

**Your project is not changed.** The subject is linked into a temporary scene with its own camera, lights, background and render settings, and that scene and everything made for it are removed afterwards, also when rendering fails. Wireframe draws on private copies. The active camera, your lights, selection, visibility and render settings are not touched. Like any render, a capture updates Blender's *Render Result* image and runs registered render handlers. It adds no undo step. Objects are shown at the current frame. Images are renders, so in every mode modifiers use their **render** settings (Subdivision uses its render level). Framing and `blender_mesh_inspect` use viewport settings. When the two differ, `notes` says so, because geometry added only at render time can fall outside the frame.

| Where Blender runs | `solid` and `wireframe` | `material` |
|---|---|---|
| With its window open | Workbench | EEVEE |
| In the background, including `transport="headless"` | Cycles, CPU | Cycles, CPU |

Background captures use Cycles so that they do not need a GPU. If a build lacks Cycles, they fail with `unsupported`. Lighting is a fixed rig that follows the camera, so material views are for comparing shape and color, not for judging your scene's lighting; use `blender_render_still` for that.

Captures follow the [policy](policy.md): the `view.capture` command, the render pixel and frame limits (one frame per view), output roots for `save_directory`, and the long command deadline. They run on Blender's main thread, so the interface is busy while rendering.

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

Allowlist and parameter-shape checks run before any step starts. State-dependent checks run in order. Each result has a zero-based `index` and a `status` of `succeeded`, `failed`, or `skipped`. Earlier changes persist after a failure. Each successful mutation records an undo checkpoint after the change, just like its standalone tool, when Blender's context supports undo. A timeout after execution begins can leave completed edits in the scene. The batch stops starting new steps at its command deadline.

The batch supports mesh inspection and ordinary scene, object, modifier, material, camera, light, timeline, keyframe, and collection operations. Use standalone tools for project files, textures, renders, exports, Python, jobs, and history. The entire input is capped at 64 KiB. Results larger than 16 KiB per step are marked with `result_omitted: "size_limit"`.

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
