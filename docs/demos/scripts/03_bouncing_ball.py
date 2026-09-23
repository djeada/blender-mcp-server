"""Demo 3 without an AI: a keyframed bouncing ball, saved to a .blend and rendered frame by frame.

Run it any of these ways (see scripts/run_demo.sh):
  blender --python docs/demos/scripts/03_bouncing_ball.py              # then press Space to play
  blender -b --factory-startup --python docs/demos/scripts/03_bouncing_ball.py -- --frames 12 24 40
  paste into Blender's Scripting tab and press Run
  send it to a running Blender through the MCP bridge (run_demo.sh --bridge)
"""

import argparse
import math
import os
import sys

import bpy


def options() -> argparse.Namespace:
    """CLI args after `--`, or the `args` dict when sent through blender_python_exec."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--blend", default="/tmp/blender-mcp-demos/bouncing-ball-script.blend")
    parser.add_argument("--output-dir", default="/tmp/blender-mcp-demos")
    parser.add_argument("--frames", type=int, nargs="*", default=[12, 24, 40])
    parser.add_argument("--no-render", dest="render", action="store_false")
    bridge_args = globals().get("args")
    if isinstance(bridge_args, dict):  # blender_python_exec: ignore Blender's own command line
        opts = parser.parse_args([])
        vars(opts).update(bridge_args)
        return opts
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else [])


def eevee_engine() -> str:
    engines = {item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    return "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"


def clear_scene() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for blocks in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.actions):
        for block in list(blocks):
            blocks.remove(block)


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*color, 1.0)
    mat.diffuse_color = (*color, 1.0)
    return mat


def key_height(ball, frame, z):
    ball.location.z = z
    ball.keyframe_insert("location", index=2, frame=frame)


def key_squash(ball, frame, squash):
    """Volume-preserving squash: flatter in Z, wider in X/Y."""
    ball.scale = (1 / math.sqrt(squash), 1 / math.sqrt(squash), squash)
    ball.keyframe_insert("scale", frame=frame)


def main() -> None:
    opts = options()
    clear_scene()
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end, scene.render.fps = 1, 72, 24
    radius = 0.5

    bpy.ops.mesh.primitive_plane_add(size=30)
    bpy.context.object.data.materials.append(material("Grey", (0.35, 0.35, 0.36)))
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=48, ring_count=24, location=(0, 0, 4))
    ball = bpy.context.object
    ball.name = "Ball"
    ball.data.materials.append(material("Orange", (0.9, 0.35, 0.05)))
    for polygon in ball.data.polygons:
        polygon.use_smooth = True

    # Drop from 4 m, then three bounces of decreasing height.
    for frame, z in [(1, 4.0), (16, radius), (28, 2.2), (40, radius), (49, 1.1), (58, radius), (64, 1.0), (70, radius)]:
        key_height(ball, frame, z)
    # Round in the air, squashed only on the frames around each impact.
    key_squash(ball, 1, 1.0)
    for impact, squash in [(16, 0.72), (40, 0.8), (58, 0.88), (70, 0.95)]:
        key_squash(ball, impact - 1, 1.0)
        key_squash(ball, impact, squash)
        key_squash(ball, impact + 2, 1.0)
        key_height(ball, impact, radius * squash)  # keep the squashed ball on the ground

    bpy.ops.object.light_add(type="SUN", rotation=(math.radians(45), 0, math.radians(30)))
    bpy.context.object.data.energy = 3.0
    bpy.ops.object.camera_add(location=(0, -12, 2.2), rotation=(math.radians(88), 0, 0))
    scene.camera = bpy.context.object
    scene.render.engine = eevee_engine()
    scene.render.resolution_x, scene.render.resolution_y = 640, 360

    os.makedirs(os.path.dirname(opts.blend), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=opts.blend, copy=True)
    print(f"Saved {opts.blend}")
    if opts.render:
        for frame in opts.frames:
            scene.frame_set(frame)
            scene.render.filepath = os.path.join(opts.output_dir, f"script-03-frame-{frame:03d}.png")
            bpy.ops.render.render(write_still=True)
            print(f"Rendered {scene.render.filepath}")
    scene.frame_set(1)


main()
