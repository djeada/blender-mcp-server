<!-- {"version": 1, "domain": "modeling", "title": "Box and polygon modeling",
"summary": "Build forms from a primitive by extruding, insetting and moving polygons with deliberate edge flow.",
"tags": ["box", "polygon", "extrude", "inset", "low-poly", "lowpoly", "prop", "weapon", "sword", "blade", "building", "house", "furniture", "blockout", "crate"],
"related": ["hard-surface", "modular-modeling", "uv-unwrapping"]} -->
# Box and polygon modeling

## Use when
The shape is made of recognisable volumes and you need control of every face: low-poly props, buildings, furniture, weapon parts, and blockouts of almost anything.

## Avoid when
The surface is mostly smooth and flowing (see organic-modeling), or a modifier or curve describes it exactly (see curves, hard-surface).

## Tradeoffs
Exact face counts and clean quads, at the cost of explicit coordinates for every change. Detail added early is expensive to move later, so settle proportions with a blockout first.

## Pattern
Extruding a face with `bmesh` leaves the original face inside the solid. Delete it, or the mesh becomes non-manifold.

```python
import bmesh
from mathutils import Vector

bm = bmesh.new()
bmesh.ops.create_cube(bm, size=2.0)


def extrude_up(faces, height):
    result = bmesh.ops.extrude_face_region(bm, geom=faces)
    verts = [item for item in result["geom"] if isinstance(item, bmesh.types.BMVert)]
    caps = [item for item in result["geom"] if isinstance(item, bmesh.types.BMFace)]
    bmesh.ops.delete(bm, geom=faces, context="FACES_ONLY")  # remove the now internal faces
    bmesh.ops.translate(bm, vec=Vector((0, 0, height)), verts=verts)
    return caps


bm.normal_update()
top = [face for face in bm.faces if face.normal.z > 0.9]
caps = extrude_up(top, 1.0)
bmesh.ops.inset_region(bm, faces=caps, thickness=0.3)  # a border ring around the cap
extrude_up(caps, 0.5)
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

mesh = bpy.data.meshes.new("GuideTower")
bm.to_mesh(mesh)
bm.free()
obj = bpy.data.objects.new("GuideTower", mesh)
bpy.context.scene.collection.objects.link(obj)
__result__ = {"object": obj.name, "faces": len(mesh.polygons)}
```

## Pitfalls
- `face.normal` is stale after geometry changes until `bm.normal_update()`.
- Element references die when you delete or merge geometry. Re-select by position or normal.
- Object scale distorts inset and bevel widths. Edit mesh coordinates, or apply the scale first.
- Long thin n-gons shade and deform badly. Keep deforming areas in quads.

## Checks
`blender_mesh_inspect` should report no errors and, for a solid, `closed_edge_manifold: true`. Compare `counts.raw.triangles` with your budget. Capture `front` and `right` views to check proportions.
