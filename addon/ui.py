"""Blender preferences, panel, operators, and add-on registration."""

import bpy
from bpy.app.handlers import persistent

from .auth import token_file_path
from .runtime import runtime


@persistent
def _on_load_post(_dummy):
    bpy.app.timers.register(runtime.ensure_server_running, first_interval=0.1)


def _on_port_changed(_prefs, _context):
    """Rebind the bridge when the port preference changes."""
    bpy.app.timers.register(runtime.ensure_server_running, first_interval=0.1)


class MCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    safe_mode: bpy.props.BoolProperty(  # type: ignore[valid-type]
        name="Safe Mode",
        description=(
            "Restrict file access to the approved directories (or the .blend file's directory) "
            "and disable inline Python code"
        ),
        default=False,
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
    )
    approved_script_roots: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Approved Script Roots",
        description="Semicolon-separated list of directories from which script files may be loaded",
        default="",
    )
    allowed_commands: bpy.props.StringProperty(  # type: ignore[valid-type]
        name="Allowed Commands",
        description="Comma-separated bridge commands to accept (e.g. scene.get_info,object.create_mesh). Empty = all",
        default="",
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
        if runtime.server is None:
            runtime.server = runtime.create_server()
        runtime.server.start()
        self.report({"INFO"}, f"MCP Bridge started on {runtime.server.address}")
        return {"FINISHED"}


class MCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "mcp.stop_server"
    bl_label = "Stop MCP Server"

    def execute(self, context):
        if runtime.server:
            runtime.server.stop()
        self.report({"INFO"}, "MCP Bridge stopped")
        return {"FINISHED"}


classes = (MCP_AddonPreferences, MCP_PT_Panel, MCP_OT_StartServer, MCP_OT_StopServer)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)
    runtime.ensure_server_running()


def unregister():
    if _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    if runtime.server:
        runtime.server.stop()
        runtime.server = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
