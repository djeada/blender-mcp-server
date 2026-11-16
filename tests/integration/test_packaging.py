"""Install the release archive into an isolated Blender profile."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from .test_blender_bridge import BLENDER, _free_port, _raw, pytestmark  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts" / "lib" / "blender_addon_setup.py"
HARNESS = Path(__file__).with_name("blender_bridge_harness.py")


def test_packaged_addon_installs_and_authenticates(tmp_path):
    port = _free_port()
    token = tmp_path / "token"
    archive = tmp_path / "bridge.zip"
    log_dir = Path(os.environ.get("BLENDER_MCP_TEST_LOG_DIR", tmp_path))
    log_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "BLENDER_USER_RESOURCES": str(tmp_path / "profile"),
        "BLENDER_MCP_TOKEN_FILE": str(token),
        "BLENDER_MCP_PORT": str(port),
        "BLENDER_MCP_USE_INSTALLED": "1",
    }
    env.pop("BLENDER_MCP_TOKEN", None)

    def run(*cmd):
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=90, check=False)
        with (log_dir / "installation.log").open("a", encoding="utf-8") as log:
            log.write(result.stdout + result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    run(sys.executable, str(ROOT / "scripts" / "build_addon_zip.py"), "--output", str(archive))
    version = tuple(map(int, run(BLENDER, "--version").splitlines()[0].split()[1].split(".")[:2]))
    helper_args = (BLENDER, "-b", "--python-exit-code", "1", "--python", str(HELPER), "--")
    if version >= (4, 2):
        run(
            BLENDER,
            "-b",
            "--factory-startup",
            "--command",
            "extension",
            "install-file",
            "-r",
            "user_default",
            "-e",
            str(archive),
        )
    else:
        run(*helper_args, "install-legacy", str(archive))
    assert "MCP_ADDON_OK " in run(*helper_args, "verify")

    path = log_dir / "installed-bridge.log"
    with (
        path.open("w", encoding="utf-8") as output,
        subprocess.Popen(
            [BLENDER, "-b", "-t", "4", "--python-exit-code", "1", "--python", str(HARNESS)],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        ) as process,
    ):
        try:
            deadline = time.monotonic() + 30
            while "BRIDGE_READY" not in path.read_text(encoding="utf-8", errors="replace"):
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail(path.read_text(encoding="utf-8", errors="replace"))
                time.sleep(0.05)
            for command in ("bridge.status", "scene.get_info"):
                request = json.dumps({"id": "smoke", "command": command, "token": token.read_text()})
                response = _raw(port, (request + "\n").encode())[0]
                assert response["success"], response
                if command == "bridge.status":
                    assert response["result"]["protocol_version"] == 2
                    assert response["result"]["main_thread_progress"]
        finally:
            process.kill()
            process.wait(timeout=10)
