"""Create or configure a fluid inflow source.

Args:
    name (str): Object name. Default: "FluidInflow"
    location (list[float]): [x, y, z] location. Default: [0, 0, 3]
    size (float): Cube size for new inflow object. Default: 1.0
    use_existing (str|None): Name of existing object to convert. Default: None
    flow_type (str): "LIQUID", "SMOKE", or "FIRE". Default: "LIQUID"
    flow_behavior (str): "INFLOW", "OUTFLOW", or "GEOMETRY". Default: "INFLOW"
    use_initial_velocity (bool): Enable initial velocity. Default: False
    initial_velocity (list[float]): [vx, vy, vz]. Default: [0, 0, 0]
    show_viewport (bool): Whether to evaluate the fluid modifier in the viewport. Default: False
    hide_viewport (bool): Whether to hide the source object in the viewport. Default: True
    hide_render (bool): Whether to hide the source object in renders. Default: True

Result:
    name (str): Object name
    flow_type (str): Flow type set
"""

import bpy


def create_cube_mesh(name: str, size: float):
    half = size / 2.0
    verts = [
        (-half, -half, -half),
        (half, -half, -half),
        (half, half, -half),
        (-half, half, -half),
        (-half, -half, half),
        (half, -half, half),
        (half, half, half),
        (-half, half, half),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    ]
    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


obj_name = args.get("name", "FluidInflow")
use_existing = args.get("use_existing")

if use_existing:
    obj = bpy.data.objects.get(use_existing)
    if not obj:
        raise ValueError(f"Object '{use_existing}' not found")
    bpy.context.view_layer.objects.active = obj
else:
    location = args.get("location", [0, 0, 3])
    size = args.get("size", 1.0)
    obj = create_cube_mesh(obj_name, size)
    obj.location = tuple(location)
    bpy.context.view_layer.objects.active = obj

flow_type = args.get("flow_type", "LIQUID")
flow_behavior = args.get("flow_behavior", "INFLOW")
show_viewport = args.get("show_viewport", False)
hide_viewport = args.get("hide_viewport", True)
hide_render = args.get("hide_render", True)

modifier = obj.modifiers.get("Fluid")
if modifier is None:
    modifier = obj.modifiers.new(name="Fluid", type="FLUID")

modifier.fluid_type = "FLOW"
modifier.show_viewport = show_viewport
flow = modifier.flow_settings
flow.flow_type = flow_type
flow.flow_behavior = flow_behavior

if args.get("use_initial_velocity", False):
    flow.use_initial_velocity = True
    vel = args.get("initial_velocity", [0, 0, 0])
    flow.velocity_coord = tuple(vel)

obj.hide_viewport = hide_viewport
obj.hide_render = hide_render

__result__ = {
    "name": obj.name,
    "flow_type": flow_type,
    "flow_behavior": flow_behavior,
    "show_viewport": modifier.show_viewport,
    "hide_viewport": obj.hide_viewport,
    "hide_render": obj.hide_render,
}
