"""Blender MCP Server — External MCP server that bridges Claude Desktop to Blender."""

import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Literal

from mcp.server.fastmcp import Context, FastMCP

from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.headless import HeadlessBlenderExecutor, HeadlessJobManager, validate_source
from blender_mcp_server.headless_scripts import EXPORT_FBX, EXPORT_GLTF, EXPORT_OBJ, RENDER_ANIMATION, RENDER_STILL

logger = logging.getLogger(__name__)

HEADLESS_JOB_MANAGER = HeadlessJobManager()
Transport = Literal["bridge", "headless"]


@asynccontextmanager
async def blender_lifespan(server: FastMCP):
    """Manage the Blender connection lifecycle."""
    conn = BlenderConnection()
    try:
        await conn.connect()
    except OSError:
        logger.warning("Could not connect to Blender on startup. Will retry on first tool call.")
    try:
        yield conn
    finally:
        await conn.disconnect()


mcp = FastMCP(
    "Blender MCP Server",
    lifespan=blender_lifespan,
    log_level="INFO",
)


def _get_conn(ctx: Context) -> BlenderConnection:
    return ctx.request_context.lifespan_context  # type: ignore[no-any-return]


async def _bridge(ctx: Context, command: str, **params: Any) -> str:
    """Forward a command to the add-on, omitting unset (None) parameters."""
    payload = {key: value for key, value in params.items() if value is not None}
    result = await _get_conn(ctx).send_command(command, payload)
    return json.dumps(result, indent=2)


def _headless_executor() -> HeadlessBlenderExecutor:
    if os.environ.get("BLENDER_MCP_HEADLESS", "1").lower() in {"0", "false", "no", "off"}:
        raise PermissionError("Headless transport is disabled (BLENDER_MCP_HEADLESS=0)")
    return HeadlessBlenderExecutor()


# -- Scene tools --


@mcp.tool(
    name="blender_scene_get_info",
    description="Get information about the current Blender scene including name, frame range, render engine, resolution, and object count.",
)
async def scene_get_info(ctx: Context) -> str:
    return await _bridge(ctx, "scene.get_info")


