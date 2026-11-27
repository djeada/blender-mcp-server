"""Scale-aware lighting rigs and camera framing around a target's evaluated bounds.

Every rig distance and source size is a multiple of the subject's radius R, and each area
light's power is proportional to its distance squared. A subject and rig scaled together
are geometrically similar, so the subject receives the same irradiance at any size.

Rigs only create and remove their own tagged objects, in their own collection.
"""

from __future__ import annotations

import math
from typing import Any

import bpy

from . import capture, lighting
from .placement import look_at_rotation
from .protocol import BridgeError, MissingResourceError, UnsupportedError

# Irradiance from the key light at the subject, in W/m². An 18% grey surface facing the key
# then has a radiance of about 0.18.
KEY_IRRADIANCE = 3.0
MIN_RADIUS = 1e-6
ON_EXISTING = ("error", "replace")
RIG_TAG, ROLE_TAG = "mcp_rig", "mcp_rig_role"
CAMERA_COLLECTION = "MCP Cameras"
SENSOR_WIDTH = 36.0

# role: (azimuth from the camera toward its right, elevation, distance/R, size/R, strength relative to key, kelvin)
RIGS: dict[str, dict[str, tuple[float, float, float, float, float, float]]] = {
    "three_point": {
        "key": (35, 35, 4.0, 1.5, 1.0, 5600),
        "fill": (-45, 10, 4.0, 2.5, 0.35, 6500),
        "rim": (160, 35, 4.0, 1.0, 0.8, 6500),
    },
    "studio_softbox": {
        "key": (45, 25, 3.5, 3.0, 1.0, 5600),
        "fill": (-60, 15, 3.5, 3.0, 0.6, 5600),
        "top": (0, 80, 3.5, 3.0, 0.5, 5600),
    },
    "turntable": {
        "front_right": (45, 30, 4.0, 2.5, 0.6, 6500),
        "front_left": (-45, 30, 4.0, 2.5, 0.6, 6500),
        "back_right": (135, 30, 4.0, 2.5, 0.6, 6500),
        "back_left": (-135, 30, 4.0, 2.5, 0.6, 6500),
    },
    "portrait": {
        "key": (40, 30, 4.0, 1.5, 1.0, 5200),
        "fill": (-30, 5, 4.0, 3.0, 0.3, 6000),
        "rim": (-140, 40, 4.0, 1.0, 0.6, 7000),
    },
    "low_key": {
        "key": (75, 30, 4.0, 0.8, 1.0, 4500),
        "fill": (-50, 10, 4.5, 2.0, 0.05, 7500),
        "rim": (-150, 30, 4.0, 0.6, 0.9, 7500),
    },
}


# --- bounds -----------------------------------------------------------------------------


def target_bounds(params: dict) -> tuple[dict, list]:
    """Corner points of the target's evaluated geometry, measured in a temporary scene."""
    target, members, _ = capture._targets(
        {
            "object": params.get("object"),
            "collection": params.get("collection"),
            "include_children": params.get("include_children", True),
            "mode": "solid",
        }
    )
    scene = bpy.data.scenes.new("mcp-bounds")
    try:
        scene.frame_current = bpy.context.scene.frame_current
        for member in members:
            scene.collection.objects.link(member)
        view_layer = scene.view_layers[0]
        view_layer.update()
        points = capture._world_points(view_layer)
    finally:
        bpy.data.scenes.remove(scene)
    if not points:
        raise UnsupportedError("The target has no geometry to measure")
    return target, points


def extent(points: list) -> tuple[tuple, float, list, list]:
    low = [min(point[i] for point in points) for i in range(3)]
    high = [max(point[i] for point in points) for i in range(3)]
    center = tuple((low[i] + high[i]) / 2 for i in range(3))
    radius = math.dist(low, high) / 2
    if not radius > MIN_RADIUS:
        raise UnsupportedError("The target has no size (all of its geometry is at one point), so nothing can be fitted")
    return center, radius, low, high


# --- rig layout (pure geometry) ---------------------------------------------------------


