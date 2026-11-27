<!-- {"version": 1, "domain": "modeling", "title": "Voxel remeshing and procedural surface detail",
"summary": "Fuse blockout parts into one surface and add programmatic detail; brush sculpting is not available.",
"tags": ["sculpt", "voxel", "remesh", "high-poly", "detail", "displacement", "noise", "rock", "creature", "realistic", "terrain"],
"related": ["retopology", "organic-modeling", "game-optimization"]} -->
# Voxel remeshing and procedural surface detail

## Use when
Overlapping blockout parts must become one surface, or a high-poly source needs broad or noisy detail: rocks, bark, terrain, creature masses. It is optional. A stylised or low-poly asset often needs none of it.

## Avoid when
The mesh must keep its UVs, edge flow or vertex groups (remeshing discards them), the part is hard-surface, or thin parts are smaller than the voxel size.

## Tradeoffs
Fast, seamless surfaces with uniform dense triangles or quads that deform poorly and need retopology before rigging. Scripts cannot paint brush strokes; detail comes from booleans, remeshing, displacement and math.

## Pattern
Keep it non-destructive: a Remesh modifier leaves the blockout editable.

```python
import bmesh
from mathutils import Matrix

mesh = bpy.data.meshes.new("GuideBlob")
bm = bmesh.new()
bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
bmesh.ops.create_icosphere(bm, subdivisions=3, radius=0.7, matrix=Matrix.Translation((1.1, 0.0, 0.4)))
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new("GuideBlob", mesh)
bpy.context.scene.collection.objects.link(obj)

remesh = obj.modifiers.new("Fuse", "REMESH")
remesh.mode = "VOXEL"
remesh.voxel_size = 0.12

texture = bpy.data.textures.new("GuideNoise", type="CLOUDS")
texture.noise_scale = 0.6
displace = obj.modifiers.new("Surface", "DISPLACE")
displace.texture = texture
displace.strength = 0.12
displace.mid_level = 0.5
__result__ = {"object": obj.name}
```

## Pitfalls
- Halving the voxel size roughly quadruples the face count. Start coarse and check counts.
- Parts that only touch may stay separate; overlap them by more than one voxel.
- Apply or fix object scale first, because voxel size is in object space.
- Do not rig or UV the voxel result directly; see retopology.

## Checks
`blender_mesh_inspect(source="evaluated")` should show one component and no non-manifold edges. Watch `counts.evaluated.triangles`; raise `element_budget` only if you mean to. Capture to check that thin features survived.
