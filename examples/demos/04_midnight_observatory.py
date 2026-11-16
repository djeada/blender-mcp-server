"""Build a miniature radio observatory for the README gallery.

Run with Blender or use blender_python_exec with an absolute output path:
    blender -b -t 6 --python examples/demos/04_midnight_observatory.py -- observatory.png
"""

import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def material(name, rgb, *, metallic=0.0, roughness=0.42, emission=0.0):
    surface = bpy.data.materials.new(name)
    surface.diffuse_color = (*rgb, 1)
    surface.use_nodes = True
    shader = surface.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*rgb, 1)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    if emission:
        socket = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
        socket.default_value = (*rgb, 1)
        shader.inputs["Emission Strength"].default_value = emission
    return surface


def box(name, position, size, surface, *, bevel=0.04):
    bpy.ops.mesh.primitive_cube_add(size=1, location=position)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(surface)
    if bevel:
        edge = obj.modifiers.new("Machined edges", "BEVEL")
        edge.width = bevel
        edge.segments = 3
    return obj


def cylinder(name, position, radius, depth, surface, vertices=96):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=position)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(surface)
    return obj


def sphere(name, position, radius, surface):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=radius, location=position)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(surface)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def ring(name, position, radius, thickness, surface, direction=(0, 0, 1)):
    bpy.ops.mesh.primitive_torus_add(
        major_segments=96, minor_segments=12, location=position, major_radius=radius, minor_radius=thickness
    )
    obj = bpy.context.object
    obj.name = name
    obj.rotation_euler = Vector(direction).to_track_quat("Z", "Y").to_euler()
    obj.data.materials.append(surface)
    return obj


def strut(name, a, b, radius, surface):
    axis = Vector(b) - Vector(a)
    obj = cylinder(name, (Vector(a) + Vector(b)) / 2, radius, axis.length, surface, 16)
    obj.rotation_euler = axis.to_track_quat("Z", "Y").to_euler()
    return obj


def dish(center, direction, surfaces):
    """Create independent radial panels in the reflector's tilted local frame."""
    normal = Vector(direction).normalized()
    rotation = normal.to_track_quat("Z", "Y")

    def point(radius, angle):
        return Vector(center) + rotation @ Vector(
            (radius * math.cos(angle), radius * math.sin(angle), 0.15 * radius**2)
        )

    for sector in range(24):
        start = math.tau * sector / 24 + 0.012
        end = math.tau * (sector + 1) / 24 - 0.012
        vertices = [
            point(radius, start + (end - start) * i / 5) for radius in (0.20, 1.08, 2.02, 2.88) for i in range(6)
        ]
        faces = [(i, i + 1, i + 7, i + 6) for i in range(17) if i % 6 != 5]
        mesh = bpy.data.meshes.new("Reflector panel")
        mesh.from_pydata(vertices, [], faces)
        obj = bpy.data.objects.new(f"Reflector panel {sector + 1:02d}", mesh)
        bpy.context.collection.objects.link(obj)
        obj.data.materials.append(surfaces[sector % 2])
        obj.modifiers.new("Panel thickness", "SOLIDIFY").thickness = 0.025

    rim_center = Vector(center) + normal * (0.15 * 2.88**2)
    ring("Copper reflector rim", rim_center, 2.88, 0.055, surfaces[2], normal)
    receiver = Vector(center) + normal * 2.45
    sphere("Ceramic feed antenna", receiver, 0.22, surfaces[2])
    sphere("Receiver beacon", receiver + normal * 0.17, 0.11, surfaces[3])
    for index in range(3):
        strut("Feed support", point(2.78, math.tau * index / 3), receiver, 0.035, surfaces[2])


def light(name, position, target, power, color, size):
    bpy.ops.object.light_add(type="AREA", location=position)
    obj = bpy.context.object
    obj.name = name
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    obj.data.energy, obj.data.color, obj.data.shape, obj.data.size = power, color, "DISK", size


