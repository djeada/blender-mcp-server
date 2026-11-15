"""Load the same pure policy and wire contract as the Blender add-on."""

from pathlib import Path

ADDON_PATH = Path(__file__).with_name("_addon")
if ADDON_PATH.is_dir():
    from blender_mcp_server._addon import policy, protocol
else:
    # Editable installs read the add-on directly from the checkout.
    ADDON_PATH = Path(__file__).resolve().parents[2] / "addon"
    from addon import policy, protocol

__all__ = ["ADDON_PATH", "policy", "protocol"]
