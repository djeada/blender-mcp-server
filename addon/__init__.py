bl_info = {
    "name": "Blender MCP Bridge",
    "author": "Adam Djellouli",
    "version": (0, 2, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "TCP bridge for MCP server to control Blender",
    "category": "Development",
}


from .ui import register, unregister

BRIDGE_API_VERSION = 1

__all__ = ["register", "unregister"]