@mcp.tool(
    name="blender_scene_list_objects",
    description=(
        "List all objects in the current Blender scene with stable name sorting, pagination and filters. "
        "Optional: type (MESH, CAMERA, LIGHT, EMPTY, CURVE, ...), name substring, collection membership, "
        "visibility, limit and offset. Returns total matches plus the returned page."
    ),
)
async def scene_list_objects(
    ctx: Context,
    type: str | None = None,
    name: str | None = None,
    collection: str | None = None,
    visible: bool | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> str:
    return await _bridge(
        ctx,
        "scene.list_objects",
        type=type,
        name=name,
        collection=collection,
        visible=visible,
        limit=limit,
        offset=offset,
    )


@mcp.tool(
    name="blender_object_get_transform",
    description="Get the position, rotation, and scale of a Blender object by name.",
)
async def object_get_transform(ctx: Context, name: str) -> str:
    return await _bridge(ctx, "object.get_transform", name=name)


@mcp.tool(
    name="blender_object_get_hierarchy",
    description="Get the parent/child hierarchy of objects. If name is provided, returns the subtree for that object. Otherwise returns the full scene hierarchy.",
)
async def object_get_hierarchy(ctx: Context, name: str | None = None) -> str:
    return await _bridge(ctx, "object.get_hierarchy", name=name or None)


@mcp.tool(
    name="blender_material_list",
    description="List all materials in the Blender file.",
)
async def material_list(ctx: Context) -> str:
    return await _bridge(ctx, "material.list")


# -- Object mutation tools --


@mcp.tool(
    name="blender_object_create",
    description="Create a new mesh object in Blender. Supported types: cube, sphere, cylinder, plane, cone, torus.",
)
async def object_create(
    ctx: Context,
    mesh_type: str = "cube",
    name: str | None = None,
    location: list[float] | None = None,
    size: float = 2.0,
) -> str:
    return await _bridge(ctx, "object.create_mesh", type=mesh_type, name=name or None, location=location, size=size)


@mcp.tool(
    name="blender_object_delete",
    description="Delete an object from the Blender scene by name.",
)
async def object_delete(ctx: Context, name: str) -> str:
    return await _bridge(ctx, "object.delete", name=name)


@mcp.tool(
    name="blender_object_translate",
    description="Move an object. Provide either 'location' for absolute positioning or 'offset' for relative movement, not both.",
)
async def object_translate(
    ctx: Context,
    name: str,
    location: list[float] | None = None,
    offset: list[float] | None = None,
) -> str:
    return await _bridge(ctx, "object.translate", name=name, location=location, offset=offset)


@mcp.tool(
    name="blender_object_rotate",
    description="Set the rotation of an object. Provide rotation as [x, y, z] angles. By default angles are in degrees.",
)
async def object_rotate(
    ctx: Context,
    name: str,
    rotation: list[float],
    degrees: bool = True,
) -> str:
    return await _bridge(ctx, "object.rotate", name=name, rotation=rotation, degrees=degrees)


@mcp.tool(
    name="blender_object_scale",
    description="Set the scale of an object. Provide scale as [x, y, z].",
)
async def object_scale(ctx: Context, name: str, scale: list[float]) -> str:
    return await _bridge(ctx, "object.scale", name=name, scale=scale)


@mcp.tool(
    name="blender_object_duplicate",
    description="Duplicate an object in the Blender scene. Optionally provide a new name.",
)
async def object_duplicate(ctx: Context, name: str, new_name: str | None = None) -> str:
    return await _bridge(ctx, "object.duplicate", name=name, new_name=new_name or None)


# -- Material tools --


@mcp.tool(
    name="blender_material_create",
    description="Create a new material. Optionally set an initial base color as [r, g, b] or [r, g, b, a] with values 0-1.",
)
async def material_create(ctx: Context, name: str = "Material", color: list[float] | None = None) -> str:
    return await _bridge(ctx, "material.create", name=name, color=color)


@mcp.tool(
    name="blender_material_assign",
    description="Assign an existing material to an object.",
)
async def material_assign(ctx: Context, object: str, material: str) -> str:
    return await _bridge(ctx, "material.assign", object=object, material=material)


@mcp.tool(
    name="blender_material_set_color",
    description="Set the base color of a material. Color is [r, g, b] or [r, g, b, a] with values 0-1.",
)
async def material_set_color(ctx: Context, name: str, color: list[float]) -> str:
    return await _bridge(ctx, "material.set_color", name=name, color=color)


@mcp.tool(
    name="blender_material_set_texture",
    description="Set an image texture as the base color of a material. Provide the file path to the image.",
)
async def material_set_texture(ctx: Context, name: str, filepath: str) -> str:
    return await _bridge(ctx, "material.set_texture", name=name, filepath=filepath)


# -- Camera & light tools --


@mcp.tool(
    name="blender_camera_create",
    description=(
        "Create a camera. Optionally set name, location, orientation via rotation (degrees) or look_at "
        "[x, y, z] target (not both), projection ('PERSP' or 'ORTHO'), focal length in mm (PERSP only), "
        "ortho_scale (ORTHO only), clip_start/clip_end, and set_active to make it the active scene camera."
    ),
)
async def camera_create(
    ctx: Context,
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    projection: str | None = None,
    lens: float | None = None,
    ortho_scale: float | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    set_active: bool | None = None,
) -> str:
    return await _bridge(
        ctx,
        "camera.create",
        name=name,
        location=location,
        rotation=rotation,
        look_at=look_at,
        projection=projection,
        lens=lens,
        ortho_scale=ortho_scale,
        clip_start=clip_start,
        clip_end=clip_end,
        set_active=set_active,
    )


@mcp.tool(
    name="blender_camera_update",
    description=(
        "Update an existing camera by name. Optionally change location, orientation via rotation (degrees) "
        "or look_at [x, y, z] target (not both), projection ('PERSP' or 'ORTHO'), focal length in mm "
        "(PERSP only), ortho_scale (ORTHO only), clip_start/clip_end, and set_active to make it the "
        "active scene camera."
    ),
)
async def camera_update(
    ctx: Context,
    name: str,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    projection: str | None = None,
    lens: float | None = None,
    ortho_scale: float | None = None,
    clip_start: float | None = None,
    clip_end: float | None = None,
    set_active: bool | None = None,
) -> str:
    return await _bridge(
        ctx,
        "camera.update",
        name=name,
        location=location,
        rotation=rotation,
        look_at=look_at,
        projection=projection,
        lens=lens,
        ortho_scale=ortho_scale,
        clip_start=clip_start,
        clip_end=clip_end,
        set_active=set_active,
    )


@mcp.tool(
    name="blender_light_create",
    description=(
        "Create a light. type is POINT, SUN, SPOT, or AREA (default POINT). Optionally set name, location, "
        "orientation via rotation (degrees) or look_at [x, y, z] target (not both), color [r, g, b] (0-1), "
        "energy, size (POINT/SPOT radius, AREA size), size_y (AREA rectangle only), angle in degrees (SUN "
        "only), spot_angle in degrees (SPOT only), and spot_blend 0-1 (SPOT only). Unsupported parameters "
        "for the chosen type produce explicit errors."
    ),
)
async def light_create(
    ctx: Context,
    light_type: str = "POINT",
    name: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    color: list[float] | None = None,
    energy: float | None = None,
    size: float | None = None,
    size_y: float | None = None,
    angle: float | None = None,
    spot_angle: float | None = None,
    spot_blend: float | None = None,
) -> str:
    return await _bridge(
        ctx,
        "light.create",
        type=light_type,
        name=name,
        location=location,
        rotation=rotation,
        look_at=look_at,
        color=color,
        energy=energy,
        size=size,
        size_y=size_y,
        angle=angle,
        spot_angle=spot_angle,
        spot_blend=spot_blend,
    )


@mcp.tool(
    name="blender_light_update",
    description=(
        "Update an existing light by name. Optionally change type (POINT, SUN, SPOT, AREA), location, "
        "orientation via rotation (degrees) or look_at [x, y, z] target (not both), color [r, g, b] (0-1), "
        "energy, size (POINT/SPOT radius, AREA size), size_y (AREA rectangle only), angle in degrees (SUN "
        "only), spot_angle in degrees (SPOT only), and spot_blend 0-1 (SPOT only). Unsupported parameters "
        "for the current type produce explicit errors."
    ),
)
async def light_update(
    ctx: Context,
    name: str,
    light_type: str | None = None,
    location: list[float] | None = None,
    rotation: list[float] | None = None,
    look_at: list[float] | None = None,
    color: list[float] | None = None,
    energy: float | None = None,
    size: float | None = None,
    size_y: float | None = None,
    angle: float | None = None,
    spot_angle: float | None = None,
    spot_blend: float | None = None,
) -> str:
    return await _bridge(
        ctx,
        "light.update",
        name=name,
        type=light_type,
        location=location,
        rotation=rotation,
        look_at=look_at,
        color=color,
        energy=energy,
        size=size,
        size_y=size_y,
        angle=angle,
        spot_angle=spot_angle,
        spot_blend=spot_blend,
    )


# -- Timeline & animation tools --


@mcp.tool(
    name="blender_timeline_get",
    description="Get the current frame and scene frame range (frame_start, frame_current, frame_end).",
)
async def timeline_get(ctx: Context) -> str:
    return await _bridge(ctx, "timeline.get")


@mcp.tool(
    name="blender_timeline_set",
    description=(
        "Set the current frame and/or scene frame range. Rotation-independent; frames are integers. "
        "Provide any subset of frame_current, frame_start, frame_end. Returns the resulting timeline."
    ),
)
async def timeline_set(
    ctx: Context,
    frame_current: int | None = None,
    frame_start: int | None = None,
    frame_end: int | None = None,
) -> str:
    return await _bridge(ctx, "timeline.set", frame_current=frame_current, frame_start=frame_start, frame_end=frame_end)


@mcp.tool(
    name="blender_keyframe_add",
    description=(
        "Insert a keyframe on an object for a common animatable property: 'location', 'rotation' (values in "
        "degrees) or 'scale'. Optionally set the property's value at the given frame and an interpolation mode "
        "(BEZIER, LINEAR, CONSTANT) applied to the inserted keys. Returns the action name, keyframe count, "
        "and whether the key was inserted or overwrote an existing key."
    ),
)
async def keyframe_add(
    ctx: Context,
    name: str,
    property: str,
    frame: int,
    value: list[float] | None = None,
    interpolation: str | None = None,
) -> str:
    return await _bridge(
        ctx,
        "keyframe.insert",
        name=name,
        property=property,
        frame=frame,
        value=value,
        interpolation=interpolation,
    )


@mcp.tool(
    name="blender_keyframe_list",
    description=(
        "List keyframes on an object for 'location', 'rotation' or 'scale'. Returns channel index, frame and "
        "value for each key (rotation values are radians as stored by Blender). Fails clearly when the "
        "object has no animation data."
    ),
)
async def keyframe_list(ctx: Context, name: str, property: str | None = None) -> str:
    return await _bridge(ctx, "keyframe.list", name=name, property=property)


@mcp.tool(
    name="blender_keyframe_remove",
    description=(
        "Remove the keyframe(s) at a given frame on an object for 'location', 'rotation' or 'scale'. "
        "Returns how many keys were removed and the remaining count; fails clearly when none exist."
    ),
)
async def keyframe_remove(ctx: Context, name: str, property: str, frame: int) -> str:
    return await _bridge(ctx, "keyframe.remove", name=name, property=property, frame=frame)


# -- Scene organization tools --


@mcp.tool(
    name="blender_collection_create",
    description="Create a collection. Optionally link it under an existing parent collection (otherwise at scene root).",
)
async def collection_create(ctx: Context, name: str, parent: str | None = None) -> str:
    return await _bridge(ctx, "collection.create", name=name, parent=parent)


@mcp.tool(
    name="blender_collection_list",
    description="List all collections with their object counts.",
)
async def collection_list(ctx: Context) -> str:
    return await _bridge(ctx, "collection.list")


@mcp.tool(
    name="blender_collection_rename",
    description=(
        "Rename a collection. Blender appends a .001 suffix when the requested name is taken; "
        "the returned 'name' is the canonical one."
    ),
)
async def collection_rename(ctx: Context, name: str, new_name: str) -> str:
    return await _bridge(ctx, "collection.rename", name=name, new_name=new_name)


@mcp.tool(
    name="blender_collection_add_object",
    description=(
        "Add an object to a collection, moving it out of its current collection(s). Returns whether it moved "
        "and the collections it left."
    ),
)
async def collection_add_object(ctx: Context, collection: str, object: str) -> str:
    return await _bridge(ctx, "collection.add_object", collection=collection, object=object)


@mcp.tool(
    name="blender_collection_remove_object",
    description=(
        "Remove an object from a collection. If the object would be left unlinked, it is re-linked to the "
        "scene root collection so it stays part of the scene."
    ),
)
async def collection_remove_object(ctx: Context, collection: str, object: str) -> str:
    return await _bridge(ctx, "collection.remove_object", collection=collection, object=object)


@mcp.tool(
    name="blender_object_rename",
    description=(
        "Rename an object. Blender appends a .001 suffix when the requested name is taken; "
        "the returned 'name' is the canonical one."
    ),
)
async def object_rename(ctx: Context, name: str, new_name: str) -> str:
    return await _bridge(ctx, "object.rename", name=name, new_name=new_name)


@mcp.tool(
    name="blender_object_parent",
    description=(
        "Parent an object to another object. Parenting to itself or a descendant is refused (cycle detection). "
        "Set keep_transform=true to preserve the object's current world transform via the parent inverse "
        "matrix; otherwise the object moves with the parent's local space."
    ),
)
async def object_parent(ctx: Context, name: str, parent: str, keep_transform: bool | None = None) -> str:
    return await _bridge(ctx, "object.parent", name=name, parent=parent, keep_transform=keep_transform)


@mcp.tool(
    name="blender_object_unparent",
    description=(
        "Clear an object's parent. Set keep_transform=true to bake the current world transform first so the "
        "object stays in place; otherwise it keeps its local transform."
    ),
)
async def object_unparent(ctx: Context, name: str, keep_transform: bool | None = None) -> str:
    return await _bridge(ctx, "object.unparent", name=name, keep_transform=keep_transform)


# -- Render tools --


@mcp.tool(
    name="blender_render_still",
    description=(
        "Render the current scene as a still image and return the absolute path of the written file. "
        "Optionally set output path, resolution, and render engine (EEVEE, CYCLES, or WORKBENCH). "
        "A path starting with '//' is relative to the .blend file, or to a temp folder while the file is unsaved. "
        "Use transport='bridge' for the live Blender add-on session, or "
        "transport='headless' with blend_file='/path/to/file.blend' to render in a separate background Blender process."
    ),
)
async def render_still(
    ctx: Context,
    output_path: str = "//render.png",
    resolution_x: int | None = None,
    resolution_y: int | None = None,
    engine: str | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        result = await _headless_executor().execute(
            code=RENDER_STILL,
            args={
                "output_path": output_path,
                "resolution_x": resolution_x,
                "resolution_y": resolution_y,
                "engine": engine,
            },
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps(result, indent=2)
    return await _bridge(
        ctx,
        "render.still",
        output_path=output_path,
        resolution_x=resolution_x,
        resolution_y=resolution_y,
        engine=engine or None,
    )


@mcp.tool(
    name="blender_render_animation",
    description=(
        "Render an animation and return the absolute output path prefix. Optionally set output path, frame range, "
        "and render engine (EEVEE, CYCLES, or WORKBENCH). "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with a blend_file "
        "to render in a separate background Blender process."
    ),
)
async def render_animation(
    ctx: Context,
    output_path: str = "//render_",
    frame_start: int | None = None,
    frame_end: int | None = None,
    engine: str | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        result = await _headless_executor().execute(
            code=RENDER_ANIMATION,
            args={
                "output_path": output_path,
                "frame_start": frame_start,
                "frame_end": frame_end,
                "engine": engine,
            },
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps(result, indent=2)
    return await _bridge(
        ctx,
        "render.animation",
        output_path=output_path,
        frame_start=frame_start,
        frame_end=frame_end,
        engine=engine or None,
    )


# -- Export tools --


async def _headless_export(script: str, filepath: str, blend_file: str | None, factory_startup: bool | None) -> str:
    result = await _headless_executor().execute(
        code=script,
        args={"filepath": filepath},
        blend_file=blend_file,
        factory_startup=factory_startup,
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_export_gltf",
    description=(
        "Export the scene as glTF/GLB and return the absolute path written. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with blend_file="
        "'/path/to/file.blend' to export in a separate background Blender process."
    ),
)
async def export_gltf(
    ctx: Context,
    filepath: str,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        return await _headless_export(EXPORT_GLTF, filepath, blend_file, factory_startup)
    return await _bridge(ctx, "export.gltf", filepath=filepath)


@mcp.tool(
    name="blender_export_obj",
    description=(
        "Export the scene as OBJ and return the absolute path written. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with blend_file="
        "'/path/to/file.blend' to export in a separate background Blender process."
    ),
)
async def export_obj(
    ctx: Context,
    filepath: str,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        return await _headless_export(EXPORT_OBJ, filepath, blend_file, factory_startup)
    return await _bridge(ctx, "export.obj", filepath=filepath)


@mcp.tool(
    name="blender_export_fbx",
    description=(
        "Export the scene as FBX and return the absolute path written. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' with blend_file="
        "'/path/to/file.blend' to export in a separate background Blender process."
    ),
)
async def export_fbx(
    ctx: Context,
    filepath: str,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        return await _headless_export(EXPORT_FBX, filepath, blend_file, factory_startup)
    return await _bridge(ctx, "export.fbx", filepath=filepath)


# -- History tools --


@mcp.tool(
    name="blender_history_undo",
    description="Undo the last operation in Blender.",
)
async def history_undo(ctx: Context) -> str:
    return await _bridge(ctx, "history.undo")


@mcp.tool(
    name="blender_history_redo",
    description="Redo the last undone operation in Blender.",
)
async def history_redo(ctx: Context) -> str:
    return await _bridge(ctx, "history.redo")


# -- Python execution tools --


@mcp.tool(
    name="blender_python_exec",
    description=(
        "Execute a Python script in Blender's context synchronously. "
        "Provide either 'code' (inline Python string) or 'script_path' (path to a .py file), not both. "
        "The script has access to 'bpy', 'mathutils', and an 'args' dict with your supplied arguments. "
        "Set '__result__' in the script to return a JSON-serializable value. "
        "Returns the result, captured stdout/stderr, and execution duration. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' to run the script "
        "in a separate `blender -b` process. For long-running tasks like baking, use blender_python_exec_async."
    ),
)
async def python_exec(
    ctx: Context,
    code: str | None = None,
    script_path: str | None = None,
    args: dict | None = None,
    timeout_seconds: int | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        result = await _headless_executor().execute(
            code=code,
            script_path=script_path,
            args=args,
            timeout_seconds=timeout_seconds,
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps(result, indent=2)
    return await _bridge(
        ctx,
        "python.execute",
        code=code,
        script_path=script_path,
        args=args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(
    name="blender_python_exec_async",
    description=(
        "Start a long-running Python script in Blender asynchronously. "
        "Same parameters as blender_python_exec. Returns a job_id immediately. "
        "Use blender_job_status to poll for completion, and blender_job_cancel to abort. "
        "The script can check '__cancel_event__.is_set()' to detect cancellation. "
        "Ideal for fluid baking, rigid body simulation, or heavy scene generation. "
        "Note: bridge jobs run on Blender's main thread, so the Blender UI is busy while they run. "
        "Use transport='headless' to run the job in a separate background Blender process instead."
    ),
)
async def python_exec_async(
    ctx: Context,
    code: str | None = None,
    script_path: str | None = None,
    args: dict | None = None,
    timeout_seconds: int | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        validate_source(code, script_path)
        job_id = await HEADLESS_JOB_MANAGER.create_job(
            _headless_executor(),
            code=code,
            script_path=script_path,
            args=args,
            timeout_seconds=timeout_seconds,
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps({"job_id": job_id}, indent=2)
    return await _bridge(
        ctx,
        "python.execute_async",
        code=code,
        script_path=script_path,
        args=args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(
    name="blender_job_status",
    description=(
        "Get the status of an async Blender job. Returns job_id, status "
        "(queued/running/succeeded/failed/cancelled), timestamps, result, stdout, stderr, and error. "
        "Poll this after starting a job with blender_python_exec_async."
    ),
)
async def job_status(ctx: Context, job_id: str) -> str:
    if job_id.startswith("headless-job-"):
        return json.dumps(HEADLESS_JOB_MANAGER.get_status(job_id), indent=2)
    return await _bridge(ctx, "job.status", job_id=job_id)


@mcp.tool(
    name="blender_job_cancel",
    description=(
        "Cancel a running or queued async Blender job. "
        "The job's __cancel_event__ is set; scripts that check it will stop gracefully."
    ),
)
async def job_cancel(ctx: Context, job_id: str) -> str:
    if job_id.startswith("headless-job-"):
        return json.dumps(await HEADLESS_JOB_MANAGER.cancel(job_id), indent=2)
    return await _bridge(ctx, "job.cancel", job_id=job_id)


@mcp.tool(
    name="blender_job_list",
    description="List known async Blender jobs with their IDs, statuses, and creation timestamps.",
)
async def job_list(ctx: Context) -> str:
    headless_jobs = HEADLESS_JOB_MANAGER.list_jobs()["jobs"]
    try:
        bridge_result = await _get_conn(ctx).send_command("job.list")
        bridge_jobs = bridge_result.get("jobs", [])
    except Exception as exc:
        logger.info("Bridge job list unavailable: %s", exc)
        bridge_jobs = []
    result = {"jobs": bridge_jobs + headless_jobs}
    return json.dumps(result, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
