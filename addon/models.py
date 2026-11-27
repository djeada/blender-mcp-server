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
        if expected == "list" and not isinstance(value, list):
            raise ValueError(f"Parameter '{name}' must be a list")
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
        if spec.get("ge") is not None and value < spec["ge"]:
            raise ValueError(f"Parameter '{name}' must be at least {spec['ge']}")
        if spec.get("le") is not None and value > spec["le"]:
            raise ValueError(f"Parameter '{name}' must be at most {spec['le']}")
        return value

    def model_dump(self, exclude_none: bool = False) -> dict[str, Any]:
        if exclude_none:
            return {key: value for key, value in self._values.items() if value is not None}
        return dict(self._values)


def _is_finite_number(value: Any) -> bool:
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


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
    ge: float | int | None = None,
    le: float | int | None = None,
) -> dict[str, Any]:
    spec = {
        "type": field_type,
        "required": required,
        "allow_none": allow_none,
        "min_length": min_length,
        "max_length": max_length,
        "gt": gt,
        "ge": ge,
        "le": le,
    }
    if default_factory is not None:
        spec["default_factory"] = default_factory
    elif required:
        pass
    else:
        spec["default"] = default
    return spec


class SceneListObjectsParams(BridgeParams):
    fields = {
        "type": field("str", allow_none=True),
        "name": field("str", allow_none=True),
        "collection": field("str", allow_none=True),
        "visible": field("bool", allow_none=True),
        "limit": field("int", allow_none=True, gt=0),
        "offset": field("int", allow_none=True, ge=0),
    }


class PageParams(BridgeParams):
    fields = {
        "limit": field("int", allow_none=True, gt=0),
        "offset": field("int", allow_none=True, ge=0),
    }


class ObjectGetTransformParams(BridgeParams):
    fields = {"name": field("str", required=True)}


class ObjectGetHierarchyParams(BridgeParams):
    fields = {
        "name": field("str", allow_none=True),
        "max_nodes": field("int", allow_none=True, gt=0),
        "max_depth": field("int", allow_none=True, ge=0),
        "offset": field("int", allow_none=True, ge=0),
    }


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


class CameraCreateParams(BridgeParams):
    fields = {
        "name": field("str", allow_none=True),
        "location": field("number_list", allow_none=True, min_length=3, max_length=3),
        "rotation": field("number_list", allow_none=True, min_length=3, max_length=3),
        "look_at": field("number_list", allow_none=True, min_length=3, max_length=3),
        "projection": field("str", allow_none=True),
        "lens": field("float", allow_none=True, gt=0),
        "ortho_scale": field("float", allow_none=True, gt=0),
        "clip_start": field("float", allow_none=True, gt=0),
        "clip_end": field("float", allow_none=True, gt=0),
        "set_active": field("bool", False),
    }


class CameraUpdateParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "location": field("number_list", allow_none=True, min_length=3, max_length=3),
        "rotation": field("number_list", allow_none=True, min_length=3, max_length=3),
        "look_at": field("number_list", allow_none=True, min_length=3, max_length=3),
        "projection": field("str", allow_none=True),
        "lens": field("float", allow_none=True, gt=0),
        "ortho_scale": field("float", allow_none=True, gt=0),
        "clip_start": field("float", allow_none=True, gt=0),
        "clip_end": field("float", allow_none=True, gt=0),
        "set_active": field("bool", False),
    }


class LightCreateParams(BridgeParams):
    fields = {
        "type": field("str", "POINT"),
        "name": field("str", allow_none=True),
        "location": field("number_list", allow_none=True, min_length=3, max_length=3),
        "rotation": field("number_list", allow_none=True, min_length=3, max_length=3),
        "look_at": field("number_list", allow_none=True, min_length=3, max_length=3),
        "color": field("number_list", allow_none=True, min_length=3, max_length=4),
        "energy": field("float", allow_none=True, gt=0),
        "size": field("float", allow_none=True, gt=0),
        "size_y": field("float", allow_none=True, gt=0),
        "angle": field("float", allow_none=True, gt=0),
        "spot_angle": field("float", allow_none=True, gt=0),
        "spot_blend": field("float", allow_none=True),
        "shape": field("str", allow_none=True),
        "temperature": field("float", allow_none=True, gt=0),
    }


class LightUpdateParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "type": field("str", allow_none=True),
        "location": field("number_list", allow_none=True, min_length=3, max_length=3),
        "rotation": field("number_list", allow_none=True, min_length=3, max_length=3),
        "look_at": field("number_list", allow_none=True, min_length=3, max_length=3),
        "color": field("number_list", allow_none=True, min_length=3, max_length=4),
        "energy": field("float", allow_none=True, gt=0),
        "size": field("float", allow_none=True, gt=0),
        "size_y": field("float", allow_none=True, gt=0),
        "angle": field("float", allow_none=True, gt=0),
        "spot_angle": field("float", allow_none=True, gt=0),
        "spot_blend": field("float", allow_none=True),
        "shape": field("str", allow_none=True),
        "temperature": field("float", allow_none=True, gt=0),
        "shared_data": field("str", "error"),
    }


