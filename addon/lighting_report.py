"""A bounded, read-only report of everything that lights the active scene."""

import bpy

from . import color_management, lighting, world


def _camera(scene) -> dict | None:
    camera = scene.camera
    if camera is None:
        return None
    matrix = camera.matrix_world
    info = {
        "name": camera.name,
        "world_location": [round(float(matrix[row][3]), 6) for row in range(3)],
        "world_direction": [round(-float(matrix[row][2]), 6) for row in range(3)],
    }
    if camera.type == "CAMERA":
        info["projection"] = camera.data.type
        key = "ortho_scale" if camera.data.type == "ORTHO" else "lens"
        info[key] = round(getattr(camera.data, key), 4)
    return info


def _render(scene) -> dict:
    render = scene.render
    info = {
        "engine": render.engine,
        "resolution": [render.resolution_x, render.resolution_y],
        "resolution_percentage": render.resolution_percentage,
        "film_transparent": bool(render.film_transparent),
    }
    if render.engine == "CYCLES":
        info["samples"] = scene.cycles.samples
    elif "EEVEE" in render.engine:
        info["samples"] = getattr(scene.eevee, "taa_render_samples", None)
    return info


def inspect(params: dict) -> dict:
    scene = bpy.context.scene
    lights, metadata = lighting.scene_lights(params)
    report = {
        "scene": scene.name,
        "lights": lights,
        **metadata,
        "camera": _camera(scene),
        "world": world.summary(scene.world),
        "render": _render(scene),
        "color_management": color_management.current(scene),
    }
    if params.get("include_options"):
        report["color_management_options"] = color_management.options(scene)
    return report
