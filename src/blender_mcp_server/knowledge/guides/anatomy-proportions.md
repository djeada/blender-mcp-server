<!-- {"version": 1, "domain": "art-direction", "title": "Anatomy, proportion and silhouette",
"summary": "Block out believable or stylized characters using head units, landmarks and a readable silhouette.",
"tags": ["anatomy", "proportion", "silhouette", "character", "creature", "orc", "human", "humanoid", "monster", "head", "blockout", "stylized", "style"],
"related": ["organic-modeling", "base-mesh-deformation", "rigging"]} -->
# Anatomy, proportion and silhouette

## Use when
Before modeling any character or creature, and whenever it "looks wrong" although the mesh is clean. Also for props whose shape must read at a distance.

## Avoid when
You are reproducing supplied reference or measured drawings; follow those instead.

## Tradeoffs
Starting from proportions avoids late rework. Rules of thumb are starting points: style deliberately breaks them.

## Proportions
Measure height in head units (crown to chin).

| Style | Heads tall | Shoulder width (heads) | Notes |
|---|---|---|---|
| Realistic adult human | 7.5 | 2 | Crotch near half height; elbows at the waist; wrists at the crotch |
| Heroic | 8–8.5 | 2.5–3 | Longer legs, small head, large chest |
| Brute such as an orc | 5.5–6.5 | 3–3.5 | Heavy jaw and brow, thick neck, long forearms, large hands, short legs |
| Stylized / chibi | 2–4 | 1–1.5 | Large head, simple hands, exaggerated features |

Landmarks to place first: crown, chin, shoulders, chest, pelvis, knees, ankles, elbows, wrists.

## Pattern
Place landmark boxes from head units, then check the silhouette before shaping anything.

```python
import bmesh
from mathutils import Vector

height = float(args.get("height", 2.0))
heads = float(args.get("heads", 6.0))
head = height / heads
# name: (center height in heads from the ground, width, depth, height) in heads
blocks = {
    "Head": (heads - 0.5, 0.9, 0.9, 1.0),
    "Chest": (heads - 2.0, 2.4, 1.1, 1.6),
    "Pelvis": (heads - 3.2, 1.5, 0.9, 0.8),
    "Legs": ((heads - 3.6) / 2, 1.3, 0.6, heads - 3.6),
}
group = bpy.data.collections.new("GuideBlockout")
bpy.context.scene.collection.children.link(group)
for name, (center, width, depth, tall) in blocks.items():
    mesh = bpy.data.meshes.new(f"Blockout{name}")
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=head)
    bmesh.ops.scale(bm, vec=Vector((width, depth, tall)), verts=bm.verts)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(f"Blockout{name}", mesh)
    obj.location.z = center * head
    group.objects.link(obj)
__result__ = {"collection": group.name, "head_unit": head}
```

## Pitfalls
- Detailing before the silhouette works.
- Symmetric, evenly thick limbs look like tubes; vary thickness and offset the muscle masses.
- Judging only from a perspective view. Use orthographic views to measure.
- A character facing the wrong way: Blender's front view looks along +Y, so a character faces -Y.

## Checks
Capture `front` and `right` orthographic views in `solid` mode. The subject should be recognisable from outline alone, and the largest, middle and smallest shapes should differ clearly. Compare `bounds_world` heights with your head units.
