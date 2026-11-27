# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `blender_mesh_inspect` reports raw and evaluated mesh counts, local and world bounds, material slots, vertex
  groups, modifiers, connected components and topology findings with sample element IDs, without changing the
  scene. Duplicate-vertex and per-region checks are opt-in, and meshes over `element_budget` fail with
  `budget_exceeded`. Also available as `mesh.inspect` in batches.
- Typed timeline and keyframe tools: `blender_timeline_get` / `blender_timeline_set` and
  `blender_keyframe_add` / `blender_keyframe_list` / `blender_keyframe_remove` over a small allowlist of
  object transforms (`location`, `rotation` in degrees, `scale`) with explicit interpolation modes,
  inserted-vs-overwritten reporting, and clear failures for absent objects/actions.
- Scene organization tools: `blender_collection_create` / `blender_collection_list` /
  `blender_collection_rename` / `blender_collection_add_object` / `blender_collection_remove_object` and
  `blender_object_rename` / `blender_object_parent` / `blender_object_unparent`, including keep-world-transform
  parenting, cycle detection, orphan re-linking, and canonical (collision-suffixed) name reporting.
- `blender_scene_list_objects` gained filters (`name` substring, `collection`, `visibility`) and pagination
  (`limit`, `offset`) with total-match counts; existing callers are unaffected.
- First-class camera and light tools: `blender_camera_create` / `blender_camera_update` (projection, focal
  length or orthographic scale, clipping ranges, rotation or look-at orientation, set active scene camera) and
  `blender_light_create` / `blender_light_update` (`POINT`, `SUN`, `SPOT`, `AREA` with color, energy and
  type-specific shape parameters). Parameters that do not apply to the chosen type return explicit errors.
- `blender_export_gltf` / `blender_export_obj` / `blender_export_fbx` accept `transport="headless"`, exporting
  a `.blend` file in a separate `blender -b` process without a live Blender session (same resolution rules as
  renders: absolute path returned, missing folders created, extensions appended only when absent).

### Fixed
- Rejected mutation requests no longer add undo entries, and the bridge also rejects oversized
  requests when their terminating newline has already arrived.
- Parenting and unparenting with `keep_transform=true` restore a copy of the world matrix after
  changing the parent, so moved children retain their world transform.
- `blender_render_still` / `blender_render_animation` failed with their default output path in an unsaved
  Blender file (`cannot save: 'render.png'`). `//` paths now resolve next to the `.blend` file, or to
  `<temp dir>/blender-mcp/` while the file is unsaved, on both transports.
- Render engine names work across Blender versions: `EEVEE`, `BLENDER_EEVEE` and `BLENDER_EEVEE_NEXT` all
  select EEVEE (its identifier differs between Blender 4.2–4.5 and other releases), `WORKBENCH` is accepted,
  and an unknown engine is reported with the available ones before anything renders.
- Exports accept `//` paths, create missing folders, and no longer turn `model.OBJ` into `model.OBJ.obj`.
- `blender_object_duplicate` failed on Empties (`'NoneType' object has no attribute 'copy'`).
- `blender_material_assign` on a camera, light or Empty now explains that the object cannot have materials.
- A failed `blender_material_set_texture` no longer leaves a stray Image Texture node in the material, and
  setting a texture again reuses the linked node instead of stacking a new one each time.
- Script files are read as UTF-8 by the add-on regardless of the platform's default encoding.

### Changed
- Replaced the add-on entrypoint and monolithic command handler with feature modules, an explicit
  runtime, and a single command registry for validation, undo, and worker-thread dispatch.
- Moved MCP tool definitions into feature modules while preserving all 44 tool names and schemas;
  organized add-on and server tests by feature.
- Moved runnable scenes and workflow recipes into `examples/demos/` and `examples/library/`.
  Saved script paths and approved roots must use the new locations.
- Tree generation, object scattering, and emissive material creation are example scripts executed
  through `blender_python_exec`; their dedicated MCP tools and bridge commands were removed.
- Split TCP transport, headless script templates, and primitive geometry into focused core modules.
- Render and export tools return the absolute path that was written.
- Clearer errors when Blender is not running (`Cannot reach Blender at host:port …`) and when the headless
  transport cannot find the Blender executable (points at `BLENDER_BIN`).

## [0.2.0] — 2026-09-23

### Added
- `scripts/setup.sh`: one-command setup on macOS and Linux (venv, add-on install as a Blender 4.2+
  extension or legacy add-on, replacing old copies; optional `--register claude,codex,claude-desktop`).
- `scripts/start.sh claude|codex|none`: opens Blender with the bridge and launches the client already
  connected to it (MCP server passed on the command line, no client config changes); `scripts/stop.sh`.
- `docs/demos/`: three demos recorded end to end with Claude Code and Codex against a live Blender
  (prompt, tool calls, agent reply, render and Blender screenshot), re-recordable with
  `scripts/record_demos.sh`.
- Plain Blender Python scripts for each demo and `scripts/run_demo.sh` to run them without an AI
  (GUI, background, or through the bridge).
- The add-on honours `BLENDER_MCP_PORT`, so one variable sets the port for both sides.

### Removed
- `scripts/server_start.sh` and `scripts/launch_blender_gui.py` (superseded by `setup.sh` / `start.sh`).

### Security
- The bridge now requires a shared-secret token on every request. The add-on creates
  `~/.blender-mcp/token` (mode 0600); the server and helper scripts read it
  (`BLENDER_MCP_TOKEN` / `BLENDER_MCP_TOKEN_FILE` override). **Update the add-on and server together.**
