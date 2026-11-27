"""Render every lighting rig on a character and a reflective product into one labelled sheet.

Usage (renders on the CPU with Cycles; no display needed):
    blender -b --factory-startup --python scripts/render_lighting_examples.py -- docs/images/lighting-rigs.png

Rows: a character, then a metal product. Columns, left to right: three_point, studio_softbox,
portrait, low_key, turntable. Subjects are generated here, so no external assets are used.
"""

import importlib.util
import math
import os
import sys
import tempfile

import bpy

ADDON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "addon")
spec = importlib.util.spec_from_file_location("mcp_addon", os.path.join(ADDON, "__init__.py"))
spec.submodule_search_locations = [ADDON]
addon = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = addon
spec.loader.exec_module(addon)
from mcp_addon.commands import CommandHandler  # noqa: E402

RIGS = ("three_point", "studio_softbox", "portrait", "low_key", "turntable")
SIZE = 256


def material(name, color, metallic, roughness):
    result = bpy.data.materials.new(name)
    result.use_nodes = True
    shader = next(node for node in result.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    return result


def smooth(obj):
    for polygon in obj.data.polygons:
        polygon.use_smooth = True


def character():
    bpy.ops.mesh.primitive_monkey_add()
    head = bpy.context.object
    head.name = "Character"
    modifier = head.modifiers.new("Smooth", "SUBSURF")
    modifier.levels = modifier.render_levels = 2
    smooth(head)
    head.data.materials.append(material("Skin", (0.32, 0.2, 0.13), 0.0, 0.5))
    return head.name


def product():
    bpy.ops.mesh.primitive_cylinder_add(vertices=96, radius=0.55, depth=1.6, location=(20, 0, 0))
    body = bpy.context.object
    body.name = "Product"
    bevel = body.modifiers.new("Edges", "BEVEL")
    bevel.width, bevel.segments = 0.08, 4
    smooth(body)
    body.data.materials.append(material("Steel", (0.62, 0.64, 0.66), 1.0, 0.22))
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=0.28, depth=0.3, location=(20, 0, 0.95))
    cap = bpy.context.object
    cap.name = "ProductCap"
    cap.data.materials.append(material("Cap", (0.03, 0.03, 0.03), 0.0, 0.35))
    cap.parent = body
    cap.matrix_parent_inverse = body.matrix_world.inverted()
    return body.name


def render(handler, subject, rig, path):
    camera = f"Camera {subject}"
    handler.handle(
        "camera.frame",
        {"camera": camera, "object": subject, "azimuth": 18, "elevation": 8, "lens": 85, "aspect": 1.0, "margin": 1.12},
    )
    built = handler.handle("lighting.rig_apply", {"rig": rig, "object": subject, "camera": camera, "name": "example"})
    names = {light["name"] for light in built["lights"]}
    scene = bpy.context.scene
    for obj in scene.objects:
        mine = obj.name == subject or (obj.parent is not None and obj.parent.name == subject) or obj.name in names
        obj.hide_render = not (mine or obj.name == camera)
    scene.camera = bpy.data.objects[camera]
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    handler.handle("lighting.rig_remove", {"name": "example"})
    for obj in scene.objects:
        obj.hide_render = False


def main():
    output = os.path.abspath(sys.argv[sys.argv.index("--") + 1])
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 96
    scene.cycles.seed = 1
    scene.cycles.use_denoising = False
    scene.render.resolution_x = scene.render.resolution_y = SIZE
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.view_settings.view_transform = "Standard"
    scene.world.use_nodes = False
    scene.world.color = (0.012, 0.012, 0.012)
    handler = CommandHandler()
    subjects = (character(), product())

    sheet = [0.0] * (len(RIGS) * SIZE * len(subjects) * SIZE * 4)
    width = len(RIGS) * SIZE
    with tempfile.TemporaryDirectory() as directory:
        for row, subject in enumerate(subjects):
            for column, rig in enumerate(RIGS):
                path = os.path.join(directory, f"{row}-{column}.png")
                render(handler, subject, rig, path)
                tile = bpy.data.images.load(path, check_existing=False)
                pixels = list(tile.pixels)
                bpy.data.images.remove(tile)
                top = (len(subjects) - 1 - row) * SIZE  # image rows are stored bottom up
                for y in range(SIZE):
                    start = ((top + y) * width + column * SIZE) * 4
                    sheet[start : start + SIZE * 4] = pixels[y * SIZE * 4 : (y + 1) * SIZE * 4]
                    sheet[start : start + 8] = [0.5, 0.5, 0.5, 1.0] * 2  # thin separator
    image = bpy.data.images.new("sheet", width, len(subjects) * SIZE, alpha=True)
    image.pixels = sheet
    image.filepath_raw = output
    image.file_format = "PNG"
    os.makedirs(os.path.dirname(output), exist_ok=True)
    image.save()
    print(f"WROTE {output} {width}x{len(subjects) * SIZE} spread={math.fsum(sheet[0::4]) / (len(sheet) / 4):.3f}")


main()
