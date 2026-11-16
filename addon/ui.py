"""Blender preferences, panel, operators, and add-on registration."""

import bpy
from bpy.app.handlers import persistent

from .auth import token_file_path
from .runtime import runtime

_restart_bridge = runtime.ensure_server_running


@persistent
def _on_load_pre(_dummy):
    if runtime.server:
        runtime.server.begin_scene_load()


@persistent
def _on_load_post(_dummy):
    if runtime.server:
        runtime.server.end_scene_load()
    _schedule_restart()


def _schedule_restart():
    if runtime.enabled and not bpy.app.timers.is_registered(_restart_bridge):
        bpy.app.timers.register(_restart_bridge, first_interval=0.1)


def _on_port_changed(_prefs, _context):
    _schedule_restart()


def _on_policy_changed(_prefs, _context):
    runtime.settings.sync_preferences()


class MCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    safe_mode: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Safe Mode",
        description=(
            "Restrict file access to the approved directories (or the .blend file's directory) "
            "and disable inline Python code"
        ),
        default=False,
        update=_on_policy_changed,
    )
    port: bpy.props.IntProperty(  # type: ignore[valid-type]
        name="Port",
        description="TCP port for the MCP bridge",
        default=9876,
        min=1024,
        max=65535,
        update=_on_port_changed,
    )
    allow_inline_code: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Allow Inline Code",
        description="Allow python.execute to run inline code strings. Disable to only allow script files",
        default=True,
        update=_on_policy_changed,
    )
    approved_script_roots: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Approved Script Roots",
        description="Semicolon-separated list of directories from which script files may be loaded",
        default="",
        update=_on_policy_changed,
    )
    allowed_commands: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Allowed Commands",
        description="Comma-separated bridge commands to accept (e.g. scene.get_info,object.create_mesh). Empty = all",
        default="",
        update=_on_policy_changed,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "safe_mode")
        layout.prop(self, "port")
        layout.prop(self, "allowed_commands")
        layout.label(text=f"Auth token file: {token_file_path()}")
        layout.separator()
        layout.label(text="Python Execution")
        layout.prop(self, "allow_inline_code")
        layout.prop(self, "approved_script_roots")


class MCP_PT_Panel(bpy.types.Panel):
    bl_label = "MCP Bridge"
    bl_idname = "MCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP"

    def draw(self, context):
        layout = self.layout

        if runtime.server and runtime.server.running:
            layout.label(text=f"● Listening on {runtime.server.address}", icon="LINKED")
            layout.operator("mcp.stop_server", text="Stop Server")
        else:
            layout.label(text="○ Server stopped", icon="UNLINKED")
            layout.operator("mcp.start_server", text="Start Server")

        # Last script execution status
        last_execution = runtime.handler.executor.last_execution
        if last_execution["request_id"]:
            layout.separator()
            layout.label(text="Last Execution", icon="SCRIPT")
            box = layout.box()
            status = last_execution["status"]
            icon = "CHECKMARK" if status in ("ok", "succeeded") else "ERROR"
            box.label(text=f"Status: {status}", icon=icon)
            box.label(text=f"ID: {last_execution['request_id']}")
            if last_execution["duration_seconds"] is not None:
                box.label(text=f"Duration: {last_execution['duration_seconds']:.3f}s")
            if last_execution["error_summary"]:
                box.label(text=f"Error: {last_execution['error_summary']}", icon="ERROR")


class MCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "mcp.start_server"
    bl_label = "Start MCP Server"

    def execute(self, context):
        runtime.enabled = True
        try:
            runtime.settings.policy.require_transport("bridge")
            runtime.ensure_server_running()
        except (OSError, PermissionError, ValueError) as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        assert runtime.server is not None
        self.report({"INFO"}, f"MCP Bridge started on {runtime.server.address}")
        return {"FINISHED"}


class MCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "mcp.stop_server"
    bl_label = "Stop MCP Server"

    def execute(self, context):
        runtime.stop()
        self.report({"INFO"}, "MCP Bridge stopped")
        return {"FINISHED"}


classes = (MCP_AddonPreferences, MCP_PT_Panel, MCP_OT_StartServer, MCP_OT_StopServer)


def _load_handlers():
    handlers = bpy.app.handlers
    pairs = [(handlers.load_pre, _on_load_pre), (handlers.load_post, _on_load_post)]
    if hasattr(handlers, "load_post_fail"):
        pairs.append((handlers.load_post_fail, _on_load_post))
    return pairs


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    for handlers, callback in _load_handlers():
        if callback not in handlers:
            handlers.append(callback)
    runtime.enabled = True
    runtime.ensure_server_running()


def unregister():
    for handlers, callback in _load_handlers():
        if callback in handlers:
            handlers.remove(callback)
    if bpy.app.timers.is_registered(_restart_bridge):
        bpy.app.timers.unregister(_restart_bridge)
    runtime.stop()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
