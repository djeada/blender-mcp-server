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
| `blender.python.*` | Execute Python scripts (sync and async) |
| `blender.job.*` | Query, cancel, and list async jobs |

## Python Script Execution

The `python.*` commands let MCP clients execute arbitrary Blender Python code
through the bridge. This is the primary extension point for advanced workflows
that go beyond the predefined tool set.

### Command Flow — `python.execute` (synchronous)

```
MCP Client                MCP Server             Blender Add-on
    │                         │                        │
    │  blender_python_exec    │                        │
    │  {code, args}           │                        │
    │────────────────────────►│                        │
    │                         │  python.execute        │
    │                         │  {code, args, timeout} │
    │                         │───────────────────────►│
    │                         │                        │ validate safety
    │                         │                        │ exec(code, namespace)
    │                         │                        │ capture stdout/stderr
    │                         │                        │◄─── __result__
    │                         │  {success, result,     │
    │                         │   stdout, stderr,      │
    │                         │   duration_seconds}    │
    │                         │◄───────────────────────│
    │  tool response          │                        │
    │◄────────────────────────│                        │
```

### Command Flow — `python.execute_async` (long-running jobs)

```
MCP Client                MCP Server             Blender Add-on
    │                         │                        │
    │  blender_python_exec    │                        │
    │  _async {code}          │                        │
    │────────────────────────►│  python.execute_async  │
    │                         │───────────────────────►│
    │                         │                        │ create job, enqueue
    │                         │  {job_id}              │
    │                         │◄───────────────────────│
    │  {job_id}               │                        │
    │◄────────────────────────│                        │
    │                         │                        │ timer fires → exec
    │  blender_job_status     │                        │
    │  {job_id}               │                        │
    │────────────────────────►│  job.status            │
    │                         │───────────────────────►│
    │                         │  {status:"running"}    │
    │                         │◄───────────────────────│
    │  {status:"running"}     │                        │
    │◄────────────────────────│                        │
    │          ...            │         ...            │ job completes
    │  blender_job_status     │                        │
    │────────────────────────►│  job.status            │
    │                         │───────────────────────►│
    │                         │  {status:"succeeded",  │
    │                         │   result, stdout,      │
    │                         │   stderr}              │
    │                         │◄───────────────────────│
    │  final result           │                        │
    │◄────────────────────────│                        │
```

### Job Lifecycle State Machine

```
                ┌──────────┐
       create ──►  queued  │
                └────┬─────┘
                     │ timer fires
                ┌────▼─────┐
                │ running  ├──── cancel ──► cancelled
                └────┬─────┘
                     │
              ┌──────┴──────┐
              │             │
         ┌────▼────┐  ┌────▼────┐
         │succeeded│  │ failed  │
         └─────────┘  └─────────┘
```

### Safety Model

Script execution runs with a pragmatic local trust model:

1. **Script path restriction** — `script_path` must be under an explicitly
   configured project root (add-on preference `approved_script_roots`).
   Symlinks are resolved before checking.
2. **Inline code toggle** — `allow_inline_code` preference (default: on). When
   off, only file-based execution is allowed.
3. **Module blocklist** — A lightweight import hook blocks `subprocess`,
   `shutil`, `socket`, `ctypes`, and other dangerous modules during execution.
4. **Timeout** — Per-request timeout (default 30s sync, 300s async).
5. **Output bounding** — stdout/stderr are capped at 50 KB to prevent
   memory exhaustion.

This is not a sandbox. It is an explicit, auditable policy suitable for local
desktop automation. See `docs/python-execute-design.md` for the full design.

### Execution Logging & Audit Trail

Every script execution is logged with:

- **Request ID** — unique identifier (`exec-<uuid4>` for sync, `job-<uuid4>`
  for async)
- **Source** — `inline` or the script file path (truncated in logs)
- **Duration** — wall-clock seconds
- **Status** — `ok`, `error`, `succeeded`, `failed`, `cancelled`
- **Error summary** — first line of traceback on failure

The add-on's UI panel shows the last execution status, making it visible inside
Blender for debugging.

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
