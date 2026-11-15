"""Typed .blend inspection, saving and scene transitions."""

import os
from pathlib import Path
from typing import TYPE_CHECKING

import bpy

from .policy import resolve_path
from .protocol import BridgeError

if TYPE_CHECKING:
    from .paths import PathPolicy


def get_info(params: dict) -> dict:
    filepath = str(bpy.data.filepath)
    dirty = getattr(bpy.data, "is_dirty", None)
    return {
        "filepath": os.path.realpath(filepath) if filepath else None,
        "saved": bool(filepath),
        "dirty": dirty if isinstance(dirty, bool) else None,
        "blender_version": str(bpy.app.version_string),
    }


def _blend_path(path: str, policy: "PathPolicy") -> Path:
    if not path.strip().lower().endswith(".blend"):
        raise ValueError("Project paths must end in .blend")
    resolved = policy.validate_filepath(resolve_path(path, str(bpy.data.filepath)))
    if Path(resolved).suffix.lower() != ".blend":
        raise ValueError("Resolved project path must end in .blend")
    return Path(resolved)


def _require_write_access(path: Path) -> None:
    if not path.parent.is_dir():
        raise FileNotFoundError("Create the parent directory before saving the project")
    if not os.access(path.parent, os.W_OK) or (path.exists() and not os.access(path, os.W_OK)):
        raise PermissionError("Project file or its directory is read-only")


def save(params: dict, *, policy: "PathPolicy", protect_source: bool = False) -> dict:
    current = str(bpy.data.filepath)
    raw_target = params.get("filepath")
    if raw_target is None and (not current or protect_source):
        raise ValueError("Provide an explicit .blend filepath to save")
    target = _blend_path(raw_target if raw_target is not None else current, policy)
    same_path = bool(current and os.path.normcase(str(target)) == os.path.normcase(os.path.realpath(current)))
    same_inode = bool(current and target.exists() and os.path.exists(current) and os.path.samefile(target, current))
    if protect_source and (same_path or same_inode):
        raise PermissionError("Headless save requires an output distinct from its source project")
    if target.exists():
        if not target.is_file():
            raise ValueError("Project save target must be a regular file")
        if not same_path and not params.get("overwrite", False):
            raise PermissionError("Project already exists. Use overwrite=true to replace it")
    _require_write_access(target)
    if policy.restricts_outputs:
        versions = bpy.context.preferences.filepaths.save_version
        for version in range(1, versions + 1):
            policy.validate_filepath(f"{target}{version}")
        # Blender may use a transient sibling while writing the file.
        policy.validate_filepath(f"{target}@")
    result = bpy.ops.wm.save_as_mainfile(filepath=str(target), check_existing=False)
    if "FINISHED" not in result or not target.is_file():
        raise BridgeError("command_failed", "Blender did not finish saving the project")
    return get_info({})


def open_project(params: dict, *, policy: "PathPolicy") -> dict:
    path = _blend_path(params["filepath"], policy)
    if not path.is_file():
        raise FileNotFoundError("Project file does not exist")
    if get_info({})["dirty"] is not False and not params.get("discard_changes", False):
        raise PermissionError("Project changes may be lost. Save first or use discard_changes=true")
    result = bpy.ops.wm.open_mainfile(filepath=str(path), load_ui=False, use_scripts=False)
    info = get_info({})
    if "FINISHED" not in result or info["filepath"] != str(path):
        raise BridgeError("command_failed", "Blender could not confirm that the requested project opened")
    return info


def revert(params: dict, *, policy: "PathPolicy") -> dict:
    if not params["confirm"]:
        raise PermissionError("Reverting discards unsaved edits. Use confirm=true to continue")
    if not bpy.data.filepath:
        raise ValueError("The current project has never been saved")
    return open_project({"filepath": bpy.data.filepath, "discard_changes": True}, policy=policy)
