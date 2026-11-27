"""Render labelled inspection views of an object or collection without touching the user's setup.

Views are rendered in a temporary scene with its own camera, lights, world and render
settings. The target objects are only linked into it, and everything created here is
removed again, also when a render fails.
"""

from __future__ import annotations

import base64
import contextlib
import math
import os
import shutil
import tempfile
from typing import TYPE_CHECKING

import bpy

from .protocol import BridgeError, MissingResourceError, UnsupportedError

if TYPE_CHECKING:
    from .paths import PathPolicy

MIN_RESOLUTION, MAX_RESOLUTION = 64, 1024
MAX_VIEWS = 6
MAX_MEMBERS = 5_000
MAX_LISTED_EXCLUSIONS = 20
MARGIN = 1.12
PERSPECTIVE_LENS = 70.0
SENSOR_WIDTH = 36.0
CYCLES_SAMPLES = 16

# View name -> (direction the camera looks, up hint). Blender's front view looks along +Y.
_Q = 1 / math.sqrt(1 + 1 + 0.7**2)
VIEWS: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
    "front": ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    "back": ((0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    "right": ((-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "left": ((1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    "top": ((0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    "bottom": ((0.0, 0.0, 1.0), (0.0, -1.0, 0.0)),
    "three_quarter": ((-_Q, _Q, -0.7 * _Q), (0.0, 0.0, 1.0)),
}
PROJECTIONS = ("orthographic", "perspective")
MODES = ("solid", "material", "wireframe")
RENDERABLE = frozenset(
    {"MESH", "CURVE", "SURFACE", "META", "FONT", "CURVES", "POINTCLOUD", "VOLUME", "GPENCIL", "GREASEPENCIL"}
)


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _normalize(a):
    length = math.sqrt(_dot(a, a))
    return tuple(x / length for x in a)


def _combine(*terms):
    return tuple(sum(weight * vector[i] for weight, vector in terms) for i in range(3))


def camera_axes(view: str) -> tuple[tuple, tuple, tuple]:
    """Return the camera's (right, up, forward) unit vectors for a named view."""
    forward, up_hint = VIEWS[view]
    right = _normalize(_cross(forward, up_hint))
    return right, _cross(right, forward), forward


def frame_points(points: list, view: str, projection: str) -> dict:
    """Place a square camera so that every point is inside the picture with a margin."""
    low = [min(point[i] for point in points) for i in range(3)]
    high = [max(point[i] for point in points) for i in range(3)]
    center = tuple((low[i] + high[i]) / 2 for i in range(3))
    radius = max(math.dist(point, center) for point in points) or 1.0
    right, up, forward = camera_axes(view)
    offsets = [tuple(point[i] - center[i] for i in range(3)) for point in points]
    if projection == "orthographic":
        half = max(max(abs(_dot(o, right)), abs(_dot(o, up))) for o in offsets) or radius
        distance = radius * 3
        framing = {"ortho_scale": 2 * half * MARGIN}
    else:
        tangent = SENSOR_WIDTH / (2 * PERSPECTIVE_LENS)
        distance = max(
            max(abs(_dot(o, right)), abs(_dot(o, up))) * MARGIN / tangent - _dot(o, forward) for o in offsets
        )
        # Keep the camera outside the bounds, also for flat or tiny subjects.
        distance = max(distance, radius * 1.5)
        framing = {"lens": PERSPECTIVE_LENS}
    location = tuple(center[i] - forward[i] * distance for i in range(3))
    depths = [distance + _dot(o, forward) for o in offsets]
    return {
        "location": location,
        "clip_start": max(min(depths) * 0.5, radius * 1e-3),
        "clip_end": max(depths) + radius * 4,
        **framing,
    }


def _matrix(x, y, z, location=(0.0, 0.0, 0.0)):
    import mathutils

    return mathutils.Matrix(
        (
            (x[0], y[0], z[0], location[0]),
            (x[1], y[1], z[1], location[1]),
            (x[2], y[2], z[2], location[2]),
            (0, 0, 0, 1),
        )
    )


def _light_matrix(direction):
    """Orient a sun, which shines along its -Z axis, in the given direction."""
    z = _normalize(tuple(-value for value in direction))
    helper = (0.0, 0.0, 1.0) if abs(z[2]) < 0.9 else (1.0, 0.0, 0.0)
    x = _normalize(_cross(helper, z))
    return _matrix(x, _cross(z, x), z)


def _walk(obj, seen):
    if obj.name in seen:
        return
    seen[obj.name] = obj
    for child in sorted(obj.children, key=lambda item: item.name):
        _walk(child, seen)


def _targets(params: dict) -> tuple[dict, list, list]:
    """Resolve the target to objects worth rendering and explain the ones left out."""
    object_name, collection_name = params.get("object"), params.get("collection")
    if bool(object_name) == bool(collection_name):
        raise ValueError("Provide exactly one of 'object' or 'collection'")
    if object_name:
        obj = bpy.data.objects.get(object_name)
        if obj is None:
            raise MissingResourceError("Object not found")
        found: dict = {}
        if params["include_children"]:
            _walk(obj, found)
        else:
            found[obj.name] = obj
        candidates = list(found.values())
        target = {"object": obj.name, "include_children": params["include_children"]}
    else:
        collection = bpy.data.collections.get(collection_name)
        if collection is None:
            raise MissingResourceError("Collection not found")
        candidates = sorted(collection.all_objects, key=lambda item: item.name)
        target = {"collection": collection.name}
    if len(candidates) > MAX_MEMBERS:
        raise BridgeError("budget_exceeded", f"The target has more than {MAX_MEMBERS} objects")

    members, excluded = [], []
    for item in candidates:
        instancer = item.type == "EMPTY" and item.instance_type == "COLLECTION"
        if not (item.type in RENDERABLE or instancer):
            reason = f"{item.type} objects have no renderable surface"
        elif item.hide_render:
            reason = "hidden from render"
        elif item.hide_viewport:
            reason = "disabled in viewports, so Blender cannot report its current bounds"
        elif params["mode"] == "wireframe" and item.type != "MESH":
            reason = "wireframe views support mesh objects only"
        else:
            members.append(item)
            continue
        excluded.append({"object": item.name, "reason": reason})
    if not members:
        detail = f": {excluded[0]['object']} is {excluded[0]['reason']}" if len(excluded) == 1 else ""
        raise UnsupportedError(f"The target has nothing that can be rendered{detail}")
    return target, members, excluded


def _world_points(view_layer) -> list:
    """Bounding box corners of every evaluated instance, including instanced geometry."""
    points: list[tuple] = []
    for instance in view_layer.depsgraph.object_instances:
        obj = instance.object
        if obj.type not in RENDERABLE:
            continue
        corners = [tuple(corner) for corner in obj.bound_box]
        if len(set(corners)) < 2:
            continue  # empty geometry
        matrix = [[float(instance.matrix_world[row][column]) for column in range(4)] for row in range(3)]
        points.extend(tuple(sum(row[i] * c[i] for i in range(3)) + row[3] for row in matrix) for c in corners)
    return [point for point in points if all(math.isfinite(value) for value in point)]


def _differs_in_render(obj) -> bool:
    for modifier in getattr(obj, "modifiers", ()):
        if modifier.show_viewport != modifier.show_render:
            return True
        levels = getattr(modifier, "levels", None)
        if levels is not None and getattr(modifier, "render_levels", levels) != levels:
            return True
    return False


def _notes(members: list, cleanup_failures: list[str]) -> list[str]:
    notes = []
    if differing := [member.name for member in members if _differs_in_render(member)]:
        notes.append(
            "Images use render modifier settings, but framing and mesh_inspect use viewport settings. They differ "
            f"on {len(differing)} object(s), such as {', '.join(differing[:3])}; geometry added only at render "
            "time can fall outside the frame."
        )
    if cleanup_failures:
        notes.append(f"Temporary data could not be removed ({', '.join(cleanup_failures)})")
    return notes


class _Temporary:
    """Remember every datablock created for a capture and remove them in reverse order."""

    def __init__(self):
        self.created: list[tuple[str, object]] = []

    def add(self, kind: str, block):
        self.created.append((kind, block))
        return block

    def remove(self):
        failures = []
        for kind, block in reversed(self.created):
            try:
                getattr(bpy.data, kind).remove(block)
            except (ReferenceError, RuntimeError) as exc:
                failures.append(f"{kind}: {type(exc).__name__}")
        self.created.clear()
        return failures


def _material(temp: _Temporary, name: str, color: tuple, *, emission: bool = False):
    material = temp.add("materials", bpy.data.materials.new(name))
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    shader = nodes.new("ShaderNodeEmission" if emission else "ShaderNodeBsdfDiffuse")
    shader.inputs["Color"].default_value = (*color, 1.0)
    material.node_tree.links.new(shader.outputs[0], output.inputs["Surface"])
    return material


def _add_wireframe_copies(temp: _Temporary, scene, members: list, thickness: float) -> None:
    """Show topology using private copies: a light surface with the evaluated edges drawn on top."""
    surface = _material(temp, "mcp-capture-surface", (0.55, 0.55, 0.55))
    wire = _material(temp, "mcp-capture-wire", (0.0, 0.0, 0.0), emission=True)
    for member in members:
        for suffix, material, color in (("surface", surface, 0.7), ("wire", wire, 0.0)):
            # The mesh is registered first so that it is removed after the object using it.
            data = temp.add("meshes", member.data.copy())
            copy = temp.add("objects", member.copy())
            copy.data = data
            copy.data.materials.clear()
            copy.data.materials.append(material)
            for polygon in copy.data.polygons:
                polygon.material_index = 0
            for slot in copy.material_slots:
                slot.link = "DATA"
            copy.color = (color, color, color, 1.0)
            if suffix == "wire":
                modifier = copy.modifiers.new("mcp-capture-wireframe", "WIREFRAME")
                largest = max(abs(value) for value in member.matrix_world.to_scale()) or 1.0
                modifier.thickness = thickness / largest
                modifier.use_replace = True
                modifier.use_even_offset = False
                modifier.use_boundary = True
            scene.collection.objects.link(copy)


def _engine(mode: str) -> str:
    """Background Blender may have no GPU, so it renders on the CPU with Cycles."""
    if bpy.app.background:
        return "CYCLES"
    return "EEVEE" if mode == "material" else "WORKBENCH"


def _configure(scene, view_layer, temp: _Temporary, engine: str, mode: str, resolution: int, rendering) -> None:
    rendering._set_render_engine(scene, engine)
    render = scene.render
    render.resolution_x = render.resolution_y = resolution
    render.resolution_percentage = 100
    render.image_settings.file_format = "PNG"
    render.image_settings.color_mode = "RGB"
    render.image_settings.color_depth = "8"
    render.image_settings.compression = 90
    render.film_transparent = False
    render.use_compositing = False
    render.use_sequencer = False
    render.use_file_extension = True
    with contextlib.suppress(TypeError):  # a custom color configuration without the Standard view
        scene.view_settings.view_transform = "Standard"
    world = temp.add("worlds", bpy.data.worlds.new("mcp-capture-world"))
    world.color = (0.18, 0.18, 0.18)
    world.use_nodes = True
    background = next(node for node in world.node_tree.nodes if node.type == "BACKGROUND")
    background.inputs["Color"].default_value = (0.18, 0.18, 0.18, 1.0)
    background.inputs["Strength"].default_value = 1.0
    scene.world = world
    if engine == "WORKBENCH":
        shading = scene.display.shading
        shading.light = "STUDIO"
        shading.show_cavity = False  # cavity outlines flat faces, which reads as a wireframe
        shading.color_type = "OBJECT" if mode == "wireframe" else "SINGLE"
        shading.single_color = (0.6, 0.6, 0.6)
    elif engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = CYCLES_SAMPLES
        scene.cycles.use_denoising = False
        scene.cycles.seed = 0
        if mode == "solid":
            view_layer.material_override = _material(temp, "mcp-capture-clay", (0.5, 0.5, 0.5))


def _add_lights(temp: _Temporary, scene) -> list:
    lights = []
    for name, energy in (("key", 2.5), ("fill", 1.0), ("rim", 1.5)):
        data = temp.add("lights", bpy.data.lights.new(f"mcp-capture-{name}", "SUN"))
        data.energy = energy
        light = temp.add("objects", bpy.data.objects.new(f"mcp-capture-{name}", data))
        scene.collection.objects.link(light)
        lights.append(light)
    return lights


def _aim_lights(lights: list, view: str) -> None:
    """Light each view the same way relative to its camera."""
    right, up, forward = camera_axes(view)
    directions = (
        _combine((1, forward), (-0.8, up), (0.6, right)),
        _combine((1, forward), (-0.1, up), (-0.9, right)),
        _combine((-0.6, forward), (-0.8, up), (0.2, right)),
    )
    for light, direction in zip(lights, directions, strict=True):
        light.matrix_world = _light_matrix(direction)


def _rounded(values) -> list:
    return [round(value, 6) for value in values]


def _validate(params: dict, policy: PathPolicy) -> list[str]:
    views: list = params["views"]
    if not 1 <= len(views) <= MAX_VIEWS or not all(isinstance(view, str) and view in VIEWS for view in views):
        raise ValueError(f"'views' must list 1-{MAX_VIEWS} of: {', '.join(VIEWS)}")
    if len(set(views)) != len(views):
        raise ValueError("'views' must not repeat")
    if params["projection"] not in PROJECTIONS:
        raise ValueError(f"'projection' must be one of: {', '.join(PROJECTIONS)}")
    if params["mode"] not in MODES:
        raise ValueError(f"'mode' must be one of: {', '.join(MODES)}")
    limits = policy.settings.policy
    if params["resolution"] ** 2 > limits.max_render_pixels or len(views) > limits.max_render_frames:
        raise ValueError("Capture exceeds the configured render limits")
    return views


def capture(params: dict, *, policy: PathPolicy) -> dict:
    from . import rendering

    views = _validate(params, policy)
    target, members, excluded = _targets(params)
    saved_paths = {}
    if directory := params.get("save_directory"):
        # Fixed file names: nothing from the scene reaches the filesystem path.
        saved_paths = {
            view: policy.prepare_output_path(os.path.join(directory, f"capture_{view}.png")) for view in views
        }
    include_images = params["include_images"]
    renders = include_images or bool(saved_paths)
    resolution, mode, projection = params["resolution"], params["mode"], params["projection"]
    source = bpy.context.scene
    engine = _engine(mode)

    temp = _Temporary()
    results: list[dict] = []
    try:
        scene = temp.add("scenes", bpy.data.scenes.new("mcp-capture"))
        scene.frame_current = source.frame_current
        for member in members:
            scene.collection.objects.link(member)
        view_layer = scene.view_layers[0]
        view_layer.update()
        points = _world_points(view_layer)
        if not points:
            raise UnsupportedError("The target has no geometry to frame")
        low = [min(point[i] for point in points) for i in range(3)]
        high = [max(point[i] for point in points) for i in range(3)]

        if renders:
            if mode == "wireframe":
                thickness = (math.dist(low, high) or 1.0) * 0.0018
                _add_wireframe_copies(temp, scene, members, thickness)
                for member in members:
                    scene.collection.objects.unlink(member)
            _configure(scene, view_layer, temp, engine, mode, resolution, rendering)
            lights = _add_lights(temp, scene) if engine != "WORKBENCH" else []
            camera_data = temp.add("cameras", bpy.data.cameras.new("mcp-capture-camera"))
            camera = temp.add("objects", bpy.data.objects.new("mcp-capture-camera", camera_data))
            scene.collection.objects.link(camera)
            scene.camera = camera

        directory_path = tempfile.mkdtemp(prefix="blender-mcp-capture-")
        try:
            total = 0
            for view in views:
                framing = frame_points(points, view, projection)
                right, up, forward = camera_axes(view)
                entry = {
                    "view": view,
                    "direction": _rounded(forward),
                    "up": _rounded(up),
                    "camera_location": _rounded(framing["location"]),
                    **{key: round(framing[key], 6) for key in ("ortho_scale", "lens") if key in framing},
                }
                if renders:
                    camera_data.type = "ORTHO" if projection == "orthographic" else "PERSP"
                    camera_data.sensor_width = SENSOR_WIDTH
                    for key in ("ortho_scale", "lens", "clip_start", "clip_end"):
                        if key in framing:
                            setattr(camera_data, key, framing[key])
                    camera.matrix_world = _matrix(right, up, tuple(-v for v in forward), framing["location"])
                    if lights:
                        _aim_lights(lights, view)
                    filepath = os.path.join(directory_path, f"{view}.png")
                    scene.render.filepath = filepath
                    if "CANCELLED" in bpy.ops.render.render(write_still=True, scene=scene.name):
                        raise BridgeError("command_failed", "Blender cancelled the capture render")
                    if not os.path.isfile(filepath):
                        raise BridgeError("command_failed", "Blender did not write the capture image")
                    size = os.path.getsize(filepath)
                    entry["bytes"] = size
                    if include_images:
                        total += size
                        if total > params["max_bytes"]:
                            raise BridgeError(
                                "budget_exceeded",
                                f"Images exceed max_bytes={params['max_bytes']}; lower the resolution or "
                                "request fewer views",
                                details={"bytes_so_far": total, "views_rendered": len(results) + 1},
                            )
                        with open(filepath, "rb") as handle:
                            entry["png_base64"] = base64.b64encode(handle.read()).decode("ascii")
                    if view in saved_paths:
                        shutil.copyfile(filepath, saved_paths[view])
                        entry["path"] = saved_paths[view]
                results.append(entry)
        finally:
            shutil.rmtree(directory_path, ignore_errors=True)
    finally:
        cleanup_failures = temp.remove()

    return {
        "target": target,
        "mode": mode,
        "projection": projection,
        "engine": engine if renders else None,
        "resolution": [resolution, resolution],
        "frame": source.frame_current,
        "bounds_world": {
            "min": _rounded(low),
            "max": _rounded(high),
            "size": _rounded(high[i] - low[i] for i in range(3)),
        },
        "objects_shown": len(members),
        "excluded": {
            "count": len(excluded),
            "items": excluded[:MAX_LISTED_EXCLUSIONS],
            "truncated": len(excluded) > MAX_LISTED_EXCLUSIONS,
        },
        "views": results,
        "notes": _notes(members, cleanup_failures),
    }
