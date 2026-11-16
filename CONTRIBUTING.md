# Contributing to blender-mcp-server

Thanks for your interest in contributing! This document explains how to get
started, what we expect from pull requests, and how the project is organised.

## Quick Start

```bash
git clone https://github.com/djeada/blender-mcp-server.git
cd blender-mcp-server
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Development Workflow

### 1. Create a Branch

```bash
git checkout -b your-feature-name
```

### 2. Make Changes

The project has two main components:

| Component | Location | Runs inside |
|-----------|----------|-------------|
| MCP server | `src/blender_mcp_server/` | Standalone Python process (stdio) |
| Blender add-on | `addon/` | Blender's embedded Python (`bpy`) |

Scripts in `examples/library/` and `examples/demos/` run inside Blender via
`python.execute` and may reference `bpy`, `args`, or `mathutils` at module
level — this is expected.

### 3. Lint and Format

```bash
ruff check src/ addon/ tests/ scripts/ examples/
ruff format --check src/ addon/ tests/ scripts/ examples/
mypy src/ addon/
```

All three commands must pass with zero errors. CI will reject PRs that fail.
Shell scripts are checked with `shellcheck -x -P scripts scripts/*.sh`; keep them bash 3.2 compatible (macOS).

### 4. Run Tests

```bash
pytest -v                          # Server + add-on unit tests (mocked bpy, no Blender required)
BLENDER_MCP_INTEGRATION=1 pytest tests/integration -v --no-cov   # End-to-end against a real Blender
```

Coverage (server and add-on) is collected automatically; the minimum threshold is 70 %.
CI runs the unit tests on Python 3.10–3.13 and uses pinned Blender builds for the [integration matrix](docs/compatibility.md).

### 5. Commit and Push

Write clear commit messages. One logical change per commit.

```bash
git push origin your-feature-name
```

### 6. Open a Pull Request

- Fill in a description of **what** changed and **why**.
- Link any related issues.
- CI must pass before merge.

## Code Style

- **Formatter/Linter**: [Ruff](https://docs.astral.sh/ruff/) — configured in `pyproject.toml`.
- **Type checker**: [mypy](https://mypy-lang.org/) — `ignore_missing_imports = true` for `bpy`.
- **Line length**: 120 characters.
- **Imports**: sorted by `isort` rules via Ruff.
- **Python version**: 3.10+ (use `X | Y` unions, not `Optional[X]`).

## Project Layout

```
blender-mcp-server/
├── addon/                        # Blender add-on (TCP server + handlers)
├── src/blender_mcp_server/       # MCP server (stdio + tool definitions)
├── scripts/                     # Installation, launch, packaging, and bridge helpers
├── examples/
│   ├── library/                  # Optional Blender workflow and generation recipes
│   └── demos/                    # Runnable scenes, animation, and physics demos
├── tests/                        # Unit tests (no Blender install required)
├── docs/                         # Architecture & design documentation
└── pyproject.toml                # Build, lint, test, and type-check config
```

## Adding a New MCP Tool

Keep core tools general-purpose: scene inspection, primitive operations, materials,
rendering, exports, script execution, and jobs. Put scene generators, asset recipes
(such as trees), scattering, and specialized physics workflows in `examples/`.
These scripts use the existing Python execution tools and should not require new
bridge commands, validators, or MCP registrations.

1. Add a handler function to the appropriate feature module in `addon/`, such as
   `camera.py`, `animation.py`, or `objects.py`.
2. Add its parameter validator in `addon/models.py`, then register one `Command`
   in `addon/commands.py`. This record owns the handler, validator, undo flag, and
   worker-thread eligibility. Only job queries/cancellation may run off the main thread.
3. Add the MCP function with `@mcp.tool(...)` to the corresponding module in
   `src/blender_mcp_server/tools/`, then export it from `server.py`.
4. Add tests under `tests/addon/` and `tests/server/`. Extend
   `TestServerAddonContract.CALLS` in `tests/addon/test_contract.py` so the tool's
   parameters are checked against the add-on validator.
5. Document the tool in `README.md` under the appropriate namespace.

Keep runtime state in `BridgeRuntime` and its settings, executor, and job manager.
Feature handlers should not import the entrypoint, transport, or UI. Tests load a
fresh add-on package with mocked Blender modules for each case; avoid sharing
mutable mocks or settings between tests.

## Reporting Issues

- Use [GitHub Issues](https://github.com/djeada/blender-mcp-server/issues).
- Include: Blender version, Python version, OS, steps to reproduce, and error output.

## License

By contributing you agree that your contributions will be licensed under the
[MIT License](LICENSE).
