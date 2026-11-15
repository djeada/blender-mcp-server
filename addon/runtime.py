"""Composition root and server lifecycle owned by one enabled add-on."""

import logging

from .commands import CommandHandler
from .settings import RuntimeSettings
from .transport import BlenderMCPServer

logger = logging.getLogger(__name__)


class BridgeRuntime:
    def __init__(self):
        self.settings = RuntimeSettings()
        self.handler = CommandHandler(self.settings)
        self.server: BlenderMCPServer | None = None

    def create_server(self) -> BlenderMCPServer:
        return BlenderMCPServer(self.handler)

    def healthy(self) -> bool:
        return self.server is not None and self.server.is_healthy()

    def ensure_server_running(self):
        self.settings.sync_preferences()
        if self.server is not None and self.healthy():
            self.server._register_request_queue_timer()
            return None
        if self.server:
            try:
                self.server.stop()
            except Exception:
                logger.exception("Failed stopping stale MCP Bridge during restart")
        self.server = self.create_server()
        self.server.start()
        return None


runtime = BridgeRuntime()