def plan(rig: str, center: tuple, radius: float, camera_azimuth: float, options: dict) -> list[dict]:
    """Where each light goes and how strong it is. `camera_azimuth` points from the subject to the camera."""
    ratios = options.get("ratios") or {}
    temperatures = options.get("temperatures") or {}
    colors = options.get("colors") or {}
    intensity = 2.0 ** options.get("exposure_stops", 0.0)
    lights = []
    for role, (azimuth, elevation, distance, size, ratio, kelvin) in RIGS[rig].items():
        angle = math.radians(camera_azimuth + azimuth + options.get("rotation", 0.0))
        lift = math.radians(elevation)
        reach = distance * radius * options.get("distance_scale", 1.0)
        direction = (math.cos(lift) * math.cos(angle), math.cos(lift) * math.sin(angle), math.sin(lift))
        strength = ratios.get(role, ratio)
        irradiance = KEY_IRRADIANCE * intensity * strength
        color = colors.get(role) or lighting.temperature_to_color(temperatures.get(role, kelvin))
        lights.append(
            {
                "role": role,
                "location": [center[i] + direction[i] * reach for i in range(3)],
                # A one-sided area light of power P gives about P / (pi d^2) on its axis.
                "energy": irradiance * math.pi * reach**2,
                "size": size * radius * options.get("size_scale", 1.0),
                "ratio": strength,
                "color": [float(channel) for channel in color[:3]],
                "distance": reach,
            }
        )
    return lights


def _validate(params: dict) -> dict:
    rig = params["rig"]
    if rig not in RIGS:
        raise ValueError(f"'rig' must be one of: {', '.join(RIGS)}")
    roles = RIGS[rig]
    options: dict[str, Any] = {
        key: params[key] for key in ("rotation", "exposure_stops", "distance_scale", "size_scale") if key in params
    }
    for key in ("ratios", "temperatures", "colors"):
        values = params.get(key) or {}
        if unknown := sorted(set(values) - set(roles)):
            raise ValueError(f"'{key}' has unknown roles {', '.join(unknown)}; {rig} has: {', '.join(roles)}")
        options[key] = values
    for role, value in options["ratios"].items():
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 20:
            raise ValueError(f"Ratio for '{role}' must be a number from 0 to 20, relative to the key light")
    if options["ratios"] and all(options["ratios"].get(role, spec[4]) == 0 for role, spec in roles.items()):
        raise ValueError("At least one light needs a ratio above 0")
    for role, value in options["temperatures"].items():
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError(f"Temperature for '{role}' must be a number of kelvin")
        lighting.temperature_to_color(value)
    for role, value in options["colors"].items():
        if role in options["temperatures"]:
            raise ValueError(f"Give '{role}' a color or a temperature, not both")
        if not (
            isinstance(value, list)
            and len(value) == 3
            and all(type(item) in (int, float) and 0 <= item <= 1 for item in value)
        ):
            raise ValueError(f"Color for '{role}' must be three values from 0 to 1")
    return options


def _camera_azimuth(params: dict, center: tuple) -> tuple[float, str | None]:
    """The compass angle from the subject to the camera the rig should be arranged around."""
    name = params.get("camera")
    camera = bpy.data.objects.get(name) if name else bpy.context.scene.camera
    if name and (camera is None or camera.type != "CAMERA"):
        raise MissingResourceError(f"Camera '{name}' not found")
    if camera is not None:
        offset_x = float(camera.matrix_world[0][3]) - center[0]
        offset_y = float(camera.matrix_world[1][3]) - center[1]
        if math.hypot(offset_x, offset_y) > 1e-6:
            return math.degrees(math.atan2(offset_y, offset_x)), camera.name
    return -90.0, None  # Blender's front view looks from -Y


def _rig_objects(name: str) -> list:
    return sorted((obj for obj in bpy.data.objects if obj.get(RIG_TAG) == name), key=lambda item: item.name)


def _remove_objects(objects: list) -> list[str]:
    removed = []
    for obj in objects:
        removed.append(obj.name)
        data, kind = obj.data, obj.type
        bpy.data.objects.remove(obj)
        if kind == "LIGHT" and data is not None and data.users == 0:
            bpy.data.lights.remove(data)
    return removed


def _collection(name: str):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
    if bpy.context.scene.collection.children.get(collection.name) is None:
        bpy.context.scene.collection.children.link(collection)
    return collection


