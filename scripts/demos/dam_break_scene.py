"""Dam-break demo scene — end-to-end Blender Python script.

Run this through the MCP bridge via ``blender_python_exec`` to build a complete
low-res fluid-through-town demo scene entirely from script.  The scene includes:

* Ground plane as a street
* Three building blockout cubes
* Fluid domain (Mantaflow liquid, low-res)
* Inflow source positioned as a water release
* Collision effectors on ground and buildings
* Two dynamic rigid-body debris objects
* Camera with keyframed dolly animation
* Frame range configured for 120-frame preview
* Render settings tuned for a fast EEVEE preview

After running, trigger a fluid bake via ``blender_python_exec_async``::

    bpy.ops.fluid.bake_all()
    __result__ = {"baked": True}

Then render a preview via ``blender_render_still``.

Args (optional overrides):
    resolution (int): Fluid domain max resolution. Default: 32
    frame_end (int): Last frame of the simulation. Default: 120
    output_dir (str): Blender-relative path for caches/renders. Default: "//"
"""

import bpy
import math


def create_cube_object(name, size, location):
    half = size / 2.0
    verts = [
        (-half, -half, -half),
        (half, -half, -half),
        (half, half, -half),
        (-half, half, -half),
        (-half, -half, half),
        (half, -half, half),
        (half, half, half),
        (-half, half, half),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    return obj


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------
resolution = args.get("resolution", 32)
frame_end = args.get("frame_end", 120)
output_dir = args.get("output_dir", "//")

# ---------------------------------------------------------------------------
# 1. Clear default scene
# ---------------------------------------------------------------------------
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# ---------------------------------------------------------------------------
# 2. Frame range
# ---------------------------------------------------------------------------
scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = frame_end
scene.frame_current = 1
scene.render.fps = 24

# ---------------------------------------------------------------------------
# 3. Ground plane (street)
# ---------------------------------------------------------------------------
bpy.ops.mesh.primitive_plane_add(size=20, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = "Ground"

# ---------------------------------------------------------------------------
# 4. Buildings
# ---------------------------------------------------------------------------
buildings = [
    {"name": "Building_A", "size": (2, 3, 4),   "loc": (3, 2, 2)},
    {"name": "Building_B", "size": (2.5, 2, 5), "loc": (-2, -1, 2.5)},
    {"name": "Building_C", "size": (1.8, 4, 3), "loc": (1, -4, 1.5)},
]

building_names = []
for b in buildings:
    bpy.ops.mesh.primitive_cube_add(location=b["loc"])
    obj = bpy.context.active_object
    obj.name = b["name"]
    obj.scale = (b["size"][0] / 2, b["size"][1] / 2, b["size"][2] / 2)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    building_names.append(obj.name)

# ---------------------------------------------------------------------------
# 5. Debris objects (small rigid-body props)
# ---------------------------------------------------------------------------
debris_names = []
debris_specs = [
    {"name": "Debris_Crate",    "loc": (2, -2, 0.4), "size": 0.8},
    {"name": "Debris_Barrel",   "loc": (-1, 1, 0.5), "size": 0.6},
]
for d in debris_specs:
    bpy.ops.mesh.primitive_cube_add(size=d["size"], location=d["loc"])
    obj = bpy.context.active_object
    obj.name = d["name"]
    debris_names.append(obj.name)

# ---------------------------------------------------------------------------
# 6. Rigid bodies on debris
# ---------------------------------------------------------------------------
for dname in debris_names:
    obj = bpy.data.objects.get(dname)
    if obj is None:
        continue
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.rigidbody.object_add()
    obj.rigid_body.type = 'ACTIVE'
    obj.rigid_body.mass = 5.0
    obj.rigid_body.friction = 0.6
    obj.rigid_body.restitution = 0.2
    obj.rigid_body.collision_shape = 'BOX'
    obj.select_set(False)

# ---------------------------------------------------------------------------
# 7. Fluid domain
# ---------------------------------------------------------------------------
domain_size = 22
domain = create_cube_object("FluidDomain", domain_size, (0, 0, 5))
dmod = domain.modifiers.new(name="Fluid", type='FLUID')
dmod.fluid_type = 'DOMAIN'
dsettings = dmod.domain_settings
dsettings.domain_type = 'LIQUID'
dsettings.resolution_max = resolution
dsettings.cache_directory = output_dir + "fluid_cache"
dsettings.use_mesh = True
dmod.show_viewport = False
domain.display_type = 'WIRE'

# ---------------------------------------------------------------------------
# 8. Inflow source (water rushing in from +X side)
# ---------------------------------------------------------------------------
inflow = create_cube_object("WaterInflow", 3, (8, 0, 3))
imod = inflow.modifiers.new(name="Fluid", type='FLUID')
imod.fluid_type = 'FLOW'
flow = imod.flow_settings
flow.flow_type = 'LIQUID'
flow.flow_behavior = 'INFLOW'
flow.use_initial_velocity = True
flow.velocity_normal = 0
flow.velocity_coord = (-4, 0, 0)  # rushing toward -X

# ---------------------------------------------------------------------------
# 9. Collision effectors — ground + buildings
# ---------------------------------------------------------------------------
collider_names = ["Ground"] + building_names
for cname in collider_names:
    obj = bpy.data.objects.get(cname)
    if obj is None:
        continue
    emod = obj.modifiers.get("Fluid") or obj.modifiers.new(name="Fluid", type='FLUID')
    emod.fluid_type = 'EFFECTOR'
    eff = emod.effector_settings
    eff.effector_type = 'COLLISION'
    eff.surface_distance = 0.01

# ---------------------------------------------------------------------------
# 10. Camera with dolly keyframes
# ---------------------------------------------------------------------------
cam_data = bpy.data.cameras.new("DamBreakCam")
cam_obj = bpy.data.objects.new("DamBreakCam", cam_data)
bpy.context.collection.objects.link(cam_obj)
cam_obj.data.lens = 35

scene.camera = cam_obj

cam_keyframes = [
    {"frame": 1,          "location": (15, -12, 8), "rotation": (math.radians(60), 0, math.radians(50))},
    {"frame": frame_end // 2, "location": (6, -10, 5),  "rotation": (math.radians(65), 0, math.radians(30))},
    {"frame": frame_end,  "location": (0, -8, 3),   "rotation": (math.radians(70), 0, math.radians(10))},
]
for kf in cam_keyframes:
    cam_obj.location = kf["location"]
    cam_obj.rotation_euler = kf["rotation"]
    cam_obj.keyframe_insert(data_path="location", frame=kf["frame"])
    cam_obj.keyframe_insert(data_path="rotation_euler", frame=kf["frame"])

# ---------------------------------------------------------------------------
# 11. Collections
# ---------------------------------------------------------------------------
def move_to_collection(obj_name, coll_name):
    obj = bpy.data.objects.get(obj_name)
    if obj is None:
        return
    coll = bpy.data.collections.get(coll_name)
    if coll is None:
        coll = bpy.data.collections.new(coll_name)
        scene.collection.children.link(coll)
    for c in obj.users_collection:
        c.objects.unlink(obj)
    coll.objects.link(obj)

for bn in building_names:
    move_to_collection(bn, "Buildings")
for dn in debris_names:
    move_to_collection(dn, "Debris")
move_to_collection("Ground", "Environment")
move_to_collection("FluidDomain", "Fluid")
move_to_collection("WaterInflow", "Fluid")
move_to_collection("DamBreakCam", "Camera")

# ---------------------------------------------------------------------------
# 12. Render settings (fast EEVEE preview)
# ---------------------------------------------------------------------------
scene.render.engine = 'BLENDER_EEVEE'
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.resolution_percentage = 100
scene.render.filepath = output_dir + "dam_break_preview"

# ---------------------------------------------------------------------------
# Result summary
# ---------------------------------------------------------------------------
__result__ = {
    "scene": scene.name,
    "frame_range": [scene.frame_start, scene.frame_end],
    "fluid_domain": domain.name,
    "fluid_resolution": resolution,
    "inflow": inflow.name,
    "colliders": collider_names,
    "debris": debris_names,
    "camera": cam_obj.name,
    "camera_keyframes": len(cam_keyframes),
    "buildings": building_names,
    "render_engine": scene.render.engine,
    "render_resolution": [scene.render.resolution_x, scene.render.resolution_y],
    "next_steps": [
        "The liquid domain stays hidden in the viewport to avoid Blender 4.0.2 view-layer update crashes.",
        "Bake fluid: blender_python_exec_async with code 'bpy.ops.fluid.bake_all(); __result__={\"baked\":True}'",
        "Render preview: blender_render_still with output_path '/tmp/dam_break.png'",
    ],
}
