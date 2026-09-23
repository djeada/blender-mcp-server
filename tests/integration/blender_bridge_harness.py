"""Run inside ``blender -b``: load the add-on from the repo and serve the bridge.

Background Blender does not run app timers once the startup script returns, so
this loop drains the request queue and runs async jobs itself until the parent
test kills it.
"""

import importlib.util
import os
import sys
import time

ADDON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "addon")
spec = importlib.util.spec_from_file_location(
    "blender_mcp_bridge", os.path.join(ADDON_DIR, "__init__.py"), submodule_search_locations=[ADDON_DIR]
)
addon = importlib.util.module_from_spec(spec)
sys.modules["blender_mcp_bridge"] = addon
spec.loader.exec_module(addon)

addon.PORT = int(os.environ["BLENDER_MCP_PORT"])
server = addon.BlenderMCPServer()
server.start()
print("BRIDGE_READY", flush=True)

deadline = time.monotonic() + float(os.environ.get("HARNESS_LIFETIME", "300"))
while time.monotonic() < deadline:
    server._drain_request_queue()
    # Stand-in for bpy.app.timers: run queued async jobs on this (main) thread.
    queued = [job_id for job_id, job in list(addon._job_manager._jobs.items()) if job["status"] == "queued"]
    for job_id in queued:
        addon._job_manager._execute_job(job_id)
    time.sleep(0.005)
