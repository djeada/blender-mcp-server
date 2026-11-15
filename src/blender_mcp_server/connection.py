"""Authenticated asynchronous TCP transport for the Blender add-on bridge."""

import asyncio
import contextlib
import json
import logging
import os
import stat
import uuid
from pathlib import Path
from typing import Any

from blender_mcp_server.shared import policy, protocol

logger = logging.getLogger(__name__)

DEFAULT_BLENDER_HOST = "127.0.0.1"
DEFAULT_BLENDER_PORT = 9876
STREAM_LIMIT = 32 * 1024 * 1024  # Also accept responses from a legacy add-on.
CONNECT_TIMEOUT = 5
MAX_REQUEST_BYTES = 16 * 1024 * 1024


def default_token_file() -> Path:
    return Path(os.environ.get("BLENDER_MCP_TOKEN_FILE") or Path.home() / ".blender-mcp" / "token").expanduser()


def load_auth_token() -> str:
    token = os.environ.get("BLENDER_MCP_TOKEN")
    if token:
        return token
    path = default_token_file()
    try:
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or (os.name == "posix" and mode & 0o077):
            raise PermissionError
        with path.open(encoding="utf-8-sig") as handle:
            token = handle.read(1025).strip()
        if len(token) > 1024:
            raise ValueError
    except FileNotFoundError:
        token = ""
    except (OSError, ValueError) as exc:
        raise protocol.BridgeConnectionError(
            "permission_denied", "Cannot read a private BLENDER_MCP_TOKEN_FILE; check its location and permissions"
        ) from exc
    if not token:
        raise protocol.BridgeConnectionError(
            "permission_denied",
            "Blender MCP auth token not found. Enable the Blender add-on or set BLENDER_MCP_TOKEN / BLENDER_MCP_TOKEN_FILE.",
        )
    return token


