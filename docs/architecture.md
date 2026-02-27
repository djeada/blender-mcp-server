# Blender MCP Server — Architecture

## Overview

The Blender MCP Server enables AI assistants (Claude Desktop, etc.) to control Blender through the **Model Context Protocol (MCP)**. It consists of two components that communicate over a local TCP socket.

## Components

```
┌─────────────────┐      stdio       ┌─────────────────────┐    JSON/TCP     ┌──────────────────┐
│  Claude Desktop  │ ◄──────────────► │  MCP Server (Python) │ ◄────────────► │  Blender Add-on  │
│  (MCP Client)    │                  │  server.py           │  localhost:9876 │  (bpy context)   │
└─────────────────┘                  └─────────────────────┘                 └──────────────────┘
```

### 1. External MCP Server (`src/blender_mcp_server/server.py`)

- Built with the official **MCP Python SDK** (`mcp`)
- Uses **stdio** transport (standard for Claude Desktop)
- Registers tools with proper names, descriptions, and JSON schemas
- On tool invocation: serializes the request as JSON, sends it to the Blender add-on via TCP, waits for a JSON response
- Handles errors, timeouts, and connection failures gracefully
- Includes structured logging

### 2. Blender Add-on (`addon/__init__.py`)

- Standard Blender add-on (register/unregister lifecycle)
- On enable: starts a **TCP socket server** on `localhost:9876`
- Listens for JSON command messages from the MCP server
- Executes commands in Blender's Python context (`bpy`)
- Returns structured JSON results
- On disable / Blender exit: gracefully shuts down the socket server

## Communication Protocol

### Request (MCP Server → Blender Add-on)
```json
{
  "id": "unique-request-id",
  "command": "scene.list_objects",
  "params": {}
}
```

### Response (Blender Add-on → MCP Server)
```json
{
  "id": "unique-request-id",
  "success": true,
  "result": { ... }
}
```

### Error Response
```json
{
  "id": "unique-request-id",
  "success": false,
  "error": "Object 'Cube' not found"
}
```

## Tool Namespaces

| Namespace | Description |
|---|---|
| `blender.scene.*` | Scene info, object listing |
| `blender.object.*` | Create, transform, delete objects |
| `blender.material.*` | Create, assign, modify materials |
| `blender.render.*` | Render stills and animations |
| `blender.export.*` | Export to glTF, OBJ, FBX |
| `blender.history.*` | Undo/redo operations |

## Lifecycle

1. User enables the Blender add-on → TCP server starts on `localhost:9876`
2. User starts the MCP server (via Claude Desktop config or manually)
3. MCP client sends tool calls → MCP server forwards to Blender → Blender executes → result flows back
4. On shutdown: MCP server closes TCP connection, Blender add-on stops TCP server

## Configuration

### Claude Desktop (`claude_desktop_config.json`)
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