class LightingInspectParams(BridgeParams):
    fields = {
        "include_options": field("bool", False),
        **PageParams.fields,
    }


class ColorManagementParams(BridgeParams):
    fields = {
        "display_device": field("str", allow_none=True),
        "view_transform": field("str", allow_none=True),
        "look": field("str", allow_none=True),
        "exposure": field("float", allow_none=True, ge=-32, le=32),
        "gamma": field("float", allow_none=True, ge=0, le=5),
    }


class TimelineSetParams(BridgeParams):
    fields = {
        "frame_current": field("int", allow_none=True),
        "frame_start": field("int", allow_none=True),
        "frame_end": field("int", allow_none=True),
    }


class KeyframeInsertParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "property": field("str", required=True),
        "frame": field("int", required=True),
        "value": field("number_list", allow_none=True, min_length=3, max_length=3),
        "interpolation": field("str", allow_none=True),
    }


class KeyframeListParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "property": field("str", allow_none=True),
        **PageParams.fields,
    }


class KeyframeRemoveParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "property": field("str", required=True),
        "frame": field("int", required=True),
    }


class CollectionCreateParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "parent": field("str", allow_none=True),
    }


class CollectionRenameParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "new_name": field("str", required=True),
    }


class CollectionObjectParams(BridgeParams):
    fields = {
        "collection": field("str", required=True),
        "object": field("str", required=True),
    }


class ObjectRenameParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "new_name": field("str", required=True),
    }


class ObjectParentParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "parent": field("str", required=True),
        "keep_transform": field("bool", False),
    }


class ObjectUnparentParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "keep_transform": field("bool", False),
    }


class ProjectSaveParams(BridgeParams):
    fields = {"filepath": field("str", allow_none=True), "overwrite": field("bool", False)}


class ProjectOpenParams(BridgeParams):
    fields = {"filepath": field("str", required=True), "discard_changes": field("bool", False)}


class ProjectRevertParams(BridgeParams):
    fields = {"confirm": field("bool", required=True)}


class BatchParams(BridgeParams):
    fields = {"commands": field("list", required=True), "stop_on_error": field("bool", True)}


class ModifierListParams(BridgeParams):
    fields = {"name": field("str", required=True)}


class ModifierAddParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "modifier_type": field("str", required=True),
        "modifier_name": field("str", allow_none=True),
        "properties": field("dict", default_factory=dict),
    }


class ModifierUpdateParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "modifier_name": field("str", required=True),
        "properties": field("dict", required=True),
    }


class ModifierRemoveParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "modifier_name": field("str", required=True),
    }


class MeshInspectParams(BridgeParams):
    fields = {
        "name": field("str", required=True),
        "source": field("str", "raw"),
        "check_duplicates": field("bool", False),
        "include_regions": field("bool", False),
        "tolerance": field("float", 1e-5, ge=0, le=1000),
        "max_ids": field("int", 10, ge=0, le=100),
        "element_budget": field("int", 500_000, ge=1, le=2_000_000),
    }


class ViewCaptureParams(BridgeParams):
    fields = {
        "object": field("str", allow_none=True),
        "collection": field("str", allow_none=True),
        "include_children": field("bool", True),
        "views": field("list", default_factory=lambda: ["three_quarter"]),
        "projection": field("str", "orthographic"),
        "mode": field("str", "solid"),
        "lighting": field("str", "rig"),
        "resolution": field("int", 512, ge=64, le=1024),
        "include_images": field("bool", True),
        "save_directory": field("str", allow_none=True),
        "max_bytes": field("int", 4_000_000, ge=10_000, le=5_000_000),
    }


class WorldSetParams(BridgeParams):
    fields = {
        "mode": field("str", allow_none=True),
        "color": field("number_list", allow_none=True, min_length=3, max_length=3),
        "strength": field("float", allow_none=True, ge=0, le=10_000),
        "filepath": field("str", allow_none=True),
        "rotation": field("float", allow_none=True),
        "sky_type": field("str", allow_none=True),
        "sun_elevation": field("float", allow_none=True),
        "sun_rotation": field("float", allow_none=True),
        "sun_intensity": field("float", allow_none=True),
        "sun_disc": field("bool", allow_none=True),
        "turbidity": field("float", allow_none=True),
        "camera_background": field("number_list", allow_none=True, min_length=3, max_length=3),
        "clear_camera_background": field("bool", False),
        "on_conflict": field("str", "error"),
    }
