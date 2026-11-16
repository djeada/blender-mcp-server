"""Runtime ownership and Blender registration after modularization."""


def test_runtime_settings_and_job_tables_are_independent(runtime):
    other = type(runtime)()
    runtime.settings.safe_mode = True
    runtime.settings.blocked_modules.add("example_module")
    runtime.handler.executor.last_execution["request_id"] = "first"
    assert other.settings.safe_mode is False
    assert "example_module" not in other.settings.blocked_modules
    assert other.handler.executor.last_execution["request_id"] is None
    assert other.handler.jobs is not runtime.handler.jobs


def test_preferences_belong_to_the_addon_package(addon_module):
    assert addon_module.ui.MCP_AddonPreferences.bl_idname == addon_module.__name__


def test_registration_starts_runtime_and_unregister_stops_it(addon_module, runtime, mock_bpy, monkeypatch):
    from unittest.mock import MagicMock

    server = MagicMock()
    monkeypatch.setattr(runtime, "create_server", lambda: server)
    addon_module.register()
    server.start.assert_called_once_with()
    assert addon_module.ui._on_load_post in mock_bpy.app.handlers.load_post
    addon_module.unregister()
    server.stop.assert_called_once_with()
    assert runtime.server is None
    assert addon_module.ui._on_load_post not in mock_bpy.app.handlers.load_post


def test_bridge_recovery_timer_keeps_same_callback(addon_module, mock_bpy):
    callbacks = set()
    timers = mock_bpy.app.timers
    timers.is_registered.side_effect = callbacks.__contains__
    timers.register.side_effect = lambda callback, **kwargs: callbacks.add(callback)

    addon_module.ui._on_port_changed(None, None)
    addon_module.ui._on_port_changed(None, None)
    timers.register.assert_called_once()
    assert next(iter(callbacks)) is addon_module.ui._restart_bridge
