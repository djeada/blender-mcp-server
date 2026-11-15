# Examples

Optional scene builders and workflow recipes live here. The MCP server and Blender
add-on provide general operations and Python execution; they do not import these scripts.

- [`library/`](library/README.md) contains parameterized scripts for trees, scattering,
  emissive materials, cameras, animation, collections, and physics setup.
- [`demos/`](demos/README.md) contains complete scenes, including still life, a procedural
  city, a bouncing ball, dam breaks, and pipe simulations.
- [`docs/demos/`](../docs/demos/README.md) contains recorded prompts and results.

## Run a recipe

Pass an absolute script path and an `args` dictionary to `blender_python_exec`:

```json
{
  "script_path": "/path/to/blender-mcp-server/examples/library/create_tree.py",
  "args": {"name": "Oak", "height": 3.0, "seed": 7}
}
```

The script sets `__result__`, returned under the execution response's `result` field.
For the live bridge, add the repository's `examples/` directory to **Approved Script Roots**
in the add-on preferences. Alternatively, send the file contents as `code` when inline
execution is enabled. See each script's docstring for its parameters.

To scatter the tree, run `library/scatter_objects.py` with
`{"source": "Oak", "count": 20, "radius": 8.0, "seed": 7}`. Run
`library/create_emissive_material.py` with `{"name": "Glow", "emission_strength": 8}`
to create an emissive material, then assign it with `blender_material_assign`.

These three recipes also support `transport="headless"`. A headless call starts a new
Blender process; use `blend_file` to load an existing scene and save it within the script
when changes should persist. `create_mesh.py` uses the live bridge's injected
`mcp_create_mesh` helper.

## Run a complete demo

From the repository root:

```bash
scripts/run_demo.sh 1                       # Still life in the Blender GUI
scripts/run_demo.sh --background 2          # Render a procedural city
scripts/run_demo.sh --bridge 3 --no-render  # Animate in an existing bridge session
python3 examples/demos/run_dam_break.py --dry-run
```

The numbered demos also run directly with `blender --python examples/demos/<script>.py`.
Their output defaults to `/tmp/blender-mcp-demos/`.

## Migrating from the old layout

`scripts/library/` moved to `examples/library/`. Scene scripts from `scripts/demos/`
and `docs/demos/scripts/` moved to `examples/demos/`. Update saved `script_path` values
and approved roots accordingly; `scripts/run_demo.sh` still accepts the same demo numbers.

The former `blender_object_create_tree`, `blender_object_scatter`, and
`blender_material_create_emissive` tools are now the recipes above, executed through
`blender_python_exec`.
