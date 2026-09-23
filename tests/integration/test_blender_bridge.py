"""End-to-end tests against a real Blender process.

Opt in with BLENDER_MCP_INTEGRATION=1 (and BLENDER_BIN if blender is not on PATH):

    BLENDER_MCP_INTEGRATION=1 pytest tests/integration --no-cov
"""

import asyncio
import json
import os
import shutil
import socket
import struct
import subprocess
import time
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from blender_mcp_server import server
from blender_mcp_server.headless import HeadlessBlenderExecutor

BLENDER = os.environ.get("BLENDER_BIN", "blender")

pytestmark = pytest.mark.skipif(
    os.environ.get("BLENDER_MCP_INTEGRATION") != "1" or shutil.which(BLENDER) is None,
    reason="set BLENDER_MCP_INTEGRATION=1 and install Blender to run integration tests",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _tiny_png(path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = zlib.compress(b"\x00\xff\x00\x00")
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("bridge")
    port = _free_port()
    env = dict(os.environ)
    env.pop("BLENDER_MCP_TOKEN", None)
    env.update({"BLENDER_MCP_PORT": str(port), "BLENDER_MCP_TOKEN_FILE": str(tmp / "token")})
    harness = Path(__file__).with_name("blender_bridge_harness.py")
    proc = subprocess.Popen(
        [BLENDER, "-b", "--factory-startup", "--python", str(harness)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if "BRIDGE_READY" in line:
            break
        if not line and proc.poll() is not None:
            pytest.fail("Blender exited before the bridge started")
    yield {"port": port, "token_file": tmp / "token", "tmp": tmp}
    proc.kill()
    proc.wait()


@pytest.fixture
def call(bridge, monkeypatch):
    monkeypatch.delenv("BLENDER_MCP_TOKEN", raising=False)
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(bridge["token_file"]))
    conn = server.BlenderConnection(port=bridge["port"])
    ctx = MagicMock()
    ctx.request_context.lifespan_context = conn

    loop = asyncio.new_event_loop()

    def run(tool, **kwargs):
        return json.loads(loop.run_until_complete(getattr(server, tool)(ctx, **kwargs)))

    yield run
    loop.run_until_complete(conn.disconnect())
    loop.close()


def _raw(port: int, payload: bytes) -> list[dict]:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def test_token_file_is_private(bridge):
    assert (bridge["token_file"].stat().st_mode & 0o777) == 0o600


def test_scene_and_object_tools(call):
    assert call("scene_get_info")["name"] == "Scene"
    created = call("object_create", mesh_type="cube", name="ITCube", location=[1, 2, 3])
    assert created["location"] == [1.0, 2.0, 3.0]
    moved = call("object_translate", name="ITCube", offset=[1, 0, 0])
    assert moved["location"] == [2.0, 2.0, 3.0]


def test_material_tools(call, bridge):
    call("object_create", mesh_type="plane", name="ITPlane")
    call("material_create", name="ITMat")
    call("material_assign", object="ITPlane", material="ITMat")
    assert call("material_set_color", name="ITMat", color=[1, 0, 0])["color"] == [1.0, 0.0, 0.0, 1.0]
    texture = bridge["tmp"] / "tex.png"
    _tiny_png(texture)
    assert call("material_set_texture", name="ITMat", filepath=str(texture))["texture"] == str(texture)


def test_large_response(call):
    result = call("python_exec", code="print('y' * 49000)\n__result__ = 'x' * 200000")
    assert len(result["result"]) == 200000
    assert call("scene_get_info")["name"] == "Scene"


def test_system_exit_does_not_break_bridge(call):
    result = call("python_exec", code="raise SystemExit(3)")
    assert "SystemExit" in result["error"]
    assert call("scene_get_info")["name"] == "Scene"


def test_running_async_job_can_be_cancelled(call):
    """job.cancel must reach a job that is busy on Blender's main thread."""
    code = "import time\nwhile not __cancel_event__.is_set():\n    time.sleep(0.01)\n"
    job_id = call("python_exec_async", code=code, timeout_seconds=60)["job_id"]
    deadline = time.monotonic() + 10
    while call("job_status", job_id=job_id)["status"] != "running":
        assert time.monotonic() < deadline, "job never started"
        time.sleep(0.05)
    assert call("job_cancel", job_id=job_id)["cancellation_requested"] is True
    while (status := call("job_status", job_id=job_id)["status"]) == "running":
        assert time.monotonic() < deadline, "cancellation never took effect"
        time.sleep(0.05)
    assert status == "cancelled"


def test_unauthenticated_request_rejected(bridge):
    responses = _raw(bridge["port"], b'{"id": "1", "command": "scene.get_info"}\n')
    assert responses == [{"id": None, "success": False, "error": "Unauthorized: missing or invalid token"}]


def test_http_smuggled_command_not_executed(bridge):
    token = bridge["token_file"].read_text()
    body = json.dumps({"id": "x", "command": "python.execute", "params": {"code": "pass"}, "token": token})
    http = f"POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: text/plain\r\n\r\n{body}\n".encode()
    responses = _raw(bridge["port"], http)
    assert len(responses) == 1
    assert "Invalid JSON" in responses[0]["error"]


def test_headless_execution_and_system_exit():
    executor = HeadlessBlenderExecutor(BLENDER)
    ok = asyncio.run(executor.execute(code="__result__ = bpy.app.version_string", timeout_seconds=120))
    assert ok["error"] is None and ok["result"]
    exited = asyncio.run(executor.execute(code="import sys; sys.exit(0)", timeout_seconds=120))
    assert "SystemExit" in exited["error"]
