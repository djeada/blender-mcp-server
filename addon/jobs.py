"""Thread-safe lifecycle of asynchronous jobs executed on Blender's main thread."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import TYPE_CHECKING, Any

import bpy

from .execution import DEFAULT_ASYNC_TIMEOUT, MAX_ASYNC_TIMEOUT, truncate

if TYPE_CHECKING:
    from .execution import ScriptExecutor

logger = logging.getLogger(__name__)
MAX_FINISHED_JOBS = 100


class JobManager:
    """Manages async job lifecycle for long-running Blender scripts."""

    def __init__(self, executor: ScriptExecutor):
        self.executor = executor
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def create_job(
        self,
        code: str,
        args: dict,
        timeout_seconds: float,
    ) -> str:
        job_id = f"job-{uuid.uuid4().hex[:8]}"
        now = time.time()
        cancel_event = threading.Event()

        job = {
            "job_id": job_id,
            "status": "queued",
            "cancellation_requested": False,
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "result": None,
            "stdout": "",
            "stderr": "",
            "error": None,
            "code": code,
            "args": args,
            "timeout_seconds": timeout_seconds,
            "cancel_event": cancel_event,
        }

        with self._lock:
            self._prune_finished_jobs()
            self._jobs[job_id] = job

        bpy.app.timers.register(lambda: self._execute_job(job_id), first_interval=0.01)
        return job_id

    def _prune_finished_jobs(self) -> None:
        """Drop the oldest finished jobs so the job table cannot grow without bound. Caller holds the lock."""
        finished = [j for j in self._jobs.values() if j["status"] in {"succeeded", "failed", "cancelled"}]
        excess = len(finished) - MAX_FINISHED_JOBS + 1
        for job in sorted(finished, key=lambda j: j["created_at"])[: max(excess, 0)]:
            del self._jobs[job["job_id"]]

    @staticmethod
    def _release_job_inputs(job: dict[str, Any]) -> None:
        """Free the script source and arguments once a job can no longer run. Caller holds the lock."""
        job["code"] = None
        job["args"] = None

    def _execute_job(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job or job["status"] != "queued":
                return
            job["status"] = "running"
            job["started_at"] = time.time()

        logger.info("Job [%s] running", job_id)

        cancel_event = job["cancel_event"]
        if cancel_event.is_set():
            with self._lock:
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                self._release_job_inputs(job)
            logger.info("Job [%s] cancelled before start", job_id)
            return

        namespace = self.executor.make_namespace(job["args"], cancel_event)
        result = self.executor.run_code(
            job["code"],
            namespace,
            job["timeout_seconds"],
            job_id,
            cancel_event=cancel_event,
        )

        with self._lock:
            job["result"] = result.get("result")
            job["stdout"] = result.get("stdout", "")
            job["stderr"] = result.get("stderr", "")
            job["error"] = result.get("error")
            if result.get("cancelled") or cancel_event.is_set():
                job["status"] = "cancelled"
            else:
                job["status"] = "failed" if result.get("error") else "succeeded"
            job["completed_at"] = time.time()
            self._release_job_inputs(job)

        elapsed = (job["completed_at"] - job["started_at"]) if job["started_at"] else 0
        logger.info("Job [%s] %s in %.3fs", job_id, job["status"], elapsed)

        self.executor.last_execution = {
            "request_id": job_id,
            "source": "async job",
            "status": job["status"],
            "duration_seconds": round(elapsed, 4),
            "error_summary": truncate(job["error"], 200) if job.get("error") else None,
        }

    def get_status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError(f"Unknown job: {job_id}")
            return {
                "job_id": job["job_id"],
                "status": job["status"],
                "cancellation_requested": job["cancellation_requested"],
                "created_at": job["created_at"],
                "started_at": job["started_at"],
                "completed_at": job["completed_at"],
                "result": job["result"],
                "stdout": job["stdout"],
                "stderr": job["stderr"],
                "error": job["error"],
            }

    def cancel(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                raise ValueError(f"Unknown job: {job_id}")

            job["cancel_event"].set()
            job["cancellation_requested"] = True

            if job["status"] == "queued":
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                self._release_job_inputs(job)

            status = job["status"]
            cancellation_requested = job["cancellation_requested"]

        return {
            "job_id": job_id,
            "status": status,
            "cancellation_requested": cancellation_requested,
        }

    def list_jobs(self) -> dict:
        with self._lock:
            jobs = [
                {
                    "job_id": j["job_id"],
                    "status": j["status"],
                    "created_at": j["created_at"],
                }
                for j in self._jobs.values()
            ]
        return {"jobs": jobs}

    def execute_async(self, params: dict) -> dict:
        code, source_label = self.executor.prepare_source(params)
        timeout = min(params.get("timeout_seconds", DEFAULT_ASYNC_TIMEOUT), MAX_ASYNC_TIMEOUT)
        job_id = self.create_job(code, params.get("args", {}), timeout)
        logger.info("python.execute_async [%s] queued: %s", job_id, source_label)
        return {"job_id": job_id}
