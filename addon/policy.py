"""Shared policy for the Blender add-on and MCP process. This module needs no bpy."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

POLICY_ENV = "BLENDER_MCP_POLICY_FILE"


def env_seconds(name: str, default: float) -> float:
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite number greater than zero")
    return value


@dataclass(frozen=True)
class Policy:
    transports: tuple[str, ...] = ("bridge",)
    allow_python: bool = True
    allow_inline_code: bool = True
    allowed_commands: tuple[str, ...] | None = None
    script_roots: tuple[str, ...] = ()
    # None preserves legacy output behavior. An empty managed list uses the project directory.
    output_roots: tuple[str, ...] | None = None
    queue_capacity: int = 16
    queue_timeout: float = 10
    command_timeout: float = 60
    long_timeout: float = 3600
    max_script_seconds: int = 3600
    max_jobs: int = 8
    max_render_pixels: int = 33_554_432
    max_render_frames: int = 2500

    @classmethod
    def load(cls) -> Policy:
        filename = os.environ.get(POLICY_ENV)
        if not filename:
            return cls()
        try:
            with open(filename, encoding="utf-8-sig") as file:
                config = json.load(file)
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read a valid JSON policy from {POLICY_ENV}") from exc
        if not isinstance(config, dict):
            raise ValueError(f"{POLICY_ENV} must contain a JSON object")
        defaults = asdict(cls(allow_python=False, allow_inline_code=False, output_roots=()))
        for name, value in config.items():
            if name not in defaults:
                raise ValueError(f"Unknown policy setting: {name!r}")
            default = defaults[name]
            if name in {"transports", "allowed_commands", "script_roots", "output_roots"}:
                if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
                    raise ValueError(f"Policy setting {name} must be a list of nonempty strings")
                if name.endswith("_roots"):
                    if any(
                        not os.path.isabs(root) or root.startswith("//") or not Path(root).drive and os.name == "nt"
                        for root in value
                    ):
                        raise ValueError(f"Policy setting {name} requires absolute native paths")
                    value = [os.path.realpath(root) for root in value]
                value = tuple(sorted(set(value)))
            elif type(default) is bool:
                if type(value) is not bool:
                    raise ValueError(f"Policy setting {name} must be a boolean")
            elif (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not (0 < value <= 2**31 - 1)
                or (not name.endswith("timeout") and type(value) is not int)
            ):
                raise ValueError(f"Policy setting {name} must be a positive finite number in range")
            defaults[name] = value
        policy = cls(**defaults)
        if set(policy.transports) - {"bridge", "headless"}:
            raise ValueError("Policy transports must be 'bridge' or 'headless'")
        if os.environ.get("BLENDER_MCP_HEADLESS", "").lower() in {"0", "false", "no", "off"}:
            policy = replace(policy, transports=tuple(mode for mode in policy.transports if mode != "headless"))
        return policy

    @property
    def policy_id(self) -> str | None:
        if self.output_roots is None:
            return None
        snapshot = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(snapshot.encode()).hexdigest()

    def require_transport(self, transport: str) -> None:
        if transport not in self.transports:
            raise PermissionError(f"{transport.capitalize()} transport is disabled by policy")

    def require_command(self, command: str) -> None:
        if self.allowed_commands is not None and command not in self.allowed_commands:
            raise PermissionError(f"Command '{command}' is not in the configured allowlist")
        if command in {"python.execute", "python.execute_async"} and not self.allow_python:
            raise PermissionError("Python execution is disabled by policy")

    def summary(self) -> dict:
        return {
            "id": self.policy_id,
            "transports": list(self.transports),
            "allow_python": self.allow_python,
            "allow_inline_code": self.allow_python and self.allow_inline_code,
            "script_roots_configured": bool(self.script_roots),
            "output_roots_configured": bool(self.output_roots),
            "restricts_outputs": self.output_roots is not None,
            "limits": {
                name: getattr(self, name)
                for name in (
                    "queue_capacity",
                    "queue_timeout",
                    "command_timeout",
                    "long_timeout",
                    "max_script_seconds",
                    "max_jobs",
                    "max_render_pixels",
                    "max_render_frames",
                )
            },
        }


def project_directory(blend_file: str) -> str:
    if not blend_file:
        raise PermissionError("No approved directories are configured and the .blend file is unsaved")
    return os.path.dirname(os.path.realpath(blend_file))


def resolve_path(path: str, blend_file: str, *, unsaved_output: bool = False) -> str:
    if not path.strip() or "\0" in path:
        raise ValueError("Provide a nonempty filesystem path")
    if path.startswith("//"):
        if not blend_file and unsaved_output:
            parent = os.path.join(tempfile.gettempdir(), "blender-mcp")
        else:
            parent = project_directory(blend_file)
        path = os.path.join(parent, path[2:].lstrip("/\\"))
    return os.path.realpath(path)


def require_within(path: str, roots: Iterable[str], message: str) -> None:
    candidate = os.path.normcase(os.path.realpath(path))
    for root in roots:
        normalized = os.path.normcase(os.path.realpath(root))
        try:
            if os.path.commonpath([candidate, normalized]) == normalized:
                return
        except ValueError:
            continue  # drives may differ on Windows
    raise PermissionError(message)
