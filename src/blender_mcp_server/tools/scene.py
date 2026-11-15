"""MCP tools for scene."""

from typing import Any

from mcp.server.fastmcp import Context
from typing_extensions import NotRequired, TypedDict

from blender_mcp_server.app import bridge, bridge_result, mcp


@mcp.tool(
    name="blender_scene_get_info",
    description="Get information about the current Blender scene including name, frame range, render engine, resolution, and object count.",
)
async def scene_get_info(ctx: Context) -> str:
    return await bridge(ctx, "scene.get_info")


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
    return await bridge(
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
    name="blender_collection_create",
    description="Create a collection. Optionally link it under an existing parent collection (otherwise at scene root).",
)
async def collection_create(ctx: Context, name: str, parent: str | None = None) -> str:
    return await bridge(ctx, "collection.create", name=name, parent=parent)


@mcp.tool(
    name="blender_collection_list",
    description="List all collections with their object counts.",
)
async def collection_list(ctx: Context) -> str:
    return await bridge(ctx, "collection.list")


@mcp.tool(
    name="blender_collection_rename",
    description=(
        "Rename a collection. Blender appends a .001 suffix when the requested name is taken; "
        "the returned 'name' is the canonical one."
    ),
)
async def collection_rename(ctx: Context, name: str, new_name: str) -> str:
    return await bridge(ctx, "collection.rename", name=name, new_name=new_name)


@mcp.tool(
    name="blender_collection_add_object",
    description=(
        "Add an object to a collection, moving it out of its current collection(s). Returns whether it moved "
        "and the collections it left."
    ),
)
async def collection_add_object(ctx: Context, collection: str, object: str) -> str:
    return await bridge(ctx, "collection.add_object", collection=collection, object=object)


@mcp.tool(
    name="blender_collection_remove_object",
    description=(
        "Remove an object from a collection. If the object would be left unlinked, it is re-linked to the "
        "scene root collection so it stays part of the scene."
    ),
)
async def collection_remove_object(ctx: Context, collection: str, object: str) -> str:
    return await bridge(ctx, "collection.remove_object", collection=collection, object=object)


class BatchStep(TypedDict):
    command: str
    params: NotRequired[dict[str, Any]]


@mcp.tool(
    name="blender_scene_execute_batch",
    description="Run up to 32 ordered scene commands and report each step. Successful changes persist on failure.",
)
async def scene_execute_batch(ctx: Context, commands: list[BatchStep], stop_on_error: bool = True) -> dict:
    return {"result": await bridge_result(ctx, "scene.execute_batch", commands=commands, stop_on_error=stop_on_error)}
