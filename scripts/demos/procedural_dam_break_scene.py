"""Stable procedural dam-break scene for Blender 4.0.x.

This scene avoids Mantaflow entirely and builds a visible flood animation from a
lightweight grid-based flood simulation. The result is intended for preview and
storyboarding in Blender builds where liquid domains are unstable in the
viewport.

Args:
    frame_end (int): End frame. Default 120.
    output_dir (str): Render output directory. Default "//".
    water_frames (int): Number of animated water frames to generate. Default 120.
"""

from __future__ import annotations

import bpy
import math


def ensure_collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(coll)
    return coll


def link_to_collection(obj: bpy.types.Object, coll: bpy.types.Collection) -> None:
    for existing in tuple(obj.users_collection):
        existing.objects.unlink(obj)
    coll.objects.link(obj)


def create_block(name: str, size: tuple[float, float, float], location: tuple[float, float, float], coll: bpy.types.Collection) -> bpy.types.Object:
    sx, sy, sz = size
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    verts = [
        (-hx, -hy, -hz),
        (hx, -hy, -hz),
        (hx, hy, -hz),
        (-hx, hy, -hz),
        (-hx, -hy, hz),
        (hx, -hy, hz),
        (hx, hy, hz),
        (-hx, hy, hz),
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
    obj.location = location
    coll.objects.link(obj)
    return obj


def create_plane(name: str, size_x: float, size_y: float, z: float, coll: bpy.types.Collection) -> bpy.types.Object:
    hx, hy = size_x / 2.0, size_y / 2.0
    verts = [(-hx, -hy, z), (hx, -hy, z), (hx, hy, z), (-hx, hy, z)]
    faces = [(0, 1, 2, 3)]
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def create_material(
    name: str,
    base_color: tuple[float, float, float, float],
    *,
    roughness: float = 0.4,
    metallic: float = 0.0,
    transmission: float = 0.0,
    alpha: float = 1.0,
    emission_strength: float = 0.0,
) -> bpy.types.Material:
    mat = bpy.data.materials.get(name)
    if mat is None:
        mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.blend_method = "BLEND" if alpha < 1.0 or transmission > 0.0 else "OPAQUE"
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = base_color
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Transmission Weight"].default_value = transmission
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = alpha
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = base_color
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emission_strength
    return mat


def assign_material(obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    if obj.data.materials:
        obj.data.materials[0] = mat
    else:
        obj.data.materials.append(mat)


def cell_center(ix: int, iy: int, origin_x: float, origin_y: float, cell_size: float) -> tuple[float, float]:
    return origin_x + (ix + 0.5) * cell_size, origin_y + (iy + 0.5) * cell_size


def build_environment(scene: bpy.types.Scene) -> tuple[list[dict], bpy.types.Collection, bpy.types.Collection]:
    env_coll = ensure_collection("Environment")
    bld_coll = ensure_collection("Buildings")
    debris_coll = ensure_collection("Debris")

    ground = create_plane("Ground", 26.0, 20.0, -0.04, env_coll)
    sidewalks = [
        create_block("Sidewalk_North", (26.0, 2.0, 0.18), (0.0, 4.1, 0.05), env_coll),
        create_block("Sidewalk_South", (26.0, 2.0, 0.18), (0.0, -4.1, 0.05), env_coll),
        create_block("Sidewalk_East", (2.2, 20.0, 0.18), (4.6, 0.0, 0.05), env_coll),
        create_block("Sidewalk_West", (2.2, 20.0, 0.18), (-4.6, 0.0, 0.05), env_coll),
    ]
    road_main = create_block("MainStreet", (26.0, 4.2, 0.06), (0.0, 0.0, 0.0), env_coll)
    road_cross = create_block("CrossStreet", (4.0, 20.0, 0.06), (0.0, 0.0, 0.001), env_coll)
    barrier = create_block("DamWall", (0.5, 4.8, 1.8), (9.3, 0.0, 0.9), env_coll)
    barrier.keyframe_insert(data_path="location", frame=1)
    barrier.location = (10.4, 0.0, -1.2)
    barrier.rotation_euler = (0.0, math.radians(16), math.radians(-8))
    barrier.keyframe_insert(data_path="location", frame=10)
    barrier.keyframe_insert(data_path="rotation_euler", frame=10)

    building_specs = [
        {"name": "Building_A", "size": (3.6, 3.1, 4.4), "loc": (6.3, 5.7, 2.2)},
        {"name": "Building_B", "size": (3.0, 3.8, 5.4), "loc": (1.5, 5.5, 2.7)},
        {"name": "Building_C", "size": (4.2, 2.8, 3.8), "loc": (-5.6, 5.1, 1.9)},
        {"name": "Building_D", "size": (3.2, 3.4, 4.2), "loc": (6.8, -5.6, 2.1)},
        {"name": "Building_E", "size": (3.6, 4.4, 5.0), "loc": (-2.4, -5.7, 2.5)},
        {"name": "Building_F", "size": (3.4, 3.0, 4.0), "loc": (-7.0, -5.0, 2.0)},
    ]

    buildings = []
    for spec in building_specs:
        obj = create_block(spec["name"], spec["size"], spec["loc"], bld_coll)
        spec["object"] = obj
        spec["footprint"] = (
            spec["loc"][0] - spec["size"][0] / 2.0 - 0.15,
            spec["loc"][0] + spec["size"][0] / 2.0 + 0.15,
            spec["loc"][1] - spec["size"][1] / 2.0 - 0.15,
            spec["loc"][1] + spec["size"][1] / 2.0 + 0.15,
        )
        buildings.append(spec)

    debris_specs = [
        {"name": "Debris_Crate", "size": (0.8, 0.8, 0.6), "loc": (3.0, -1.0, 0.32)},
        {"name": "Debris_Barrel", "size": (0.7, 0.7, 0.9), "loc": (1.0, 1.1, 0.45)},
        {"name": "Debris_Pallet", "size": (1.2, 0.8, 0.16), "loc": (5.6, 1.6, 0.08)},
        {"name": "Debris_Bin", "size": (0.7, 0.7, 1.0), "loc": (-0.8, -1.2, 0.5)},
    ]
    for spec in debris_specs:
        spec["object"] = create_block(spec["name"], spec["size"], spec["loc"], debris_coll)

    road_mat = create_material("RoadMaterial", (0.11, 0.12, 0.13, 1.0), roughness=0.92)
    sidewalk_mat = create_material("SidewalkMaterial", (0.28, 0.29, 0.30, 1.0), roughness=0.88)
    building_mat = create_material("BuildingMaterial", (0.73, 0.73, 0.72, 1.0), roughness=0.7)
    wall_mat = create_material("BarrierMaterial", (0.46, 0.47, 0.50, 1.0), roughness=0.84)
    debris_mat = create_material("DebrisMaterial", (0.42, 0.29, 0.18, 1.0), roughness=0.75)

    assign_material(ground, road_mat)
    assign_material(road_main, road_mat)
    assign_material(road_cross, road_mat)
    assign_material(barrier, wall_mat)
    for obj in sidewalks:
        assign_material(obj, sidewalk_mat)
    for spec in buildings:
        assign_material(spec["object"], building_mat)
    for spec in debris_specs:
        assign_material(spec["object"], debris_mat)

    return buildings, debris_coll, env_coll


def terrain_height(x: float, y: float) -> float:
    height = 0.05 * x
    if abs(y) < 2.1:
        height -= 0.28
    if abs(x) < 1.7:
        height -= 0.18
    if abs(y) > 7.0:
        height += 0.06
    return height


def inside_footprint(x: float, y: float, footprint: tuple[float, float, float, float]) -> bool:
    min_x, max_x, min_y, max_y = footprint
    return min_x <= x <= max_x and min_y <= y <= max_y


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def smoothstep(edge0: float, edge1: float, x: float) -> float:
    if edge0 == edge1:
        return 0.0
    t = clamp((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def wave_state(frame: int, frame_end: int) -> dict[str, float]:
    t = (frame - 1) / max(1.0, float(frame_end - 1))
    lead_x = 10.4 - 18.6 * (t ** 0.82)
    crest_x = lead_x + 1.45
    branch_strength = smoothstep(2.2, -1.2, lead_x)
    north_front = branch_strength * (1.0 + 8.2 * (t ** 0.95))
    south_front = branch_strength * (0.8 + 6.6 * (t ** 0.98))
    return {
        "t": t,
        "lead_x": lead_x,
        "crest_x": crest_x,
        "crest_height": 1.9 - 0.55 * t,
        "body_depth": 0.45 + 0.25 * (1.0 - t),
        "branch_strength": branch_strength,
        "north_front": north_front,
        "south_front": south_front,
    }


def water_depth_at(frame: int, frame_end: int, x: float, y: float) -> float:
    state = wave_state(frame, frame_end)
    road_mask = 1.0 - smoothstep(1.55, 2.35, abs(y))
    main_fill = smoothstep(state["lead_x"] - 0.2, state["lead_x"] + 0.85, x)
    source_cut = 1.0 - smoothstep(10.0, 10.9, x)
    crest = math.exp(-((x - state["crest_x"]) / 1.25) ** 2) * state["crest_height"]
    wake = state["body_depth"] * (0.7 + 0.3 * (1.0 - smoothstep(6.5, 10.2, x)))
    main_depth = road_mask * source_cut * main_fill * (wake + crest)

    branch_x_mask = 1.0 - smoothstep(1.35, 2.15, abs(x - 0.3))

    north_gate = smoothstep(0.15, 0.8, y)
    north_fill = 1.0 - smoothstep(state["north_front"] - 0.7, state["north_front"] + 0.45, y)
    north_crest = math.exp(-((y - state["north_front"]) / 0.75) ** 2) * 0.75
    north_depth = branch_x_mask * state["branch_strength"] * north_gate * north_fill * (0.18 + 0.35 * state["branch_strength"] + north_crest)

    south_gate = smoothstep(0.15, 0.8, -y)
    south_fill = 1.0 - smoothstep(state["south_front"] - 0.7, state["south_front"] + 0.45, -y)
    south_crest = math.exp(-((-y - state["south_front"]) / 0.75) ** 2) * 0.62
    south_depth = branch_x_mask * state["branch_strength"] * south_gate * south_fill * (0.16 + 0.28 * state["branch_strength"] + south_crest)

    source_burst = (1.0 - smoothstep(0.0, 0.18, state["t"])) * (1.0 - smoothstep(7.6, 10.8, x)) * (1.0 - smoothstep(1.9, 3.1, abs(y))) * 0.85
    return max(0.0, main_depth, north_depth, south_depth, source_burst)


def foam_strength_at(frame: int, frame_end: int, x: float, y: float) -> float:
    state = wave_state(frame, frame_end)
    main_crest = math.exp(-((x - state["crest_x"]) / 0.42) ** 2) * (1.0 - smoothstep(1.4, 2.2, abs(y)))
    north_crest = math.exp(-((y - state["north_front"]) / 0.35) ** 2) * (1.0 - smoothstep(1.1, 1.9, abs(x - 0.3))) if state["north_front"] > 0.4 else 0.0
    south_crest = math.exp(-((-y - state["south_front"]) / 0.35) ** 2) * (1.0 - smoothstep(1.1, 1.9, abs(x - 0.3))) if state["south_front"] > 0.4 else 0.0
    source = (1.0 - smoothstep(0.0, 0.24, state["t"])) * (1.0 - smoothstep(7.8, 10.8, x)) * (1.0 - smoothstep(1.5, 2.7, abs(y)))
    return max(main_crest, north_crest, south_crest, source)


def append_surface_patch(
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int, int]],
    frame: int,
    frame_end: int,
    buildings: list[dict],
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    nx: int,
    ny: int,
) -> None:
    base_index = len(verts)
    depths = [[0.0 for _ in range(ny + 1)] for _ in range(nx + 1)]
    for ix in range(nx + 1):
        for iy in range(ny + 1):
            x = x0 + (x1 - x0) * ix / max(1, nx)
            y = y0 + (y1 - y0) * iy / max(1, ny)
            blocked = any(inside_footprint(x, y, b["footprint"]) for b in buildings)
            depth = 0.0 if blocked else water_depth_at(frame, frame_end, x, y)
            depths[ix][iy] = depth
            ripple = 0.06 * math.sin(x * 0.9 + frame * 0.17) * math.cos(y * 1.25 - frame * 0.11)
            z = terrain_height(x, y) + depth * 0.95 + ripple * min(1.0, depth * 2.8)
            verts.append((x, y, z))

    for ix in range(nx):
        for iy in range(ny):
            avg_depth = (depths[ix][iy] + depths[ix + 1][iy] + depths[ix + 1][iy + 1] + depths[ix][iy + 1]) * 0.25
            if avg_depth <= 0.02:
                continue
            v0 = base_index + ix * (ny + 1) + iy
            v1 = base_index + (ix + 1) * (ny + 1) + iy
            v2 = base_index + (ix + 1) * (ny + 1) + iy + 1
            v3 = base_index + ix * (ny + 1) + iy + 1
            faces.append((v0, v1, v2, v3))


def create_water_mesh(name: str, frame: int, frame_end: int, buildings: list[dict], mat: bpy.types.Material, coll: bpy.types.Collection) -> bpy.types.Object:
    state = wave_state(frame, frame_end)
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []

    append_surface_patch(
        verts,
        faces,
        frame,
        frame_end,
        buildings,
        max(-10.8, state["lead_x"] - 0.6),
        10.8,
        -2.4,
        2.4,
        60,
        16,
    )
    if state["north_front"] > 0.35:
        append_surface_patch(
            verts,
            faces,
            frame,
            frame_end,
            buildings,
            -2.2,
            2.4,
            -0.3,
            min(9.2, state["north_front"] + 0.6),
            18,
            28,
        )
    if state["south_front"] > 0.35:
        append_surface_patch(
            verts,
            faces,
            frame,
            frame_end,
            buildings,
            -2.1,
            2.2,
            -min(8.0, state["south_front"] + 0.6),
            0.3,
            18,
            24,
        )

    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    assign_material(obj, mat)
    obj.hide_render = True
    obj.hide_viewport = True
    mod = obj.modifiers.new(name="FloodSmooth", type="SUBSURF")
    mod.levels = 1
    mod.render_levels = 1
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def create_foam_mesh(name: str, frame: int, frame_end: int, buildings: list[dict], mat: bpy.types.Material, coll: bpy.types.Collection) -> bpy.types.Object:
    x0, x1 = -11.0, 10.8
    y0, y1 = -8.2, 9.6
    nx, ny = 52, 38
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    strengths = [[0.0 for _ in range(ny + 1)] for _ in range(nx + 1)]
    for ix in range(nx + 1):
        for iy in range(ny + 1):
            x = x0 + (x1 - x0) * ix / nx
            y = y0 + (y1 - y0) * iy / ny
            blocked = any(inside_footprint(x, y, b["footprint"]) for b in buildings)
            depth = 0.0 if blocked else water_depth_at(frame, frame_end, x, y)
            strength = 0.0 if depth <= 0.04 else foam_strength_at(frame, frame_end, x, y)
            strengths[ix][iy] = strength
            z = terrain_height(x, y) + depth * 0.98 + strength * 0.18 + 0.02
            verts.append((x, y, z))
    for ix in range(nx):
        for iy in range(ny):
            avg = (strengths[ix][iy] + strengths[ix + 1][iy] + strengths[ix + 1][iy + 1] + strengths[ix][iy + 1]) * 0.25
            if avg <= 0.06:
                continue
            v0 = ix * (ny + 1) + iy
            v1 = (ix + 1) * (ny + 1) + iy
            v2 = (ix + 1) * (ny + 1) + iy + 1
            v3 = ix * (ny + 1) + iy + 1
            faces.append((v0, v1, v2, v3))
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    assign_material(obj, mat)
    obj.hide_render = True
    obj.hide_viewport = True
    for poly in mesh.polygons:
        poly.use_smooth = True
    return obj


def key_single_frame_visibility(obj: bpy.types.Object, frame: int, frame_end: int) -> None:
    for frame_num, hidden in ((1, True), (max(1, frame - 1), True), (frame, False), (min(frame_end, frame + 1), True)):
        obj.hide_viewport = hidden
        obj.hide_render = hidden
        obj.keyframe_insert(data_path="hide_viewport", frame=frame_num)
        obj.keyframe_insert(data_path="hide_render", frame=frame_num)


def water_velocity_at(frame: int, frame_end: int, x: float, y: float) -> tuple[float, float]:
    state = wave_state(frame, frame_end)
    depth = water_depth_at(frame, frame_end, x, y)
    if depth <= 0.03:
        return 0.0, 0.0
    vx = -0.11 - 0.08 * math.exp(-((x - state["crest_x"]) / 1.5) ** 2)
    vy = 0.0
    if abs(x - 0.3) < 1.7:
        if y > 0.1 and y < state["north_front"]:
            vy += 0.05 + 0.04 * state["branch_strength"]
        if y < -0.1 and -y < state["south_front"]:
            vy -= 0.04 + 0.035 * state["branch_strength"]
    return vx, vy


def animate_debris(debris_specs: list[dict], frame_end: int) -> None:
    for spec in debris_specs:
        obj = spec["object"]
        x, y, z = spec["loc"]
        for frame in range(1, frame_end + 1, 3):
            depth = water_depth_at(frame, frame_end, x, y)
            vx, vy = water_velocity_at(frame, frame_end, x, y)
            if depth > 0.04:
                x += vx * 1.5
                y += vy * 1.7
                z = 0.08 + min(0.7, depth * 0.7)
                obj.rotation_euler.z += (-vx + vy) * 0.4
                obj.rotation_euler.x += 0.08
            obj.location = (x, y, z)
            obj.keyframe_insert(data_path="location", frame=frame)
            obj.keyframe_insert(data_path="rotation_euler", frame=frame)


def create_camera(scene: bpy.types.Scene) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("DamBreakCam")
    cam_data.lens = 28
    cam_obj = bpy.data.objects.new("DamBreakCam", cam_data)
    ensure_collection("Camera").objects.link(cam_obj)
    scene.camera = cam_obj

    keys = [
        (1, (18.0, -15.0, 10.5), (math.radians(60), 0.0, math.radians(48))),
        (45, (13.0, -12.5, 8.0), (math.radians(63), 0.0, math.radians(38))),
        (90, (9.0, -10.5, 6.2), (math.radians(66), 0.0, math.radians(27))),
        (120, (5.0, -9.0, 4.6), (math.radians(69), 0.0, math.radians(18))),
    ]
    for frame, location, rotation in keys:
        cam_obj.location = location
        cam_obj.rotation_euler = rotation
        cam_obj.keyframe_insert(data_path="location", frame=frame)
        cam_obj.keyframe_insert(data_path="rotation_euler", frame=frame)
    return cam_obj


frame_end = int(args.get("frame_end", 120))
output_dir = args.get("output_dir", "//")
water_frames = int(args.get("water_frames", frame_end))
water_frames = max(1, min(frame_end, water_frames))

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)

scene = bpy.context.scene
scene.frame_start = 1
scene.frame_end = frame_end
scene.frame_current = 1
scene.render.fps = 24
scene.render.engine = "BLENDER_EEVEE"
scene.render.resolution_x = 1280
scene.render.resolution_y = 720
scene.render.resolution_percentage = 100
scene.render.filepath = output_dir + "procedural_dam_break"

world = scene.world
if world:
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.58, 0.63, 0.69, 1.0)
        bg.inputs[1].default_value = 0.95

