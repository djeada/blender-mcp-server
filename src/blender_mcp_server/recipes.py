"""The catalog of reviewed recipe scripts shipped with the package.

A recipe is a script from `examples/library/` plus a manifest entry describing its
arguments, results and side effects. IDs are looked up in the manifest only; no part of
a request is ever turned into a file path.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from blender_mcp_server.shared import protocol

_PACKAGED = Path(__file__).with_name("_recipes")
# Editable installs read the scripts from the checkout, so there is one copy of each.
RECIPE_PATH = _PACKAGED if _PACKAGED.is_dir() else Path(__file__).resolve().parents[2] / "examples" / "library"
MANIFEST = Path(__file__).with_name("recipes.json")


@dataclass(frozen=True)
class Recipe:
    id: str
    version: int
    file: str
    category: str
    title: str
    description: str
    tags: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    blender_min: str
    side_effects: tuple[str, ...]
    prerequisites: tuple[str, ...]
    examples: tuple[dict[str, Any], ...]

    @property
    def path(self) -> Path:
        return RECIPE_PATH / self.file

    def source(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def arguments(self, supplied: dict[str, Any]) -> dict[str, Any]:
        """Validate arguments and fill in the manifest's defaults."""
        _require_finite(supplied)
        errors = sorted(Draft202012Validator(self.input_schema).iter_errors(supplied), key=lambda e: list(e.path))
        if errors:
            problems = "; ".join(
                f"{'.'.join(map(str, error.path)) or 'arguments'}: {error.message[:120]}" for error in errors[:5]
            )
            raise protocol.InvalidArgumentsError(f"Invalid arguments for recipe {self.id}. {problems}")
        defaults = {
            name: spec["default"] for name, spec in self.input_schema["properties"].items() if "default" in spec
        }
        return {**defaults, **supplied}


def _require_finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise protocol.InvalidArgumentsError("Recipe arguments must be finite JSON values")
    for item in value.values() if isinstance(value, dict) else value if isinstance(value, list) else ():
        _require_finite(item)


def _recipe(entry: dict[str, Any]) -> Recipe:
    fields: dict[str, Any] = {key: tuple(value) if isinstance(value, list) else value for key, value in entry.items()}
    return Recipe(**fields)


@cache
def catalog() -> dict[str, Recipe]:
    entries = json.loads(MANIFEST.read_text(encoding="utf-8"))["recipes"]
    return {entry["id"]: _recipe(entry) for entry in entries}


def get_recipe(recipe_id: str) -> Recipe:
    recipe = catalog().get(recipe_id)
    if recipe is None:
        raise protocol.BridgeError("not_found", "Unknown recipe; use blender_recipe_search to find recipe IDs")
    return recipe
