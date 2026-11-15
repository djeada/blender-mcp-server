"""Build a pipe-pressure failure animation focused on a single weak joint.

Run through Blender MCP via ``blender_python_exec``. The script constructs a
muted industrial corridor, places a bright readable pipe system against the
wall, and animates a clear sequence:

1. Mechanical stress build-up
2. Steam warning leak at the flange seam
3. Joint deformation and support strain
4. Full liquid rupture with recoil and violent sustained shaking

Args:
    frame_end (int): Last frame of the preview. Default: 120.
    fps (int): Scene frame rate. Default: 24.
    resolution_x (int): Render width. Default: 1280.
    resolution_y (int): Render height. Default: 720.
    render_engine (str): Blender render engine. Default: BLENDER_EEVEE_NEXT.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Euler, Vector

FRAME_END = int(args.get("frame_end", 120))
FPS = int(args.get("fps", 24))
RES_X = int(args.get("resolution_x", 1280))
RES_Y = int(args.get("resolution_y", 720))
RENDER_ENGINE = args.get("render_engine", "BLENDER_EEVEE_NEXT")

SCENE_NAME = "PipeBurstSequence"


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


def ensure_collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def link_to_collection(obj: bpy.types.Object, coll: bpy.types.Collection) -> None:
    if obj.name not in coll.objects:
        coll.objects.link(obj)
    for other in list(obj.users_collection):
        if other != coll:
            other.objects.unlink(obj)


def parent_keep_transform(obj: bpy.types.Object, parent: bpy.types.Object) -> None:
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 1.0
    t = max(0.0, min(1.0, (x - edge0) / (edge1 - edge0)))
    return t * t * (3.0 - 2.0 * t)


def align_x_to_vector(direction: Vector) -> Euler:
    quat = direction.normalized().to_track_quat("X", "Z")
    return quat.to_euler()


def mesh_object(
    name: str,
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    location=(0.0, 0.0, 0.0),
    rotation=(0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = rotation
    obj.scale = scale
    return obj


def cube_data() -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
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


def cylinder_x_data(segments: int = 24) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    verts = []
    for x in (-1.0, 1.0):
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            verts.append((x, math.cos(angle), math.sin(angle)))
    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        n = (i + 1) % segments
        faces.append((i, n, segments + n, segments + i))
    faces.append(tuple(reversed(range(segments))))
    faces.append(tuple(range(segments, 2 * segments)))
    return verts, faces


def cone_y_data(segments: int = 20) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    verts = [(0.0, 1.0, 0.0)]
    for i in range(segments):
        angle = 2.0 * math.pi * i / segments
        verts.append((math.cos(angle), 0.0, math.sin(angle)))
    faces: list[tuple[int, ...]] = []
    for i in range(segments):
        n = 1 + (i + 1) % segments
        faces.append((0, 1 + i, n))
    faces.append(tuple(range(1, segments + 1)))
    return verts, faces


def torus_data(
    major_segments: int = 28, minor_segments: int = 10
) -> tuple[list[tuple[float, float, float]], list[tuple[int, ...]]]:
    verts = []
    faces = []
    for i in range(major_segments):
        theta = 2.0 * math.pi * i / major_segments
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        for j in range(minor_segments):
            phi = 2.0 * math.pi * j / minor_segments
            cos_p = math.cos(phi)
            sin_p = math.sin(phi)
            x = (1.0 + 0.22 * cos_p) * cos_t
            y = (1.0 + 0.22 * cos_p) * sin_t
            z = 0.22 * sin_p
            verts.append((x, y, z))
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


def create_box(name: str, size, location, collection, material=None) -> bpy.types.Object:
    verts, faces = cube_data()
    sx, sy, sz = size
    obj = mesh_object(name, verts, faces, location=location, scale=(sx / 2.0, sy / 2.0, sz / 2.0))
    link_to_collection(obj, collection)
    if material:
        obj.data.materials.append(material)
    return obj


def create_pipe(name: str, start, end, radius: float, collection, material=None) -> bpy.types.Object:
    verts, faces = cylinder_x_data()
    start_v = Vector(start)
    end_v = Vector(end)
    direction = end_v - start_v
    obj = mesh_object(
        name,
        verts,
        faces,
        location=(start_v + end_v) / 2.0,
        rotation=align_x_to_vector(direction),
        scale=(direction.length / 2.0, radius, radius),
    )
    link_to_collection(obj, collection)
    if material:
        obj.data.materials.append(material)
    return obj


def create_torus(name: str, location, rotation, scale, collection, material=None) -> bpy.types.Object:
    verts, faces = torus_data()
    obj = mesh_object(name, verts, faces, location=location, rotation=rotation, scale=scale)
    link_to_collection(obj, collection)
    if material:
        obj.data.materials.append(material)
    return obj


def create_cone(name: str, location, rotation, scale, collection, material=None) -> bpy.types.Object:
    verts, faces = cone_y_data()
    obj = mesh_object(name, verts, faces, location=location, rotation=rotation, scale=scale)
    link_to_collection(obj, collection)
    if material:
        obj.data.materials.append(material)
    return obj


def make_material(
    name: str,
    base_color,
    *,
    metallic: float = 0.0,
    roughness: float = 0.5,
    emission=None,
    emission_strength: float = 0.0,
    alpha: float = 1.0,
    transmission: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Transmission Weight"].default_value = transmission
    bsdf.inputs["Alpha"].default_value = alpha
    if emission is not None:
        bsdf.inputs["Emission Color"].default_value = (*emission, 1.0)
        bsdf.inputs["Emission Strength"].default_value = emission_strength
    if hasattr(mat, "blend_method"):
        mat.blend_method = "BLEND" if alpha < 1.0 else "OPAQUE"
    if hasattr(mat, "shadow_method"):
        mat.shadow_method = "HASHED"
    return mat


def make_empty(name: str, location, collection) -> bpy.types.Object:
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.location = location
    bpy.context.scene.collection.objects.link(obj)
    link_to_collection(obj, collection)
    return obj


def insert_loc_rot(obj: bpy.types.Object, frame: int) -> None:
    obj.keyframe_insert(data_path="location", frame=frame)
    obj.keyframe_insert(data_path="rotation_euler", frame=frame)


def insert_loc_scale(obj: bpy.types.Object, frame: int) -> None:
    obj.keyframe_insert(data_path="location", frame=frame)
    obj.keyframe_insert(data_path="scale", frame=frame)


clear_scene()
scene = bpy.context.scene
scene.name = SCENE_NAME
scene.frame_start = 1
scene.frame_end = FRAME_END
scene.frame_current = 1
scene.render.fps = FPS
scene.render.engine = RENDER_ENGINE
scene.render.resolution_x = RES_X
scene.render.resolution_y = RES_Y
scene.render.resolution_percentage = 100
if hasattr(scene, "eevee"):
    if hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 32
    if hasattr(scene.eevee, "use_bloom"):
        scene.eevee.use_bloom = True
scene.world.color = (0.17, 0.18, 0.20)
if scene.world and scene.world.use_nodes:
    bg = scene.world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.17, 0.18, 0.20, 1.0)
        bg.inputs[1].default_value = 0.75
scene.view_settings.exposure = 1.5

environment_coll = ensure_collection("Environment")
pipes_coll = ensure_collection("Pipes")
fx_coll = ensure_collection("FX")
camera_coll = ensure_collection("Camera")
light_coll = ensure_collection("Lights")

mat_room = make_material("Room", (0.12, 0.13, 0.15), roughness=0.85)
mat_floor = make_material("Floor", (0.17, 0.18, 0.19), roughness=0.9)
mat_pipe = make_material(
    "PrimaryPipe",
    (0.82, 0.84, 0.78),
    metallic=0.7,
    roughness=0.28,
    emission=(0.82, 0.84, 0.78),
    emission_strength=0.48,
)
mat_secondary = make_material(
    "SecondaryPipe",
    (0.67, 0.72, 0.70),
    metallic=0.55,
    roughness=0.35,
    emission=(0.67, 0.72, 0.70),
    emission_strength=0.22,
)
mat_flange = make_material(
    "Flange",
    (0.74, 0.34, 0.20),
    metallic=0.6,
    roughness=0.38,
    emission=(0.74, 0.34, 0.20),
    emission_strength=0.42,
)
mat_support = make_material("Support", (0.22, 0.24, 0.27), metallic=0.8, roughness=0.34)
mat_machine = make_material("Machine", (0.19, 0.23, 0.27), metallic=0.45, roughness=0.55)
mat_gauge = make_material("Gauge", (0.94, 0.94, 0.91), roughness=0.18)
mat_dark = make_material("DarkSteel", (0.07, 0.08, 0.09), metallic=0.7, roughness=0.28)
mat_steam = make_material(
    "Steam",
    (0.95, 0.97, 1.0),
    roughness=0.05,
    emission=(0.95, 0.97, 1.0),
    emission_strength=0.8,
    alpha=0.08,
)
mat_mist = make_material(
    "Mist",
    (0.82, 0.90, 1.0),
    roughness=0.08,
    emission=(0.84, 0.92, 1.0),
    emission_strength=0.55,
    alpha=0.05,
)
mat_liquid = make_material(
    "LiquidBurst",
    (0.46, 0.74, 0.96),
    roughness=0.05,
    emission=(0.52, 0.78, 1.0),
    emission_strength=1.8,
    alpha=0.32,
    transmission=0.15,
)

# Room shell
create_box("Floor", (14.0, 8.0, 0.12), (0.0, 0.0, 0.0), environment_coll, mat_floor)
create_box("BackWall", (14.0, 0.16, 4.8), (0.0, -3.42, 2.4), environment_coll, mat_room)
create_box("CeilingBeam", (14.0, 0.36, 0.2), (0.0, -0.4, 4.4), environment_coll, mat_room)
create_box("LeftWallStub", (0.18, 8.0, 4.8), (-6.92, 0.0, 2.4), environment_coll, mat_room)
create_box("RightWallStub", (0.18, 8.0, 4.8), (6.92, 0.0, 2.4), environment_coll, mat_room)

# Background machinery kept quiet and blocky so the pipe line stays dominant.
create_box("ControlCabinet_A", (0.9, 0.55, 1.9), (-3.1, -3.05, 1.25), environment_coll, mat_machine)
create_box("ControlCabinet_B", (0.95, 0.55, 2.1), (2.9, -3.05, 1.38), environment_coll, mat_machine)
create_box("PumpBody_A", (1.2, 0.9, 0.8), (2.55, -1.55, 0.42), environment_coll, mat_machine)
create_box("PumpBase_A", (1.5, 1.2, 0.2), (2.55, -1.55, 0.10), environment_coll, mat_dark)
create_box("ControlDesk", (1.4, 0.7, 1.0), (1.85, 2.45, 0.55), environment_coll, mat_machine)

# Main pipe run and joint assembly.
pipe_y = -2.74
pipe_z = 1.46
main_r = 0.15
joint_center = Vector((0.0, pipe_y, pipe_z))
leak_point = Vector((0.74, pipe_y + 0.14, pipe_z + 0.01))

main_rig = make_empty("MainLineRig", joint_center, pipes_coll)
joint_rig = make_empty("WeakJointRig", joint_center, pipes_coll)
damaged_rig = make_empty("DamagedSectionRig", (0.95, pipe_y, pipe_z), pipes_coll)
support_right_rig = make_empty("SupportRightRig", (1.0, -3.18, 1.14), pipes_coll)
support_left_rig = make_empty("SupportLeftRig", (-0.9, -3.18, 1.14), pipes_coll)
steam_rig = make_empty("SteamRig", leak_point, fx_coll)
burst_rig = make_empty("BurstRig", leak_point, fx_coll)

main_left = create_pipe("MainPipeLeft", (-5.6, pipe_y, pipe_z), (-0.92, pipe_y, pipe_z), main_r, pipes_coll, mat_pipe)
main_right = create_pipe("MainPipeRight", (1.18, pipe_y, pipe_z), (5.6, pipe_y, pipe_z), main_r, pipes_coll, mat_pipe)
flange_left = create_pipe("FlangeLeft", (-0.90, pipe_y, pipe_z), (-0.66, pipe_y, pipe_z), 0.22, pipes_coll, mat_flange)
flange_right = create_pipe("FlangeRight", (0.66, pipe_y, pipe_z), (0.90, pipe_y, pipe_z), 0.22, pipes_coll, mat_flange)
gasket = create_pipe("Gasket", (-0.05, pipe_y, pipe_z), (0.05, pipe_y, pipe_z), 0.205, pipes_coll, mat_dark)
joint_core = create_pipe("JointCore", (-0.60, pipe_y, pipe_z), (0.60, pipe_y, pipe_z), 0.13, pipes_coll, mat_secondary)

for idx, x in enumerate((-0.48, -0.34, -0.20, -0.06, 0.08, 0.22, 0.36, 0.50)):
    ring = create_pipe(
        f"BellowsRing_{idx:02d}", (x - 0.02, pipe_y, pipe_z), (x + 0.02, pipe_y, pipe_z), 0.17, pipes_coll, mat_flange
    )
    parent_keep_transform(ring, joint_rig)

bolt_angles = [0.0, 1.10, 2.20, 3.14, 4.25, 5.35]
bolt_objects = []
for idx, angle in enumerate(bolt_angles):
    z = pipe_z + math.sin(angle) * 0.165
    y = pipe_y + math.cos(angle) * 0.165
    bolt = create_pipe(f"Bolt_{idx:02d}", (-0.64, y, z), (0.64, y, z), 0.022, pipes_coll, mat_dark)
    bolt_objects.append(bolt)
    parent_keep_transform(bolt, joint_rig)

gauge_stem = create_pipe("GaugeStem", (0.0, pipe_y, pipe_z + 0.15), (0.0, pipe_y, 2.02), 0.022, pipes_coll, mat_support)
gauge_body = create_pipe("GaugeBody", (0.0, -2.62, 2.05), (0.0, -2.40, 2.05), 0.14, pipes_coll, mat_gauge)
gauge_rim = create_pipe("GaugeRim", (0.0, -2.39, 2.05), (0.0, -2.34, 2.05), 0.15, pipes_coll, mat_dark)
gauge_needle = create_box("GaugeNeedle", (0.02, 0.025, 0.22), (0.0, -2.29, 2.05), pipes_coll, mat_flange)
gauge_needle.location.z -= 0.05
gauge_needle.rotation_euler = (0.0, 0.0, 0.0)

valve_stem = create_pipe(
    "ValveStem", (0.92, pipe_y, pipe_z + 0.15), (0.92, pipe_y, 1.90), 0.020, pipes_coll, mat_support
)
valve_hub = create_pipe("ValveHub", (0.92, -2.64, 1.90), (0.92, -2.54, 1.90), 0.05, pipes_coll, mat_dark)
valve_wheel = create_torus(
    "ValveWheel",
    (0.92, -2.48, 1.90),
    (math.pi / 2.0, 0.0, 0.0),
    (0.17, 0.17, 0.17),
    pipes_coll,
    mat_flange,
)

for idx, angle in enumerate((0.0, math.pi / 3.0, 2.0 * math.pi / 3.0)):
    spoke_dir = Vector((math.cos(angle), 0.0, math.sin(angle)))
    spoke = create_pipe(
        f"ValveSpoke_{idx:02d}",
        Vector((0.92, -2.48, 1.90)) - spoke_dir * 0.10,
        Vector((0.92, -2.48, 1.90)) + spoke_dir * 0.10,
        0.012,
        pipes_coll,
        mat_dark,
    )
    parent_keep_transform(spoke, valve_wheel)

branch_up_main = create_pipe(
    "BranchUpMain", (-2.7, pipe_y, pipe_z), (-2.7, pipe_y, 3.05), 0.07, pipes_coll, mat_secondary
)
branch_up_feed = create_pipe(
    "BranchUpFeed", (-2.7, pipe_y, 3.05), (-3.12, -3.05, 3.05), 0.06, pipes_coll, mat_secondary
)
branch_down_main = create_pipe(
    "BranchDownMain", (2.45, pipe_y, pipe_z), (2.45, pipe_y, 0.64), 0.08, pipes_coll, mat_secondary
)
branch_down_feed = create_pipe(
    "BranchDownFeed", (2.45, -2.20, 0.64), (2.45, -1.10, 0.64), 0.06, pipes_coll, mat_secondary
)
branch_valve = create_pipe(
    "BranchValve", (3.55, pipe_y, pipe_z), (3.55, pipe_y, 2.25), 0.055, pipes_coll, mat_secondary
)
branch_valve_cap = create_torus(
    "BranchValveWheel",
    (3.55, -2.49, 2.26),
    (math.pi / 2.0, 0.0, 0.0),
    (0.10, 0.10, 0.10),
    pipes_coll,
    mat_flange,
)


def support_group(prefix: str, x: float, rig: bpy.types.Object | None = None) -> list[bpy.types.Object]:
    objs = []
    plate = create_box(f"{prefix}_Plate", (0.18, 0.08, 0.85), (x, -3.36, 1.20), pipes_coll, mat_support)
    arm = create_box(f"{prefix}_Arm", (0.12, 0.56, 0.10), (x, -3.08, 1.46), pipes_coll, mat_support)
    lower = create_box(f"{prefix}_Lower", (0.12, 0.28, 0.08), (x, -2.94, 1.31), pipes_coll, mat_support)
    upper = create_box(f"{prefix}_Upper", (0.12, 0.28, 0.08), (x, -2.94, 1.61), pipes_coll, mat_support)
    objs.extend([plate, arm, lower, upper])
    if rig is not None:
        for obj in objs:
            parent_keep_transform(obj, rig)
    return objs


support_group("SupportFarLeft", -4.5)
support_group("SupportMidLeft", -2.5)
support_group("SupportNearLeft", -0.9, support_left_rig)
support_group("SupportNearRight", 1.0, support_right_rig)
support_group("SupportFarRight", 3.1)
support_group("SupportEdgeRight", 5.1)

for obj in (
    main_left,
    main_right,
    flange_left,
    flange_right,
    gasket,
    joint_core,
    gauge_stem,
    gauge_body,
    gauge_rim,
    valve_stem,
    valve_hub,
    valve_wheel,
):
    parent_keep_transform(
        obj, joint_rig if obj.name.startswith(("Flange", "Gasket", "Joint", "Gauge", "Valve")) else main_rig
    )

parent_keep_transform(gauge_needle, gauge_body)
parent_keep_transform(joint_rig, main_rig)
parent_keep_transform(damaged_rig, joint_rig)
parent_keep_transform(support_left_rig, main_rig)
parent_keep_transform(support_right_rig, main_rig)

for obj in (branch_up_main, branch_up_feed, branch_down_main, branch_down_feed, branch_valve, branch_valve_cap):
    if obj.name in {"BranchDownMain"}:
        parent_keep_transform(obj, main_rig)

# Local damaged side section.
ruptured_stub = create_pipe("RupturedStub", (0.92, pipe_y, pipe_z), (1.22, pipe_y, pipe_z), 0.15, pipes_coll, mat_pipe)
parent_keep_transform(ruptured_stub, damaged_rig)

# Steam and liquid FX.
steam_front = create_cone(
    "SteamFront",
    leak_point,
    (math.radians(-12), math.radians(6), math.radians(-4)),
    (0.10, 0.01, 0.10),
    fx_coll,
    mat_steam,
)
steam_upper = create_cone(
    "SteamUpper",
    leak_point + Vector((0.0, 0.02, 0.03)),
    (math.radians(-28), math.radians(0), math.radians(-6)),
    (0.08, 0.01, 0.08),
    fx_coll,
    mat_steam,
)
steam_side = create_cone(
    "SteamSide",
    leak_point + Vector((0.0, 0.0, -0.01)),
    (math.radians(-8), math.radians(14), math.radians(6)),
    (0.07, 0.01, 0.07),
    fx_coll,
    mat_steam,
)
mist_cloud = create_cone(
    "MistCloud",
    leak_point + Vector((0.0, 0.28, 0.06)),
    (math.radians(-12), math.radians(4), 0.0),
    (0.14, 0.01, 0.14),
    fx_coll,
    mat_mist,
)
liquid_jet = create_cone(
    "LiquidJet",
    leak_point + Vector((0.02, 0.02, 0.0)),
    (math.radians(-8), math.radians(-14), math.radians(-4)),
    (0.18, 0.01, 0.18),
    fx_coll,
    mat_liquid,
)
liquid_spray = create_cone(
    "LiquidSpray",
    leak_point + Vector((0.05, 0.08, 0.02)),
    (math.radians(-10), math.radians(-12), math.radians(-2)),
    (0.32, 0.01, 0.30),
    fx_coll,
    mat_mist,
)

for obj in (steam_front, steam_upper, steam_side, mist_cloud):
    parent_keep_transform(obj, steam_rig)
for obj in (liquid_jet, liquid_spray):
    parent_keep_transform(obj, burst_rig)
parent_keep_transform(steam_rig, joint_rig)
parent_keep_transform(burst_rig, damaged_rig)

# Camera and lights.
cam_data = bpy.data.cameras.new("PipeBurstCam")
camera = bpy.data.objects.new("PipeBurstCam", cam_data)
bpy.context.scene.collection.objects.link(camera)
link_to_collection(camera, camera_coll)
camera.location = (0.4, 3.5, 2.0)
camera.data.lens = 24
scene.camera = camera

cam_focus = create_box("FocusTarget", (0.02, 0.02, 0.02), (0.0, -2.72, 1.50), environment_coll, mat_dark)
cam_focus.hide_render = True
cam_focus.hide_viewport = True
camera.data.dof.use_dof = True
camera.data.dof.focus_object = cam_focus
camera.data.dof.aperture_fstop = 2.8
cam_track = camera.constraints.new(type="TRACK_TO")
cam_track.target = cam_focus
cam_track.track_axis = "TRACK_NEGATIVE_Z"
cam_track.up_axis = "UP_Y"

for frame, loc in (
    (1, (0.40, 3.50, 2.00)),
    (74, (0.18, 3.18, 1.95)),
    (FRAME_END, (0.00, 3.00, 1.90)),
):
    camera.location = loc
    camera.keyframe_insert(data_path="location", frame=frame)

key_light_data = bpy.data.lights.new("KeyLight", type="AREA")
key_light_data.energy = 7200
key_light_data.shape = "RECTANGLE"
key_light_data.size = 5.5
key_light_data.size_y = 3.0
key_light = bpy.data.objects.new("KeyLight", key_light_data)
bpy.context.scene.collection.objects.link(key_light)
link_to_collection(key_light, light_coll)
key_light.location = (1.8, 0.9, 3.9)
key_light.rotation_euler = (math.radians(-70), math.radians(8), math.radians(133))

fill_light_data = bpy.data.lights.new("FillLight", type="AREA")
fill_light_data.energy = 4200
fill_light_data.shape = "RECTANGLE"
fill_light_data.size = 4.8
fill_light_data.size_y = 2.6
fill_light = bpy.data.objects.new("FillLight", fill_light_data)
bpy.context.scene.collection.objects.link(fill_light)
link_to_collection(fill_light, light_coll)
fill_light.location = (4.0, 1.8, 2.6)
fill_light.rotation_euler = (math.radians(-78), math.radians(0), math.radians(126))

rim_light_data = bpy.data.lights.new("RimLight", type="SPOT")
rim_light_data.energy = 2600
rim_light_data.spot_size = math.radians(42)
rim_light_data.spot_blend = 0.35
rim_light = bpy.data.objects.new("RimLight", rim_light_data)
bpy.context.scene.collection.objects.link(rim_light)
link_to_collection(rim_light, light_coll)
rim_light.location = (-2.2, 1.3, 3.2)
rim_light.rotation_euler = (math.radians(-72), 0.0, math.radians(-128))

# Remember rest transforms for local animations.
flange_right_rest = flange_right.location.copy()
joint_core_rest_scale = joint_core.scale.copy()
gasket_rest = gasket.location.copy()
damaged_rest_loc = damaged_rig.location.copy()
steam_rest_loc = steam_rig.location.copy()
burst_rest_loc = burst_rig.location.copy()
wheel_rest_rot = valve_wheel.rotation_euler.copy()
gauge_body_rot = gauge_body.rotation_euler.copy()
support_left_rest = support_left_rig.rotation_euler.copy()
support_right_rest = support_right_rig.rotation_euler.copy()


for frame in range(1, FRAME_END + 1):
    stress = smoothstep(20.0, 42.0, frame)
    leak_start = smoothstep(44.0, 56.0, frame)
    leak_steady = smoothstep(58.0, 76.0, frame)
    burst = smoothstep(82.0, 86.0, frame)
    post = max(0.0, frame - 86.0)
    burst_hold = smoothstep(86.0, 92.0, frame)

    main_amp = 0.0025 + 0.010 * stress + 0.018 * leak_start + 0.020 * leak_steady
    main_phase = frame * 2.0 * math.pi / 5.0
    pre_burst_y = main_amp * math.sin(main_phase)
    pre_burst_rot = math.radians(0.2 + 0.9 * stress + 1.6 * leak_start + 2.3 * leak_steady) * math.sin(
        main_phase + 0.45
    )

    recoil = burst * (-0.085 + 0.11 * math.exp(-post / 16.0) * math.sin(post * 1.18))
    violent = burst_hold * 0.06 * math.exp(-post / 24.0) * math.sin(post * 1.56)
    main_rig.location = joint_center + Vector((0.0, pre_burst_y + recoil + violent, 0.002 * math.sin(main_phase + 0.7)))
    main_rig.rotation_euler = Euler(
        (0.0, 0.0, pre_burst_rot + math.radians(2.4) * burst_hold * math.exp(-post / 14.0) * math.sin(post * 1.05)),
        "XYZ",
    )
    insert_loc_rot(main_rig, frame)

    joint_shake = (0.004 + 0.014 * stress + 0.022 * leak_start + 0.028 * leak_steady) * math.sin(
        frame * 2.0 * math.pi / 4.0 + 0.8
    )
    torsion = math.radians(0.5 * stress + 1.2 * leak_start + 2.1 * leak_steady) * math.sin(
        frame * 2.0 * math.pi / 4.0 + 1.1
    )
    burst_torsion = math.radians(8.0) * burst_hold * math.exp(-post / 18.0) * math.sin(post * 1.42)
    joint_rig.location = joint_center + Vector((0.0, joint_shake, 0.0015 * math.sin(main_phase + 0.4)))
    joint_rig.rotation_euler = Euler(
        (torsion * 0.55 + burst_torsion * 0.35, math.radians(1.4) * leak_steady, torsion + burst_torsion), "XYZ"
    )
    insert_loc_rot(joint_rig, frame)

    whip = burst_hold * math.exp(-post / 11.0)
    damaged_rig.location = damaged_rest_loc + Vector(
        (
            0.012 * burst_hold,
            0.05 * burst_hold + 0.10 * whip * math.sin(post * 1.65),
            0.015 * burst_hold * math.sin(post * 0.8),
        )
    )
    damaged_rig.rotation_euler = Euler(
        (
            math.radians(5.5) * whip * math.sin(post * 1.35),
            math.radians(-4.0) * burst_hold,
            math.radians(18.0) * whip * math.sin(post * 1.52),
        ),
        "XYZ",
    )
    insert_loc_rot(damaged_rig, frame)

    support_left_rig.rotation_euler = Euler(
        (
            0.0,
            0.0,
            support_left_rest.z + math.radians(0.3 + 0.5 * stress) * math.sin(main_phase + 1.4),
        ),
        "XYZ",
    )
    support_left_rig.location = support_left_rig.location
    insert_loc_rot(support_left_rig, frame)

    support_right_rig.rotation_euler = Euler(
        (
            math.radians(0.7) * leak_start * math.sin(main_phase + 0.6),
            0.0,
            support_right_rest.z
            + math.radians(0.4 + 0.8 * stress + 1.3 * leak_start) * math.sin(main_phase + 1.7)
            + math.radians(-14.0) * burst_hold
            + math.radians(9.0) * whip * math.sin(post * 1.18),
        ),
        "XYZ",
    )
    insert_loc_rot(support_right_rig, frame)

    separation = 0.008 * leak_start + 0.028 * leak_steady + 0.050 * burst_hold
    flange_right.location = flange_right_rest + Vector((separation, 0.0, 0.0))
    flange_right.keyframe_insert(data_path="location", frame=frame)
    gasket.location = gasket_rest + Vector((separation * 0.38, 0.0, 0.0))
    gasket.keyframe_insert(data_path="location", frame=frame)
    joint_core.scale = (
        joint_core_rest_scale.x * (1.0 + 0.22 * leak_start + 0.30 * leak_steady + 0.34 * burst_hold),
        joint_core_rest_scale.y * (1.0 - 0.04 * leak_steady),
        joint_core_rest_scale.z * (1.0 + 0.02 * leak_start),
    )
    joint_core.keyframe_insert(data_path="scale", frame=frame)

    needle_base = math.radians(-58.0)
    needle_target = math.radians(62.0) * smoothstep(12.0, 42.0, frame)
    needle_spike = math.radians(38.0) * smoothstep(52.0, 78.0, frame)
    needle_drop = math.radians(64.0) * burst_hold * smoothstep(86.0, 102.0, frame)
    needle_chatter = math.radians(1.4 + 2.4 * leak_start + 3.2 * leak_steady) * math.sin(frame * 2.0 * math.pi / 3.0)
    gauge_needle.rotation_euler = gauge_body_rot.copy()
    gauge_needle.rotation_euler.y = needle_base + needle_target + needle_spike - needle_drop + needle_chatter
    gauge_needle.keyframe_insert(data_path="rotation_euler", frame=frame)

    chatter = math.radians(3.0 + 7.0 * stress + 12.0 * leak_start) * math.sin(frame * 2.0 * math.pi / 2.0)
    valve_wheel.rotation_euler = Euler(
        (wheel_rest_rot.x, wheel_rest_rot.y + chatter * (1.0 - burst), wheel_rest_rot.z), "XYZ"
    )
    if burst_hold > 0.0:
        valve_wheel.rotation_euler.y += math.radians(12.0) * whip * math.sin(post * 2.1)
    valve_wheel.keyframe_insert(data_path="rotation_euler", frame=frame)

    pulse = max(0.0, math.sin((frame - 44.0) * math.pi / 3.0))
    pulse_strength = leak_start * (0.25 + 0.85 * pulse)
    steady_steam = leak_steady * (0.55 + 0.08 * math.sin(frame * 2.0 * math.pi / 6.0))
    steam_strength = max(pulse_strength, steady_steam)
    steam_rig.location = steam_rest_loc + Vector(
        (0.0, 0.004 * steam_strength * math.sin(main_phase), 0.002 * steam_strength)
    )
    steam_rig.keyframe_insert(data_path="location", frame=frame)

    steam_front.scale = (0.10 + 0.08 * steam_strength, 0.01 + 1.35 * steam_strength, 0.10 + 0.08 * steam_strength)
    steam_upper.scale = (0.07 + 0.07 * steam_strength, 0.01 + 1.05 * steam_strength, 0.07 + 0.07 * steam_strength)
    steam_side.scale = (0.06 + 0.05 * steam_strength, 0.01 + 0.85 * steam_strength, 0.06 + 0.05 * steam_strength)
    mist_cloud.scale = (
        0.12 + 0.30 * steam_strength,
        0.01 + 1.10 * max(steam_strength, burst_hold * 0.55),
        0.12 + 0.28 * steam_strength,
    )
    for obj in (steam_front, steam_upper, steam_side, mist_cloud):
        obj.keyframe_insert(data_path="scale", frame=frame)

    burst_strength = burst_hold * (0.65 + 0.35 * math.sin(post * 1.25 + 0.5) ** 2)
    burst_rig.location = burst_rest_loc + Vector((0.03 * burst_hold, 0.0, 0.0))
    burst_rig.keyframe_insert(data_path="location", frame=frame)
    liquid_jet.scale = (0.18 + 0.16 * burst_strength, 0.01 + 4.8 * burst_strength, 0.18 + 0.12 * burst_strength)
    liquid_spray.scale = (0.26 + 0.40 * burst_strength, 0.01 + 3.2 * burst_strength, 0.24 + 0.34 * burst_strength)
    liquid_jet.keyframe_insert(data_path="scale", frame=frame)
    liquid_spray.keyframe_insert(data_path="scale", frame=frame)


for action in bpy.data.actions:
    for fcurve in action.fcurves:
        for key in fcurve.keyframe_points:
            key.interpolation = "LINEAR"

scene.frame_set(1)

__result__ = {
    "scene": scene.name,
    "frame_range": [scene.frame_start, scene.frame_end],
    "camera": camera.name,
    "main_rig": main_rig.name,
    "joint_rig": joint_rig.name,
    "steam_fx": [steam_front.name, steam_upper.name, steam_side.name, mist_cloud.name],
    "burst_fx": [liquid_jet.name, liquid_spray.name],
}
