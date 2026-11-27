"""Blender lighting commands and their local helpers.

Every request is validated against the light's final type before anything changes, so a
rejected create leaves no datablocks behind and a rejected update leaves the light as it was.
"""

import math

import bpy

from .objects import get_object_of_type
from .paging import paginate
from .placement import apply_placement

LIGHT_TYPES = ("POINT", "SUN", "SPOT", "AREA")
AREA_SHAPES = ("SQUARE", "RECTANGLE", "DISK", "ELLIPSE")
TWO_SIZED_SHAPES = ("RECTANGLE", "ELLIPSE")
SHARED_DATA_MODES = ("error", "update_all", "make_single_user")
# Settings stored on the light datablock, which every object using it shares.
DATA_SETTINGS = (
    "type",
    "energy",
    "color",
    "temperature",
    "size",
    "size_y",
    "shape",
    "angle",
    "spot_angle",
    "spot_blend",
)
# The Planckian locus approximation below is valid in this range.
MIN_KELVIN, MAX_KELVIN = 1667.0, 25000.0


def temperature_to_color(kelvin: float) -> list[float]:
    """Linear sRGB color of a black body, scaled so that its strongest channel is 1.

    Uses the Kim et al. cubic approximation of the Planckian locus. The result changes
    only the color; set energy separately.
    """
    if not MIN_KELVIN <= kelvin <= MAX_KELVIN:
        raise ValueError(f"'temperature' must be between {MIN_KELVIN:g} and {MAX_KELVIN:g} kelvin")
    t = kelvin
    if t <= 4000:
        x = -0.2661239e9 / t**3 - 0.2343589e6 / t**2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t**3 + 2.1070379e6 / t**2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x**3 - 1.34811020 * x**2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x**3 - 1.37418593 * x**2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x**3 - 5.87338670 * x**2 + 3.75112997 * x - 0.37001483
    big_x, big_z = x / y, (1 - x - y) / y
    rgb = [
        3.2406 * big_x - 1.5372 - 0.4986 * big_z,
        -0.9689 * big_x + 1.8758 + 0.0415 * big_z,
        0.0557 * big_x - 0.2040 + 1.0570 * big_z,
    ]
    rgb = [max(channel, 0.0) for channel in rgb]
    peak = max(rgb)
    return [round(channel / peak, 6) for channel in rgb]


def _light_type(value: str) -> str:
    light_type = value.strip().upper()
    if light_type not in LIGHT_TYPES:
        raise ValueError(f"Unsupported light type '{value}': use {', '.join(LIGHT_TYPES)}")
    return light_type


def validate(light_type: str, params: dict, current_location, current_shape: str | None) -> None:
    """Reject a request that does not apply to `light_type`, without touching Blender data."""
    color = params.get("color")
    if color is not None and any(component < 0 or component > 1 for component in color):
        raise ValueError("Light 'color' components must be between 0 and 1")
    if params.get("temperature") is not None:
        if color is not None:
            raise ValueError("Provide either 'color' or 'temperature', not both")
        temperature_to_color(params["temperature"])
    if params.get("size") is not None and light_type == "SUN":
        raise ValueError("'size' does not apply to SUN lights; use 'angle'")
    shape = params.get("shape")
    if shape is not None:
        if light_type != "AREA":
            raise ValueError(f"'shape' applies to AREA lights, not {light_type}")
        if shape.upper() not in AREA_SHAPES:
            raise ValueError(f"Unsupported area shape '{shape}': use {', '.join(AREA_SHAPES)}")
    if params.get("size_y") is not None:
        if light_type != "AREA":
            raise ValueError(f"'size_y' applies to AREA lights, not {light_type}")
        if shape is not None and shape.upper() not in TWO_SIZED_SHAPES:
            raise ValueError(f"'size_y' needs a {' or '.join(TWO_SIZED_SHAPES)} shape, not {shape.upper()}")
        if shape is None and current_shape == "DISK":
            raise ValueError("'size_y' needs a RECTANGLE or ELLIPSE shape; pass 'shape' to change the disk")
    if params.get("angle") is not None:
        if light_type != "SUN":
            raise ValueError(f"'angle' applies to SUN lights, not {light_type}")
        if params["angle"] > 180:
            raise ValueError("'angle' must be at most 180 degrees")
    if params.get("spot_angle") is not None:
        if light_type != "SPOT":
            raise ValueError(f"'spot_angle' applies to SPOT lights, not {light_type}")
        if not 1 <= params["spot_angle"] <= 180:
            raise ValueError("'spot_angle' must be between 1 and 180 degrees")
    if params.get("spot_blend") is not None:
        if light_type != "SPOT":
            raise ValueError(f"'spot_blend' applies to SPOT lights, not {light_type}")
        if not 0 <= params["spot_blend"] <= 1:
            raise ValueError("'spot_blend' must be between 0 and 1")
    if params.get("look_at") is not None:
        if params.get("rotation") is not None:
            raise ValueError("Provide either 'rotation' or 'look_at', not both")
        location = params.get("location", current_location)
        if all(abs(float(a) - float(b)) < 1e-9 for a, b in zip(location, params["look_at"], strict=True)):
            raise ValueError("'look_at' target must differ from the object location")


