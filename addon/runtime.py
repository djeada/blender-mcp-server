"""Composition root and server lifecycle owned by one enabled add-on."""

from .commands import CommandHandler
from .settings import RuntimeSettings
from .transport import BlenderMCPServer


class BridgeRuntime:
    def __init__(self):
        self.settings = RuntimeSettings()
        self.handler = CommandHandler(self.settings)
        self.server: BlenderMCPServer | None = None
        self.enabled = True

    def create_server(self) -> BlenderMCPServer:
        return BlenderMCPServer(self.handler)

    def healthy(self) -> bool:
        return self.server is not None and self.server.is_healthy()

    def ensure_server_running(self):
        if not self.enabled or "bridge" not in self.settings.policy.transports:
            return None
        self.settings.sync_preferences()
        if self.server is not None and self.healthy():
            self.server.end_scene_load()
            return None
        if self.server is not None:
            self.server.stop()
        self.server = self.create_server()
        self.server.start()
        return None

    def stop(self):
        self.enabled = False
        if self.server is not None:
            self.server.stop()
            self.server = None


runtime = BridgeRuntime()
