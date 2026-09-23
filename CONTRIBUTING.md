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

Scripts in `scripts/library/` and `scripts/demos/` run inside Blender via
`python.execute` and may reference `bpy`, `args`, or `mathutils` at module
level — this is expected.

### 3. Lint and Format

```bash
ruff check src/ addon/ tests/ scripts/ --exclude scripts/.venv
ruff format src/ addon/ tests/ scripts/ --exclude scripts/.venv
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
CI runs the unit tests on Python 3.10–3.13 and the integration tests against Ubuntu's Blender package.

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
├── scripts/
│   ├── library/                  # Reusable Blender scripts
│   └── demos/                    # End-to-end demo scenes
├── tests/                        # Unit tests (no Blender install required)
├── docs/                         # Architecture & design documentation
└── pyproject.toml                # Build, lint, test, and type-check config
```

## Adding a New MCP Tool

1. Add the bridge command handler in `addon/__init__.py` under `CommandHandler`.
2. Register the MCP tool in `src/blender_mcp_server/server.py` using `@mcp.tool(...)`.
3. Add a validator in `addon/models.py` and register it in `CommandHandler._VALIDATORS`.
4. Add tests in `tests/test_server.py` (tool registration) and `tests/test_addon.py`
   (handler logic), and add the tool to `TestServerAddonContract.CALLS` so the server's
   parameter names are checked against the add-on's validator.
5. Document the tool in `README.md` under the appropriate namespace.

## Reporting Issues

- Use [GitHub Issues](https://github.com/djeada/blender-mcp-server/issues).
- Include: Blender version, Python version, OS, steps to reproduce, and error output.

## License

By contributing you agree that your contributions will be licensed under the
[MIT License](LICENSE).
