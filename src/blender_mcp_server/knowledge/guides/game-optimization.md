<!-- {"version": 1, "domain": "delivery", "title": "Preparing assets for real-time engines",
"summary": "Meet triangle budgets, clean transforms, make levels of detail and export predictably.",
"tags": ["game", "optimization", "triangle", "budget", "lod", "decimate", "export", "gltf", "fbx", "unity", "unreal", "godot", "performance"],
"related": ["uv-unwrapping", "pbr-materials", "retopology"]} -->
# Preparing assets for real-time engines

## Use when
Before exporting anything to a game engine, the web or AR.

## Avoid when
The target is an offline render, where density and unapplied transforms matter much less.

## Tradeoffs
Fewer triangles, materials and objects run faster but lose silhouette and flexibility. Budgets depend on platform and on how large the asset appears; ask for them rather than assuming.

## Pattern
Apply the object's scale to its mesh and make a lighter level of detail without touching the original.

```python
import bmesh
from mathutils import Matrix

mesh = bpy.data.meshes.new("GuideRock")
bm = bmesh.new()
bmesh.ops.create_icosphere(bm, subdivisions=4, radius=1.0)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new("GuideRock", mesh)
obj.scale = (1.5, 1.0, 0.7)
bpy.context.scene.collection.objects.link(obj)

mesh.transform(Matrix.Diagonal((*obj.scale, 1.0)))  # bake scale into the vertices
obj.scale = (1.0, 1.0, 1.0)

lod = obj.copy()
lod.data = mesh.copy()
lod.name = f"{obj.name}_LOD1"
bpy.context.scene.collection.objects.link(lod)
decimate = lod.modifiers.new("LOD", "DECIMATE")
decimate.ratio = float(args.get("ratio", 0.3))
__result__ = {"object": obj.name, "lod": lod.name}
```

## Pitfalls
- Shared mesh data is transformed for every user; copy it first when instanced.
- Negative scale must be applied and normals checked.
- Decimate damages UV seams and deforming joints; inspect them.
- Every material slot is usually a separate draw call.
- Engines differ in axis and unit conventions; verify one test asset end to end.

## Checks
For each mesh, `blender_mesh_inspect(source="evaluated")`: triangles within budget, no errors, expected `material_slots`. Export with `blender_export_gltf` or `blender_export_fbx` and confirm the file in the target engine or by importing it into an empty scene.
