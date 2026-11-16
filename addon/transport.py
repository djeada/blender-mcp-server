"""Authenticated TCP framing and bounded main-thread scheduling for Blender."""

from __future__ import annotations

import contextlib
import errno
import hmac
import json
import logging
import socket
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import bpy

from .auth import load_or_create_token
from .protocol import (
    ADDON_VERSION,
    BRIDGE_STATUS,
    LONG_COMMANDS,
    MAX_RESPONSE_BYTES,
    PROTOCOL_VERSION,
    BridgeError,
    command_error,
    failure,
    label,
)

if TYPE_CHECKING:
    from .commands import CommandHandler

logger = logging.getLogger(__name__)
BUFFER_SIZE = 65536
MAX_REQUEST_SIZE = 16 * 1024 * 1024
MAX_CLIENTS = 24
CLIENT_IDLE_SECONDS = 60
TIMER_INTERVAL = 0.01


@dataclass(eq=False)
class Pending:
    request: dict
    generation: str
    queued_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    state: str = "queued"
    changed: threading.Event = field(default_factory=threading.Event)
    response: dict | None = None

    @property
    def command(self) -> str:
        return str(self.request.get("command", ""))

    @property
    def request_id(self) -> str | None:
        return self.request.get("id")


class BlenderMCPServer:
    """One TCP listener, one Blender timer and a bounded queue per active server."""

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
        self._lock = threading.RLock()
        self._request_queue: deque[Pending] = deque()
        self._active: Pending | None = None
        self._generation = uuid.uuid4().hex
        self._loading = False
        self._clients: set[socket.socket] = set()
        self._drain_timer_callback = self._drain_request_queue

    @property
    def running(self) -> bool:
        return self._running

    @property
    def address(self) -> str:
        return f"{self._host}:{self._port}"

    def is_healthy(self) -> bool:
        return bool(
            self._running and self._thread is not None and self._thread.is_alive() and self._port == self.settings.port
        )

    def start(self):
        if self._running:
            self._register_request_queue_timer()
            return
        self.settings.sync_preferences()
        self.settings.policy.require_transport("bridge")
        self._auth_token = load_or_create_token()
        self._host, self._port = self.settings.host, self.settings.port
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.settimeout(0.5)
            listener.bind((self._host, self._port))
            listener.listen(MAX_CLIENTS)
        except OSError as exc:
            listener.close()
            if exc.errno in {errno.EADDRINUSE, 10048, 10013}:
                raise OSError(f"Cannot bind Blender MCP bridge to {self.address}; check for another listener") from exc
            raise
        self._server_socket = listener
        with self._lock:
            self._generation = uuid.uuid4().hex
            self._loading = False
            self._running = True
        try:
            self._register_request_queue_timer()
            self._thread = threading.Thread(target=self._accept_loop, args=(listener,), daemon=True)
            self._thread.start()
        except Exception:
            self.stop()
            raise
        logger.info("Blender MCP Bridge listening on %s", self.address)

    def _register_request_queue_timer(self):
        timers = bpy.app.timers
        if timers.is_registered(self._drain_timer_callback):
            return
        timers.register(self._drain_timer_callback, first_interval=TIMER_INTERVAL, persistent=True)

    def _finish(self, pending: Pending, state: str, response: dict):
        """Complete a request at most once. Caller holds the state lock."""
        if pending.response is not None:
            return
        pending.state = state
        pending.response = response
        pending.changed.set()
        logger.debug("MCP request %s id=%s command=%s", state, label(pending.request_id), label(pending.command))

    def _fail(self, pending: Pending, code: str, message: str, *, state: str = "failed", retryable=False, details=None):
        error = BridgeError(
            code, message, command=pending.command, request_id=pending.request_id, retryable=retryable, details=details
        )
        self._finish(pending, state, failure(error, wire_id=pending.request_id))

    def begin_scene_load(self):
        with self._lock:
            self._loading = True
            self._generation = uuid.uuid4().hex
            while self._request_queue:
                self._fail(
                    self._request_queue.popleft(),
                    "session_changed",
                    "Scene loading; check bridge status",
                    state="cancelled",
                    retryable=True,
                )
        self._handler.jobs.invalidate_queued("Scene changed before the job started")

    def end_scene_load(self):
        with self._lock:
            self._loading = False
        if self._running:
            self._register_request_queue_timer()

    def stop(self):
        with self._lock:
            self._running = False
            self._loading = False
            clients = tuple(self._clients)
            while self._request_queue:
                self._fail(
                    self._request_queue.popleft(),
                    "disconnected",
                    "Blender MCP Bridge stopped",
                    state="cancelled",
                    retryable=True,
                )
            if self._active:
                self._fail(
                    self._active,
                    "disconnected",
                    "Blender MCP Bridge stopped during execution",
                    details={"outcome_uncertain": True},
                )
        self._handler.jobs.invalidate_queued("Bridge stopped before the job started")
        timers = bpy.app.timers
        if timers.is_registered(self._drain_timer_callback):
            timers.unregister(self._drain_timer_callback)
        if self._server_socket:
            self._server_socket.close()
            self._server_socket = None
        for conn in clients:
            # Wake idle readers while allowing in-flight requests to send their final response.
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RD)
        if self._thread and self._thread.ident is not None:
            self._thread.join(timeout=1)
        self._thread = None
        logger.info("Blender MCP Bridge stopped")

    def _accept_loop(self, listener: socket.socket):
        while self._running and listener is self._server_socket:
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            with self._lock:
                if not self._running or listener is not self._server_socket or len(self._clients) >= MAX_CLIENTS:
                    conn.close()
                    continue
                self._clients.add(conn)
            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

    def _is_authorized(self, request: dict) -> bool:
        token = request.get("token")
        return bool(
            self._auth_token is not None
            and isinstance(token, str)
            and hmac.compare_digest(token.encode("utf-8", "surrogatepass"), self._auth_token.encode())
        )

    @staticmethod
    def _write_response(conn: socket.socket, response: dict) -> None:
        try:
            data = json.dumps(response, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, RecursionError):
            error = BridgeError(
                "command_failed", "Blender returned an unserializable response", request_id=response["id"]
            )
            data = json.dumps(failure(error, wire_id=response["id"])).encode()
        if len(data) > MAX_RESPONSE_BYTES:
            error = BridgeError(
                "response_too_large", "Blender response exceeds the byte limit", request_id=response["id"]
            )
            data = json.dumps(failure(error, wire_id=response["id"])).encode()
        conn.sendall(data + b"\n")

    def _reject(self, conn: socket.socket, code: str, error: str) -> None:
        with contextlib.suppress(OSError):
            self._write_response(conn, failure(BridgeError(code, error)))

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(CLIENT_IDLE_SECONDS)
        buffer = b""
        frame_started = time.monotonic()
        try:
            while self._running:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                if not buffer:
                    frame_started = time.monotonic()
                if time.monotonic() - frame_started > CLIENT_IDLE_SECONDS:
                    return
                buffer += data
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if len(line) > self.max_request_size:
                        self._reject(conn, "invalid_arguments", f"Request exceeds {self.max_request_size} bytes")
                        return
                    if not line.strip():
                        continue
                    # Close on malformed frames, including cross-protocol traffic.
                    try:
                        request = json.loads(line)
                    except (ValueError, RecursionError):
                        self._reject(conn, "invalid_arguments", "Invalid JSON request")
                        return
                    if not isinstance(request, dict):
                        self._reject(conn, "invalid_arguments", "Request must be a JSON object")
                        return
                    if not self._is_authorized(request):
                        logger.warning("Rejected unauthenticated MCP bridge request")
                        self._reject(conn, "permission_denied", "Unauthorized: missing or invalid token")
                        return
                    request.pop("token", None)
                    if request.get("id") is not None and label(request["id"]) is None:
                        self._reject(conn, "invalid_arguments", "Invalid request ID")
                        return
                    self._write_response(conn, self._submit_request(request))
                    frame_started = time.monotonic()
                if len(buffer) > self.max_request_size:
                    self._reject(conn, "invalid_arguments", f"Request exceeds {self.max_request_size} bytes")
                    return
        except OSError:
            logger.debug("MCP client socket closed")
        finally:
            conn.close()
            with self._lock:
                self._clients.discard(conn)

    def _submit_request(self, request: dict) -> dict:
        command = request.get("command")
        request_id = request.get("id")
        if not isinstance(command, str) or label(command) is None:
            error = BridgeError("invalid_arguments", "Invalid or missing command", request_id=request_id)
            return failure(error, wire_id=request_id)
        if command == BRIDGE_STATUS or request.get("policy_id") == self.settings.policy.policy_id:
            if self._handler.is_worker_command(command):
                return self._process_request(request, sync_settings=False)
        else:
            error = BridgeError(
                "policy_mismatch",
                "Bridge and MCP policy differ; restart both with the same policy",
                command=command,
                request_id=request_id,
            )
            return failure(error, wire_id=request_id)

        with self._lock:
            pending = Pending(request, self._generation)
            if not self._running or self._loading:
                self._fail(
                    pending, "session_changed", "Blender session is changing; check bridge status", retryable=True
                )
            elif len(self._request_queue) >= self.settings.policy.queue_capacity:
                self._fail(pending, "busy", "Blender request queue is full; check bridge status", retryable=True)
            else:
                self._request_queue.append(pending)
                logger.debug("MCP request queued id=%s command=%s", label(request_id), command)
        return self._wait_for_request(pending)

    def _wait_for_request(self, pending: Pending) -> dict:
        policy = self.settings.policy
        while True:
            with self._lock:
                if pending.response is not None:
                    return pending.response
                started = pending.started_at
                budget = policy.long_timeout if pending.command in LONG_COMMANDS else policy.command_timeout
                deadline = pending.queued_at + policy.queue_timeout if started is None else started + budget
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    if started is None:
                        self._request_queue.remove(pending)
                        details: dict = {"started": False}
                        if active := self._active_request():
                            details["active_request"] = active
                        self._fail(
                            pending,
                            "queue_timeout",
                            "Blender main thread did not start the request in time",
                            state="cancelled",
                            retryable=True,
                            details=details,
                        )
                    else:
                        self._fail(
                            pending,
                            "execution_timeout",
                            "Blender execution deadline passed; check bridge status",
                            details={"outcome_uncertain": True},
                        )
                    continue
                pending.changed.clear()
            pending.changed.wait(remaining)

    def _drain_request_queue(self):
        with self._lock:
            if not self._running:
                return None
            if self._active is not None or self._loading or not self._request_queue:
                return TIMER_INTERVAL
            pending = self._request_queue.popleft()
            now = time.monotonic()
            if now - pending.queued_at >= self.settings.policy.queue_timeout:
                self._fail(
                    pending,
                    "queue_timeout",
                    "Blender main thread did not start the request in time",
                    state="cancelled",
                    retryable=True,
                    details={"started": False},
                )
                return TIMER_INTERVAL
            self._active = pending
            pending.started_at = now
            pending.state = "executing"
            pending.changed.set()
            logger.debug("MCP request executing id=%s command=%s", label(pending.request_id), label(pending.command))
        try:
            response = self._process_request(pending.request)
        except BaseException as exc:  # Keep the timer alive even on SystemExit.
            response = failure(command_error(exc, pending.command, pending.request_id), wire_id=pending.request_id)
        finally:
            with self._lock:
                self._finish(pending, "completed" if response["success"] else "failed", response)
                self._active = None
        return TIMER_INTERVAL if self._running else None

    def _active_request(self) -> dict | None:
        active = self._active
        if active is None or active.command == BRIDGE_STATUS:
            return None
        return {"id": active.request_id, "command": active.command}

    def _status(self) -> dict:
        with self._lock:
            oldest = self._request_queue[0] if self._request_queue else None
            return {
                "main_thread_progress": True,
                "generation": self._generation,
                "protocol_version": PROTOCOL_VERSION,
                "bridge_version": ".".join(map(str, ADDON_VERSION)),
                "blender_version": str(bpy.app.version_string),
                "queue_depth": len(self._request_queue),
                "oldest_queue_age_seconds": round(time.monotonic() - oldest.queued_at, 3) if oldest else None,
                "active_request": self._active_request(),
                "commands": [BRIDGE_STATUS, *sorted(self._handler.available_commands())],
                "policy": {
                    **self.settings.policy.summary(),
                    "allow_inline_code": self.settings.policy.allow_python and self.settings.inline_enabled,
                    "safe_mode": self.settings.safe_mode,
                    "local_restrictions": self.settings.local_restrictions,
                },
            }

    def _process_request(self, request: dict, sync_settings: bool = True) -> dict:
        req_id = request.get("id")
        command = request.get("command", "")
        params = request.get("params", {})
        try:
            if command == BRIDGE_STATUS:
                self.settings.sync_preferences()
                result = self._status()
            else:
                result = self._handler.dispatch(command, params, sync_settings=sync_settings)
            return {"id": req_id, "success": True, "result": result}
        except Exception as exc:
            error = command_error(exc, command, req_id)
            logger.debug("MCP request failed id=%s command=%s code=%s", label(req_id), label(command), error.code)
            return failure(error, wire_id=req_id)