buildings, debris_coll, env_coll = build_environment(scene)
debris_specs = [
    {"name": obj.name, "object": obj, "loc": tuple(obj.location)}
    for obj in debris_coll.objects
]

water_coll = ensure_collection("FloodWater")
foam_coll = ensure_collection("FloodFoam")
water_mat = create_material(
    "FloodWaterMaterial",
    (0.05, 0.44, 0.96, 1.0),
    roughness=0.06,
    transmission=0.0,
    alpha=1.0,
    emission_strength=0.18,
)
foam_mat = create_material(
    "FloodFoamMaterial",
    (0.88, 0.96, 1.0, 1.0),
    roughness=0.18,
    transmission=0.0,
    alpha=1.0,
    emission_strength=0.42,
)

water_objects = []
foam_objects = []
for frame_idx in range(1, water_frames + 1):
    obj = create_water_mesh(f"FloodSurface_{frame_idx:04d}", frame_idx, frame_end, buildings, water_mat, water_coll)
    key_single_frame_visibility(obj, frame_idx, frame_end)
    water_objects.append(obj.name)
    foam = create_foam_mesh(f"FloodFoam_{frame_idx:04d}", frame_idx, frame_end, buildings, foam_mat, foam_coll)
    key_single_frame_visibility(foam, frame_idx, frame_end)
    foam_objects.append(foam.name)

animate_debris(debris_specs, frame_end)
cam_obj = create_camera(scene)

for obj in env_coll.objects:
    obj.pass_index = 1
for obj in debris_coll.objects:
    obj.pass_index = 2

scene.frame_set(min(frame_end, 72))

sample_frames = {}
for frame in (1, min(30, water_frames), min(60, water_frames), water_frames):
    state = wave_state(frame, frame_end)
    sample_frames[frame] = {
        "lead_x": round(state["lead_x"], 2),
        "north_front": round(state["north_front"], 2),
        "south_front": round(state["south_front"], 2),
    }

__result__ = {
    "scene": scene.name,
    "frame_range": [scene.frame_start, scene.frame_end],
    "water_objects": len(water_objects),
    "water_collection": water_coll.name,
    "foam_objects": len(foam_objects),
    "buildings": [spec["name"] for spec in buildings],
    "debris": [spec["name"] for spec in debris_specs],
    "camera": cam_obj.name,
    "render_engine": scene.render.engine,
    "sample_frames": sample_frames,
    "notes": [
        "This scene uses a stable procedural flood mesh sequence instead of Mantaflow.",
        "Scrub or play frames 1-120 to see the wave advance through the streets.",
    ],
}
