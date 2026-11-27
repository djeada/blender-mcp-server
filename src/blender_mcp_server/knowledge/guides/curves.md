<!-- {"version": 1, "domain": "modeling", "title": "Curves for sweeps, pipes and tapered forms",
"summary": "Describe cables, handles, horns, rails and trim with editable splines, bevel depth and taper.",
"tags": ["curve", "spline", "bezier", "pipe", "cable", "rope", "horn", "handle", "grip", "sword", "rail", "vine", "trim"],
"related": ["hard-surface", "organic-modeling", "modular-modeling"]} -->
# Curves for sweeps, pipes and tapered forms

## Use when
The form follows a line: pipes, cables, grips, crossguards, horns, vines, railings and mouldings.

## Avoid when
The cross-section changes shape (not just size) along the path, or you need specific quad loops for deformation.

## Tradeoffs
A few control points stay editable and smooth. Resolution settings, not you, decide the final topology, and mesh tools see the surface only after conversion or export.

## Pattern
A tapered horn: point radius scales the bevel.

```python
curve = bpy.data.curves.new("GuideHorn", "CURVE")
curve.dimensions = "3D"
curve.resolution_u = 8
curve.bevel_depth = 0.2
curve.bevel_resolution = 3
curve.use_fill_caps = True

points = [((0, 0, 0), 1.0), ((0.5, 0, 0.7), 0.7), ((1.3, 0, 0.9), 0.35), ((1.8, 0, 1.4), 0.05)]
spline = curve.splines.new("BEZIER")
spline.bezier_points.add(len(points) - 1)
for point, (position, radius) in zip(spline.bezier_points, points):
    point.co = position
    point.radius = radius
    point.handle_left_type = point.handle_right_type = "AUTO"

obj = bpy.data.objects.new("GuideHorn", curve)
bpy.context.scene.collection.objects.link(obj)
__result__ = {"object": obj.name, "type": obj.type}
```

## Pitfalls
- A new Bezier spline already has one point; add `len(points) - 1`.
- High resolution with a large bevel creates many triangles quickly.
- Tight bends smaller than the bevel radius pinch and self-intersect.
- Caps and the surface may be separate components after conversion; merge them if you need a closed solid.

## Checks
`blender_mesh_inspect` only reads mesh objects. To check a curve's topology, convert a copy with `bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))`. `blender_view_capture` shows curves in `solid` and `material` modes.
