# Tool Reference

The server advertises all of these by default. [Tool profiles](profiles.md) explains how to advertise fewer and discover the rest on demand.

Object, material, collection, keyframe and job listings accept `limit` and `offset`, and then report `total` and `next_offset`. Without them they return everything, except in [compact output](profiles.md#compact-output).

### Recipes

`blender_recipe_search`, `blender_recipe_get` and `blender_recipe_run` run reviewed scripts by ID. See [Recipe catalog](recipes.md).

### Modeling Knowledge

`blender_workflow`, `blender_guide_search` and `blender_guide_get` give staged plans and short technique guides offline. See [Modeling knowledge](knowledge.md).

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
| `blender_lighting_inspect` | Read-only report of the scene's lights, active camera, world, render engine and color management |
| `blender_color_management_set` | Change `view_transform`, `look`, `exposure`, `gamma` or `display_device` |

Both light tools also accept `shape` (`SQUARE`, `RECTANGLE`, `DISK`, `ELLIPSE`; AREA only; `size_y` needs
`RECTANGLE` or `ELLIPSE`) and `temperature` in kelvin (1667–25000) instead of `color`.

`energy` is in watts, except for `SUN` lights, where it is irradiance in W/m². `size` is a radius for `POINT` and
`SPOT` and a width for `AREA`, in Blender units. `angle`, `spot_angle` and `rotation` are in degrees.
`temperature` sets the light's linear color to an approximation of a black body at that temperature, scaled so the
strongest channel is 1. It changes color, not energy. On Blender 4.5+ it also turns off the light's own
`use_temperature` option, which would otherwise apply a second time.

A request is checked against the light's final type before anything changes: a rejected create makes nothing, and a
rejected update leaves the light as it was. Parameters that do not apply to the chosen type (e.g. `spot_angle` on
a `POINT` light) return an explicit error instead of being silently ignored.

If several objects share a light's data (linked duplicates), changing anything except the transform fails and names
them. Pass `shared_data="update_all"` to change every user, or `"make_single_user"` to give this object its own copy
first.

#### Inspect and color management

`blender_lighting_inspect` lists lights in name order (`limit`, `offset`; paged automatically in compact output).
Each has its world position, the direction it shines (except `POINT`), energy and unit, linear color, settings for
its type, shadow and visibility flags, its data name, and `data_shared_by` when shared. The report also has the
active camera, a world summary (`color`, `environment`, `sky`, `custom` or `none`), engine, resolution and samples,
and the color management settings. `include_options=true` adds the valid view transforms, looks and display devices.

Valid names come from Blender's color configuration and differ between versions; the `look` list also depends on the
view transform. `blender_color_management_set` changes only the settings you pass, in the order display, view
transform, look, exposure (stops, −32 to 32), gamma (0–5). If any is invalid, nothing changes and the error lists
the valid values. When Blender adjusts a setting you did not pass, such as resetting an incompatible look,
`adjusted_by_blender` reports it. Color management affects renders and image output, not light energy. For advanced camera rigging, see [`examples/library/camera.py`](../examples/library/camera.py).

Example — frame and light a product shot:

```
blender_camera_create(name="ProductCam", location=[3, -3, 2], look_at=[0, 0, 0.5],
                      lens=85, clip_start=0.1, clip_end=100, set_active=true)
blender_light_create(light_type="AREA", name="KeyLight", location=[2, -2, 3],
                     look_at=[0, 0, 0.5], energy=400, color=[1.0, 0.97, 0.92],
                     size=2, size_y=3)
```

### World and Environment

`blender_world_get` describes the scene's world: its settings, whether it can be edited in place (and why not), the sky models this Blender offers, and whether the film is transparent. `blender_world_set` changes it. Only the settings you pass change, and the mode is kept unless you pass `mode`.

| Mode | Settings |
|---|---|
| `color` | `color`: linear RGB, may exceed 1 |
| `environment` | `filepath` to a local `.hdr`, `.exr`, `.png`, `.jpg`, `.tif` or `.webp`; `rotation` in degrees |
| `sky` | `sun_elevation` and `sun_rotation` in degrees; `sky_type`. Physical models also take `sun_intensity` and `sun_disc`; `PREETHAM` and `HOSEK_WILKIE` take `turbidity` (1–10) |

`strength` (0–10,000) multiplies the light in every mode. `camera_background` (linear RGB) shows a plain color to the camera while the environment still lights and reflects in the scene; `clear_camera_background` removes it. To make the background transparent in the output instead, enable the scene's *Film > Transparent* setting; these tools report it but do not change it.

**Orientation.** For an equirectangular image at `rotation=0`, the **horizontal center of the image faces +X**, +Y is a quarter of the width from the left edge, and −X is at the left and right edges. Moving right across the image turns clockwise seen from above. A positive `rotation` turns the environment **counterclockwise** seen from above (about +Z). `sun_rotation` is Blender's compass heading and turns the **other** way: at 0 the sun is toward +Y, and at 90 toward +X. Both were checked from rendered pixels.

**Sky models** differ between versions: `physical` (the default) picks the newest physical model available, such as Multiple Scattering on Blender 5 or Nishita before it. Physical skies are very bright. Reduce `strength` or lower `exposure` with `blender_color_management_set`. They are dark below the horizon, so add ground geometry if the camera looks down. EEVEE support for physical skies depends on the Blender version; compare with Cycles if a sky renders black.

**Color space.** `.hdr` and `.exr` hold linear light; other formats are treated as sRGB by Blender and cannot represent a bright sun. The tools never change an image's color space, because the image may be used elsewhere.

**Your work is protected.** A plain color world, such as Blender's default, or a world these tools built is edited in place. Nodes you added that do not feed the output are left alone. If the world has a custom node setup, is used by another scene, or is linked from a library, the call fails with `conflict` and changes nothing. Choose:

- `on_conflict="new_world"`: give this scene a new world. The old one is kept unchanged, with a fake user so that saving does not discard it.
- `on_conflict="replace"`: replace what feeds the world's output, **for every scene that uses it**. Linked worlds cannot be replaced.

All inputs are validated, and an image is loaded and checked (at most 256 MB and 16384×8192 pixels), before anything changes. Only local files are read, under the [policy's](policy.md) path rules. Each change is one undo step.

**Preview.** `blender_view_capture(..., mode="material", lighting="world")` shows a subject lit only by this world, using the scene's color management; `lighting="scene"` adds the scene's lights. Neither changes the project. The default `lighting="rig"` ignores both, so it cannot judge environment lighting.

### Materials

| Tool | Description |
|---|---|
| `blender_material_list` | List all materials in the file |
| `blender_material_create` | Create a material with optional base color `[r, g, b]` (0–1) |
| `blender_material_assign` | Assign a material to an object |
| `blender_material_set_color` | Set the Principled BSDF base color |
| `blender_material_set_texture` | Set an image texture as base color |

#### PBR texture sets

`blender_material_set_texture_set` binds several image maps to a material's Principled BSDF in one step. `blender_material_set_texture` still binds a single base color image.

```json
{
  "name": "Crate",
  "orm": "/project/textures/crate_orm.png",
  "maps": {
    "base_color": "/project/textures/crate_basecolor.png",
    "normal": {"path": "/project/textures/crate_normal.png", "convention": "opengl"}
  },
  "mapping": {"scale": [2, 2]}
}
```

| Map | Color space | Settings | Connects to |
|---|---|---|---|
| `base_color` | sRGB | | Base Color |
| `metallic`, `roughness` | Non-Color | `channel` | Metallic, Roughness |
| `normal` | Non-Color | **`convention`** `opengl` or `directx`; `strength` 0–10 | Normal Map node (tangent space) → Normal |
| `ao` | Non-Color | **`mode`** `gltf` or `multiply`; `channel` | See below. Principled BSDF has no occlusion input |
| `emission` | sRGB | `strength` (default 1) | Emission Color and Strength |
| `opacity` | Non-Color | **`mode`** `blend` or `clip`; `channel`; `threshold` for clip | Alpha, and the material's transparency setting |
| `height` | Non-Color | **`mode`** `bump` or `displacement`; `channel`; `strength`, `distance`, and `midlevel` for displacement | Bump node in front of the normal map, or Displacement on the material output |

Settings in **bold** are required, because they change the result in ways that cannot be guessed. A map can be given as a bare path when it needs none. `channel` is `R` (default), `G`, `B` or `A`. `orm` is shorthand for the glTF packed layout: occlusion in red, roughness in green and metallic in blue, with occlusion in `gltf` mode. Give maps explicit channels for any other packing. Maps that use one file share one texture node.

`uv_map` names a UV layer. `mapping` takes `scale` and `offset` as `[u, v]` and `rotation` in degrees. Both apply to every texture bound by this tool.

**Safety.** The whole request is checked, and every file is validated and loaded, before the material changes. A missing or unreadable file changes nothing. Only local files are read, under the [policy's](policy.md) path rules, at most 256 MB and 16384×8192 pixels each. A color space belongs to the image, so if a loaded image already uses another one, a separate copy is loaded and the original is left alone. Calls only add to or replace bindings made by this tool; maps you do not list are kept, and `remove` unbinds maps. If an input is fed by a node you made, the call fails with `conflict`; `on_conflict="replace"` disconnects your link and keeps your node. The change is one undo step.

The result lists the effective `bindings`, what was `replaced` and `removed`, `warnings`, and how many users the material has.

**glTF export.** These behaviours were checked by inspecting exported GLB files:

| Binding | In the GLB |
|---|---|
| Base color, normal (OpenGL), metallic, roughness, emission | Exported |
| `orm`, or occlusion, roughness and metallic from one file | One shared texture |
| `ao` mode `gltf` | Exported as occlusion, through the `glTF Material Output` node group the exporter looks for |
| `ao` mode `multiply` | **Occlusion is lost**: base color is written without it |
| `opacity` `clip` / `blend` | `alphaMode` `MASK` with the threshold as cutoff / `BLEND` |
| `mapping` | `KHR_texture_transform`; the viewer must support it |
| Normal with `convention="directx"` | **Wrong in glTF viewers**: the original image is written without the green flip |
| `height`, bump or displacement | Not exported. Bake bump detail into the normal map |

In Blender, `directx` renders identically to the OpenGL version of the same map: the green channel is inverted with nodes and the file is not modified. For export, convert the file itself to OpenGL and bind it as `opengl`. Displacement needs geometry fine enough to move, and Cycles and EEVEE support it differently. Normals are tangent space only.

#### Material slots and face regions

One mesh can use several materials, such as skin, eyes and armor. `blender_material_assign` still sets the mesh's first slot (or adds one). These tools manage the others. They work on mesh objects outside Edit Mode.

| Tool | Does |
|---|---|
| `blender_material_slots` | Read-only: each slot's `index`, `material`, `link` (`DATA` or `OBJECT`) and face count; `faces_without_slot`; other objects sharing the mesh (`limit`, `offset`) |
| `blender_material_slot_append` | Add a slot, empty or with a material |
| `blender_material_slot_replace` | Set or empty one slot's material, optionally changing its link |
| `blender_material_slot_remove` | Remove a slot; `remap_to` names the slot that takes its faces |
| `blender_material_assign_faces` | Move faces to a slot, given by `slot` or by a `material` already in a slot |

`blender_material_assign_faces` takes exactly one selector:

- `face_indices`: raw mesh face indices (up to 100,000), such as those reported by `blender_mesh_inspect` with `source="raw"`.
- `vertex_group`: faces whose vertices are in the group with weight above `min_weight` (default 0). `match="all"` (default) needs every vertex of a face; `match="any"` needs one.
- `from_slot`: every face now using that slot.

**Shared meshes.** Linked duplicates share a mesh, including its slots, data-linked materials and face assignments. Changing any of those fails and names the objects unless you pass `shared_data="update_all"` or `"make_single_user"`, which gives this object its own copy first. Replacing a material with `link="OBJECT"` affects only one object and needs no choice. Appending an object-linked slot still adds a slot to the shared mesh.

**Removal.** If faces use the slot, `remap_to` is required, using the slot numbers from before the removal. Every other face, and every object's object-linked materials, show the same material afterwards. These tools restore that explicitly, because Blender's own slot removal can drop or misplace object-linked materials.

Each change is checked completely before anything is modified and is one undo step.

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
| `lighting` | `rig` | With `mode="material"`: `rig` (fixed, comparable lights), `world` (the scene's environment and color management) or `scene` (also the scene's lights) |
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

Background captures use Cycles so that they do not need a GPU. If a build lacks Cycles, they fail with `unsupported`. By default lighting is a fixed rig that follows the camera, so material views compare shape and color. To judge your own lighting, use `lighting="world"` or `"scene"`, or `blender_render_still`.

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
