<!-- {"version": 1, "domain": "surfacing", "title": "UV coordinates",
"summary": "Give meshes texture coordinates, from simple projection to unwrapping, with consistent texel density.",
"tags": ["uv", "unwrap", "projection", "seam", "texel", "texture", "atlas", "bake", "game"],
"related": ["pbr-materials", "retopology", "game-optimization"]} -->
# UV coordinates

## Use when
Any image texture, bake or game engine export. Do it after the shape is final and before painting.

## Avoid when
The material is a flat color or purely procedural with object coordinates.

## Tradeoffs
Projection is predictable but splits at every change of direction. Seam-based or smart unwrapping packs better with fewer seams but needs operators in Edit Mode. Overlapping UVs save texture space and break unique baking.

## Pattern
Box projection with a fixed scale in world units gives uniform texel density and needs no operators.

```python
import bmesh

mesh = bpy.data.meshes.new("GuideCrate")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new("GuideCrate", mesh)
bpy.context.scene.collection.objects.link(obj)

units_per_tile = float(args.get("units_per_tile", 2.0))
layer = mesh.uv_layers.new(name="UVMap")
for polygon in mesh.polygons:
    normal = polygon.normal
    axis = max(range(3), key=lambda i: abs(normal[i]))
    u_axis, v_axis = [i for i in range(3) if i != axis]
    for loop_index in polygon.loop_indices:
        co = mesh.vertices[mesh.loops[loop_index].vertex_index].co
        uv = (co[u_axis] / units_per_tile + 0.5, co[v_axis] / units_per_tile + 0.5)
        if hasattr(layer, "uv"):
            layer.uv[loop_index].vector = uv
        else:  # before Blender 3.5
            layer.data[loop_index].uv = uv
__result__ = {"object": obj.name, "uv_layer": layer.name}
```

## Pitfalls
- Some faces come out mirrored with simple projection. Flip U where text or decals matter.
- Non-uniform object scale stretches the texture although the UVs look right.
- Remesh, boolean and decimate operations can discard or distort UVs.
- `bpy.ops.uv.smart_project` needs Edit Mode with faces selected; restore the previous mode afterwards.

## Checks
Assign a checker or other regular image with `blender_material_set_texture` and capture in `material` mode: squares should be even and equally sized across parts. There is no automatic overlap or distortion report yet.
