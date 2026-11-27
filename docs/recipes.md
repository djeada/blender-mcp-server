# Recipe catalog

Recipes are reviewed scripts that run by ID with checked arguments. They cover common jobs without adding one tool per script, and they ship inside the installed package, so clients do not need to know any file paths.

| Recipe | Does |
|---|---|
| `create-mesh` | Primitive mesh through the data API |
| `create-tree` | Seeded low-poly tree with two materials |
| `scatter-objects` | Seeded linked copies across a disk |
| `emissive-material` | Glowing Principled material |
| `setup-camera` | Create or place a camera |
| `rigid-body` | Rigid body physics |
| `physics-effector` | Fluid and collision obstacles |
| `apply-transforms` | Bake transforms into mesh data |

## Use

1. `blender_recipe_search(query="scatter rocks")` returns IDs and one-line descriptions, in pages.
2. `blender_recipe_get(recipe="scatter-objects")` returns the argument JSON schema with defaults, result fields, side effects, prerequisites, minimum Blender version and an example.
3. `blender_recipe_run(recipe="scatter-objects", arguments={"source": "Oak", "count": 12})` runs it and returns `result`.

These tools form the `recipes` group. The `full` profile advertises them; other profiles reach them through [discovery](profiles.md#use-actions-that-are-not-advertised). `transport="headless"` with `blend_file` runs a recipe in background Blender. As with other headless scripts, changes are not saved unless you save them.

## Safety

A recipe is Python running in Blender, so it **needs the same permission as Python execution**: `allow_python` and, if `allowed_commands` is set, `python.execute`. The catalog grants nothing extra.

- Arguments are checked against the recipe's schema before anything is sent to Blender. Unknown names and non-finite numbers are rejected.
- IDs are looked up in the packaged manifest. No part of a request becomes a file path, and no recipe takes a path argument.
- Recipes are normally sent as inline code. If the policy or Blender preferences forbid inline code, the server sends the installed script's path instead, and Blender runs it only if its folder is in the approved script roots. `blender_recipe_get` reports that folder as `script_root_to_approve` when the shared policy forbids inline code. Approving it requires Blender and the server to see the same files.
- A failed recipe may have made part of its changes. Scripts add no undo step, so inspect the scene before retrying.

To let a client run recipes but not arbitrary scripts through this server, use `--allow-groups` with `recipes` and without `scripting`. The shared policy must still allow Python execution.

Your own scripts are unaffected: run them with `blender_python_exec` and `script_path` as before.

## Add a recipe

Add a reviewed script to `examples/library/` that reads `args` and sets `__result__`. Then add an entry to `src/blender_mcp_server/recipes.json` and list the script under `only-include` in `pyproject.toml`; the script is not copied anywhere else. Leave out scripts that write to caller-chosen paths. Tests validate the manifest and packaging, and the integration suite must run every recipe and check its result against `output_schema`. Increase the recipe's `version` when its arguments, result or behaviour change.

Scripts in the library that are not in the catalog either write to arbitrary paths (`save_blend.py`, and the fluid cache path in `fluid_domain.py`; use `blender_project_save` to save), set up fluids that can crash some Blender versions, or duplicate typed tools (frame range, keyframes and collections).
