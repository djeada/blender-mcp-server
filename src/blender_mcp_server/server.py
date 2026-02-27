"""Blender MCP Server — External MCP server that bridges Claude Desktop to Blender."""

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

BLENDER_HOST = "127.0.0.1"
BLENDER_PORT = 9876


class BlenderConnection:
    """Async TCP client that communicates with the Blender add-on."""

    def __init__(self, host: str = BLENDER_HOST, port: int = BLENDER_PORT):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        logger.info(f"Connected to Blender at {self.host}:{self.port}")

    async def disconnect(self):
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

    async def send_command(self, command: str, params: dict | None = None) -> Any:
        """Send a command to Blender and return the result."""
        if not self._writer:
            await self.connect()

        request = {
            "id": str(uuid.uuid4()),
            "command": command,
            "params": params or {},
        }

        async with self._lock:
            try:
                self._writer.write(json.dumps(request).encode() + b"\n")
                await self._writer.drain()

                line = await self._reader.readline()
                if not line:
                    raise ConnectionError("Blender connection closed")

                response = json.loads(line)
                if not response.get("success"):
                    raise RuntimeError(response.get("error", "Unknown error from Blender"))
                return response.get("result")
            except (ConnectionError, OSError) as e:
                # Connection lost — reset and re-raise
                self._writer = None
                self._reader = None
                raise ConnectionError(f"Lost connection to Blender: {e}") from e


@asynccontextmanager
async def blender_lifespan(server: FastMCP):
    """Manage the Blender connection lifecycle."""
    conn = BlenderConnection()
    try:
        await conn.connect()
    except OSError:
        logger.warning("Could not connect to Blender on startup. Will retry on first tool call.")
    yield conn
    await conn.disconnect()


mcp = FastMCP(
    "Blender MCP Server",
    lifespan=blender_lifespan,
    log_level="INFO",
)


def _get_conn(ctx) -> BlenderConnection:
    return ctx.request_context.lifespan_context


# -- Scene tools --

@mcp.tool(
    name="blender_scene_get_info",
    description="Get information about the current Blender scene including name, frame range, render engine, resolution, and object count.",
)
async def scene_get_info(ctx: Any) -> str:
    result = await _get_conn(ctx).send_command("scene.get_info")
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_scene_list_objects",
    description="List all objects in the current Blender scene. Optionally filter by type (MESH, CAMERA, LIGHT, EMPTY, CURVE, etc.).",
)
async def scene_list_objects(ctx: Any, type: str | None = None) -> str:
    params = {}
    if type:
        params["type"] = type
    result = await _get_conn(ctx).send_command("scene.list_objects", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_object_get_transform",
    description="Get the position, rotation, and scale of a Blender object by name.",
)
async def object_get_transform(ctx: Any, name: str) -> str:
    result = await _get_conn(ctx).send_command("object.get_transform", {"name": name})
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_object_get_hierarchy",
    description="Get the parent/child hierarchy of objects. If name is provided, returns the subtree for that object. Otherwise returns the full scene hierarchy.",
)
async def object_get_hierarchy(ctx: Any, name: str | None = None) -> str:
    params = {}
    if name:
        params["name"] = name
    result = await _get_conn(ctx).send_command("object.get_hierarchy", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_material_list",
    description="List all materials in the Blender file.",
)
async def material_list(ctx: Any) -> str:
    result = await _get_conn(ctx).send_command("material.list")
    return json.dumps(result, indent=2)


# -- Object mutation tools --

@mcp.tool(
    name="blender_object_create",
    description="Create a new mesh object in Blender. Supported types: cube, sphere, cylinder, plane, cone, torus.",
)
async def object_create(
    ctx: Any,
    mesh_type: str = "cube",
    name: str | None = None,
    location: list[float] | None = None,
    size: float = 2.0,
) -> str:
    params: dict[str, Any] = {"type": mesh_type, "size": size}
    if name:
        params["name"] = name
    if location:
        params["location"] = location
    result = await _get_conn(ctx).send_command("object.create_mesh", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_object_delete",
    description="Delete an object from the Blender scene by name.",
)
async def object_delete(ctx: Any, name: str) -> str:
    result = await _get_conn(ctx).send_command("object.delete", {"name": name})
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_object_translate",
    description="Move an object. Provide either 'location' for absolute positioning or 'offset' for relative movement.",
)
async def object_translate(
    ctx: Any,
    name: str,
    location: list[float] | None = None,
    offset: list[float] | None = None,
) -> str:
    params: dict[str, Any] = {"name": name}
    if location:
        params["location"] = location
    if offset:
        params["offset"] = offset
    result = await _get_conn(ctx).send_command("object.translate", params)
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_object_rotate",
    description="Set the rotation of an object. Provide rotation as [x, y, z] angles. By default angles are in degrees.",
)
async def object_rotate(
    ctx: Any,
    name: str,
    rotation: list[float],
    degrees: bool = True,
) -> str:
    result = await _get_conn(ctx).send_command(
        "object.rotate", {"name": name, "rotation": rotation, "degrees": degrees}
    )
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_object_scale",
    description="Set the scale of an object. Provide scale as [x, y, z].",
)
async def object_scale(ctx: Any, name: str, scale: list[float]) -> str:
    result = await _get_conn(ctx).send_command("object.scale", {"name": name, "scale": scale})
    return json.dumps(result, indent=2)


@mcp.tool(
    name="blender_object_duplicate",
    description="Duplicate an object in the Blender scene. Optionally provide a new name.",
)
async def object_duplicate(ctx: Any, name: str, new_name: str | None = None) -> str:
    params: dict[str, Any] = {"name": name}
    if new_name:
        params["new_name"] = new_name
    result = await _get_conn(ctx).send_command("object.duplicate", params)
    return json.dumps(result, indent=2)


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
