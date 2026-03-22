"""Create a camera, set it active, and optionally position it.

Args:
    name (str): Camera name. Default: "Camera"
    location (list[float]): [x, y, z] location. Default: [7, -6, 5]
    rotation (list[float]): [rx, ry, rz] Euler rotation in radians. Default: None
    focal_length (float): Lens focal length in mm. Default: 50.0
    set_active (bool): Make this the scene's active camera. Default: True
    use_existing (str|None): Name of existing camera to configure instead. Default: None

Result:
    name (str): Camera object name
    location (list[float]): Final location
    focal_length (float): Focal length set
    is_active (bool): Whether it is the active scene camera
"""
import bpy

use_existing = args.get("use_existing")

if use_existing:
    cam_obj = bpy.data.objects.get(use_existing)
    if not cam_obj:
        raise ValueError(f"Camera '{use_existing}' not found")
else:
    cam_name = args.get("name", "Camera")
    cam_data = bpy.data.cameras.new(cam_name)
    cam_obj = bpy.data.objects.new(cam_name, cam_data)
    bpy.context.collection.objects.link(cam_obj)

location = args.get("location")
if location:
    cam_obj.location = tuple(location)

rotation = args.get("rotation")
if rotation:
    cam_obj.rotation_euler = tuple(rotation)

focal_length = args.get("focal_length", 50.0)
cam_obj.data.lens = focal_length

if args.get("set_active", True):
    bpy.context.scene.camera = cam_obj

__result__ = {
    "name": cam_obj.name,
    "location": list(cam_obj.location),
    "focal_length": cam_obj.data.lens,
    "is_active": bpy.context.scene.camera == cam_obj,
}
