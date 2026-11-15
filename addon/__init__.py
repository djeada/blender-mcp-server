from .protocol import ADDON_VERSION
from .protocol import PROTOCOL_VERSION as BRIDGE_API_VERSION

bl_info = {
    "name": "Blender MCP Bridge",
    "author": "Adam Djellouli",
    "version": ADDON_VERSION,
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "TCP bridge for MCP server to control Blender",
    "category": "Development",
}


def register():
    from .ui import register as register_ui

    register_ui()


def unregister():
    from .ui import unregister as unregister_ui

    unregister_ui()


__all__ = ["BRIDGE_API_VERSION", "register", "unregister"]
