#!/usr/bin/env python3
"""Drive dam-break demo scenes through the Blender MCP bridge.

This script connects directly to the Blender add-on TCP bridge and sends a
sequence of ``python.execute`` commands that build the scene step-by-step.
It supports two modes:

* ``procedural``: stable, visible flood animation built from a procedural mesh
  sequence. This is the default for Blender 4.0.x.
* ``mantaflow``: the original experimental Mantaflow blockout pipeline.

Usage::

    # Start Blender with the MCP add-on enabled, then:
    python3 scripts/demos/run_dam_break.py

    # With custom library path:
    python3 scripts/demos/run_dam_break.py --library /path/to/scripts/library

    # Dry-run — print commands without sending:
    python3 scripts/demos/run_dam_break.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 9876
TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# Bridge communication
# ---------------------------------------------------------------------------

def send_command(
    command: str,
    params: dict[str, Any],
    *,
    host: str = BRIDGE_HOST,
    port: int = BRIDGE_PORT,
    timeout: float = TIMEOUT,
) -> dict[str, Any]:
    """Send a single command to the Blender bridge and return the response."""
    request = {"id": str(uuid.uuid4()), "command": command, "params": params}
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("Connection closed before response")
            buf += chunk
    return json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))


def exec_inline(code: str, args: dict | None = None, **kw: Any) -> dict:
    """Execute inline Python code through the bridge."""
    params: dict[str, Any] = {"code": code}
    if args:
        params["args"] = args
    return send_command("python.execute", params, **kw)


def exec_script(script_path: str, args: dict | None = None, **kw: Any) -> dict:
    """Execute a local library script through the bridge as inline code.

    This avoids dependence on the Blender add-on's approved script root
    configuration for local demo runs.
    """
    code = Path(script_path).read_text()
    return exec_inline(code, args, **kw)


def exec_async(code: str, args: dict | None = None, **kw: Any) -> dict:
    """Start an async job through the bridge."""
    params: dict[str, Any] = {"code": code}
    if args:
        params["args"] = args
    return send_command("python.execute_async", params, **kw)


def job_status(job_id: str, **kw: Any) -> dict:
    """Query job status."""
    return send_command("job.status", {"job_id": job_id}, **kw)


def render_still(output_path: str, **kw: Any) -> dict:
    """Render a still frame."""
    return send_command("render.still", {"output_path": output_path}, **kw)


# ---------------------------------------------------------------------------
# Step definitions
# ---------------------------------------------------------------------------

def build_steps(library_dir: str) -> list[dict[str, Any]]:
    """Return the ordered list of demo steps."""
    lib = Path(library_dir)

    return [
        # --- Step 1: Clear scene & set frame range --------------------------
        {
            "label": "Clear scene and set frame range",
            "method": "inline",
            "code": (
                "import bpy\n"
                "bpy.ops.object.select_all(action='SELECT')\n"
                "bpy.ops.object.delete(use_global=False)\n"
            ),
        },
        {
            "label": "Set frame range 1–120 at 24 fps",
            "method": "script",
            "script_path": str(lib / "frame_range.py"),
            "args": {"frame_start": 1, "frame_end": 120, "fps": 24},
        },

        # --- Step 2: Street blockout ----------------------------------------
        {
            "label": "Create ground plane (street)",
            "method": "inline",
            "code": (
                "obj = mcp_create_mesh('plane', name='Ground', location=(0,0,0), size=20)\n"
                "__result__ = {'object': obj.name}\n"
            ),
        },
        {
            "label": "Create buildings",
            "method": "inline",
            "code": (
                "buildings = [\n"
                "    ('Building_A', (3,2,2),    (1,1.5,2)),\n"
                "    ('Building_B', (-2,-1,2.5),(1.25,1,2.5)),\n"
                "    ('Building_C', (1,-4,1.5), (0.9,2,1.5)),\n"
                "]\n"
                "names = []\n"
                "for name, loc, scl in buildings:\n"
                "    obj = mcp_create_mesh('cube', name=name, location=loc, size=2.0)\n"
                "    obj.scale = scl\n"
                "    names.append(obj.name)\n"
                "__result__ = {'buildings': names}\n"
            ),
        },

        # --- Step 3: Debris objects -----------------------------------------
        {
            "label": "Create debris props",
            "method": "inline",
            "code": (
                "debris = [\n"
                "    ('Debris_Crate',  (2,-2,0.4), 0.8),\n"
                "    ('Debris_Barrel', (-1,1,0.5), 0.6),\n"
                "]\n"
                "names = []\n"
                "for name, loc, size in debris:\n"
                "    obj = mcp_create_mesh('cube', name=name, location=loc, size=size)\n"
                "    names.append(obj.name)\n"
                "__result__ = {'debris': names}\n"
            ),
        },

        # --- Step 4: Rigid bodies -------------------------------------------
        {
            "label": "Add rigid bodies to debris",
            "method": "script",
            "script_path": str(lib / "rigid_body.py"),
            "args": {
                "objects": ["Debris_Crate", "Debris_Barrel"],
                "rb_type": "ACTIVE",
                "mass": 5.0,
                "collision_shape": "BOX",
            },
        },

        # --- Step 5: Fluid domain -------------------------------------------
        {
            "label": "Create fluid domain (res 32)",
            "method": "script",
            "script_path": str(lib / "fluid_domain.py"),
            "args": {
                "domain_name": "FluidDomain",
                "location": [0, 0, 5],
                "size": 22,
                "resolution": 32,
                "cache_dir": "//fluid_cache",
            },
        },

        # --- Step 6: Inflow source ------------------------------------------
        {
            "label": "Create water inflow",
            "method": "script",
            "script_path": str(lib / "fluid_inflow.py"),
            "args": {
                "name": "WaterInflow",
                "location": [8, 0, 3],
                "size": 3,
                "flow_type": "LIQUID",
                "flow_behavior": "INFLOW",
                "use_initial_velocity": True,
                "initial_velocity": [-4, 0, 0],
            },
        },

        # --- Step 7: Colliders ----------------------------------------------
        {
            "label": "Set ground & buildings as colliders",
            "method": "script",
            "script_path": str(lib / "effector.py"),
            "args": {
                "objects": ["Ground", "Building_A", "Building_B", "Building_C"],
            },
        },

        # --- Step 8: Camera -------------------------------------------------
        {
            "label": "Create camera",
            "method": "script",
            "script_path": str(lib / "camera.py"),
            "args": {
                "name": "DamBreakCam",
                "location": [15, -12, 8],
                "rotation": [1.0472, 0, 0.8727],  # ~60°, 0°, 50° in radians
                "focal_length": 35,
                "set_active": True,
            },
        },

        # --- Step 9: Camera keyframes ---------------------------------------
        {
            "label": "Animate camera dolly",
            "method": "script",
            "script_path": str(lib / "keyframes.py"),
            "args": {
                "keyframes": [
                    {"object": "DamBreakCam", "frame": 1,
                     "location": [15, -12, 8],
                     "rotation": [1.0472, 0, 0.8727]},
                    {"object": "DamBreakCam", "frame": 60,
                     "location": [6, -10, 5],
                     "rotation": [1.1345, 0, 0.5236]},
                    {"object": "DamBreakCam", "frame": 120,
                     "location": [0, -8, 3],
                     "rotation": [1.2217, 0, 0.1745]},
                ],
            },
        },

        # --- Step 10: Collections -------------------------------------------
        {
            "label": "Organize into collections",
            "method": "script",
            "script_path": str(lib / "collections.py"),
            "args": {
                "collections": [
                    {"name": "Buildings", "objects": ["Building_A", "Building_B", "Building_C"]},
                    {"name": "Debris",    "objects": ["Debris_Crate", "Debris_Barrel"]},
                    {"name": "Fluid",     "objects": ["FluidDomain", "WaterInflow"]},
                    {"name": "Environment", "objects": ["Ground"]},
                    {"name": "Camera",    "objects": ["DamBreakCam"]},
                ],
            },
        },

        # --- Step 11: Render settings ---------------------------------------
        {
            "label": "Set EEVEE preview render settings",
            "method": "inline",
            "code": (
                "import bpy\n"
                "s = bpy.context.scene\n"
                "s.render.engine = 'BLENDER_EEVEE'\n"
                "s.render.resolution_x = 960\n"
                "s.render.resolution_y = 540\n"
                "s.render.filepath = '//dam_break_preview'\n"
                "__result__ = {\n"
                "    'engine': s.render.engine,\n"
                "    'resolution': [960, 540],\n"
                "}\n"
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_mantaflow_demo(
    host: str,
    port: int,
    library_dir: str,
    *,
    dry_run: bool = False,
    bake: bool = False,
    render: bool = False,
    render_output: str = "/tmp/dam_break_preview.png",
) -> int:
    steps = build_steps(library_dir)
    ok = True

    for i, step in enumerate(steps, 1):
        label = step["label"]
        print(f"\n{'─' * 60}")
        print(f"  Step {i}/{len(steps)}: {label}")
        print(f"{'─' * 60}")

        if dry_run:
            method = step["method"]
            if method == "inline":
                print(f"  [dry-run] inline code ({len(step['code'])} chars)")
            else:
                print(f"  [dry-run] script: {step['script_path']}")
                print(f"  [dry-run] args: {json.dumps(step.get('args', {}), indent=4)}")
            continue

        t0 = time.monotonic()
        try:
            if step["method"] == "inline":
                resp = exec_inline(step["code"], step.get("args"), host=host, port=port)
            else:
                resp = exec_script(step["script_path"], step.get("args"), host=host, port=port)
        except Exception as exc:
            print(f"  ✗ Connection error: {exc}")
            ok = False
            continue

        elapsed = time.monotonic() - t0

        if resp.get("success"):
            result = resp.get("result", {})
            inner_error = result.get("error") if isinstance(result, dict) else None
            if inner_error:
                print(f"  ✗ SCRIPT ERROR ({elapsed:.2f}s): {inner_error}")
                ok = False
                break

            print(f"  ✓ OK ({elapsed:.2f}s)")
            if isinstance(result, dict):
                for k, v in result.items():
                    print(f"    {k}: {v}")
            elif result is not None:
                print(f"    result: {result}")
        else:
            print(f"  ✗ FAILED ({elapsed:.2f}s): {resp.get('error', 'unknown')}")
            ok = False
            break
    # Optional: fluid bake (async) ------------------------------------------
    if bake and not dry_run:
        print(f"\n{'─' * 60}")
        print(f"  Baking fluid simulation (async)...")
        print(f"{'─' * 60}")
        try:
            resp = exec_async(
                "import bpy\nbpy.ops.fluid.bake_all()\n__result__ = {'baked': True}",
                host=host, port=port,
            )
            if resp.get("success"):
                job_id = resp["result"]["job_id"]
                print(f"  Job started: {job_id}")
                # Poll until done
                while True:
                    time.sleep(5)
                    status_resp = job_status(job_id, host=host, port=port)
                    st = status_resp.get("result", {}).get("status", "unknown")
                    print(f"    status: {st}")
                    if st in ("succeeded", "failed", "cancelled"):
                        break
            else:
                print(f"  ✗ Bake failed: {resp.get('error')}")
                ok = False
        except Exception as exc:
            print(f"  ✗ Bake error: {exc}")
            ok = False

    # Optional: render preview ----------------------------------------------
    if render and not dry_run:
        print(f"\n{'─' * 60}")
        print(f"  Rendering preview still...")
        print(f"{'─' * 60}")
        try:
            resp = render_still(render_output, host=host, port=port, timeout=120.0)
            if resp.get("success"):
                print(f"  ✓ Rendered to {resp['result'].get('output_path', render_output)}")
            else:
                print(f"  ✗ Render failed: {resp.get('error')}")
                ok = False
        except Exception as exc:
            print(f"  ✗ Render error: {exc}")
            ok = False

    # Summary ---------------------------------------------------------------
    print(f"\n{'═' * 60}")
    if dry_run:
        print(f"  Dry run complete — {len(steps)} steps printed")
    elif ok:
        print(f"  ✓ Mantaflow dam-break scene built successfully ({len(steps)} steps)")
    else:
        print(f"  ✗ Some steps failed — check output above")
    print(f"{'═' * 60}\n")

    return 0 if ok else 1


def run_procedural_demo(
    host: str,
    port: int,
    *,
    dry_run: bool = False,
    render: bool = False,
    render_output: str = "/tmp/dam_break_preview.png",
) -> int:
    scene_script = Path(__file__).resolve().parent / "procedural_dam_break_scene.py"
    print(f"\n{'═' * 60}")
    print("  Procedural dam-break demo")
    print(f"{'═' * 60}")

    if dry_run:
        print(f"  [dry-run] script: {scene_script}")
        return 0

    try:
        response = exec_script(str(scene_script), {"frame_end": 120}, host=host, port=port, timeout=120.0)
    except Exception as exc:
        print(f"  ✗ Connection error: {exc}")
        return 1

    if not response.get("success"):
        print(f"  ✗ FAILED: {response.get('error', 'unknown')}")
        return 1

    result = response.get("result", {})
    inner_error = result.get("error") if isinstance(result, dict) else None
    if inner_error:
        print(f"  ✗ SCRIPT ERROR: {inner_error}")
        return 1

    print("  ✓ Scene built")
    if isinstance(result, dict):
        for key, value in result.items():
            print(f"    {key}: {value}")

    if render:
        print(f"\n{'─' * 60}")
        print("  Rendering preview still...")
        print(f"{'─' * 60}")
        try:
            resp = render_still(render_output, host=host, port=port, timeout=120.0)
            if resp.get("success"):
                print(f"  ✓ Rendered to {resp['result'].get('output_path', render_output)}")
            else:
                print(f"  ✗ Render failed: {resp.get('error')}")
                return 1
        except Exception as exc:
            print(f"  ✗ Render error: {exc}")
            return 1

    print(f"\n{'═' * 60}")
    print("  ✓ Procedural dam-break scene built successfully")
    print(f"{'═' * 60}\n")
    return 0


def run_demo(*args: Any, **kwargs: Any) -> int:
    """Backward-compatible alias for the original Mantaflow demo runner."""
    return run_mantaflow_demo(*args, **kwargs)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    default_library = str(
        Path(__file__).resolve().parent.parent / "library"
    )

    parser = argparse.ArgumentParser(
        description="Build a dam-break demo scene through the Blender MCP bridge."
    )
    parser.add_argument("--host", default=BRIDGE_HOST)
    parser.add_argument("--port", type=int, default=BRIDGE_PORT)
    parser.add_argument("--library", default=default_library,
                        help="Path to scripts/library/ directory")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print commands without sending")
    parser.add_argument("--bake", action="store_true",
                        help="Trigger fluid bake after scene setup")
    parser.add_argument("--render", action="store_true",
                        help="Render a preview still after setup")
    parser.add_argument("--render-output", default="/tmp/dam_break_preview.png",
                        help="Output path for the preview render")
    parser.add_argument(
        "--simulation",
        choices=("procedural", "mantaflow"),
        default="procedural",
        help="Scene generation mode. 'procedural' is the stable default for Blender 4.0.x.",
    )
    args = parser.parse_args()

    if args.simulation == "procedural":
        return run_procedural_demo(
            args.host,
            args.port,
            dry_run=args.dry_run,
            render=args.render,
            render_output=args.render_output,
        )

    return run_mantaflow_demo(
        args.host,
        args.port,
        args.library,
        dry_run=args.dry_run,
        bake=args.bake,
        render=args.render,
        render_output=args.render_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
