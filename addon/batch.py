"""Compose bounded, non-file scene commands on the Blender main thread."""

import json
import time
from typing import TYPE_CHECKING

from .protocol import BridgeError, InvalidArgumentsError, command_error

if TYPE_CHECKING:
    from .commands import CommandHandler

MAX_STEPS = 32
MAX_INPUT_BYTES = 64 * 1024
MAX_STEP_RESULT_BYTES = 16 * 1024
BATCH_COMMANDS = frozenset(
    {
        "scene.get_info",
        "scene.list_objects",
        "object.get_transform",
        "object.get_hierarchy",
        "mesh.inspect",
        "object.create_mesh",
        "object.delete",
        "object.translate",
        "object.rotate",
        "object.scale",
        "object.duplicate",
        "object.rename",
        "object.parent",
        "object.unparent",
        "object.list_modifiers",
        "object.add_modifier",
        "object.update_modifier",
        "object.remove_modifier",
        "material.list",
        "material.create",
        "material.assign",
        "material.set_color",
        "material.list_slots",
        "shader.inspect_graph",
        "shader.edit_graph",
        "material.slot_append",
        "material.slot_replace",
        "material.slot_remove",
        "material.assign_faces",
        "camera.create",
        "camera.update",
        "lighting.inspect",
        "render.set_color_management",
        "world.get",
        "light.create",
        "light.update",
        "timeline.get",
        "timeline.set",
        "keyframe.insert",
        "keyframe.list",
        "keyframe.remove",
        "collection.create",
        "collection.list",
        "collection.rename",
        "collection.add_object",
        "collection.remove_object",
    }
)


def execute(params: dict, *, handler: "CommandHandler") -> dict:
    deadline = time.monotonic() + handler.settings.policy.command_timeout
    steps = params["commands"]
    if not 1 <= len(steps) <= MAX_STEPS:
        raise InvalidArgumentsError(f"Batch must contain 1–{MAX_STEPS} commands")
    try:
        size = len(json.dumps(steps, allow_nan=False, separators=(",", ":")).encode())
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidArgumentsError("Batch must contain finite JSON values") from exc
    if size > MAX_INPUT_BYTES:
        raise InvalidArgumentsError("Batch exceeds the 64 KiB input limit")

    # Prepare every step before making changes. Dependencies on scene state are evaluated in order.
    prepared = []
    for index, step in enumerate(steps):
        try:
            if not isinstance(step, dict) or step.keys() - {"command", "params"}:
                raise InvalidArgumentsError("Batch steps must contain a command and an optional params object")
            name = step.get("command")
            if not isinstance(name, str) or name not in BATCH_COMMANDS:
                raise PermissionError("Command is not available in batches")
            specification, values = handler.prepare(name, step.get("params", {}), sync_settings=False)
        except Exception as exc:
            error = command_error(exc, None, None)
            raise BridgeError(
                error.code, f"Batch step {index}: {error}", details={"index": index, "started": False}
            ) from exc
        prepared.append((name, specification, values))

    results = []
    stopped = False
    for index, (name, specification, values) in enumerate(prepared):
        entry = {"index": index, "command": name}
        if stopped or time.monotonic() >= deadline:
            results.append({**entry, "status": "skipped", "reason": "previous_failure" if stopped else "deadline"})
            continue
        try:
            result = handler.execute_prepared(name, specification, values)
        except Exception as exc:
            error = command_error(exc, name, None)
            results.append({**entry, "status": "failed", "error": error.as_dict()})
            stopped = params["stop_on_error"]
            continue
        result_size = len(json.dumps(result, default=str).encode())
        if result_size > MAX_STEP_RESULT_BYTES:
            results.append({**entry, "status": "succeeded", "result_omitted": "size_limit"})
        else:
            results.append({**entry, "status": "succeeded", "result": result})
    return {"steps": results, "undo": "per_mutation"}
