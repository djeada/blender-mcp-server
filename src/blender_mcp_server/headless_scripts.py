"""Built-in render and export scripts sent to a separate headless Blender process."""

# Mirrors _resolve_output_path / _set_render_engine in the add-on, which headless Blender does not load.
_HEADLESS_PATH_PRELUDE = """
import os
import tempfile

import bpy


def output_path(path, extensions=()):
    if path.startswith("//") and not bpy.data.filepath:
        resolved = os.path.join(tempfile.gettempdir(), "blender-mcp", path[2:].lstrip("/" + os.sep))
    else:
        resolved = bpy.path.abspath(path)
    absolute = os.path.abspath(resolved)
    if path.endswith(("/", os.sep)) and not absolute.endswith(os.sep):
        absolute += os.sep
    if extensions and not absolute.lower().endswith(extensions):
        absolute += extensions[0]
    os.makedirs(os.path.dirname(absolute), exist_ok=True)
    return absolute
"""

_HEADLESS_RENDER_PRELUDE = (
    _HEADLESS_PATH_PRELUDE
    + """
ENGINE_ALIASES = {
    "EEVEE": ("BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"),
    "EEVEE_NEXT": ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"),
    "BLENDER_EEVEE": ("BLENDER_EEVEE_NEXT",),
    "BLENDER_EEVEE_NEXT": ("BLENDER_EEVEE",),
    "WORKBENCH": ("BLENDER_WORKBENCH",),
}


def set_engine(scene, engine):
    requested = engine.strip().upper().replace(" ", "_")
    first_error = None
    for candidate in (requested, *ENGINE_ALIASES.get(requested, ())):
        try:
            scene.render.engine = candidate
            return
        except TypeError as exc:
            first_error = first_error or exc
    raise ValueError(f"Unknown render engine {engine!r}: {first_error}")


scene = bpy.context.scene
scene.render.filepath = output_path(args["output_path"])
if args.get("engine"):
    set_engine(scene, args["engine"])
"""
)

RENDER_STILL = (
    _HEADLESS_RENDER_PRELUDE
    + """
if args.get("resolution_x") is not None:
    scene.render.resolution_x = args["resolution_x"]
if args.get("resolution_y") is not None:
    scene.render.resolution_y = args["resolution_y"]
bpy.ops.render.render(write_still=True)
__result__ = {
    "output_path": scene.render.filepath,
    "engine": scene.render.engine,
    "resolution": [scene.render.resolution_x, scene.render.resolution_y],
}
"""
)

RENDER_ANIMATION = (
    _HEADLESS_RENDER_PRELUDE
    + """
if args.get("frame_start") is not None:
    scene.frame_start = args["frame_start"]
if args.get("frame_end") is not None:
    scene.frame_end = args["frame_end"]
bpy.ops.render.render(animation=True)
__result__ = {
    "output_path": scene.render.filepath,
    "engine": scene.render.engine,
    "frame_range": [scene.frame_start, scene.frame_end],
}
"""
)


def _headless_export_script(operator: str, extensions: tuple[str, ...]) -> str:
    """Build a headless export script whose result carries the absolute path written."""
    return (
        _HEADLESS_PATH_PRELUDE
        + f"""
__result__ = {{"filepath": output_path(args["filepath"], {extensions!r})}}
{operator}(filepath=__result__["filepath"])
"""
    )


EXPORT_GLTF = _headless_export_script("bpy.ops.export_scene.gltf", (".glb", ".gltf"))
EXPORT_OBJ = _headless_export_script("bpy.ops.wm.obj_export", (".obj",))
EXPORT_FBX = _headless_export_script("bpy.ops.export_scene.fbx", (".fbx",))
