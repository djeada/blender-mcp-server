"""Create a Mantaflow fluid domain.

Args:
    domain_name (str): Name for the domain object. Default: "FluidDomain"
    location (list[float]): [x, y, z] location. Default: [0, 0, 2]
    size (float): Cube size. Default: 4.0
    resolution (int): Domain max resolution. Default: 64
    cache_dir (str): Cache directory (Blender relative path OK). Default: "//fluid_cache"
    domain_type (str): "LIQUID" or "GAS". Default: "LIQUID"

Result:
    domain (str): Created object name
    resolution (int): Resolution set
    cache_dir (str): Cache directory set
"""
import bpy

name = args.get("domain_name", "FluidDomain")
location = args.get("location", [0, 0, 2])
size = args.get("size", 4.0)
resolution = args.get("resolution", 64)
cache_dir = args.get("cache_dir", "//fluid_cache")
domain_type = args.get("domain_type", "LIQUID")

bpy.ops.mesh.primitive_cube_add(size=size, location=tuple(location))
domain = bpy.context.active_object
domain.name = name

bpy.ops.object.modifier_add(type='FLUID')
domain.modifiers["Fluid"].fluid_type = 'DOMAIN'
settings = domain.modifiers["Fluid"].domain_settings
settings.domain_type = domain_type
settings.resolution_max = resolution
settings.cache_directory = cache_dir

# Make domain wireframe for visibility
domain.display_type = 'WIRE'

__result__ = {
    "domain": domain.name,
    "resolution": settings.resolution_max,
    "cache_dir": settings.cache_directory,
    "domain_type": domain_type,
}
