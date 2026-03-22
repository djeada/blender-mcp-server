#!/usr/bin/env python3
"""Launch Blender as a detached GUI process and surface early startup failures."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    log_path = Path("/tmp/blender-mcp-launch.log")
    blender_cmd = ["blender", "--addons", "blender_mcp_bridge"]

    env = os.environ.copy()
    with log_path.open("wb") as log_file:
        proc = subprocess.Popen(
            blender_cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )

    # Give Blender a moment to either detach successfully or fail fast.
    time.sleep(2.0)
    returncode = proc.poll()
    if returncode is None:
        print(f"started pid={proc.pid} log={log_path}")
        return 0

    output = log_path.read_text(errors="replace").strip()
    print(f"failed code={returncode} log={log_path}")
    if output:
        print(output)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
