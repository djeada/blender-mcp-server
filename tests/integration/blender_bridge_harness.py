"""Enable the Blender add-on and drive its real queue in background Blender."""

import importlib.util
import os
import sys
import time

ADDON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir, "addon")
if os.environ.get("BLENDER_MCP_USE_INSTALLED") == "1":
    addon = next(
        module
        for name, module in tuple(sys.modules.items())
        if name.split(".")[-1] == "blender_mcp_bridge" and hasattr(module, "BRIDGE_API_VERSION")
    )
else:
    spec = importlib.util.spec_from_file_location(
        "blender_mcp_bridge", os.path.join(ADDON_DIR, "__init__.py"), submodule_search_locations=[ADDON_DIR]
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules["blender_mcp_bridge"] = addon
    spec.loader.exec_module(addon)
    addon.register()

runtime = sys.modules[f"{addon.__name__}.runtime"].runtime
server = runtime.server
assert server and server.running
print(f"BRIDGE_READY protocol={addon.BRIDGE_API_VERSION} module={addon.__name__}", flush=True)

# Background Blender doesn't revisit app timers after its startup script.
# Drain the registered callback on this main thread. Blender invokes its real file-load handlers.
deadline = time.monotonic() + float(os.environ.get("HARNESS_LIFETIME", "300"))
while time.monotonic() < deadline:
    server._drain_request_queue()
    for job_id, job in list(runtime.handler.jobs._jobs.items()):
        if job["status"] == "queued":
            runtime.handler.jobs._execute_job(job_id)
    time.sleep(0.005)
