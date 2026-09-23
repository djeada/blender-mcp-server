"""Add-on maintenance run inside Blender by scripts/setup.sh.

Usage: blender -b --python scripts/lib/blender_addon_setup.py -- <action> [zip]

Actions:
  remove-legacy   Disable and delete a legacy (pre-extension) copy of the add-on.
  install-legacy  Install and enable the add-on zip the legacy way (Blender < 4.2).
  verify          Print MCP_ADDON_OK <module> <version> when the current add-on is enabled.
"""

import os
import shutil
import sys

import addon_utils
import bpy

ADDON_ID = "blender_mcp_bridge"


def _args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def remove_legacy() -> None:
    legacy_dir = os.path.join(bpy.utils.user_resource("SCRIPTS", path="addons"), ADDON_ID)
    enabled = ADDON_ID in bpy.context.preferences.addons
    if enabled:
        addon_utils.disable(ADDON_ID, default_set=True)
    if os.path.isdir(legacy_dir):
        shutil.rmtree(legacy_dir)
    if enabled or os.path.isdir(legacy_dir):
        bpy.ops.wm.save_userpref()
    print(f"MCP_LEGACY_REMOVED enabled={enabled} dir={legacy_dir}")


def install_legacy(zip_path: str) -> None:
    bpy.ops.preferences.addon_install(filepath=zip_path, overwrite=True)
    addon_utils.enable(ADDON_ID, default_set=True)
    bpy.ops.wm.save_userpref()
    print("MCP_LEGACY_INSTALLED")


def verify() -> None:
    for name, module in list(sys.modules.items()):
        # Blender strips bl_info from extension modules, so identify the add-on by its register().
        if name.split(".")[-1] == ADDON_ID and hasattr(module, "register"):
            version = ".".join(map(str, getattr(module, "bl_info", {}).get("version", ()))) or "extension"
            current = hasattr(module, "_load_or_create_token")
            print(f"MCP_ADDON_{'OK' if current else 'OUTDATED'} {name} {version}")
            return
    print("MCP_ADDON_MISSING")


def main() -> None:
    args = _args()
    action = args[0] if args else "verify"
    if action == "remove-legacy":
        remove_legacy()
    elif action == "install-legacy":
        install_legacy(args[1])
    else:
        verify()


main()
