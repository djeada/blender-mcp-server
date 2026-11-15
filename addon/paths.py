"""Resolve output paths and enforce file/script access against explicit settings."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

import bpy

if TYPE_CHECKING:
    from .settings import RuntimeSettings


def is_within(path: str, root: str) -> bool:
    """True when the resolved path is the root itself or inside it."""
    real_path = os.path.realpath(path)
    real_root = os.path.realpath(root)
    try:
        return os.path.commonpath([real_path, real_root]) == real_root
    except ValueError:  # Different drives on Windows
        return False


def default_root() -> str:
    """Directory of the saved .blend file; refuse to guess when the file is unsaved."""
    if not bpy.data.filepath:
        raise PermissionError(
            "No approved directories are configured and the .blend file is unsaved. "
            "Save the file or set 'Approved Script Roots' in the add-on preferences."
        )
    return os.path.dirname(os.path.realpath(str(bpy.data.filepath)))


def resolve_output_path(filepath: str) -> str:
    """Absolute location for a render/export target.

    ``//`` means "next to the .blend file". An unsaved file has no such folder and Blender then
    fails to write at all, so those paths go to a ``blender-mcp`` folder in the temp directory.
    """
    if filepath.startswith("//") and not bpy.data.filepath:
        resolved = os.path.join(tempfile.gettempdir(), "blender-mcp", filepath[2:].lstrip("/\\"))
    else:
        resolved = bpy.path.abspath(filepath)
    absolute = os.path.abspath(resolved)
    # A trailing separator means "write into this folder" for renders; abspath() would drop it.
    if filepath.endswith(("/", os.sep)) and not absolute.endswith(os.sep):
        absolute += os.sep
    return absolute


class PathPolicy:
    def __init__(self, settings: RuntimeSettings):
        self.settings = settings

    def validate_filepath(self, filepath: str) -> str:
        """Security: validate that a filepath is within allowed directories."""
        if not self.settings.safe_mode:
            return filepath
        abs_path = os.path.abspath(bpy.path.abspath(filepath))
        # In safe mode with no allowed paths, only allow the blend file directory
        allowed_paths = self.settings.allowed_paths or [default_root()]
        if any(is_within(abs_path, allowed) for allowed in allowed_paths):
            return filepath
        raise PermissionError(
            f"File access denied: '{filepath}' is outside allowed directories. Allowed: {allowed_paths}"
        )

    def prepare_output_path(self, filepath: str, extensions: tuple[str, ...] = ()) -> str:
        """Resolve a render/export target, enforce Safe Mode on it, and make sure its folder exists.

        ``extensions`` lists the suffixes the exporter accepts; the first is appended when none is present.
        """
        abs_path = resolve_output_path(filepath)
        if extensions and not abs_path.lower().endswith(extensions):
            abs_path += extensions[0]
        self.validate_filepath(abs_path)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        return abs_path

    def validate_script_path(self, script_path: str) -> str:
        """Validate that a script path is under an approved root directory."""
        real_path = os.path.realpath(script_path)
        if not os.path.isfile(real_path):
            raise FileNotFoundError(f"Script not found: {script_path}")
        if not real_path.endswith(".py"):
            raise ValueError(f"Script must be a .py file: {script_path}")

        roots = self.settings.approved_script_roots or [default_root()]

        for root in roots:
            if is_within(real_path, root):
                return real_path
        raise PermissionError(f"Script path denied: '{script_path}' is outside approved roots. Approved: {roots}")
