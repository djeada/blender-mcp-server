# Policy and recovery

The bridge accepts authenticated connections on `127.0.0.1`. Blender and your stdio server must agree on `BLENDER_MCP_PORT` and the credential in `BLENDER_MCP_TOKEN_FILE` (or `BLENDER_MCP_TOKEN`, which takes precedence). The default token path is `~/.blender-mcp/token`. The add-on creates a private token on POSIX with mode `0600`. Use the Windows installer for a private NTFS ACL. Keep the bridge and its token on a trusted host.

## Shared policy

Set `BLENDER_MCP_POLICY_FILE` to the same JSON configuration for the MCP process and Blender, then restart both. This example authorizes typed file operations under one directory. Substitute a real absolute path and escape Windows backslashes in JSON.

```json
{
  "transports": ["bridge", "headless"],
  "allow_python": false,
  "allowed_commands": ["scene.get_info", "project.get_info", "project.save", "render.still", "export.gltf"],
  "output_roots": ["/home/me/blender-work"],
  "queue_capacity": 16,
  "queue_timeout": 10,
  "command_timeout": 60,
  "long_timeout": 3600
}
```

Without a file, the bridge keeps its add-on preferences and existing Python workflow. With a file, Python and inline code both require opt-in via `allow_python` and `allow_inline_code`. `allowed_commands` takes bridge command names. Omit it to allow all commands permitted by the rest of the policy, or use an empty array to allow only authenticated status. `script_roots` authorizes Python script sources. `output_roots` governs typed file access, including project loads, textures, exports, and renders. Omitted roots use the saved project's directory on the bridge. Provide explicit output roots when loading a headless input project. An unsaved project needs explicit roots for restricted output.

File checks resolve symlinks before the operation. `//` resolves against the active .blend folder, and bare relative paths use the Blender process's working directory. Use absolute paths when the two processes have different working directories. The legacy bridge uses a temporary folder for `//` render and export paths in an unsaved session. With a restricted policy, supply an authorized absolute path until you save a project. Restricted renders disable compositing, since File Output nodes can write additional files. Checked render and export files are published from a temporary staging directory.

The default bridge limits are 16 queued commands, 10 seconds waiting to start, 60 seconds for an interactive command, and one hour for a render, export, or synchronous script response. The shared policy also accepts `max_script_seconds` (3600), `max_jobs` (8), `max_render_pixels` (33554432), and `max_render_frames` (2500). The bridge enforces its shorter synchronous script cap of 300 seconds. Render limits apply to each frame and the total requested frame range. The policy reports limits through `blender_status`.

## Headless migration and trusted Python

To keep using `transport="headless"`, set `transports` in the shared policy and grant only the commands you need. In a session that enables both transports, headless first checks a responsive and authenticated bridge with the same policy. Move local Safe Mode, inline-code, script-root, and command restrictions into the shared policy before using the mixed configuration. For a dedicated background worker, configure `"transports": ["headless"]`. `BLENDER_MCP_HEADLESS=0` disables headless even when the file enables it.

Headless Blender loads its input with automatic script execution disabled. Explicitly approved Python runs as the process user and can read files, modify Blender state, and use OS privileges. The import guard and time limits provide application-level controls. If you need isolation, run Blender and the MCP server under a separate OS account or container with dedicated project mounts and credentials. Keep approved script directories under the control of trusted users.

## Status, timeouts, and errors

Call `blender_status` to see the server and bridge versions, session generation, queue depth, oldest queued request age, active request, Blender version, effective bridge command list, and headless policy readiness. A successful bridge status passes through Blender's main-thread queue. When a queued command times out behind an active bridge command, the timeout can identify that command. Use `reconnect: true` to drop the current socket and explicitly check a new connection. Native render and Blender operator calls can outlive their response deadlines. Async Python jobs have a separate status and cancel API.

A queue timeout means the command did not start. Blender fails queued work when a project load changes the generation. The connection may drop during shutdown or a crash. An execution timeout or disconnect after sending a mutation can leave its outcome uncertain. Check status and inspect the scene or output before retrying. If the queue remains stalled, use the MCP panel to stop and start the bridge. The MCP client does not replay mutations automatically. Set `BLENDER_MCP_TIMEOUT` to override the MCP client's socket response budget. By default it includes the appropriate bridge queue and execution limits. `BLENDER_MCP_HEADLESS_TIMEOUT` sets the default headless process deadline within the shared maximum.

With MCP SDK 1.20 or later, clients receive `isError: true` plus `structuredContent.error` for tool failures. This response tells the client the command never started.

```json
{
  "code": "queue_timeout",
  "message": "Blender main thread did not start the request in time",
  "command": "object.create_mesh",
  "request_id": "0c40a9c4-6e94-4db2-b308-df9ee0396cef",
  "retryable": true,
  "details": {"started": false}
}
```

Other codes include `invalid_arguments`, `not_found`, `unsupported`, `permission_denied`, `policy_mismatch`, `busy`, `session_changed`, `execution_timeout`, `response_timeout`, `disconnected`, `response_too_large`, `budget_exceeded`, and `command_failed`. `retryable` refers to whether the command could be attempted after resolving the reported condition. Existing tools keep their JSON text success payloads. New project, batch and modifier tools return structured `result` payloads. `blender_status` returns diagnostics directly. TCP protocol 2 keeps the original `error` string and adds `error_details`. Legacy add-ons produce less specific errors, and shared policy requires a protocol 2 add-on.