def create(params: dict) -> dict:
    light_type = _light_type(params.get("type", "POINT"))
    validate(light_type, params, (0.0, 0.0, 0.0), None)
    name = params.get("name") or f"{light_type.capitalize()}Light"
    light_data = bpy.data.lights.new(name, type=light_type)
    obj = None
    try:
        obj = bpy.data.objects.new(name, light_data)
        bpy.context.scene.collection.objects.link(obj)
        apply_light_settings(light_data, obj, params)
    except Exception:
        if obj is not None:
            bpy.data.objects.remove(obj)
        bpy.data.lights.remove(light_data)
        raise
    return result(light_data, obj)


def _users(light_data) -> list[str]:
    return sorted(obj.name for obj in bpy.data.objects if obj.type == "LIGHT" and obj.data == light_data)


def update(params: dict) -> dict:
    obj = get_object_of_type(params["name"], "LIGHT")
    light_data = obj.data
    if light_data is None:
        raise ValueError(f"Object '{params['name']}' has no light data")
    new_type = _light_type(params["type"]) if params.get("type") is not None else None
    current_shape = light_data.shape if light_data.type == "AREA" else None
    validate(new_type or light_data.type, params, obj.location, current_shape)
    users = _users(light_data)
    mode = params.get("shared_data", "error")
    if mode not in SHARED_DATA_MODES:
        raise ValueError(f"'shared_data' must be one of: {', '.join(SHARED_DATA_MODES)}")
    if len(users) > 1 and any(params.get(key) is not None for key in DATA_SETTINGS):
        if mode == "error":
            raise ValueError(
                f"Light data is shared by {len(users)} objects ({', '.join(users[:5])}). Pass "
                "shared_data='update_all' to change them all, or 'make_single_user' to change only this one"
            )
        if mode == "make_single_user":
            obj.data = light_data = light_data.copy()
    if new_type is not None:
        light_data.type = new_type
        light_data = obj.data  # Blender changes the datablock's class with its type
    apply_light_settings(light_data, obj, params)
    return result(light_data, obj)


def settings(light_data) -> dict:
    """The effective type-specific settings, in the units the commands accept."""
    values: dict = {}
    if light_data.type in {"POINT", "SPOT"}:
        values["size"] = round(light_data.shadow_soft_size, 6)
    if light_data.type == "SUN":
        values["angle"] = round(math.degrees(light_data.angle), 4)
    if light_data.type == "SPOT":
        values["spot_angle"] = round(math.degrees(light_data.spot_size), 4)
        values["spot_blend"] = round(light_data.spot_blend, 6)
    if light_data.type == "AREA":
        values["shape"] = light_data.shape
        values["size"] = round(light_data.size, 6)
        if light_data.shape in TWO_SIZED_SHAPES:
            values["size_y"] = round(light_data.size_y, 6)
    # Blender 4.5+ can multiply the color by a color temperature.
    if getattr(light_data, "use_temperature", False) is True:
        values["blender_temperature"] = round(light_data.temperature, 2)
    return values


