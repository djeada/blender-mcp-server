"""Smoke-test an installed wheel: packaged data must load without the source checkout.

Usage (with the wheel installed in the interpreter that runs this): python scripts/check_wheel.py
"""

import sys
from pathlib import Path

from blender_mcp_server import knowledge, recipes
from blender_mcp_server.server import mcp
from blender_mcp_server.shared import ADDON_PATH

REPOSITORY = Path(__file__).resolve().parents[1]


def main() -> int:
    installed = Path(knowledge.__file__).resolve()
    if installed.is_relative_to(REPOSITORY / "src"):
        print("Install the wheel first; this imported the source checkout.", file=sys.stderr)
        return 1
    guides = knowledge.guides()
    for flow in knowledge.workflows()["workflows"]:
        for stage in flow["stages"]:
            for link in stage["guides"]:
                guide, section = link.split("#")
                assert guides[guide].sections[section].text
    for recipe in recipes.catalog().values():
        assert recipe.path.is_relative_to(installed.parent.parent), recipe.path
        compile(recipe.source(), recipe.file, "exec")
        recipe.arguments(recipe.examples[0])
    assert (ADDON_PATH / "mesh.py").is_file()
    print(
        f"OK: {len(guides)} guides, {len(recipes.catalog())} recipes and {len(mcp._tool_manager._tools)} tools "
        f"load from {installed.parent.parent}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
