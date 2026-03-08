#!/usr/bin/env python3
"""Send a single JSON command to the Blender MCP add-on TCP bridge."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import uuid
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send a JSON command to the Blender add-on bridge on localhost."
    )
    parser.add_argument(
        "command",
        help="Bridge command, for example: scene.get_info or object.create_mesh",
    )
    parser.add_argument(
        "--params",
        default="{}",
        help='JSON object string for command parameters, for example: \'{"name":"Cube"}\'',
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bridge host")
    parser.add_argument("--port", type=int, default=9876, help="Bridge port")
    parser.add_argument(
        "--timeout", type=float, default=10.0, help="Socket timeout in seconds"
    )
    return parser.parse_args()


def send_request(
    host: str, port: int, command: str, params: dict[str, Any], timeout: float
) -> dict[str, Any]:
    request = {
        "id": str(uuid.uuid4()),
        "command": command,
        "params": params,
    }
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buffer = b""
        while b"\n" not in buffer:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError(
                    "Connection closed before a full response arrived"
                )
            buffer += chunk
    line = buffer.split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))


def main() -> int:
    args = parse_args()
    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as exc:
        print(f"Invalid --params JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(params, dict):
        print("--params must decode to a JSON object", file=sys.stderr)
        return 2

    try:
        response = send_request(
            args.host, args.port, args.command, params, args.timeout
        )
    except OSError as exc:
        print(f"Bridge request failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(response, indent=2))
    return 0 if response.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
