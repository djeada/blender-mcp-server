"""Small standard-library validators for bridge command parameters.

Blender add-ons run inside Blender's bundled Python, so they cannot assume
third-party packages are installed. These classes intentionally expose the
tiny validation API used by the command handler:
``model_validate(params).model_dump(exclude_none=True)``.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

MISSING = object()


class BridgeParams:
    fields: dict[str, dict[str, Any]] = {}

    def __init__(self, values: dict[str, Any]):
        self._values = values

    @classmethod
    def model_validate(cls, params: dict | None):
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise ValueError(f"{cls.__name__} parameters must be an object")

        values: dict[str, Any] = {}
        for name, spec in cls.fields.items():
            value = params.get(name, MISSING)
            if value is MISSING:
                if spec.get("required", False):
                    raise ValueError(f"Missing required parameter: {name}")
                if "default_factory" in spec:
                    value = spec["default_factory"]()
                elif "default" in spec:
                    value = deepcopy(spec["default"])
                else:
                    value = None
            values[name] = cls._validate_field(name, value, spec)

        return cls(values)

    @staticmethod
    def _validate_field(name: str, value: Any, spec: dict[str, Any]) -> Any:
        if value is None:
            if spec.get("allow_none", False):
                return None
            raise ValueError(f"Parameter '{name}' is required")

        expected = spec.get("type")
        if expected == "str" and not isinstance(value, str):
            raise ValueError(f"Parameter '{name}' must be a string")
        if expected == "bool" and not isinstance(value, bool):
            raise ValueError(f"Parameter '{name}' must be a boolean")
        if expected == "dict" and not isinstance(value, dict):
            raise ValueError(f"Parameter '{name}' must be an object")
        if expected == "int" and (not isinstance(value, int) or isinstance(value, bool)):
            raise ValueError(f"Parameter '{name}' must be an integer")
        if expected == "float":
            if not _is_finite_number(value):
                raise ValueError(f"Parameter '{name}' must be a finite number")
            value = float(value)
        if expected == "number_list":
            if not isinstance(value, list):
                raise ValueError(f"Parameter '{name}' must be a list")
            min_length = spec.get("min_length")
            max_length = spec.get("max_length")
            if min_length is not None and len(value) < min_length:
                raise ValueError(f"Parameter '{name}' must have at least {min_length} items")
            if max_length is not None and len(value) > max_length:
                raise ValueError(f"Parameter '{name}' must have at most {max_length} items")
            if not all(_is_finite_number(item) for item in value):
                raise ValueError(f"Parameter '{name}' must contain only finite numbers")
            value = [float(item) for item in value]

        if spec.get("gt") is not None and value <= spec["gt"]:
            raise ValueError(f"Parameter '{name}' must be greater than {spec['gt']}")
        return value

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if exclude_none:
            return {key: value for key, value in self._values.items() if value is not None}
        return dict(self._values)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def field(
    field_type: str,
    default: Any = None,
    *,
    required: bool = False,
    allow_none: bool = False,
    default_factory=None,
    min_length: int | None = None,
    max_length: int | None = None,
    gt: float | int | None = None,
) -> dict[str, Any]:
    spec = {
        "type": field_type,
        "required": required,
        "allow_none": allow_none,
        "min_length": min_length,
        "max_length": max_length,
        "gt": gt,
    }
    if default_factory is not None:
        spec["default_factory"] = default_factory
    elif required:
        pass
    else:
        spec["default"] = default
    return spec


class SceneListObjectsParams(BridgeParams):
    fields = {"type": field("str", allow_none=True)}


class ObjectGetTransformParams(BridgeParams):
    fields = {"name": field("str", required=True)}


class ObjectGetHierarchyParams(BridgeParams):
    fields = {"name": field("str", allow_none=True)}


class ObjectCreateMeshParams(BridgeParams):
    fields = {
        "type": field("str", "cube"),
        "name": field("str", allow_none=True),
        "location": field("number_list", default_factory=lambda: [0, 0, 0], min_length=3, max_length=3),
        "size": field("float", 2.0, gt=0),
    }


class ObjectDeleteParams(BridgeParams):
    fields = {"name": field("str", required=True)}


class ObjectTranslateParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "location": field("number_list", allow_none=True, min_length=3, max_length=3),
        "offset": field("number_list", allow_none=True, min_length=3, max_length=3),
    }


class ObjectRotateParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "rotation": field("number_list", default_factory=lambda: [0, 0, 0], min_length=3, max_length=3),
        "degrees": field("bool", True),
    }


class ObjectScaleParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "scale": field("number_list", default_factory=lambda: [1, 1, 1], min_length=3, max_length=3),
    }


class ObjectDuplicateParams(BridgeParams):
    fields = {"name": field("str", required=True), "new_name": field("str", allow_none=True)}


class MaterialCreateParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "color": field("number_list", allow_none=True, min_length=3, max_length=4),
    }


class MaterialAssignParams(BridgeParams):
    fields = {"object": field("str", required=True), "material": field("str", required=True)}


class MaterialSetColorParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "color": field("number_list", required=True, min_length=3, max_length=4),
    }


class MaterialSetTextureParams(BridgeParams):
    fields = {"name": field("str", required=True), "filepath": field("str", required=True)}


class RenderStillParams(BridgeParams):
    fields = {
        "output_path": field("str", "//render.png"),
        "resolution_x": field("int", allow_none=True, gt=0),
        "resolution_y": field("int", allow_none=True, gt=0),
        "engine": field("str", allow_none=True),
    }


class RenderAnimationParams(BridgeParams):
    fields = {
        "output_path": field("str", "//render_"),
        "frame_start": field("int", allow_none=True),
        "frame_end": field("int", allow_none=True),
        "engine": field("str", allow_none=True),
    }


class ExportFileParams(BridgeParams):
    fields = {"filepath": field("str", required=True)}


class PythonExecuteParams(BridgeParams):
    fields = {
        "code": field("str", allow_none=True),
        "script_path": field("str", allow_none=True),
        "args": field("dict", allow_none=True),
        "timeout_seconds": field("float", allow_none=True, gt=0),
    }


class JobIdParams(BridgeParams):
    fields = {"job_id": field("str", required=True)}
