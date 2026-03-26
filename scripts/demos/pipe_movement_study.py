"""Movement-first pipe pressure study for Blender MCP.

This pass intentionally excludes steam, fluid, and rupture FX. It focuses on a
single readable mechanical system:

* main pressure pipe mounted to the wall
* one weak joint assembly with flange + bellows + gauge + shutoff wheel
* heavy brackets that mostly hold, but begin to creak near the weak joint
* a clear animation arc from idle vibration to dangerous shudder

Args:
    frame_end (int): Last frame. Default 96.
    fps (int): Frame rate. Default 24.
    resolution_x (int): Render width. Default 1280.
    resolution_y (int): Render height. Default 720.
    render_engine (str): Blender render engine. Default BLENDER_EEVEE_NEXT.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Euler, Vector


FRAME_END = int(args.get("frame_end", 96))
FPS = int(args.get("fps", 24))
RES_X = int(args.get("resolution_x", 1280))
RES_Y = int(args.get("resolution_y", 720))
RENDER_ENGINE = args.get("render_engine", "BLENDER_EEVEE_NEXT")


def clear_scene() -> None:
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes,
        bpy.data.materials,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.collections,
        bpy.data.actions,
    ):
        for block in list(datablocks):
            if block.users == 0:
                datablocks.remove(block)


def ensure_collection(name: str) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def link_only(obj: bpy.types.Object, coll: bpy.types.Collection) -> None:
    for other in list(obj.users_collection):
        other.objects.unlink(obj)
    coll.objects.link(obj)


def parent_keep_transform(obj: bpy.types.Object, parent: bpy.types.Object) -> None:
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()


def smoothstep(a: float, b: float, x: float) -> float:
    if a == b:
        return 1.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def align_x(direction: Vector) -> Euler:
    return direction.normalized().to_track_quat("X", "Z").to_euler()


def cube_data():
    verts = [
        (-1.0, -1.0, -1.0),
        (1.0, -1.0, -1.0),
        (1.0, 1.0, -1.0),
        (-1.0, 1.0, -1.0),
        (-1.0, -1.0, 1.0),
        (1.0, -1.0, 1.0),
        (1.0, 1.0, 1.0),
        (-1.0, 1.0, 1.0),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    return verts, faces


def cylinder_x_data(segments: int = 28):
    verts = []
    for x in (-1.0, 1.0):
        for i in range(segments):
            a = 2.0 * math.pi * i / segments
            verts.append((x, math.cos(a), math.sin(a)))
    faces = []
    for i in range(segments):
        n = (i + 1) % segments
        faces.append((i, n, segments + n, segments + i))
    faces.append(tuple(reversed(range(segments))))
    faces.append(tuple(range(segments, 2 * segments)))
    return verts, faces


def torus_data(major_segments: int = 28, minor_segments: int = 10):
    verts = []
    faces = []
    for i in range(major_segments):
        theta = 2.0 * math.pi * i / major_segments
        for j in range(minor_segments):
            phi = 2.0 * math.pi * j / minor_segments
            r = 1.0 + 0.20 * math.cos(phi)
            verts.append((r * math.cos(theta), r * math.sin(theta), 0.20 * math.sin(phi)))
    for i in range(major_segments):
        ni = (i + 1) % major_segments
        for j in range(minor_segments):
            nj = (j + 1) % minor_segments
            a = i * minor_segments + j
            b = i * minor_segments + nj
            c = ni * minor_segments + nj
            d = ni * minor_segments + j
            faces.append((a, b, c, d))
    return verts, faces


def make_mesh_object(name, verts, faces, location=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1)):
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = rotation
    obj.scale = scale
    return obj


def create_box(name, size, location, coll, material=None):
    verts, faces = cube_data()
    obj = make_mesh_object(name, verts, faces, location=location, scale=(size[0] / 2.0, size[1] / 2.0, size[2] / 2.0))
    link_only(obj, coll)
    if material:
        obj.data.materials.append(material)
    return obj


def create_pipe(name, start, end, radius, coll, material=None):
    verts, faces = cylinder_x_data()
    start_v = Vector(start)
    end_v = Vector(end)
    direction = end_v - start_v
    obj = make_mesh_object(
        name,
        verts,
        faces,
        location=(start_v + end_v) / 2.0,
        rotation=align_x(direction),
        scale=(direction.length / 2.0, radius, radius),
    )
    link_only(obj, coll)
    if material:
        obj.data.materials.append(material)
    return obj


def create_torus(name, location, rotation, scale, coll, material=None):
    verts, faces = torus_data()
    obj = make_mesh_object(name, verts, faces, location=location, rotation=rotation, scale=scale)
    link_only(obj, coll)
    if material:
        obj.data.materials.append(material)
    return obj


def make_material(name, color, *, metallic=0.0, roughness=0.5, emission_strength=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    if emission_strength > 0.0:
        bsdf.inputs["Emission Color"].default_value = (*color, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    return mat


def make_empty(name, location, coll):
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    link_only(obj, coll)
    return obj


def key_loc_rot(obj, frame):
    obj.keyframe_insert(data_path="location", frame=frame)
    obj.keyframe_insert(data_path="rotation_euler", frame=frame)


clear_scene()
scene = bpy.context.scene
scene.name = "PipeMovementStudy"
scene.frame_start = 1
scene.frame_end = FRAME_END
scene.render.fps = FPS
scene.render.engine = RENDER_ENGINE
scene.render.resolution_x = RES_X
scene.render.resolution_y = RES_Y
scene.render.resolution_percentage = 100
if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
    scene.eevee.taa_render_samples = 32
scene.view_settings.exposure = 0.8
scene.world.color = (0.03, 0.04, 0.05)
if scene.world.use_nodes:
    bg = scene.world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.03, 0.04, 0.05, 1.0)
        bg.inputs[1].default_value = 0.35

env_coll = ensure_collection("Environment")
pipes_coll = ensure_collection("Pipes")
cam_coll = ensure_collection("Camera")
light_coll = ensure_collection("Lights")

mat_wall = make_material("Wall", (0.10, 0.11, 0.13), roughness=0.92)
mat_floor = make_material("Floor", (0.16, 0.17, 0.18), roughness=0.95)
mat_pipe = make_material("Pipe", (0.86, 0.88, 0.82), metallic=0.7, roughness=0.25, emission_strength=0.35)
mat_joint = make_material("Joint", (0.78, 0.36, 0.22), metallic=0.55, roughness=0.32, emission_strength=0.25)
mat_support = make_material("Support", (0.22, 0.24, 0.27), metallic=0.85, roughness=0.32)
mat_dark = make_material("Dark", (0.08, 0.09, 0.10), metallic=0.65, roughness=0.30)
mat_gauge = make_material("Gauge", (0.94, 0.94, 0.91), roughness=0.18)

create_box("Floor", (9.0, 5.5, 0.12), (0.0, 0.0, 0.0), env_coll, mat_floor)
create_box("BackWall", (9.0, 0.16, 4.5), (0.0, -2.85, 2.25), env_coll, mat_wall)

pipe_y = -2.28
pipe_z = 1.55
joint_center = Vector((0.0, pipe_y, pipe_z))

main_rig = make_empty("MainRig", joint_center, pipes_coll)
joint_rig = make_empty("JointRig", joint_center, pipes_coll)
weak_stub_rig = make_empty("WeakStubRig", (0.95, pipe_y, pipe_z), pipes_coll)
support_left_rig = make_empty("SupportLeftRig", (-0.9, -2.62, 1.20), pipes_coll)
support_right_rig = make_empty("SupportRightRig", (0.95, -2.62, 1.20), pipes_coll)

main_left = create_pipe("MainLeft", (-3.9, pipe_y, pipe_z), (-0.88, pipe_y, pipe_z), 0.17, pipes_coll, mat_pipe)
main_right = create_pipe("MainRight", (1.18, pipe_y, pipe_z), (3.9, pipe_y, pipe_z), 0.17, pipes_coll, mat_pipe)
flange_left = create_pipe("FlangeLeft", (-0.86, pipe_y, pipe_z), (-0.60, pipe_y, pipe_z), 0.24, pipes_coll, mat_joint)
flange_right = create_pipe("FlangeRight", (0.60, pipe_y, pipe_z), (0.86, pipe_y, pipe_z), 0.24, pipes_coll, mat_joint)
joint_core = create_pipe("JointCore", (-0.58, pipe_y, pipe_z), (0.58, pipe_y, pipe_z), 0.145, pipes_coll, mat_pipe)
gasket = create_pipe("Gasket", (-0.03, pipe_y, pipe_z), (0.03, pipe_y, pipe_z), 0.215, pipes_coll, mat_dark)
rupture_stub = create_pipe("RuptureStub", (0.90, pipe_y, pipe_z), (1.18, pipe_y, pipe_z), 0.17, pipes_coll, mat_pipe)

for i, x in enumerate((-0.46, -0.30, -0.14, 0.02, 0.18, 0.34, 0.50)):
    ring = create_pipe(f"Bellows_{i:02d}", (x - 0.025, pipe_y, pipe_z), (x + 0.025, pipe_y, pipe_z), 0.19, pipes_coll, mat_joint)
    parent_keep_transform(ring, joint_rig)

for i, a in enumerate((0.0, 1.1, 2.2, 3.14, 4.24, 5.34)):
    y = pipe_y + math.cos(a) * 0.18
    z = pipe_z + math.sin(a) * 0.18
    bolt = create_pipe(f"Bolt_{i:02d}", (-0.58, y, z), (0.58, y, z), 0.022, pipes_coll, mat_dark)
    parent_keep_transform(bolt, joint_rig)

gauge_stem = create_pipe("GaugeStem", (0.0, pipe_y, pipe_z + 0.17), (0.0, pipe_y, 2.02), 0.024, pipes_coll, mat_support)
gauge_body = create_pipe("GaugeBody", (0.0, -2.10, 2.02), (0.0, -1.84, 2.02), 0.16, pipes_coll, mat_gauge)
gauge_rim = create_pipe("GaugeRim", (0.0, -1.84, 2.02), (0.0, -1.78, 2.02), 0.17, pipes_coll, mat_dark)
gauge_needle = create_box("GaugeNeedle", (0.02, 0.02, 0.24), (0.0, -1.73, 1.98), pipes_coll, mat_joint)

valve_stem = create_pipe("ValveStem", (0.88, pipe_y, pipe_z + 0.15), (0.88, pipe_y, 1.92), 0.020, pipes_coll, mat_support)
valve_hub = create_pipe("ValveHub", (0.88, -2.16, 1.92), (0.88, -2.02, 1.92), 0.05, pipes_coll, mat_dark)
valve_wheel = create_torus("ValveWheel", (0.88, -1.92, 1.92), (math.pi / 2.0, 0.0, 0.0), (0.18, 0.18, 0.18), pipes_coll, mat_joint)

for i, angle in enumerate((0.0, math.pi / 3.0, 2.0 * math.pi / 3.0)):
    d = Vector((math.cos(angle), 0.0, math.sin(angle)))
    spoke = create_pipe(f"ValveSpoke_{i:02d}", Vector((0.88, -1.92, 1.92)) - d * 0.10, Vector((0.88, -1.92, 1.92)) + d * 0.10, 0.012, pipes_coll, mat_dark)
    parent_keep_transform(spoke, valve_wheel)

branch_up = create_pipe("BranchUp", (-1.7, pipe_y, pipe_z), (-1.7, pipe_y, 2.85), 0.08, pipes_coll, mat_pipe)
branch_up_cap = create_torus("BranchUpValve", (-1.7, -1.95, 2.86), (math.pi / 2.0, 0.0, 0.0), (0.12, 0.12, 0.12), pipes_coll, mat_joint)
branch_down = create_pipe("BranchDown", (2.0, pipe_y, pipe_z), (2.0, pipe_y, 0.62), 0.08, pipes_coll, mat_pipe)


def support_group(prefix, x, rig=None):
    plate = create_box(f"{prefix}_Plate", (0.18, 0.08, 0.95), (x, -2.80, 1.18), pipes_coll, mat_support)
    arm = create_box(f"{prefix}_Arm", (0.12, 0.48, 0.10), (x, -2.54, pipe_z), pipes_coll, mat_support)
    lower = create_box(f"{prefix}_Lower", (0.12, 0.24, 0.08), (x, -2.42, pipe_z - 0.15), pipes_coll, mat_support)
    upper = create_box(f"{prefix}_Upper", (0.12, 0.24, 0.08), (x, -2.42, pipe_z + 0.15), pipes_coll, mat_support)
    if rig:
        for obj in (plate, arm, lower, upper):
            parent_keep_transform(obj, rig)


support_group("SupportFarLeft", -2.9)
support_group("SupportNearLeft", -0.9, support_left_rig)
support_group("SupportNearRight", 0.95, support_right_rig)
support_group("SupportFarRight", 2.9)

for obj in (main_left, main_right, branch_up, branch_up_cap, branch_down):
    parent_keep_transform(obj, main_rig)
for obj in (flange_left, flange_right, joint_core, gasket, gauge_stem, gauge_body, gauge_rim, valve_stem, valve_hub, valve_wheel):
    parent_keep_transform(obj, joint_rig)
parent_keep_transform(gauge_needle, gauge_body)
parent_keep_transform(joint_rig, main_rig)
parent_keep_transform(weak_stub_rig, joint_rig)
parent_keep_transform(rupture_stub, weak_stub_rig)

# Tight movement-study camera.
cam_data = bpy.data.cameras.new("MovementCam")
camera = bpy.data.objects.new("MovementCam", cam_data)
bpy.context.scene.collection.objects.link(camera)
link_only(camera, cam_coll)
camera.location = (0.15, 2.50, 1.95)
camera.data.lens = 35
scene.camera = camera

focus = create_box("Focus", (0.02, 0.02, 0.02), (0.0, -2.22, 1.70), env_coll, mat_dark)
focus.hide_viewport = True
focus.hide_render = True
track = camera.constraints.new(type="TRACK_TO")
track.target = focus
track.track_axis = "TRACK_NEGATIVE_Z"
track.up_axis = "UP_Y"

key_light_data = bpy.data.lights.new("KeyLight", type="AREA")
key_light_data.energy = 3400
key_light_data.shape = "RECTANGLE"
key_light_data.size = 3.6
key_light_data.size_y = 2.0
key_light = bpy.data.objects.new("KeyLight", key_light_data)
bpy.context.scene.collection.objects.link(key_light)
link_only(key_light, light_coll)
key_light.location = (0.7, 1.0, 3.3)
key_light.rotation_euler = (math.radians(-72), math.radians(10), math.radians(145))

fill_data = bpy.data.lights.new("FillLight", type="AREA")
fill_data.energy = 2200
fill_data.shape = "RECTANGLE"
fill_data.size = 3.0
fill_data.size_y = 1.5
fill = bpy.data.objects.new("FillLight", fill_data)
bpy.context.scene.collection.objects.link(fill)
link_only(fill, light_coll)
fill.location = (-1.8, 0.8, 2.4)
fill.rotation_euler = (math.radians(-68), math.radians(0), math.radians(-150))

joint_rest = joint_center.copy()
main_rest = joint_center.copy()
stub_rest = weak_stub_rig.location.copy()
flange_right_rest = flange_right.location.copy()
joint_scale_rest = joint_core.scale.copy()
support_left_rot_rest = support_left_rig.rotation_euler.copy()
support_right_rot_rest = support_right_rig.rotation_euler.copy()
wheel_rot_rest = valve_wheel.rotation_euler.copy()

for frame in range(1, FRAME_END + 1):
    idle = 1.0 - smoothstep(18.0, 38.0, frame)
    build = smoothstep(18.0, 48.0, frame)
    critical = smoothstep(48.0, 74.0, frame)
    danger = smoothstep(74.0, FRAME_END, frame)

    base_phase = frame * 2.0 * math.pi / 5.0
    fast_phase = frame * 2.0 * math.pi / 3.0

    main_amp = 0.0025 * idle + 0.010 * build + 0.026 * critical + 0.040 * danger
    joint_amp = 0.0040 * idle + 0.015 * build + 0.032 * critical + 0.055 * danger

    main_rig.location = main_rest + Vector((
        0.0,
        main_amp * math.sin(base_phase),
        0.002 * math.sin(base_phase + 0.8),
    ))
    main_rig.rotation_euler = Euler((
        0.0,
        math.radians(0.20 + 0.40 * build) * math.sin(base_phase + 0.5),
        math.radians(0.35 + 0.9 * critical + 1.4 * danger) * math.sin(base_phase + 0.2),
    ), "XYZ")
    key_loc_rot(main_rig, frame)

    joint_rig.location = joint_rest + Vector((
        0.0,
        joint_amp * math.sin(base_phase + 0.9),
        0.004 * critical * math.sin(fast_phase + 0.4),
    ))
    joint_rig.rotation_euler = Euler((
        math.radians(0.4 + 1.8 * critical + 3.0 * danger) * math.sin(fast_phase + 0.3),
        math.radians(0.5 + 1.4 * critical + 2.2 * danger) * math.sin(base_phase + 1.0),
        math.radians(0.7 + 2.6 * critical + 4.2 * danger) * math.sin(fast_phase + 1.1),
    ), "XYZ")
    key_loc_rot(joint_rig, frame)

    weak_stub_rig.location = stub_rest + Vector((
        0.010 * critical + 0.028 * danger,
        0.018 * critical * math.sin(fast_phase + 0.8) + 0.034 * danger * math.sin(fast_phase + 1.1),
        0.010 * danger * math.sin(base_phase + 0.6),
    ))
    weak_stub_rig.rotation_euler = Euler((
        math.radians(0.8 + 2.8 * critical + 6.0 * danger) * math.sin(fast_phase + 0.9),
        math.radians(0.6 + 2.0 * danger) * math.sin(base_phase + 0.7),
        math.radians(1.2 + 4.0 * critical + 8.0 * danger) * math.sin(fast_phase + 1.6),
    ), "XYZ")
    key_loc_rot(weak_stub_rig, frame)

    flange_sep = 0.002 * build + 0.010 * critical + 0.022 * danger
    flange_right.location = flange_right_rest + Vector((flange_sep, 0.0, 0.0))
    flange_right.keyframe_insert(data_path="location", frame=frame)
    joint_core.scale = (
        joint_scale_rest.x * (1.0 + 0.08 * critical + 0.18 * danger),
        joint_scale_rest.y * (1.0 - 0.02 * danger),
        joint_scale_rest.z * (1.0 + 0.02 * critical),
    )
    joint_core.keyframe_insert(data_path="scale", frame=frame)

    support_left_rig.rotation_euler = Euler((
        0.0,
        0.0,
        support_left_rot_rest.z + math.radians(0.2 + 0.5 * critical) * math.sin(base_phase + 1.5),
    ), "XYZ")
    key_loc_rot(support_left_rig, frame)

    support_right_rig.rotation_euler = Euler((
        math.radians(0.3 + 1.6 * danger) * math.sin(fast_phase + 0.3),
        0.0,
        support_right_rot_rest.z + math.radians(0.3 + 1.2 * critical + 3.0 * danger) * math.sin(base_phase + 1.1),
    ), "XYZ")
    key_loc_rot(support_right_rig, frame)

    gauge_needle.rotation_euler.y = (
        math.radians(-52.0)
        + math.radians(72.0) * build
        + math.radians(22.0) * critical
        + math.radians(10.0) * danger
        + math.radians(1.0 + 3.0 * critical + 5.0 * danger) * math.sin(fast_phase)
    )
    gauge_needle.keyframe_insert(data_path="rotation_euler", frame=frame)

    valve_wheel.rotation_euler = Euler((
        wheel_rot_rest.x,
        wheel_rot_rest.y + math.radians(1.0 + 5.0 * critical + 8.0 * danger) * math.sin(fast_phase + 0.5),
        wheel_rot_rest.z,
    ), "XYZ")
    valve_wheel.keyframe_insert(data_path="rotation_euler", frame=frame)

for action in bpy.data.actions:
    for fcurve in action.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = "LINEAR"

scene.frame_set(1)

__result__ = {
    "scene": scene.name,
    "frame_range": [scene.frame_start, scene.frame_end],
    "camera": camera.name,
    "rigs": [main_rig.name, joint_rig.name, weak_stub_rig.name],
}