def apply_rig(params: dict) -> dict:
    options = _validate(params)
    on_existing = params.get("on_existing", "error")
    if on_existing not in ON_EXISTING:
        raise ValueError(f"'on_existing' must be one of: {', '.join(ON_EXISTING)}")
    name = (params.get("name") or params["rig"]).strip()
    if not name or len(name.encode()) > 40 or not name.isprintable():
        raise ValueError("'name' must be 1-40 printable bytes")
    previous = _rig_objects(name)
    if previous and on_existing == "error":
        raise BridgeError(
            "conflict",
            f"Rig '{name}' already exists with {len(previous)} lights. Pass on_existing='replace' to rebuild it, "
            "or another name to add a second rig",
        )
    target, points = target_bounds(params)
    center, radius, low, high = extent(points)
    azimuth, camera_name = _camera_azimuth(params, center)
    planned = plan(params["rig"], center, radius, azimuth, options)

    created: list = []
    collection = _collection(f"MCP Rig {name}")
    try:
        for spec in planned:
            if spec["ratio"] == 0:
                continue
            label = f"{name} {spec['role']}"
            data = bpy.data.lights.new(label, type="AREA")
            obj = None
            try:
                obj = bpy.data.objects.new(label, data)
                collection.objects.link(obj)
            except Exception:
                if obj is not None:
                    bpy.data.objects.remove(obj)
                bpy.data.lights.remove(data)
                raise
            created.append(obj)
            obj[ROLE_TAG] = spec["role"]
            data.shape = "DISK"
            data.size = spec["size"]
            data.energy = spec["energy"]
            data.color = spec["color"]
            obj.location = spec["location"]
            obj.rotation_euler = look_at_rotation(spec["location"], center)
    except Exception:
        _remove_objects(created)
        raise
    # The old rig is removed only after the new one is complete.
    replaced = _remove_objects(previous)
    lights = []
    for obj, spec in zip(created, [spec for spec in planned if spec["ratio"] != 0], strict=True):
        obj[RIG_TAG] = name
        # While the old rig existed, Blender gave the new objects suffixed names.
        obj.name = obj.data.name = f"{name} {spec['role']}"
        lights.append(
            {
                "role": spec["role"],
                "name": obj.name,
                "energy": round(spec["energy"], 6),
                "size": round(spec["size"], 6),
                "distance": round(spec["distance"], 6),
                "strength_ratio": spec["ratio"],
                "color": [round(value, 4) for value in spec["color"]],
                "location": [round(value, 6) for value in spec["location"]],
            }
        )
    notes = []
    others = [
        obj.name
        for obj in bpy.context.scene.objects
        if obj.type == "LIGHT" and not obj.hide_render and obj not in created
    ]
    if others:
        notes.append(f"{len(others)} other light(s) also affect the subject, such as {', '.join(sorted(others)[:3])}")
    notes.append("The world also lights the subject; check it with blender_lighting_inspect")
    return {
        "rig": params["rig"],
        "name": name,
        "collection": collection.name,
        "target": target,
        "subject_center": [round(value, 6) for value in center],
        "subject_radius": round(radius, 6),
        "bounds_world": {"min": [round(v, 6) for v in low], "max": [round(v, 6) for v in high]},
        "camera": camera_name,
        "camera_azimuth_degrees": round(azimuth, 4),
        "lights": lights,
        "replaced": replaced,
        "notes": notes,
    }


def remove_rig(params: dict) -> dict:
    name = params["name"].strip()
    found = _rig_objects(name)
    if not found:
        raise MissingResourceError(f"No rig named '{name[:40]}'")
    removed = _remove_objects(found)
    collection = bpy.data.collections.get(f"MCP Rig {name}")
    kept: list[str] = []
    if collection is not None:
        # Anything the user moved into the rig's collection stays, and so does the collection.
        kept = sorted(obj.name for obj in collection.objects)
        if not kept and not len(collection.children):
            bpy.data.collections.remove(collection)
    return {"name": name, "removed": removed, "kept_in_collection": kept}


# --- camera framing ---------------------------------------------------------------------


def view_direction(params: dict) -> tuple[float, float, float]:
    """Unit vector from the subject toward the camera."""
    azimuth, elevation = math.radians(params.get("azimuth", 0.0) - 90.0), math.radians(params.get("elevation", 10.0))
    return (
        math.cos(elevation) * math.cos(azimuth),
        math.cos(elevation) * math.sin(azimuth),
        math.sin(elevation),
    )


