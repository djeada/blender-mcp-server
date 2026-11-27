<!-- {"version": 1, "domain": "modeling", "title": "Deforming a base mesh with falloff and shape keys",
"summary": "Reshape existing topology smoothly and non-destructively: bulk, taper, asymmetry and variants.",
"tags": ["deform", "shape-key", "proportional", "falloff", "variant", "creature", "character", "orc", "muscle", "face", "morph"],
"related": ["organic-modeling", "anatomy-proportions", "rigging"]} -->
# Deforming a base mesh with falloff and shape keys

## Use when
The topology is already good and only the form must change: a heavier jaw, broader shoulders, a belly, or several variants of one character.

## Avoid when
The change needs new topology (a new limb, a hole) or the base mesh has too few vertices to hold the shape.

## Tradeoffs
Keeps vertex count, UVs and weights intact. It cannot add detail finer than the existing edges. Shape keys keep the original, but block applying most modifiers later.

## Pattern
Move vertices by a smooth falloff and store the result in a shape key.

```python
import bmesh
from mathutils import Vector

mesh = bpy.data.meshes.new("GuideBelly")
bm = bmesh.new()
bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new("GuideBelly", mesh)
bpy.context.scene.collection.objects.link(obj)

obj.shape_key_add(name="Basis", from_mix=False)
key = obj.shape_key_add(name="Bulge", from_mix=False)
center, radius, offset = Vector((0.0, -1.0, 0.0)), 1.1, Vector((0.0, -0.35, 0.0))
moved = 0
for index, vertex in enumerate(mesh.vertices):
    distance = (vertex.co - center).length
    if distance < radius:
        t = 1.0 - distance / radius
        key.data[index].co = vertex.co + offset * (t * t * (3.0 - 2.0 * t))  # smoothstep
        moved += 1
key.value = 1.0
__result__ = {"object": obj.name, "moved_vertices": moved}
```

## Pitfalls
- Distances are in object space. Non-uniform object scale skews the falloff.
- With shape keys, edit `key.data`, not `mesh.vertices`; the Basis key is what raw inspection shows.
- Straight-line distance also moves nearby but unconnected parts, such as the other lip or leg. Limit by a vertex group or a half-space test.
- Break symmetry on purpose, in a separate key.

## Checks
`blender_mesh_inspect` with `source="evaluated"` shows the deformed bounds; raw bounds show the Basis. Compare `front` and `right` captures with the key at 0 and 1.