def result(light_data, obj) -> dict:
    return {
        "name": obj.name,
        "type": obj.type,
        "light_type": light_data.type,
        "location": list(obj.location),
        "energy": light_data.energy,
        "color": list(light_data.color),
        **_safe_settings(light_data),
    }


def _safe_settings(light_data) -> dict:
    try:
        return settings(light_data)
    except TypeError:  # incomplete data stand-ins; real light data always has numeric settings
        return {}


def apply_light_settings(light_data, obj, params: dict) -> None:
    """Apply settings that `validate` has accepted for this light's type."""
    light_type = light_data.type
    if (energy := params.get("energy")) is not None:
        light_data.energy = energy
    color = params.get("color")
    if (kelvin := params.get("temperature")) is not None:
        color = temperature_to_color(kelvin)
        if getattr(light_data, "use_temperature", False) is True:
            light_data.use_temperature = False  # otherwise Blender would apply a second temperature
    if color is not None:
        light_data.color = color[:3]
    if (shape := params.get("shape")) is not None:
        light_data.shape = shape.upper()
    if (size := params.get("size")) is not None:
        if light_type in {"POINT", "SPOT"}:
            light_data.shadow_soft_size = size
        else:  # AREA
            light_data.size = size
    if (size_y := params.get("size_y")) is not None:
        if params.get("shape") is None and light_data.shape != "ELLIPSE":
            light_data.shape = "RECTANGLE"
        light_data.size_y = size_y
    if (angle := params.get("angle")) is not None:
        light_data.angle = math.radians(angle)
    if (spot_angle := params.get("spot_angle")) is not None:
        light_data.spot_size = math.radians(spot_angle)
    if (spot_blend := params.get("spot_blend")) is not None:
        light_data.spot_blend = spot_blend
    apply_placement(obj, params)


def describe(obj) -> dict:
    """A read-only description of one light object, with its world transform."""
    light_data = obj.data
    matrix = obj.matrix_world
    rows = [[float(matrix[row][column]) for column in range(4)] for row in range(3)]
    forward = [-rows[row][2] for row in range(3)]  # lights shine along their local -Z axis
    length = math.sqrt(sum(value * value for value in forward)) or 1.0
    entry = {
        "name": obj.name,
        "light_type": light_data.type,
        "world_location": [round(rows[row][3], 6) for row in range(3)],
        "energy": round(light_data.energy, 6),
        "energy_unit": "W/m²" if light_data.type == "SUN" else "W",
        "color": [round(channel, 6) for channel in light_data.color],
        **settings(light_data),
        "use_shadow": bool(light_data.use_shadow),
        "hide_viewport": bool(obj.hide_viewport),
        "hide_render": bool(obj.hide_render),
        "data": light_data.name,
    }
    if light_data.type != "POINT":
        entry["world_direction"] = [round(value / length, 6) for value in forward]
    if (exposure := getattr(light_data, "exposure", 0.0)) != 0.0:
        entry["light_exposure"] = round(exposure, 4)
    if len(users := _users(light_data)) > 1:
        entry["data_shared_by"] = {"count": len(users), "objects": users[:10]}
    return entry


def scene_lights(params: dict) -> tuple[list[dict], dict]:
    lights = sorted((obj for obj in bpy.context.scene.objects if obj.type == "LIGHT"), key=lambda item: item.name)
    page, metadata = paginate(lights, params)
    entries = [describe(obj) for obj in page]
    return entries, {"total": len(lights), **metadata}
