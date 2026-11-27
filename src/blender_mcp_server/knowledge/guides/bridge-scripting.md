<!-- {"version": 1, "domain": "foundations", "title": "Running bpy safely through the bridge",
"summary": "Context, versions, results and undo when scripts run in Blender through MCP.",
"tags": ["python", "script", "bpy", "context", "operator", "version", "undo", "execution", "bmesh"],
"related": ["box-modeling", "game-optimization"]} -->
# Running bpy safely through the bridge

## Use when
No typed tool does what you need and `blender_python_exec` is allowed. Prefer typed tools: they validate input, add an undo step and report structured results.

## Avoid when
A typed tool or modifier tool covers the change, or the policy disables Python. Do not use scripts to get around a refused command.

## Tradeoffs
- The script runs on Blender's main thread. The interface freezes until it ends. Use `blender_python_exec_async` or `transport="headless"` for long work.
- `bpy`, `mathutils`, `math` and `args` are provided. Set `__result__` to a small JSON value; print only what you need.
- Pass names and numbers through `args` instead of building code strings.
- The bridge adds no undo step after a script, unlike typed tools. `blender_history_undo` may then revert more than the script, so save first when the work matters.
- Timeouts are checked between Python lines. A long single Blender operator can overrun.

## Pattern
Prefer the data API. It does not depend on which editor or selection is active.

```python
import bmesh

name = args.get("name", "GuideBlock")
mesh = bpy.data.meshes.new(name)
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new(name, mesh)
bpy.context.scene.collection.objects.link(obj)
__result__ = {"object": obj.name, "faces": len(mesh.polygons)}
```

Blender may rename a new block to `Name.001`. Always continue with the returned `obj.name`.

## Pitfalls
- Many `bpy.ops` calls need a 3D viewport or Edit Mode and fail with `poll()` errors here. Use `bmesh` and `bpy.data` when you can.
- Mesh data is stale while an object is in Edit Mode. Leave the mode you entered, also when your code raises.
- Free every `bmesh.new()` and release `to_mesh()` results with `to_mesh_clear()`.
- Node names are translated in some interfaces. Find nodes by `node.type`, not by name.
- APIs differ between versions. Test for the attribute (`hasattr`) instead of comparing version numbers where possible. Examples: node group sockets moved to `group.interface` in 4.0, and many Principled BSDF inputs were renamed in 4.0.
- `subprocess`, `socket` and some other imports are blocked.

## Checks
Run `blender_mesh_inspect` on every mesh you generate, then `blender_view_capture` to look at it. A script that returns without an error has not proved that the geometry is usable.
