<!-- {"version": 1, "domain": "modeling", "title": "Organic base meshes from lofted cross-sections",
"summary": "Block out limbs, torsos, horns and creatures as clean quad tubes shaped by cross-section radii.",
"tags": ["organic", "creature", "character", "orc", "monster", "animal", "body", "limb", "torso", "tail", "horn", "base-mesh", "blockout"],
"related": ["anatomy-proportions", "base-mesh-deformation", "retopology"]} -->
# Organic base meshes from lofted cross-sections

## Use when
A form is best described as a path with changing thickness: arms, legs, necks, torsos, tails, horns, tentacles and tree limbs. It gives predictable quad loops that deform and subdivide well.

## Avoid when
The form branches continuously and you need one seamless surface at once (blockout parts, then join or voxel remesh them; see sculpting-remeshing), or the object is mechanical.

## Tradeoffs
Clean loops and exact control of the silhouette, but joints between tubes need extra work. A mirrored half keeps characters symmetrical: model one side and add a Mirror modifier.

## Pattern
Each row is `(height, radius_x, radius_y)`. The ends are capped, so the result is closed.

```python
import math


def loft(name, rings, sides=12):
    verts, faces = [], []
    for z, rx, ry in rings:
        for i in range(sides):
            angle = 2 * math.pi * i / sides
            verts.append((rx * math.cos(angle), ry * math.sin(angle), z))
    for ring in range(len(rings) - 1):
        for i in range(sides):
            a, b = ring * sides + i, ring * sides + (i + 1) % sides
            faces.append((a, b, b + sides, a + sides))
    faces.append(tuple(reversed(range(sides))))
    faces.append(tuple(range((len(rings) - 1) * sides, len(rings) * sides)))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


torso = loft(
    "GuideTorso", [(0.0, 0.28, 0.18), (0.25, 0.24, 0.16), (0.55, 0.38, 0.24), (0.75, 0.42, 0.22), (0.88, 0.14, 0.12)]
)
smooth = torso.modifiers.new("Smooth", "SUBSURF")
smooth.levels = 1
smooth.render_levels = 2
__result__ = {"object": torso.name, "faces": len(torso.data.polygons)}
```

## Pitfalls
- Subdivision shrinks the form. Check the evaluated bounds, and add a loop near any edge that must stay sharp.
- Rings that cross each other make self-intersections, which `blender_mesh_inspect` does not detect. Look at the captures.
- Large radius jumps between neighbouring rings give pinched shading. Add an intermediate ring.
- Overlapping separate parts are fine for a blockout, but they do not deform as one surface.

## Checks
Inspect with `source="raw"` for loop structure and `source="evaluated"` for final size. Capture `front`, `right` and `three_quarter` in `solid` mode and judge the silhouette before adding detail. Use `wireframe` mode to check that loops follow the form.
