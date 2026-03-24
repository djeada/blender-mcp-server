"""Create a primitive mesh object without using bpy.ops.

Args:
    name (str): Object name. Default: mesh type title-cased.
    mesh_type (str): cube, sphere, cylinder, plane, cone, or torus. Default: cube
    location (list[float]): [x, y, z] location. Default: [0, 0, 0]
    size (float): Primitive size. Matches the MCP object.create_mesh size meaning.

Result:
    name (str): Created object name
    type (str): Blender object type
    location (list[float]): Object location

Notes:
    Prefer this script or the injected ``mcp_create_mesh(...)`` helper inside
    python.execute scripts over ``bpy.ops.mesh.primitive_*_add``. The operator
    path can trigger unstable view-layer updates in live bridge sessions,
    especially around Mantaflow setup.
"""

name = args.get("name")
mesh_type = args.get("mesh_type", "cube")
location = args.get("location", [0, 0, 0])
size = args.get("size", 2.0)

helper = globals().get("mcp_create_mesh")
if helper is None:
    raise RuntimeError("mcp_create_mesh helper is unavailable in this execution context")

obj = helper(
    mesh_type,
    name=name,
    location=location,
    size=size,
)

__result__ = {
    "name": obj.name,
    "type": obj.type,
    "location": list(obj.location),
}
