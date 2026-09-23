"""Demo 2 without an AI: a seeded 9x9 city block with streets, rendered with EEVEE.

Run it any of these ways (see scripts/run_demo.sh):
  blender --python docs/demos/scripts/02_procedural_city.py
  blender -b --factory-startup --python docs/demos/scripts/02_procedural_city.py -- --output out.png
  paste into Blender's Scripting tab and press Run
  send it to a running Blender through the MCP bridge (run_demo.sh --bridge)
"""

import argparse
import math
import random
import sys

import bpy


def options() -> argparse.Namespace:
    """CLI args after `--`, or the `args` dict when sent through blender_python_exec."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/blender-mcp-demos/script-02-city.png")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--no-render", dest="render", action="store_false")
    bridge_args = globals().get("args")
    if isinstance(bridge_args, dict):  # blender_python_exec: ignore Blender's own command line
        opts = parser.parse_args([])
        vars(opts).update(bridge_args)
        return opts
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])


def eevee_engine() -> str:
    """EEVEE's identifier changed across Blender 4.x releases."""
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for blocks in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for block in list(blocks):
            blocks.remove(block)


def material(name, color, roughness=0.7):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = (*color, 1.0)  # colour in Solid viewport mode
    return mat


def main() -> None:
    opts = options()
    rng = random.Random(opts.seed)
    clear_scene()
    scene = bpy.context.scene

    palette = [
        material(name, color)
        for name, color in [
            ("Terracotta", (0.55, 0.22, 0.12)),
            ("Sand", (0.62, 0.52, 0.35)),
            ("Slate", (0.28, 0.31, 0.36)),
            ("Sage", (0.35, 0.42, 0.33)),
            ("Rose", (0.55, 0.36, 0.36)),
        ]
    ]
    cell, grid = 2.4, 9
    offset = (grid - 1) * cell / 2

    bpy.ops.mesh.primitive_plane_add(size=grid * cell + 4)
    ground = bpy.context.object
    ground.name = "Asphalt"
    ground.data.materials.append(material("Asphalt", (0.05, 0.05, 0.055), 0.9))

    buildings = 0
    for row in range(grid):
        for col in range(grid):
            if row % 3 == 2 or col % 3 == 2:  # streets every third row and column
                continue
            height = rng.uniform(1.0, 7.0)
            bpy.ops.mesh.primitive_cube_add(size=1, location=(col * cell - offset, row * cell - offset, height / 2))
            building = bpy.context.object
            building.name = f"Building_{row}_{col}"
            building.scale = (cell * 0.8, cell * 0.8, height)
            building.data.materials.append(rng.choice(palette))
            buildings += 1

    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(78), 0, math.radians(-40)))
    sun = bpy.context.object
    sun.data.energy = 3.5
    sun.data.color = (1.0, 0.62, 0.35)
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.04, 0.05, 0.09)

    bpy.ops.object.camera_add(location=(-24, -26, 17))
    camera = bpy.context.object
    camera.data.lens = 40
    target = bpy.data.objects.new("CameraTarget", None)
    target.location = (0, 0, 1.5)
    scene.collection.objects.link(target)
    camera.constraints.new("TRACK_TO").target = target
    scene.camera = camera

    scene.render.engine = eevee_engine()
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.filepath = opts.output
    print(f"Built {buildings} buildings")
    if opts.render:
        bpy.ops.render.render(write_still=True)
        print(f"Rendered {opts.output}")


main()