- Any malformed line now closes the bridge connection, blocking cross-protocol requests
  (e.g. a web page POSTing a JSON command to `localhost:9876`).
- Safe Mode path checks resolve symlinks and no longer accept sibling directories that share a prefix.
- Safe Mode now disables inline code. With no approved roots and an unsaved `.blend`, script and
  Safe Mode paths are refused instead of falling back to the working directory.
- Added the **Allowed Commands** preference (the previously documented tool whitelist was never wired up).
- Docs now describe the module blocklist accurately (it is not a sandbox; `shutil` was never blocked).
- `BLENDER_MCP_HEADLESS=0` disables the headless transport.

### Fixed
- Request timeouts now raise `TimeoutError` instead of being reported as a lost connection on
  Python 3.11+, where `asyncio.TimeoutError` is a subclass of `OSError`.
- `blender_material_set_color` and `blender_material_set_texture` always failed validation.
- Bridge responses larger than 64 KiB failed; the client stream limit is now 32 MiB.
- Responses are matched by request `id`, and the connection is reset after a cancelled or timed-out
  request so a late reply can no longer be returned to the next tool call.
- `SystemExit`/`KeyboardInterrupt` in a script no longer hang the bridge or stop its request timer.
- Script timeouts and cancellation can no longer be swallowed by `except Exception:`.
- `job.status`/`job.cancel`/`job.list` no longer wait behind a running async job, so cancelling
  a running bridge job works.
- Headless jobs that fail to start (bad `BLENDER_BIN`, missing code) are marked `failed` instead of
  staying `running`; invalid requests are rejected before a job is created.
- Headless cancellation kills Blender and propagates; headless runs default to a 3600 s timeout
  (`BLENDER_MCP_HEADLESS_TIMEOUT`); `sys.exit()` in headless scripts still returns a result payload.
- Changing the add-on's Port preference rebinds the bridge.
- `object.translate` rejects `location` and `offset` together; colors accept RGBA; non-finite numbers are rejected.
- Finished jobs are pruned (100 kept) in both job managers; oversized bridge requests are rejected.

### Changed
- Server host/port are configurable via `BLENDER_MCP_HOST`/`BLENDER_MCP_PORT`, plus an optional
  `BLENDER_MCP_TIMEOUT`.
- `transport` is a `"bridge" | "headless"` enum in tool schemas.
- Requires `mcp>=1.2.0,<2` (FastMCP was added in 1.2.0); dropped the unused `pydantic` dependency.
- Add-on ships a `blender_manifest.toml` (Blender 4.2+ extension) and its version matches the package.
- Docker image runs as a non-root user and documents host networking and token mounting.

### CI
- The add-on test suite, mypy checks for the add-on, and add-on coverage now run in CI.
- New end-to-end job runs the bridge and headless transports against a real Blender.
- The publish workflow runs once per GitHub release, grants `id-token` only to the publish job,
  pins actions by SHA, and attaches the add-on zip to the release.

## [0.1.3] — 2026-06-21

### Fixed
- Packaged `models.py` in the Blender add-on zip.
- Removed the Blender add-on's runtime dependency on third-party validation packages.
- Switched the add-on model import to package-relative import for installed zip compatibility.

## [0.1.2] — 2026-06-21

### Added
- CI pipeline (`ci.yml`): ruff lint, ruff format, mypy, pytest with coverage across Python 3.10–3.13.
- Publish workflow now gates on CI passing before releasing to PyPI.
- Ruff configuration (pycodestyle, pyflakes, isort, pep8-naming, pyupgrade, bugbear, simplify, type-checking).
- Mypy configuration with `check_untyped_defs` and `ignore_missing_imports`.
- pytest-cov integration with 50 % minimum coverage threshold.
- `CONTRIBUTING.md` with development workflow, code style, and PR guidelines.
- This `CHANGELOG.md`.
- Runtime validation models for all bridge command parameters (`addon/models.py`).
- `Dockerfile` and `.dockerignore` for containerized deployment.
- Explicit `pydantic>=2.0` dependency (removed again in the next release; it was unused).

### Fixed
- Import sorting and formatting across all source files.
- Ambiguous variable names flagged by ruff (`l` → `line`, `label`).
- Replaced bare `try/except pass` with `contextlib.suppress` in headless executor.
- Kept the Blender bridge request queue timer alive across `.blend` file loads.

## [0.1.1] — 2026-03-08

### Fixed
- Blender bridge execution reliability.
- Documented Codex CLI setup in README.

## [0.1.0] — 2026-02-28

### Added
- Initial MCP server with 27 tools across 7 namespaces: scene inspection,
  object mutation, materials, rendering & export, history, and Python execution.
- Blender add-on with TCP bridge server, command handler, and job manager.
- Headless Blender execution transport (`blender -b --python`).
- Async job system (create, poll, cancel, list) for long-running scripts.
- Safety model: module blocklist, output bounding, cooperative timeouts,
  script path validation, optional tool whitelist.
- Automatic undo for mutation commands.
- Script library with 11 reusable Blender scripts.
- Demo scenes (dam-break simulation, pipe studies).
- PyPI packaging with OIDC-based GitHub Actions publishing.
- Architecture documentation and Python execution design spec.
- Unit tests for MCP server and add-on (mocked `bpy`).

[Unreleased]: https://github.com/djeada/blender-mcp-server/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/djeada/blender-mcp-server/compare/v0.1.3...v0.2.0
[0.1.3]: https://github.com/djeada/blender-mcp-server/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/djeada/blender-mcp-server/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/djeada/blender-mcp-server/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/djeada/blender-mcp-server/releases/tag/v0.1.0
