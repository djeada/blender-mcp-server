"""Create a Principled material with emission, for use with blender_python_exec.

Args:
    name (str): Material name. Default: Glow
    color (list[float]): Optional base color [r, g, b] or [r, g, b, a].
    emission_color (list[float]): Emission RGB or RGBA. Default: [1, 1, 1]
    emission_strength (float): Positive emission strength. Default: 5.0

Result:
    name, emission_color (RGBA), and emission_strength of the new material.
"""

import math

import bpy


def rgba(color):
    if len(color) not in (3, 4) or not all(math.isfinite(value) for value in color):
        raise ValueError("Colors must contain three or four finite numbers")
    return list(color) + [1.0] * (4 - len(color))


def create_emissive_material(params):
    emission = rgba(params.get("emission_color", [1, 1, 1]))
    color = rgba(params["color"]) if params.get("color") is not None else None
    strength = params.get("emission_strength", 5.0)
    if not math.isfinite(strength) or strength <= 0:
        raise ValueError("'emission_strength' must be a positive finite number")
    mat = bpy.data.materials.new(name=params.get("name", "Glow"))
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if color is not None:
        bsdf.inputs["Base Color"].default_value = color
    emission_socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
    emission_socket.default_value = emission
    bsdf.inputs["Emission Strength"].default_value = strength
    return {"name": mat.name, "emission_color": emission, "emission_strength": strength}


__result__ = create_emissive_material(globals().get("args", {}))
