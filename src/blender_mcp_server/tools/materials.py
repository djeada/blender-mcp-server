"""MCP tools for materials."""

from typing import Annotated, Literal

from mcp.server.fastmcp import Context
from pydantic import Field

from blender_mcp_server.app import bridge, bridge_result, mcp, page_limit

SharedData = Literal["error", "update_all", "make_single_user"]
Link = Literal["DATA", "OBJECT"]
Slot = Annotated[int, Field(ge=0)]


@mcp.tool(
    name="blender_material_list",
    description="List all materials in the Blender file.",
)
async def material_list(ctx: Context, limit: int | None = None, offset: int | None = None) -> str:
    return await bridge(ctx, "material.list", limit=page_limit(limit), offset=offset)


@mcp.tool(
    name="blender_material_create",
    description="Create a new material. Optionally set an initial base color as [r, g, b] or [r, g, b, a] with values 0-1.",
)
async def material_create(ctx: Context, name: str = "Material", color: list[float] | None = None) -> str:
    return await bridge(ctx, "material.create", name=name, color=color)


@mcp.tool(
    name="blender_material_assign",
    description="Assign an existing material to an object.",
)
async def material_assign(ctx: Context, object: str, material: str) -> str:
    return await bridge(ctx, "material.assign", object=object, material=material)


@mcp.tool(
    name="blender_material_set_color",
    description="Set the base color of a material. Color is [r, g, b] or [r, g, b, a] with values 0-1.",
)
async def material_set_color(ctx: Context, name: str, color: list[float]) -> str:
    return await bridge(ctx, "material.set_color", name=name, color=color)


@mcp.tool(
    name="blender_material_set_texture",
    description="Set an image texture as the base color of a material. Provide the file path to the image.",
)
async def material_set_texture(ctx: Context, name: str, filepath: str) -> str:
    return await bridge(ctx, "material.set_texture", name=name, filepath=filepath)


@mcp.tool(
    name="blender_material_slots",
    description=(
        "List a mesh object's material slots without changing them: index, material, DATA or OBJECT link, and how "
        "many faces use each. Reports other objects sharing the mesh."
    ),
)
async def material_slots(
    ctx: Context, object: str, limit: Annotated[int | None, Field(ge=1)] = None, offset: Slot | None = None
) -> dict:
    return {
        "result": await bridge_result(ctx, "material.list_slots", object=object, limit=page_limit(limit), offset=offset)
    }


@mcp.tool(
    name="blender_material_slot_append",
    description=(
        "Add a material slot, optionally holding a material, without replacing others. The slot is added to the "
        "mesh; on a shared mesh set shared_data to 'update_all' or 'make_single_user'."
    ),
)
async def material_slot_append(
    ctx: Context, object: str, material: str | None = None, link: Link = "DATA", shared_data: SharedData = "error"
) -> dict:
    return {
        "result": await bridge_result(
            ctx, "material.slot_append", object=object, material=material, link=link, shared_data=shared_data
        )
    }


@mcp.tool(
    name="blender_material_slot_replace",
    description=(
        "Set one slot's material (omit material to empty it). link='OBJECT' changes only this object; a DATA change "
        "affects every object sharing the mesh and then needs shared_data."
    ),
)
async def material_slot_replace(
    ctx: Context,
    object: str,
    index: Slot,
    material: str | None = None,
    link: Link | None = None,
    shared_data: SharedData = "error",
) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "material.slot_replace",
            object=object,
            index=index,
            material=material,
            link=link,
            shared_data=shared_data,
        )
    }


@mcp.tool(
    name="blender_material_slot_remove",
    description=(
        "Remove a slot. If faces use it, remap_to names the slot that takes them. Other faces and every object's "
        "linked materials keep what they showed."
    ),
)
async def material_slot_remove(
    ctx: Context, object: str, index: Slot, remap_to: Slot | None = None, shared_data: SharedData = "error"
) -> dict:
    return {
        "result": await bridge_result(
            ctx, "material.slot_remove", object=object, index=index, remap_to=remap_to, shared_data=shared_data
        )
    }


@mcp.tool(
    name="blender_material_assign_faces",
    description=(
        "Assign faces to a slot, given by 'slot' index or a 'material' already in a slot. Select faces with exactly "
        "one of face_indices (raw mesh indices), vertex_group (match 'all' or 'any' of a face's vertices) or "
        "from_slot."
    ),
)
async def material_assign_faces(
    ctx: Context,
    object: str,
    slot: Slot | None = None,
    material: str | None = None,
    face_indices: Annotated[list[int] | None, Field(max_length=100_000)] = None,
    vertex_group: str | None = None,
    from_slot: Slot | None = None,
    match: Literal["all", "any"] = "all",
    min_weight: Annotated[float, Field(ge=0, le=1)] = 0.0,
    shared_data: SharedData = "error",
) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "material.assign_faces",
            object=object,
            slot=slot,
            material=material,
            face_indices=face_indices,
            vertex_group=vertex_group,
            from_slot=from_slot,
            match=match,
            min_weight=min_weight,
            shared_data=shared_data,
        )
    }


@mcp.tool(
    name="blender_material_set_texture_set",
    description=(
        "Bind local PBR texture files to a material's Principled BSDF with correct color spaces. maps: "
        "{base_color, metallic, roughness, normal, ao, emission, opacity, height}, each a path or {path, ...}; "
        "metallic, roughness, ao, opacity and height take channel R/G/B/A. Required choices: normal.convention "
        "opengl|directx, ao.mode gltf|multiply, opacity.mode blend|clip, height.mode bump|displacement. orm=path "
        "binds a packed occlusion/roughness/metallic image. Unlisted maps are kept; remove=[names] unbinds. "
        "Nothing changes if a file or link check fails."
    ),
)
async def material_set_texture_set(
    ctx: Context,
    name: str,
    maps: dict[str, str | dict] | None = None,
    orm: str | None = None,
    uv_map: str | None = None,
    mapping: dict | None = None,
    remove: list[str] | None = None,
    on_conflict: Literal["error", "replace"] = "error",
) -> dict:
    return {
        "result": await bridge_result(
            ctx,
            "material.set_texture_set",
            name=name,
            maps=maps,
            orm=orm,
            uv_map=uv_map,
            mapping=mapping,
            remove=remove,
            on_conflict=on_conflict,
        )
    }
