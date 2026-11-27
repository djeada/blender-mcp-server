"""Preview a material on a temporary shape under the fixed inspection lighting."""

from __future__ import annotations

from typing import TYPE_CHECKING

import bpy

from . import capture
from .protocol import MissingResourceError

if TYPE_CHECKING:
    from .paths import PathPolicy

# Default view per shape. A sphere seen at an angle is framed from its bounding box, which wastes half
# the picture; from the front the box fits it exactly.
SHAPES = {"sphere": "front", "plane": "front", "cube": "three_quarter"}


def _mesh(shape: str):
    mesh = bpy.data.meshes.new("mcp-preview-mesh")
    try:
        if shape == "plane":
            # Upright in the XZ plane, facing the front view, with 0-1 UVs.
            mesh.from_pydata([(-1, 0, -1), (1, 0, -1), (1, 0, 1), (-1, 0, 1)], [], [(0, 1, 2, 3)])
            layer = mesh.uv_layers.new(name="UVMap")
            for index, uv in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
                if hasattr(layer, "uv"):
                    layer.uv[index].vector = uv
                else:  # before Blender 3.5
                    layer.data[index].uv = uv
        else:
            import bmesh

            bm = bmesh.new()
            try:
                bm.loops.layers.uv.new("UVMap")
                if shape == "sphere":
                    bmesh.ops.create_uvsphere(bm, u_segments=64, v_segments=32, radius=1.0, calc_uvs=True)
                    for face in bm.faces:
                        face.smooth = True
                else:
                    bmesh.ops.create_cube(bm, size=1.6, calc_uvs=True)
                bm.to_mesh(mesh)
            finally:
                bm.free()
    except Exception:
        bpy.data.meshes.remove(mesh)
        raise
    return mesh


def preview(params: dict, *, policy: PathPolicy) -> dict:
    material = bpy.data.materials.get(params["material"])
    if material is None:
        raise MissingResourceError("Material not found")
    shape = params.get("shape", "sphere")
    if shape not in SHAPES:
        raise ValueError(f"'shape' must be one of: {', '.join(SHAPES)}")
    mesh = _mesh(shape)
    obj = None
    try:
        mesh.materials.append(material)
        obj = bpy.data.objects.new("mcp-preview-subject", mesh)
        report = capture.capture(
            {
                "object": obj.name,
                "include_children": False,
                "views": params.get("views") or [SHAPES[shape]],
                "projection": "orthographic",
                "mode": "material",
                "lighting": "rig",
                "resolution": params["resolution"],
                "include_images": params["include_images"],
                "save_directory": params.get("save_directory"),
                "max_bytes": params["max_bytes"],
            },
            policy=policy,
        )
    finally:
        if obj is not None:
            bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
    report["target"] = {"material": material.name, "shape": shape}
    return report
