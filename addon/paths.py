"""Resolve paths once, then use the resolved path for Blender file operations."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import bpy

from .policy import project_directory, require_within, resolve_path

if TYPE_CHECKING:
    from .settings import RuntimeSettings


class PathPolicy:
    def __init__(self, settings: RuntimeSettings):
        self.settings = settings

    @property
    def restricts_outputs(self) -> bool:
        return self.settings.safe_mode or self.settings.policy.output_roots is not None

    def validate_filepath(self, filepath: str) -> str:
        """Check managed roots and legacy Safe Mode roots independently."""
        blend_file = str(bpy.data.filepath)
        if self.settings.policy.output_roots is not None:
            roots = self.settings.policy.output_roots or (project_directory(blend_file),)
            require_within(filepath, roots, "File access denied: path is outside configured output roots")
        if self.settings.safe_mode:
            local_roots = self.settings.allowed_paths or [project_directory(blend_file)]
            require_within(filepath, local_roots, "File access denied: path is outside Safe Mode roots")
        return filepath

    def prepare_output_path(self, filepath: str, extensions: tuple[str, ...] = ()) -> str:
        """Resolve a render/export target, validate it, and create its parent directory."""
        if extensions and not filepath.lower().endswith(extensions):
            filepath += extensions[0]
        absolute = resolve_path(filepath, str(bpy.data.filepath), unsaved_output=not self.restricts_outputs)
        if filepath.endswith(("/", os.sep)) and not absolute.endswith(os.sep):
            absolute += os.sep
        self.validate_filepath(absolute)
        os.makedirs(os.path.dirname(absolute), exist_ok=True)
        return absolute

    def validate_script_path(self, script_path: str) -> str:
        blend_file = str(bpy.data.filepath)
        real_path = resolve_path(script_path, blend_file)
        if not real_path.lower().endswith(".py"):
            raise ValueError("Script must be a .py file")

        shared_roots = self.settings.policy.script_roots
        local_roots = self.settings.approved_script_roots
        message = "Script path denied: file is outside approved script roots"
        require_within(real_path, shared_roots or local_roots or [project_directory(blend_file)], message)
        if shared_roots and local_roots:
            require_within(real_path, local_roots, message)
        if not os.path.isfile(real_path):
            raise FileNotFoundError("Script file not found")
        return real_path
