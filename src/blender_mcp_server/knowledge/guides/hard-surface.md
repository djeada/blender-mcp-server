<!-- {"version": 1, "domain": "modeling", "title": "Hard-surface modeling with bevels and booleans",
"summary": "Crisp manufactured forms using non-destructive boolean cuts, controlled bevels and mirroring.",
"tags": ["hard-surface", "bevel", "boolean", "mechanical", "weapon", "sword", "armor", "machine", "vehicle", "prop", "robot", "panel"],
"related": ["box-modeling", "uv-unwrapping", "pbr-materials"]} -->
# Hard-surface modeling with bevels and booleans

## Use when
The object is manufactured: weapons, armour plates, machines, vehicles, hardware. Real edges catch light, so almost every one needs a small bevel.

## Avoid when
The surface must deform smoothly, or a low triangle budget cannot afford booleans and bevel segments.

## Tradeoffs
Modifiers keep cuts and widths editable and are quick to change. Boolean results can have n-gons and awkward triangles, which are fine on flat static faces and poor where the mesh bends.

## Pattern
A blade-like bar with a slot cut through it, bevelled by angle.

```python
import bmesh
from mathutils import Vector


def box(name, size, location=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=Vector(size), verts=bm.verts)  # scale the mesh, not the object
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    return obj


body = box("GuidePlate", (2.0, 0.2, 0.6))
cutter = box("GuideSlotCutter", (1.2, 0.6, 0.12))
cutter.display_type = "WIRE"
cutter.hide_render = True

cut = body.modifiers.new("Slot", "BOOLEAN")
cut.operation = "DIFFERENCE"
cut.object = cutter
cut.solver = "EXACT"

bevel = body.modifiers.new("Edges", "BEVEL")
bevel.width = 0.02
bevel.segments = 2
bevel.limit_method = "ANGLE"
__result__ = {"object": body.name, "cutter": cutter.name}
```

## Pitfalls
- Modifier order matters: boolean first, then bevel.
- Cutters that share a face or edge with the target cause broken booleans. Let them pass clearly through.
- Non-uniform object scale makes bevel widths uneven.
- A bevel wider than the thinnest part self-intersects.
- Typed tools cover Bevel, Subdivision, Mirror and Solidify; booleans need a script.

## Checks
Inspect `source="evaluated"`: no non-manifold edges and no zero-area faces. Capture `three_quarter` in `solid` mode to see whether edges catch light, and `wireframe` to find stray triangles around cuts. Remember that exports may or may not apply modifiers; check the exported file.
