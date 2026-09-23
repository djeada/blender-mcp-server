# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
