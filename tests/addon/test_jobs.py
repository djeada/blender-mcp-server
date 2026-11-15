"""Tests for Blender jobs behavior."""

import pytest


class TestJobLifecycle:
    """Tests for MCP-104 async job support."""

    def test_execute_async_returns_job_id(self, handler):
        result = handler.handle(
            "python.execute_async",
            {
                "code": "__result__ = 'done'",
            },
        )
        assert "job_id" in result
        assert result["job_id"].startswith("job-")

    def test_job_status_for_unknown_job(self, handler):
        with pytest.raises(ValueError, match="Unknown job"):
            handler.handle("job.status", {"job_id": "job-nonexistent"})

    def test_job_list_returns_jobs(self, handler):
        result1 = handler.handle("python.execute_async", {"code": "pass"})
        listing = handler.handle("job.list", {})
        job_ids = [j["job_id"] for j in listing["jobs"]]
        assert result1["job_id"] in job_ids

    def test_job_cancel_sets_cancelled(self, handler):
        result = handler.handle(
            "python.execute_async",
            {
                "code": "import time; time.sleep(10)",
            },
        )
        job_id = result["job_id"]
        cancel_result = handler.handle("job.cancel", {"job_id": job_id})
        assert cancel_result["status"] == "cancelled"
        assert cancel_result["cancellation_requested"] is True

    def test_job_cancel_running_marks_request_only(self, handler, runtime):
        result = handler.handle("python.execute_async", {"code": "pass"})
        job_id = result["job_id"]
        with runtime.handler.jobs._lock:
            runtime.handler.jobs._jobs[job_id]["status"] = "running"

        cancel_result = handler.handle("job.cancel", {"job_id": job_id})

        assert cancel_result["status"] == "running"
        assert cancel_result["cancellation_requested"] is True

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "running"
        assert status["cancellation_requested"] is True

    def test_job_cancel_unknown_raises(self, handler):
        with pytest.raises(ValueError, match="Unknown job"):
            handler.handle("job.cancel", {"job_id": "job-nope"})

    def test_job_status_after_sync_execution(self, handler, runtime):
        """Run the job via the timer callback and verify completion."""
        result = handler.handle(
            "python.execute_async",
            {
                "code": "__result__ = 'async_done'",
            },
        )
        job_id = result["job_id"]

        # Manually trigger the timer callback that executes the job
        runtime.handler.jobs._execute_job(job_id)

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "succeeded"
        assert status["result"] == "async_done"
        assert status["error"] is None

    def test_failed_job_captures_error(self, handler, runtime):
        result = handler.handle(
            "python.execute_async",
            {
                "code": "raise RuntimeError('async boom')",
            },
        )
        job_id = result["job_id"]

        runtime.handler.jobs._execute_job(job_id)

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "failed"
        assert "RuntimeError" in status["error"]
        assert "async boom" in status["error"]

    def test_job_status_missing_id_raises(self, handler):
        with pytest.raises(ValueError, match="job_id"):
            handler.handle("job.status", {})


class TestExecutionControl:
    def test_sync_timeout_is_enforced(self, handler):
        result = handler.handle(
            "python.execute",
            {
                "code": "while True:\n    pass",
                "timeout_seconds": 0.01,
            },
        )
        assert result["timed_out"] is True
        assert result["cancelled"] is False
        assert "timeout" in result["error"].lower()

    def test_async_cancellation_propagates_to_final_status(self, handler, runtime):
        result = handler.handle(
            "python.execute_async",
            {
                "code": (
                    "while True:\n    if __cancel_event__.is_set():\n        raise RuntimeError('stop requested')\n"
                ),
                "timeout_seconds": 1,
            },
        )
        job_id = result["job_id"]
        runtime.handler.jobs.cancel(job_id)
        runtime.handler.jobs._execute_job(job_id)

        status = handler.handle("job.status", {"job_id": job_id})
        assert status["status"] == "cancelled"
        assert status["cancellation_requested"] is True
