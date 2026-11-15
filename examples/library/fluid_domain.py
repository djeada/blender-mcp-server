"""Create a Mantaflow fluid domain.

Args:
    domain_name (str): Name for the domain object. Default: "FluidDomain"
    location (list[float]): [x, y, z] location. Default: [0, 0, 2]
    size (float): Cube size. Default: 4.0
    resolution (int): Domain max resolution. Default: 64
    cache_dir (str): Cache directory (Blender relative path OK). Default: "//fluid_cache"
    domain_type (str): "LIQUID" or "GAS". Default: "LIQUID"
    show_viewport (bool): Whether the fluid modifier is visible in the viewport. Default: False

Result:
    domain (str): Created object name
    resolution (int): Resolution set
    cache_dir (str): Cache directory set
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


name = args.get("domain_name", "FluidDomain")
location = args.get("location", [0, 0, 2])
size = args.get("size", 4.0)
resolution = args.get("resolution", 64)
cache_dir = args.get("cache_dir", "//fluid_cache")
domain_type = args.get("domain_type", "LIQUID")
show_viewport = args.get("show_viewport", False)

domain = create_cube_mesh(name, size)
domain.location = tuple(location)

modifier = domain.modifiers.get("Fluid")
if modifier is None:
    modifier = domain.modifiers.new(name="Fluid", type="FLUID")

modifier.fluid_type = "DOMAIN"
settings = modifier.domain_settings
settings.domain_type = domain_type
settings.resolution_max = resolution
settings.cache_directory = cache_dir
modifier.show_viewport = show_viewport

# Make domain wireframe for visibility
domain.display_type = "WIRE"

__result__ = {
    "domain": domain.name,
    "resolution": settings.resolution_max,
    "cache_dir": settings.cache_directory,
    "domain_type": domain_type,
    "show_viewport": modifier.show_viewport,
}
