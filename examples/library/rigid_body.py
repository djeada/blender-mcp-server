"""Add rigid body physics to one or more objects.

Args:
    objects (list[str]): Names of objects to configure.
    rb_type (str): "ACTIVE" or "PASSIVE". Default: "ACTIVE"
    mass (float): Mass in kg. Default: 1.0
    friction (float): Friction coefficient (0-1). Default: 0.5
    restitution (float): Bounciness (0-1). Default: 0.3
    collision_shape (str): Shape type. Default: "CONVEX_HULL"
        Options: "BOX", "SPHERE", "CAPSULE", "CYLINDER", "CONE",
                 "CONVEX_HULL", "MESH"

Result:
    configured (list[str]): Objects successfully configured
    skipped (list[str]): Objects not found
    rb_type (str): Rigid body type used
"""

import bpy

obj_names = args.get("objects", [])
rb_type = args.get("rb_type", "ACTIVE")
mass = args.get("mass", 1.0)
friction = args.get("friction", 0.5)
restitution = args.get("restitution", 0.3)
collision_shape = args.get("collision_shape", "CONVEX_HULL")

configured = []
skipped = []

for name in obj_names:
    obj = bpy.data.objects.get(name)
    if obj is None:
        skipped.append(name)
        continue

    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.rigidbody.object_add()
    obj.rigid_body.type = rb_type
    obj.rigid_body.mass = mass
    obj.rigid_body.friction = friction
    obj.rigid_body.restitution = restitution
    obj.rigid_body.collision_shape = collision_shape
    obj.select_set(False)
    configured.append(name)

__result__ = {
    "configured": configured,
    "skipped": skipped,
    "rb_type": rb_type,
}
