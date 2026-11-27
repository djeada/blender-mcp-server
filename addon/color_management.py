"""Read and change the scene's render color management, limited to a fixed set of settings."""

import re

import bpy

from .protocol import InvalidArgumentsError

# parameter -> (scene attribute, property)
ENUMS = {
    "display_device": ("display_settings", "display_device"),
    "view_transform": ("view_settings", "view_transform"),
    "look": ("view_settings", "look"),
}
NUMBERS = {"exposure": "exposure", "gamma": "gamma"}
_PROBE = "__mcp_probe__"


def available(owner, name: str) -> list[str]:
    """The values this Blender build accepts for a color-management enum.

    These lists come from the OpenColorIO configuration and are missing from RNA metadata.
    Assigning an impossible value changes nothing and makes Blender name the valid ones.
    """
    try:
        setattr(owner, name, _PROBE)
    except TypeError as exc:
        listed = str(exc).partition("not found in (")[2]
        return re.findall(r"'((?:[^'\\]|\\.)*)'", listed)
    raise InvalidArgumentsError(f"This Blender build does not validate '{name}', so its values are unknown")


def current(scene) -> dict:
    values = {key: getattr(getattr(scene, owner), name) for key, (owner, name) in ENUMS.items()}
    values.update({key: round(float(getattr(scene.view_settings, name)), 6) for key, name in NUMBERS.items()})
    values["use_curve_mapping"] = bool(scene.view_settings.use_curve_mapping)
    return values


def options(scene) -> dict:
    """Valid values right now. The list of looks depends on the current view transform."""
    found = {}
    for key, (owner, name) in ENUMS.items():
        found[f"{key}s"] = available(getattr(scene, owner), name)
    return found


def update(params: dict) -> dict:
    changes = {key: params[key] for key in (*ENUMS, *NUMBERS) if params.get(key) is not None}
    if not changes:
        raise InvalidArgumentsError(f"Provide at least one of: {', '.join((*ENUMS, *NUMBERS))}")
    scene = bpy.context.scene
    before = current(scene)
    applied: list[str] = []
    try:
        # Order matters: the display decides the view transforms, which decide the looks.
        for key, (owner_name, name) in ENUMS.items():
            if key not in changes:
                continue
            owner = getattr(scene, owner_name)
            try:
                setattr(owner, name, changes[key])
            except TypeError:
                choices = available(owner, name)
                raise InvalidArgumentsError(
                    f"'{changes[key]}' is not a valid {key} here. Choose from: {', '.join(choices)}"
                ) from None
            applied.append(key)
        for key, name in NUMBERS.items():
            if key in changes:
                setattr(scene.view_settings, name, changes[key])
                applied.append(key)
    except Exception:
        _restore(scene, before)
        raise
    after = current(scene)
    adjusted = {
        key: {"was": before[key], "now": after[key]}
        for key in ENUMS
        if key not in changes and after[key] != before[key]
    }
    result = {"color_management": after, "changed": sorted(applied)}
    if adjusted:
        result["adjusted_by_blender"] = adjusted
    return result


def _restore(scene, values: dict) -> None:
    for key, (owner_name, name) in ENUMS.items():
        owner = getattr(scene, owner_name)
        if getattr(owner, name) != values[key]:
            setattr(owner, name, values[key])
    for key, name in NUMBERS.items():
        setattr(scene.view_settings, name, values[key])
