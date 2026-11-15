"""Authenticated TCP framing and main-thread request scheduling for Blender."""

from __future__ import annotations

import contextlib
import errno
import hmac
import json
import logging
import queue
import socket
import threading
import traceback
from typing import TYPE_CHECKING, Any

import bpy

from .auth import load_or_create_token

if TYPE_CHECKING:
    from .commands import CommandHandler

logger = logging.getLogger(__name__)
BUFFER_SIZE = 65536
MAX_REQUEST_SIZE = 16 * 1024 * 1024


class BlenderMCPServer:
    """TCP socket server running inside Blender."""

    def __init__(self, handler: CommandHandler, *, max_request_size: int = MAX_REQUEST_SIZE):
        self.settings = handler.settings
        self.max_request_size = max_request_size
        self._auth_token: str | None = None
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._host = self.settings.host
        self._port = self.settings.port
        self._handler = handler
        self._request_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._drain_timer_callback = self._drain_request_queue

    @property
    def running(self) -> bool:
        return self._running

    @property
    def address(self) -> str:
        return f"{self._host}:{self._port}"

    def is_healthy(self) -> bool:
        return bool(
            self._running
            and self._server_socket is not None
            and self._thread is not None
            and self._thread.is_alive()
            and self._port == self.settings.port
        )

    def start(self):
        if self._running:
            self._register_request_queue_timer()
            return
        self.settings.sync_preferences()
        self._auth_token = load_or_create_token()
        self._host = self.settings.host
        self._port = self.settings.port
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        try:
            self._server_socket.bind((self._host, self._port))
        except OSError as exc:
            if self._server_socket is not None:
                self._server_socket.close()
                self._server_socket = None
            if exc.errno == errno.EADDRINUSE:
                logger.warning(
                    "Blender MCP Bridge port %s already in use; skipping bridge startup",
                    self._port,
                )
                self._running = False
                return
            raise
        self._running = True
        self._server_socket.listen(1)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        self._register_request_queue_timer()
        logger.info(f"Blender MCP Bridge listening on {self._host}:{self._port}")

    def _register_request_queue_timer(self):
        timers = bpy.app.timers
        is_registered = getattr(timers, "is_registered", None)
        if callable(is_registered):
            try:
                if is_registered(self._drain_timer_callback):
                    return
            except Exception:
                logger.debug("Unable to check MCP Bridge queue timer registration", exc_info=True)
        try:
            timers.register(self._drain_timer_callback, first_interval=0.01, persistent=True)
        except TypeError:
            # Blender versions before the persistent timer flag still need the bridge to run.
            timers.register(self._drain_timer_callback, first_interval=0.01)
        logger.debug("Registered MCP Bridge request queue timer")

    def stop(self):
        self._running = False
        if self._server_socket:
            self._server_socket.close()
            self._server_socket = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        while not self._request_queue.empty():
            queued = self._request_queue.get_nowait()
            queued["response"] = {
                "id": queued["request"].get("id"),
                "success": False,
                "error": "Blender MCP Bridge stopped",
            }
            queued["event"].set()
        logger.info("Blender MCP Bridge stopped")

    def _accept_loop(self):
        while self._running:
            try:
                assert self._server_socket is not None
                conn, addr = self._server_socket.accept()
                logger.info(f"MCP client connected from {addr}")
                client_thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
                client_thread.start()
            except TimeoutError:
                continue
            except OSError:
                break

    def _is_authorized(self, request: dict) -> bool:
        token = request.get("token")
        if self._auth_token is None or not isinstance(token, str):
            return False
        return hmac.compare_digest(token.encode(), self._auth_token.encode())

    @staticmethod
    def _reject(conn: socket.socket, request_id: Any, error: str) -> None:
        with contextlib.suppress(OSError):
            conn.sendall(json.dumps({"id": request_id, "success": False, "error": error}).encode() + b"\n")

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(None)
        buffer = b""
        try:
            while self._running:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                buffer += data
                if b"\n" not in buffer and len(buffer) > self.max_request_size:
                    self._reject(conn, None, f"Request exceeds {self.max_request_size} bytes")
                    return
                # Messages are newline-delimited JSON
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if len(line) > self.max_request_size:
                        self._reject(conn, None, f"Request exceeds {self.max_request_size} bytes")
                        return
                    if not line.strip():
                        continue
                    # Any malformed line closes the connection. This stops cross-protocol
                    # payloads (e.g. a browser POST whose body smuggles a JSON command).
                    try:
                        request = json.loads(line)
                    except (json.JSONDecodeError, UnicodeDecodeError) as e:
                        self._reject(conn, None, f"Invalid JSON: {e}")
                        return
                    if not isinstance(request, dict):
                        self._reject(conn, None, "Request must be a JSON object")
                        return
                    if not self._is_authorized(request):
                        logger.warning("Rejected unauthenticated MCP bridge request")
                        # id=None marks a connection-level rejection; the connection is closed next.
                        self._reject(conn, None, "Unauthorized: missing or invalid token")
                        return
                    response = self._submit_request(request)
                    conn.sendall(json.dumps(response).encode() + b"\n")
                if len(buffer) > self.max_request_size:
                    self._reject(conn, None, f"Request exceeds {self.max_request_size} bytes")
                    return
        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            conn.close()

    def _submit_request(self, request: dict) -> dict:
        if self._handler.is_worker_command(request.get("command", "")):
            return self._process_request(request, sync_settings=False)
        event = threading.Event()
        queued: dict[str, Any] = {"request": request, "event": event, "response": None}
        logger.debug("Enqueue MCP request id=%s command=%s", request.get("id"), request.get("command"))
        self._request_queue.put(queued)
        event.wait()
        response: dict = queued["response"]
        return response

    def _drain_request_queue(self):
        while True:
            try:
                queued = self._request_queue.get_nowait()
            except queue.Empty:
                break
            request = queued["request"]
            logger.debug(
                "Processing MCP request id=%s command=%s",
                request.get("id"),
                request.get("command"),
            )
            try:
                queued["response"] = self._process_request(queued["request"])
            except BaseException as exc:  # Never leave a client waiting or let this kill the timer
                queued["response"] = {"id": request.get("id"), "success": False, "error": repr(exc)}
            finally:
                queued["event"].set()
            logger.debug(
                "Finished MCP request id=%s command=%s",
                request.get("id"),
                request.get("command"),
            )
        return 0.01 if self._running else None

    @staticmethod
    def _maybe_push_undo(command: str):
        undo_push = bpy.ops.ed.undo_push
        poll = getattr(undo_push, "poll", None)
        if callable(poll) and not poll():
            logger.debug(f"Skipping undo push for {command}: context poll failed")
            return
        undo_push(message=f"MCP: {command}")

    def _process_request(self, request: dict, sync_settings: bool = True) -> dict:
        req_id = request.get("id")
        command = request.get("command", "")
        params = request.get("params", {})
        try:
            specification, values = self._handler.prepare(command, params, sync_settings=sync_settings)
            if specification.mutates:
                self._maybe_push_undo(command)
            result = specification.handler(values)
            return {"id": req_id, "success": True, "result": result}
        except Exception as e:
            logger.error(f"Command '{command}' failed: {e}\n{traceback.format_exc()}")
            return {"id": req_id, "success": False, "error": str(e)}
