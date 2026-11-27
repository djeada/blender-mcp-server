<!-- {"version": 1, "domain": "animation", "title": "Basic rigging and weighting",
"summary": "Create an armature from landmarks, bind vertex groups and test that joints deform acceptably.",
"tags": ["rig", "rigging", "armature", "bone", "skeleton", "weight", "skinning", "pose", "character", "creature", "animation", "humanoid"],
"related": ["anatomy-proportions", "retopology", "game-optimization"]} -->
# Basic rigging and weighting

## Use when
A mesh must bend: characters, creatures, tails, cloth strips, hinged mechanisms with soft joints.

## Avoid when
Parts move rigidly. Parent separate objects to empties or bones instead.

## Tradeoffs
Hand-made weights from positions are predictable and testable but crude. Blender's automatic weights are smoother and need an operator and a clean, connected mesh.

## Pattern
Edit bones exist only in Edit Mode, so enter it and always leave it again.

```python
rings, sides, length = 9, 8, 2.0
import math

verts = [
    (0.2 * math.cos(2 * math.pi * i / sides), 0.2 * math.sin(2 * math.pi * i / sides), length * r / (rings - 1))
    for r in range(rings)
    for i in range(sides)
]
faces = [
    (r * sides + i, r * sides + (i + 1) % sides, (r + 1) * sides + (i + 1) % sides, (r + 1) * sides + i)
    for r in range(rings - 1)
    for i in range(sides)
]
mesh = bpy.data.meshes.new("GuideArm")
mesh.from_pydata(verts, [], faces)
arm = bpy.data.objects.new("GuideArm", mesh)
bpy.context.scene.collection.objects.link(arm)

armature = bpy.data.armatures.new("GuideSkeleton")
rig = bpy.data.objects.new("GuideSkeleton", armature)
bpy.context.scene.collection.objects.link(rig)
previous = bpy.context.view_layer.objects.active
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
try:
    upper = armature.edit_bones.new("upper")
    upper.head, upper.tail = (0, 0, 0), (0, 0, 1)
    lower = armature.edit_bones.new("lower")
    lower.head, lower.tail = (0, 0, 1), (0, 0, 2)
    lower.parent = upper
    lower.use_connect = True
finally:
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.objects.active = previous

groups = {name: arm.vertex_groups.new(name=name) for name in ("upper", "lower")}
for vertex in mesh.vertices:
    blend = min(max((vertex.co.z - 0.75) / 0.5, 0.0), 1.0)  # soft transition around the joint
    groups["lower"].add([vertex.index], blend, "REPLACE")
    groups["upper"].add([vertex.index], 1.0 - blend, "REPLACE")
modifier = arm.modifiers.new("Skeleton", "ARMATURE")
modifier.object = rig
arm.parent = rig
__result__ = {"mesh": arm.name, "rig": rig.name}
```

## Pitfalls
- Vertex group names must match bone names exactly.
- Unapplied scale on the mesh or rig distorts poses and exports.
- Too few loops at a joint collapse it. Use at least three around each bend.
- The Armature modifier should come before Subdivision.

## Checks
Pose a bone (`rig.pose.bones[...]`, set `rotation_mode` and the angle), then inspect with `source="evaluated"` and capture `right` to check volume at the joint. Reset the pose afterwards.
