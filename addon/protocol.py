"""The versioned bridge error contract, shared with the MCP server."""

from __future__ import annotations

import re

PROTOCOL_VERSION = 2
ADDON_VERSION = (0, 2, 0)
BRIDGE_STATUS = "bridge.status"
LONG_COMMANDS = frozenset(
    {"render.still", "render.animation", "export.gltf", "export.obj", "export.fbx", "python.execute"}
)
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_LABEL = re.compile(r"[a-zA-Z0-9_.:-]{1,80}\Z")


def label(value: object) -> str | None:
    """Only emit short identifiers in logs and structured metadata."""
    return value if isinstance(value, str) and _LABEL.fullmatch(value) else None


class BridgeError(RuntimeError):
    def __init__(self, code: str, message: str, *, command=None, request_id=None, retryable=False, details=None):
        super().__init__(message)
        self.code = code
        self.command = label(command)
        self.request_id = label(request_id)
        self.retryable = retryable
        self.details = details or {}

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "message": str(self),
            "command": self.command,
            "request_id": self.request_id,
            "retryable": self.retryable,
            "details": self.details,
        }


class BridgeConnectionError(BridgeError, ConnectionError):
    pass


class RequestTimeoutError(BridgeError, TimeoutError):
    pass


class UnsupportedError(BridgeError, ValueError):
    def __init__(self, message: str):
        super().__init__("unsupported", message)


class MissingResourceError(LookupError, ValueError):
    """A requested Blender data block or job does not exist."""


class InvalidArgumentsError(BridgeError, ValueError):
    def __init__(self, message: str):
        super().__init__("invalid_arguments", message)


def command_error(exc: BaseException, command: str | None, request_id: str | None) -> BridgeError:
    if isinstance(exc, BridgeError):
        return BridgeError(
            exc.code, str(exc), command=command, request_id=request_id, retryable=exc.retryable, details=exc.details
        )
    if isinstance(exc, PermissionError):
        code, message = "permission_denied", str(exc)
    elif isinstance(exc, (FileNotFoundError, MissingResourceError)):
        code, message = "not_found", str(exc)
    elif isinstance(exc, ValueError):
        code, message = "invalid_arguments", str(exc)
    else:
        code, message = "command_failed", "Blender could not complete the command"
    return BridgeError(code, message[:400], command=command, request_id=request_id)


def failure(error: BridgeError, *, wire_id=None) -> dict:
    return {"id": wire_id, "success": False, "error": str(error), "error_details": error.as_dict()}
