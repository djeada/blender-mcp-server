"""Blender MCP server package; tool registration is deferred until startup."""

__all__ = ["main"]


def main():
    from blender_mcp_server.server import main as run

    run()