def fit_camera(points: list, toward_camera: tuple, projection: str, lens: float, aspect: float, margin: float) -> dict:
    """Place a camera so every point is inside the frame of the given width/height aspect, with a margin."""
    center, radius, _, _ = extent(points)
    forward = tuple(-value for value in toward_camera)
    up_hint = (0.0, 0.0, 1.0) if abs(forward[2]) < 0.999 else (0.0, 1.0, 0.0)
    right = capture._normalize(capture._cross(forward, up_hint))
    up = capture._cross(right, forward)
    offsets = [tuple(point[i] - center[i] for i in range(3)) for point in points]
    xs = [abs(capture._dot(offset, right)) * margin for offset in offsets]
    ys = [abs(capture._dot(offset, up)) * margin for offset in offsets]
    depths = [capture._dot(offset, forward) for offset in offsets]
    if projection == "ORTHO":
        # Blender applies ortho_scale and the sensor to the longer side of the frame.
        if aspect >= 1:
            scale = 2 * max(max(xs), max(ys) * aspect)
        else:
            scale = 2 * max(max(ys), max(xs) / aspect)
        distance = radius * 3
        framing: dict = {"ortho_scale": scale}
    else:
        longer = SENSOR_WIDTH / 2 / lens
        tan_x, tan_y = (longer, longer / aspect) if aspect >= 1 else (longer * aspect, longer)
        distance = max(max(x / tan_x - d, y / tan_y - d) for x, y, d in zip(xs, ys, depths, strict=True))
        distance = max(distance, radius * 1.1)
        framing = {"lens": lens}
    location = tuple(center[i] - forward[i] * distance for i in range(3))
    along = [distance + depth for depth in depths]
    return {
        "location": location,
        "target": center,
        "clip_start": max(min(along) * 0.5, radius * 1e-3),
        "clip_end": max(along) + radius * 10,
        **framing,
    }


def frame_camera(params: dict) -> dict:
    projection = params.get("projection", "PERSP").upper()
    if projection not in {"PERSP", "ORTHO"}:
        raise ValueError("'projection' must be PERSP or ORTHO")
    scene = bpy.context.scene
    name = params["camera"]
    camera = bpy.data.objects.get(name)
    if camera is not None and camera.type != "CAMERA":
        raise UnsupportedError(f"'{name}' is a {camera.type}, not a camera")
    if camera is not None:
        if camera.parent is not None or len(camera.constraints):
            raise UnsupportedError("A parented or constrained camera cannot be placed exactly; frame another camera")
        if camera.data.users > 1:
            raise UnsupportedError("The camera's data is shared with other objects; frame another camera")
    render = scene.render
    scene_aspect = (render.resolution_x * render.pixel_aspect_x) / (render.resolution_y * render.pixel_aspect_y)
    aspect = params.get("aspect") or scene_aspect
    target, points = target_bounds(params)
    toward = view_direction(params)
    framing = fit_camera(points, toward, projection, params.get("lens", 70.0), aspect, params.get("margin", 1.15))

    created = camera is None
    if created:
        data = bpy.data.cameras.new(name)
        camera = bpy.data.objects.new(name, data)
        _collection(CAMERA_COLLECTION).objects.link(camera)
    data = camera.data
    data.type = projection
    data.sensor_fit = "AUTO"
    data.sensor_width = SENSOR_WIDTH
    data.shift_x = data.shift_y = 0.0
    for key in ("lens", "ortho_scale", "clip_start", "clip_end"):
        if key in framing:
            setattr(data, key, framing[key])
    camera.location = framing["location"]
    camera.rotation_euler = look_at_rotation(framing["location"], framing["target"])
    if params.get("set_active"):
        scene.camera = camera
    result = {
        "camera": camera.name,
        "created": created,
        "active": scene.camera == camera,
        "target": target,
        "projection": projection,
        "aspect": round(aspect, 6),
        "margin": params.get("margin", 1.15),
        "location": [round(value, 6) for value in framing["location"]],
        "looking_at": [round(value, 6) for value in framing["target"]],
        **{key: round(framing[key], 6) for key in ("lens", "ortho_scale", "clip_start", "clip_end") if key in framing},
    }
    if abs(aspect - scene_aspect) > 1e-3:
        result["notes"] = [
            f"Framed for aspect {aspect:.4g}, but the render resolution is {scene_aspect:.4g}. Render settings were "
            "not changed; set a matching resolution when rendering."
        ]
    return result
