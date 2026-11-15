"""MCP tools for execution."""

import json
import logging

from mcp.server.fastmcp import Context

from blender_mcp_server.app import HEADLESS_JOB_MANAGER, Transport, bridge, get_connection, headless_executor, mcp
from blender_mcp_server.headless import validate_source

logger = logging.getLogger(__name__)


@mcp.tool(
    name="blender_python_exec",
    description=(
        "Execute a Python script in Blender's context synchronously. "
        "Provide either 'code' (inline Python string) or 'script_path' (path to a .py file), not both. "
        "The script has access to 'bpy', 'mathutils', and an 'args' dict with your supplied arguments. "
        "Set '__result__' in the script to return a JSON-serializable value. "
        "Returns the result, captured stdout/stderr, and execution duration. "
        "Use transport='bridge' for the live Blender add-on session, or transport='headless' to run the script "
        "in a separate `blender -b` process. For long-running tasks like baking, use blender_python_exec_async."
    ),
)
async def python_exec(
    ctx: Context,
    code: str | None = None,
    script_path: str | None = None,
    args: dict | None = None,
    timeout_seconds: int | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        result = await (await headless_executor(ctx, "python.execute")).execute(
            code=code,
            script_path=script_path,
            args=args,
            timeout_seconds=timeout_seconds,
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps(result, indent=2)
    return await bridge(
        ctx,
        "python.execute",
        code=code,
        script_path=script_path,
        args=args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(
    name="blender_python_exec_async",
    description=(
        "Start a long-running Python script in Blender asynchronously. "
        "Same parameters as blender_python_exec. Returns a job_id immediately. "
        "Use blender_job_status to poll for completion, and blender_job_cancel to abort. "
        "The script can check '__cancel_event__.is_set()' to detect cancellation. "
        "Ideal for fluid baking, rigid body simulation, or heavy scene generation. "
        "Note: bridge jobs run on Blender's main thread, so the Blender UI is busy while they run. "
        "Use transport='headless' to run the job in a separate background Blender process instead."
    ),
)
async def python_exec_async(
    ctx: Context,
    code: str | None = None,
    script_path: str | None = None,
    args: dict | None = None,
    timeout_seconds: int | None = None,
    transport: Transport = "bridge",
    blend_file: str | None = None,
    factory_startup: bool | None = None,
) -> str:
    if transport == "headless":
        validate_source(code, script_path)
        job_id = await HEADLESS_JOB_MANAGER.create_job(
            await headless_executor(ctx, "python.execute_async"),
            code=code,
            script_path=script_path,
            args=args,
            timeout_seconds=timeout_seconds,
            blend_file=blend_file,
            factory_startup=factory_startup,
        )
        return json.dumps({"job_id": job_id}, indent=2)
    return await bridge(
        ctx,
        "python.execute_async",
        code=code,
        script_path=script_path,
        args=args,
        timeout_seconds=timeout_seconds,
    )


@mcp.tool(
    name="blender_job_status",
    description=(
        "Get the status of an async Blender job. Returns job_id, status "
        "(queued/running/succeeded/failed/cancelled), timestamps, result, stdout, stderr, and error. "
        "Poll this after starting a job with blender_python_exec_async."
    ),
)
async def job_status(ctx: Context, job_id: str) -> str:
    if job_id.startswith("headless-job-"):
        config = get_connection(ctx).policy
        config.require_transport("headless")
        config.require_command("job.status")
        return json.dumps(HEADLESS_JOB_MANAGER.get_status(job_id), indent=2)
    return await bridge(ctx, "job.status", job_id=job_id)


@mcp.tool(
    name="blender_job_cancel",
    description=(
        "Cancel a running or queued async Blender job. "
        "The job's __cancel_event__ is set; scripts that check it will stop gracefully."
    ),
)
async def job_cancel(ctx: Context, job_id: str) -> str:
    if job_id.startswith("headless-job-"):
        config = get_connection(ctx).policy
        config.require_transport("headless")
        config.require_command("job.cancel")
        return json.dumps(await HEADLESS_JOB_MANAGER.cancel(job_id), indent=2)
    return await bridge(ctx, "job.cancel", job_id=job_id)


@mcp.tool(
    name="blender_job_list",
    description="List known async Blender jobs with their IDs, statuses, and creation timestamps.",
)
async def job_list(ctx: Context) -> str:
    connection = get_connection(ctx)
    connection.policy.require_command("job.list")
    headless = "headless" in connection.policy.transports
    jobs = HEADLESS_JOB_MANAGER.list_jobs()["jobs"] if headless else []
    if "bridge" in connection.policy.transports:
        try:
            bridge_result = await connection.send_command("job.list")
            jobs = bridge_result.get("jobs", []) + jobs
        except Exception as exc:
            if not headless:
                raise
            logger.info("Bridge job list unavailable: %s", exc)
    return json.dumps({"jobs": jobs}, indent=2)
