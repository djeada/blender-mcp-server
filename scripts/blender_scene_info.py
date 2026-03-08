#!/usr/bin/env python3
"""Fetch current scene info from the Blender MCP add-on TCP bridge."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from blender_bridge_request import send_request


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch scene.get_info from the Blender add-on bridge."
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bridge host")
    parser.add_argument("--port", type=int, default=9876, help="Bridge port")
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Socket timeout in seconds"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        response = send_request(
            args.host, args.port, "scene.get_info", {}, args.timeout
        )
    except OSError as exc:
        print(f"Bridge request failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(response, indent=2))
    return 0 if response.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