class BlenderConnection:
    """Async client. Each tool call writes one command and never replays a mutation."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
        configured_policy: policy.Policy | None = None,
    ):
        self.host = host or os.environ.get("BLENDER_MCP_HOST", DEFAULT_BLENDER_HOST)
        self.port = port or int(os.environ.get("BLENDER_MCP_PORT", DEFAULT_BLENDER_PORT))
        self.policy = configured_policy if configured_policy is not None else policy.Policy.load()
        self.timeout = timeout
        if self.timeout is None and os.environ.get("BLENDER_MCP_TIMEOUT"):
            self.timeout = policy.env_seconds("BLENDER_MCP_TIMEOUT", 0)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()
        self._policy_verified = False

    async def connect(self):
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port, limit=STREAM_LIMIT), timeout=CONNECT_TIMEOUT
        )
        self._policy_verified = False
        logger.info("Connected to Blender at %s:%s", self.host, self.port)

    async def disconnect(self):
        writer = self._writer
        self._reset()
        if writer is not None:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(writer.wait_closed(), CONNECT_TIMEOUT)

    def _reset(self):
        if self._writer:
            self._writer.close()
        self._writer = None
        self._reader = None
        self._policy_verified = False

    async def send_command(self, command: str, params: dict | None = None, *, reconnect=False) -> Any:
        self.policy.require_transport("bridge")
        if command != protocol.BRIDGE_STATUS:
            self.policy.require_command(command)
        try:
            await asyncio.wait_for(self._lock.acquire(), self.policy.queue_timeout)
        except asyncio.TimeoutError as exc:
            raise protocol.BridgeError(
                "busy", "Another Blender MCP request is using the connection", command=command, retryable=True
            ) from exc
        try:
            if reconnect or (self._reader is not None and self._reader.at_eof() is True):
                self._reset()
            token = load_auth_token()
            if self._writer is None:
                try:
                    await self.connect()
                except (asyncio.TimeoutError, OSError) as exc:
                    raise protocol.BridgeConnectionError(
                        "disconnected",
                        f"Cannot reach Blender at {self.host}:{self.port}. Start Blender and enable the "
                        "Blender MCP Bridge add-on (View3D > Sidebar > MCP > Start Server).",
                        command=command,
                        retryable=True,
                    ) from exc
            if self.policy.policy_id is not None and not self._policy_verified and command != protocol.BRIDGE_STATUS:
                try:
                    await self._status(token)
                except protocol.BridgeError as exc:
                    if exc.code not in {"command_failed", "invalid_arguments"}:
                        raise
                    self._reset()
                    raise protocol.BridgeError(
                        "policy_mismatch", "Update the Blender add-on to use the shared policy", command=command
                    ) from exc
            if command == protocol.BRIDGE_STATUS:
                return await self._status(token)
            return await self._exchange(command, params or {}, token)
        finally:
            self._lock.release()

    async def _status(self, token: str) -> dict:
        result = await self._exchange(protocol.BRIDGE_STATUS, {}, token)
        if not isinstance(result, dict):
            self._reset()
            raise protocol.BridgeError("unsupported", "Blender did not return bridge status")
        remote_id = result.get("policy", {}).get("id")
        self._policy_verified = (
            result.get("protocol_version") == protocol.PROTOCOL_VERSION and remote_id == self.policy.policy_id
        )
        if self.policy.policy_id is not None and not self._policy_verified:
            self._reset()
            raise protocol.BridgeError(
                "policy_mismatch", "Bridge and MCP policy differ; restart both with the same policy"
            )
        return result

    async def _exchange(self, command: str, params: dict, token: str) -> Any:
        assert self._reader is not None and self._writer is not None
        request_id = str(uuid.uuid4())
        request = {"id": request_id, "command": command, "params": params, "token": token}
        if self.policy.policy_id is not None:
            request["policy_id"] = self.policy.policy_id
        try:
            data = json.dumps(request, allow_nan=False, separators=(",", ":")).encode()
        except (TypeError, ValueError, RecursionError) as exc:
            raise protocol.InvalidArgumentsError("Command parameters must be finite JSON values") from exc
        if len(data) > MAX_REQUEST_BYTES:
            raise protocol.InvalidArgumentsError("Blender request exceeds the byte limit")

        budget = self.policy.long_timeout if command in protocol.LONG_COMMANDS else self.policy.command_timeout
        timeout = self.timeout if self.timeout is not None else self.policy.queue_timeout + budget + 5
        try:
            response = await asyncio.wait_for(self._round_trip(data, request_id), timeout)
        except asyncio.TimeoutError as exc:
            self._reset()
            raise protocol.RequestTimeoutError(
                "response_timeout",
                f"Blender did not answer within {timeout:g}s; check bridge status",
                command=command,
                request_id=request_id,
                details={"outcome_uncertain": True},
            ) from exc
        except (OSError, ValueError, RecursionError) as exc:
            self._reset()
            raise protocol.BridgeConnectionError(
                "disconnected",
                "Lost connection to Blender; check bridge status",
                command=command,
                request_id=request_id,
                details={"outcome_uncertain": True},
            ) from exc
        except BaseException:
            self._reset()
            raise

        if not response.get("success"):
            connection_level = response.get("id") is None
            if connection_level:
                self._reset()
            error_details = response.get("error_details") or {}
            message = str(response.get("error", "Blender command failed"))[:400].replace(token, "[redacted]")
            code = error_details.get("code") or ("disconnected" if connection_level else "command_failed")
            error_type = protocol.BridgeConnectionError if connection_level else protocol.BridgeError
            if code in {"queue_timeout", "execution_timeout"}:
                error_type = protocol.RequestTimeoutError
            raise error_type(
                code,
                message,
                command=command,
                request_id=request_id,
                retryable=error_details.get("retryable") is True,
                details=error_details.get("details"),
            )
        return response.get("result")

    async def _round_trip(self, data: bytes, request_id: str) -> dict:
        assert self._reader is not None and self._writer is not None
        self._writer.write(data + b"\n")
        await self._writer.drain()
        while True:
            line = await self._reader.readline()
            if not line:
                raise ConnectionError("Blender connection closed")
            response = json.loads(line)
            if not isinstance(response, dict):
                raise ValueError("Invalid response")
            if response.get("id") == request_id or (response.get("id") is None and not response.get("success")):
                return response
            logger.warning("Discarding stale Blender response")
