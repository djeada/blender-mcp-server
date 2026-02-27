# Blender MCP Server

An MCP server that enables AI assistants to control Blender.

## Architecture

See [docs/architecture.md](docs/architecture.md) for details.

**Components:**
- **External MCP Server** — Python process using the MCP SDK (stdio transport)
- **Blender Add-on** — Runs inside Blender, exposes a TCP socket for commands

## Quick Start

### 1. Install the Blender Add-on

1. Open Blender → Edit → Preferences → Add-ons → Install
2. Select the `addon/` folder
3. Enable "Blender MCP Bridge"

### 2. Configure Claude Desktop

Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "blender": {
      "command": "uvx",
      "args": ["blender-mcp-server"]
    }
  }
}
```

### 3. Use It

With Blender running and the add-on enabled, start a conversation in Claude Desktop and ask it to interact with your Blender scene.

## Development

```bash
# Install in dev mode
pip install -e .

# Run the MCP server directly
blender-mcp-server
```
