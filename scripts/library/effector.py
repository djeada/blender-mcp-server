"""Set up collision/effector objects for fluid or physics simulations.

Args:
    objects (list[str]): Names of objects to configure as effectors.
    effector_type (str): "COLLISION" for fluid effectors. Default: "COLLISION"
    surface_distance (float): Surface thickness. Default: 0.01
    use_effector (bool): Whether to also add physics collision. Default: True

Result:
    configured (list[str]): Objects successfully configured
    skipped (list[str]): Objects not found
"""
import bpy

obj_names = args.get("objects", [])
effector_type = args.get("effector_type", "COLLISION")
surface_distance = args.get("surface_distance", 0.01)
use_effector = args.get("use_effector", True)

configured = []
skipped = []

for name in obj_names:
    obj = bpy.data.objects.get(name)
    if obj is None:
        skipped.append(name)
        continue

    fluid_mod = obj.modifiers.get("Fluid")
    if fluid_mod is None:
        fluid_mod = obj.modifiers.new(name="Fluid", type='FLUID')
    fluid_mod.fluid_type = 'EFFECTOR'
    eff = fluid_mod.effector_settings
    eff.effector_type = effector_type
    eff.surface_distance = surface_distance

    # Optionally add physics collision as well
    if use_effector:
        has_collision = any(m.type == 'COLLISION' for m in obj.modifiers)
        if not has_collision:
            obj.modifiers.new(name="Collision", type='COLLISION')
    configured.append(name)

__result__ = {
    "configured": configured,
    "skipped": skipped,
}
