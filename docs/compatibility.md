# Blender compatibility

The integration suite uses a small generated scene. It checks authenticated TCP and MCP stdio calls, CRUD, Principled BSDF materials, modifier edits, render and export, save, repeated file loads, and packaged installation. The CI workflow downloads fixed Blender distributions and verifies their SHA-256 digests.

| Blender | Platform | Coverage |
|---|---|---|
| 3.6.23 LTS | Linux x86-64 | Integration suite and legacy add-on installation |
| 4.5.3 LTS | Linux x86-64 | Integration suite and extension installation |
| 5.0.0 | Linux x86-64 | Integration suite and extension installation |
| 4.5.3 LTS | Windows x86-64 | PowerShell setup, token ACL, extension installation, authenticated scene query |
| Other versions from 3.6 onward | Linux, macOS, Windows | Expected to work. Check the release manually before relying on a new combination. |
| Earlier than 3.6 | All | Unsupported |

Python package tests cover 3.10–3.13 on Linux. Blender uses the Python bundled in its distribution. Match the add-on and MCP server from the same release for typed tools and shared policy. A legacy client can use the original wire fields under the default policy. A new client can call original commands on a protocol 1 add-on, with generic legacy errors and no shared policy verification.

## Release checks

- Run the CI matrix and check the Blender version, test report, and bridge/installer logs uploaded for each job.
- On Windows x86-64, use native PowerShell on a clean profile. Run Setup, Start, and Status, then call `blender_scene_get_info` from an MCP client. Save a small project, open it twice, and use `blender_status` to confirm that the generation changed each time. Stop Blender and handle the save prompt if one appears. Repeat setup with a custom port and a path containing spaces.
- On macOS, repeat the equivalent quick start on a clean Blender profile. Exercise a render and an export through the bridge. Record the OS, architecture, Blender version, and client in the release check.
- On both platforms, try a restricted policy and confirm that an unapproved path and a disabled tool produce structured errors.

For a bug report, include the exact Blender version and OS, add-on and server versions from `blender_status`, a minimal scene or steps using the default cube, the tool arguments with private data removed, and the structured error code and request ID. On Linux, reproduce the automated suite with `BLENDER_BIN=/path/to/blender BLENDER_MCP_INTEGRATION=1 pytest tests/integration --no-cov`.
