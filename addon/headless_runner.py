"""Run one validated command inside a dedicated Blender process."""

import json
import sys
from pathlib import Path

from .commands import CommandHandler
from .policy import Policy
from .project import save
from .protocol import MAX_RESPONSE_BYTES, BridgeError, command_error, failure
from .settings import RuntimeSettings


def run(request_path: str, response_path: str) -> None:
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    command = request["command"]
    try:
        policy = Policy(**request["policy"])
        policy.require_transport("headless")
        handler = CommandHandler(RuntimeSettings(policy=policy))
        if command == "project.save":
            _, values = handler.prepare(command, request["params"], sync_settings=False)
            result = save(values, policy=handler.policy, protect_source=True)
        elif command in {"python.execute", "python.execute_async"}:
            _, values = handler.prepare(command, request["params"], sync_settings=False)
            code, _ = handler.executor.prepare_source(values)
            result = handler.executor.run_code(code, handler.executor.make_namespace(values.get("args", {})), 0)
        else:
            result = handler.handle(command, request["params"], sync_settings=False)
        response = {"success": True, "result": result}
    except BaseException as exc:
        response = failure(command_error(exc, command, None))
    try:
        with open(response_path, "w", encoding="utf-8") as handle:
            size = 0
            for chunk in json.JSONEncoder(allow_nan=False, default=repr, separators=(",", ":")).iterencode(response):
                size += len(chunk)  # ASCII JSON
                if size > MAX_RESPONSE_BYTES:
                    raise BridgeError("response_too_large", "Blender response exceeds the byte limit")
                handle.write(chunk)
    except (BridgeError, ValueError, TypeError, RecursionError) as exc:
        Path(response_path).write_text(json.dumps(failure(command_error(exc, command, None))), encoding="utf-8")
    sys.stdout.flush()
