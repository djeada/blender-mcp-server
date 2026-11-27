"""Validated loading of local image files, shared by world and texture commands."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import bpy

from .policy import resolve_path

if TYPE_CHECKING:
    from .paths import PathPolicy

IMAGE_EXTENSIONS = (".hdr", ".exr", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".tga", ".bmp")
MAX_IMAGE_BYTES = 256 * 1024 * 1024
MAX_IMAGE_PIXELS = 16384 * 8192


def validate_path(filepath: str, policy: PathPolicy, label: str = "Image") -> str:
    """Resolve and authorize a local image path without opening it in Blender."""
    if "://" in filepath:
        raise ValueError(f"{label} must be a local file; nothing is downloaded")
    resolved = policy.validate_filepath(resolve_path(filepath, str(bpy.data.filepath)))
    if not resolved.lower().endswith(IMAGE_EXTENSIONS):
        raise ValueError(f"Unsupported {label.lower()} format; use one of: {', '.join(IMAGE_EXTENSIONS)}")
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"{label} file not found: {os.path.basename(resolved)}")
    if os.path.getsize(resolved) > MAX_IMAGE_BYTES:
        raise ValueError(f"{label} exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB")
    return resolved


def decode_problem(image, label: str = "Image") -> str | None:
    width, height = image.size[0], image.size[1]  # reading the size makes Blender decode the file
    if width <= 0 or height <= 0:
        return f"Blender cannot decode this {label.lower()}"
    if width * height > MAX_IMAGE_PIXELS:
        return f"{label} is {width}x{height}; the limit is {MAX_IMAGE_PIXELS} pixels"
    return None


def _same_file(image, resolved: str) -> bool:
    if image.source != "FILE" or not image.filepath:
        return False
    loaded = os.path.realpath(str(bpy.path.abspath(image.filepath)))
    return os.path.normcase(loaded) == os.path.normcase(resolved)


def load_with_color_space(resolved: str, color_space: str, created: list, label: str = "Image"):
    """Return an image of this file that has `color_space`, never changing one that already exists.

    A color space belongs to the image datablock, which other materials may share. If no
    loaded copy has the wanted space, a separate datablock is loaded and recorded in `created`.
    """
    for image in bpy.data.images:
        if _same_file(image, resolved) and image.colorspace_settings.name == color_space:
            return image
    try:
        image = bpy.data.images.load(resolved, check_existing=False)
    except RuntimeError as exc:
        raise ValueError(f"Blender cannot read this {label.lower()}: {os.path.basename(resolved)}") from exc
    created.append(image)
    if problem := decode_problem(image, label):
        raise ValueError(f"{problem}: {os.path.basename(resolved)}")
    image.colorspace_settings.name = color_space
    return image
