"""Per-runtime bridge settings refreshed from add-on preferences."""

import os
from dataclasses import dataclass, field

import bpy


def get_addon_preferences():
    """Return this add-on's preferences object when available."""
    context = getattr(bpy, "context", None)
    preferences = getattr(context, "preferences", None)
    addons = getattr(preferences, "addons", None)
    if addons is None:
        return None

    addon_entry = None
    getter = getattr(addons, "get", None)
    if callable(getter):
        addon_entry = getter(__package__)
    elif isinstance(addons, dict):
        addon_entry = addons.get(__package__)

    return getattr(addon_entry, "preferences", None)


@dataclass
class RuntimeSettings:
    host: str = "127.0.0.1"
    port: int = 9876
    safe_mode: bool = False
    allow_inline_code: bool = True
    approved_script_roots: list[str] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    tool_whitelist: set[str] | None = None
    blocked_modules: set[str] = field(
        default_factory=lambda: {
            "subprocess",
            "socket",
            "webbrowser",
            "ctypes",
            "multiprocessing",
        }
    )

    def sync_preferences(self) -> None:
        """Refresh preferences on Blender's main thread; environment port takes precedence."""

        prefs = get_addon_preferences()
        env_port = os.environ.get("BLENDER_MCP_PORT")
        if prefs is None:
            if env_port:
                self.port = int(env_port)
            return

        self.safe_mode = bool(getattr(prefs, "safe_mode", self.safe_mode))
        # BLENDER_MCP_PORT (shared with the MCP server) wins over the preference
        self.port = int(env_port) if env_port else int(getattr(prefs, "port", self.port))
        self.allow_inline_code = bool(getattr(prefs, "allow_inline_code", self.allow_inline_code))

        raw_roots = getattr(prefs, "approved_script_roots", "") or ""
        path_helper = getattr(getattr(bpy, "path", None), "abspath", None)
        approved_roots = []
        for root in raw_roots.split(";"):
            root = root.strip()
            if not root:
                continue
            resolved = path_helper(root) if callable(path_helper) else root
            approved_roots.append(os.path.realpath(resolved))

        self.approved_script_roots = approved_roots
        self.allowed_paths = approved_roots.copy() if self.safe_mode else []

        raw_commands = getattr(prefs, "allowed_commands", "") or ""
        commands = {command.strip() for command in raw_commands.replace(";", ",").split(",") if command.strip()}
        self.tool_whitelist = commands or None
