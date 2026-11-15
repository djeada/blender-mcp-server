"""Authenticated asynchronous TCP transport for the Blender add-on bridge."""

import asyncio
import contextlib
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_BLENDER_HOST = "127.0.0.1"
DEFAULT_BLENDER_PORT = 9876
# Bridge responses can carry large results plus up to 2 x 50 KB of captured output.
STREAM_LIMIT = 32 * 1024 * 1024


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    return float(raw) if raw else None


def default_token_file() -> Path:
    return Path(os.environ.get("BLENDER_MCP_TOKEN_FILE") or Path.home() / ".blender-mcp" / "token")


def load_auth_token() -> str:
    """Return the shared secret the Blender add-on expects on every request."""
    token = os.environ.get("BLENDER_MCP_TOKEN")
    if token:
        return token
    path = default_token_file()
    try:
        token = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        token = ""
    if not token:
        raise ConnectionError(
            f"Blender MCP auth token not found at {path}. Enable the Blender add-on (it creates the token) "
            "or set BLENDER_MCP_TOKEN / BLENDER_MCP_TOKEN_FILE."
        )
    return token


class BlenderConnection:
    """Async TCP client that communicates with the Blender add-on."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
    ):
        self.host = host or os.environ.get("BLENDER_MCP_HOST", DEFAULT_BLENDER_HOST)
        self.port = port or int(os.environ.get("BLENDER_MCP_PORT", DEFAULT_BLENDER_PORT))
        # Optional per-request timeout; renders can legitimately take hours, so none by default.
        self.timeout = timeout if timeout is not None else _env_float("BLENDER_MCP_TIMEOUT")
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port, limit=STREAM_LIMIT)
        logger.info(f"Connected to Blender at {self.host}:{self.port}")

    async def disconnect(self):
        if self._writer:
            writer = self._writer
            self._writer = None
            self._reader = None
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    def _reset(self):
        """Drop the connection so a late or partial response can never be read by the next request."""
        if self._writer:
            self._writer.close()
        self._writer = None
        self._reader = None

    async def send_command(self, command: str, params: dict | None = None) -> Any:
        """Send a command to Blender and return the result."""
        async with self._lock:
            if not self._writer:
                try:
                    await self.connect()
                except OSError as e:
                    raise ConnectionError(
                        f"Cannot reach Blender at {self.host}:{self.port} ({e}). Start Blender and enable the "
                        "Blender MCP Bridge add-on (View3D > Sidebar > MCP > Start Server)."
                    ) from e
            assert self._reader is not None
            assert self._writer is not None

            request_id = str(uuid.uuid4())
            request = {
                "id": request_id,
                "command": command,
                "params": params or {},
                "token": load_auth_token(),
            }
            try:
                self._writer.write(json.dumps(request).encode() + b"\n")
                await self._writer.drain()
                response = await asyncio.wait_for(self._read_response(request_id), timeout=self.timeout)
            except asyncio.TimeoutError as e:
                # Must precede OSError: on 3.11+ asyncio.TimeoutError is the builtin TimeoutError (an OSError).
                self._reset()
                raise TimeoutError(f"Blender did not answer '{command}' within {self.timeout}s") from e
            except (ConnectionError, OSError, ValueError) as e:
                # ValueError covers stream limit overruns and undecodable lines.
                self._reset()
                raise ConnectionError(f"Lost connection to Blender: {e}") from e
            except BaseException:
                # Cancelled mid-request: the response is still in flight, so the stream is unusable.
                self._reset()
                raise

            if not response.get("success"):
                raise RuntimeError(response.get("error", "Unknown error from Blender"))
            return response.get("result")

    async def _read_response(self, request_id: str) -> dict:
        assert self._reader is not None
        while True:
            line = await self._reader.readline()
            if not line:
                raise ConnectionError("Blender connection closed")
            response: dict = json.loads(line)
            if response.get("id") == request_id:
                return response
            if response.get("id") is None and not response.get("success"):
                # Connection-level rejection (bad auth, malformed request)
                raise ConnectionError(response.get("error", "Request rejected by Blender"))
            logger.warning("Discarding stale Blender response id=%s", response.get("id"))
