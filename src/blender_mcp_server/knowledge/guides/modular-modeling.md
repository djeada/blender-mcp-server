<!-- {"version": 1, "domain": "modeling", "title": "Modular kits for environments and buildings",
"summary": "Assemble houses, streets and interiors from reusable pieces on a shared grid with consistent pivots.",
"tags": ["modular", "kit", "grid", "house", "building", "architecture", "environment", "wall", "window", "door", "roof", "village", "dungeon"],
"related": ["box-modeling", "geometry-nodes", "game-optimization"]} -->
# Modular kits for environments and buildings

## Use when
Walls, floors, windows, fences, pipes or street pieces repeat. Buildings and levels are almost always faster as a kit.

## Avoid when
The object is unique and sculptural, or seen only once from one side.

## Tradeoffs
Fast assembly, shared mesh data and consistent UVs, in exchange for visible repetition and the discipline of one grid.

## Pattern
Decide the grid unit first (here 2 m walls, 3 m high). Put each module's origin on a grid corner. Reuse mesh data so one edit updates every copy.

```python
import bmesh
from mathutils import Vector

WIDTH, HEIGHT, DEPTH = 2.0, 3.0, 0.2
mesh = bpy.data.meshes.new("GuideWallModule")
bm = bmesh.new()
bmesh.ops.create_cube(bm, size=1.0)
bmesh.ops.scale(bm, vec=Vector((WIDTH, DEPTH, HEIGHT)), verts=bm.verts)
bmesh.ops.translate(bm, vec=Vector((WIDTH / 2, 0, HEIGHT / 2)), verts=bm.verts)  # origin on the bottom corner
bm.to_mesh(mesh)
bm.free()

kit = bpy.data.collections.new("GuideHouse")
bpy.context.scene.collection.children.link(kit)
placed = []
# (grid x, grid y, turned 90 degrees)
for column, row, turned in [
    (0, 0, False),
    (1, 0, False),
    (0, 2, False),
    (1, 2, False),
    (0, 0, True),
    (0, 1, True),
    (2, 0, True),
    (2, 1, True),
]:
    wall = bpy.data.objects.new(f"GuideWall_{len(placed):02}", mesh)
    wall.location = (column * WIDTH, row * WIDTH, 0)
    wall.rotation_euler.z = 1.5707963267948966 if turned else 0.0
    kit.objects.link(wall)
    placed.append(wall.name)
__result__ = {"collection": kit.name, "pieces": len(placed), "mesh_users": mesh.users}
```

## Pitfalls
- Pivots in the middle of a piece make snapping and rotation guesswork.
- Negative scale to mirror a piece flips normals and breaks some exporters.
- Walls overlap at corners; use corner pieces or shorten walls if the overlap can be seen or causes z-fighting.
- Editing one linked mesh changes all copies. `object.data = object.data.copy()` makes one unique.

## Checks
Inspect one instance of each module. Capture the whole kit with `blender_view_capture(collection=...)` from `top` to check alignment on the grid and from `front` for gaps.