def build(output, blend_path=None, render=True):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    scene = bpy.context.scene
    scene.name = "Midnight Observatory"
    blue = material("Cobalt enamel", (0.025, 0.12, 0.23), metallic=0.68)
    navy = material("Brushed titanium", (0.064, 0.095, 0.14), metallic=0.75)
    rim = material("Brushed copper", (0.53, 0.18, 0.065), metallic=0.8, roughness=0.29)
    white = material("Porcelain panels", (0.46, 0.72, 0.78), metallic=0.48, roughness=0.23)
    glass = material("Reflector coating", (0.11, 0.28, 0.5), metallic=0.75, roughness=0.22)
    amber = material("Amber navigation lights", (1, 0.31, 0.048), emission=5)
    cyan = material("Cyan instrument lights", (0.03, 0.66, 1), emission=4)
    basalt = material("Basalt plinth", (0.037, 0.057, 0.083), roughness=0.83)
    dark = material("Midnight stage", (0.016, 0.03, 0.065), roughness=0.88)

    box("Stage", (0, 0, -0.49), (200, 200, 0.1), dark, bevel=0)
    cylinder("Basalt foundation", (0, 0, -0.27), 6.8, 0.38, basalt, 12)
    cylinder("Raised observation platform", (0, 0, 0.02), 6.66, 0.23, navy, 12)
    ring("Perimeter navigation rail", (0, 0, 0.18), 5.92, 0.021, amber)
    ring("Track bed", (0, 0, 0.16), 2.75, 0.04, rim)
    ring("Azimuth indicator", (0, 0, 0.18), 2.53, 0.024, cyan)
    cylinder("Pedestal", (0, 0, 0.46), 1.47, 0.65, blue, 24)
    cylinder("Azimuth bearing", (0, 0, 0.84), 1.27, 0.19, rim, 40)
    cylinder("Drive tower", (0, 0, 1.7), 0.67, 1.64, navy, 12)
    for i in range(12):
        angle = math.tau * i / 12
        x, y = math.cos(angle), math.sin(angle)
        strut("Pedestal brace", (1.35 * x, 1.35 * y, 0.75), (0.61 * x, 0.61 * y, 2.35), 0.063, rim)
    dish((0, 0, 3.08), (0.72, -0.32, 0.62), (white, glass, rim, cyan))

    for i in range(48):
        angle = math.tau * i / 48
        obj = box(
            "Azimuth tick",
            (5.52 * math.cos(angle), 5.52 * math.sin(angle), 0.155),
            (0.29 if i % 4 == 0 else 0.16, 0.025, 0.017),
            white,
            bevel=0,
        )
        obj.rotation_euler.z = angle
    for x, y in ((-3.0, -2.9), (1.2, 4.1), (-3.6, 2.0)):
        box("Instrument enclosure", (x, y, 0.53), (1.08, 0.78, 0.76), blue)
        box("Porcelain cover", (x, y, 0.94), (1.14, 0.84, 0.11), white)
        for lane in (-0.25, 0, 0.25):
            box("Status indicator", (x + lane, y - 0.405, 0.65), (0.1, 0.028, 0.045), cyan, bevel=0.01)
    for sign in (-1, 1):
        for index in range(5):
            along = -1.5 + index * 0.66
            x = sign * 3.75
            panel = box("Photovoltaic panel", (x, along, 0.57), (1.68, 0.56, 0.09), glass)
            panel.rotation_euler.y = sign * 0.25
            for cell in range(1, 6):
                dx = (cell - 3) * 0.25
                box("Collector busbar", (x + dx, along, 0.627 - sign * 0.25 * dx), (0.014, 0.5, 0.007), rim, bevel=0)

    rng = random.Random(42)
    for _ in range(30):
        angle = rng.uniform(0, math.tau)
        radius = rng.uniform(8.4, 17)
        boulder = sphere(
            "Basalt fragment",
            (radius * math.cos(angle), radius * math.sin(angle), -0.35),
            rng.uniform(0.13, 0.65),
            basalt,
        )
        boulder.scale = (1.3, 0.74, 0.46)

    light("Warm key", (-7, -5, 11), (0, 0, 2), 1800, (1, 0.54, 0.33), 7)
    light("Blue rim", (-3, 7, 8), (0, 0, 2), 2600, (0.29, 0.56, 1), 6)
    light("Soft front fill", (8, -7, 6), (0, 0, 2), 1050, (0.57, 0.79, 1), 7)
    scene.world.use_nodes = True
    world = scene.world.node_tree.nodes["Background"]
    world.inputs["Color"].default_value = (0.074, 0.14, 0.31, 1)
    world.inputs["Strength"].default_value = 0.24

    bpy.ops.object.camera_add(location=(14, -19, 13))
    camera = bpy.context.object
    camera.name = "Gallery camera"
    camera.rotation_euler = (Vector((0, 0, 1.15)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type, camera.data.ortho_scale = "ORTHO", 17.2
    scene.camera = camera
    scene.render.engine = "CYCLES"
    scene.cycles.samples, scene.cycles.use_denoising = 28, True
    scene.view_settings.view_transform = "AgX"
    scene.render.resolution_x, scene.render.resolution_y = 1536, 960
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(output)

    for obj in bpy.context.selected_objects:
        obj.select_set(False)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type == "VIEW_3D":
                space = area.spaces.active
                space.overlay.show_overlays = False
                space.shading.color_type = "MATERIAL"
                space.region_3d.view_rotation = camera.rotation_euler.to_quaternion()
                space.region_3d.view_location = (0, 0, 1.4)
                space.region_3d.view_distance = 20
                space.region_3d.view_perspective = "ORTHO"
    if blend_path:
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    if render:
        bpy.ops.render.render(write_still=True)
    return {"scene": scene.name, "objects": len(scene.objects), "output": str(output)}


if "args" in globals():
    __result__ = build(Path(args["output"]), args.get("blend_path"), args.get("render", True))
else:
    parameters = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    output = Path(parameters[0]).resolve() if parameters else Path("observatory.png").resolve()
    build(output, output.with_suffix(".blend"))
