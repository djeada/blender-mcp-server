"""Demo 1 without an AI: a small still life, rendered with Cycles.

Run it any of these ways (see scripts/run_demo.sh):
  blender --python docs/demos/scripts/01_still_life.py                  # watch it in the GUI
  blender -b --factory-startup --python docs/demos/scripts/01_still_life.py -- --output out.png
  paste into Blender's Scripting tab and press Run
  send it to a running Blender through the MCP bridge (run_demo.sh --bridge)
"""

import argparse
import math
import sys

import bpy


def options() -> argparse.Namespace:
    """CLI args after `--`, or the `args` dict when sent through blender_python_exec."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="/tmp/blender-mcp-demos/script-01-still-life.png")
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--no-render", dest="render", action="store_false")
    bridge_args = globals().get("args")
    if isinstance(bridge_args, dict):  # blender_python_exec: ignore Blender's own command line
        opts = parser.parse_args([])
        vars(opts).update(bridge_args)
        return opts
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for blocks in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras):
        for block in list(blocks):
            blocks.remove(block)


def material(name, color, roughness, metallic=0.0):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def add(obj, mat):
    obj.data.materials.append(mat)
    for polygon in obj.data.polygons:
        polygon.use_smooth = obj.name != "Cube"
    return obj


def main() -> None:
    opts = options()
    clear_scene()
    scene = bpy.context.scene

    bpy.ops.mesh.primitive_plane_add(size=40)
    add(bpy.context.object, material("Ground", (0.8, 0.78, 0.74), 0.9)).name = "Ground"
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.8, segments=64, ring_count=32, location=(-1.2, -0.3, 0.8))
    add(bpy.context.object, material("Red", (0.75, 0.03, 0.03), 0.1)).name = "Sphere"
    bpy.ops.mesh.primitive_cube_add(size=1.4, location=(1.0, 0.4, 0.7), rotation=(0, 0, math.radians(30)))
    add(bpy.context.object, material("Blue", (0.05, 0.2, 0.65), 0.45)).name = "Cube"
    bpy.ops.mesh.primitive_torus_add(
        major_radius=0.55,
        minor_radius=0.12,
        location=(1.05, -0.45, 0.62),
        rotation=(math.radians(75), 0, math.radians(30)),
    )
    add(bpy.context.object, material("Gold", (1.0, 0.77, 0.34), 0.2, metallic=1.0)).name = "Torus"

    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(50), 0, math.radians(35)))
    sun = bpy.context.object
    sun.data.energy = 4.0
    sun.data.color = (1.0, 0.9, 0.78)

    bpy.ops.object.camera_add(location=(0.2, -7.5, 3.0))
    camera = bpy.context.object
    target = bpy.data.objects.new("CameraTarget", None)
    target.location = (0.1, 0.0, 0.6)
    scene.collection.objects.link(target)
    constraint = camera.constraints.new("TRACK_TO")
    constraint.target = target
    scene.camera = camera

    scene.render.engine = "CYCLES"
    scene.cycles.samples = opts.samples
    scene.render.resolution_x, scene.render.resolution_y = 960, 540
    scene.render.filepath = opts.output
    if opts.render:
        bpy.ops.render.render(write_still=True)
        print(f"Rendered {opts.output}")


main()
