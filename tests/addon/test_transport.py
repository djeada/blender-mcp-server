"""Tests for Blender transport behavior."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest


class TestServerExecution:
    @pytest.mark.parametrize("denied", [False, True], ids=["invalid-parameters", "not-allowed"])
    def test_rejected_mutations_do_not_push_undo(self, runtime, mock_bpy, denied):
        mock_bpy.ops.ed.undo_push.poll.return_value = True
        if denied:
            runtime.settings.tool_whitelist = {"scene.get_info"}
        params = {"name": "Cube", "offset": [1, 2, 3] if denied else [1]}
        response = runtime.create_server()._process_request({"command": "object.translate", "params": params})
        assert response["success"] is False
        mock_bpy.ops.ed.undo_push.assert_not_called()

    def test_mutation_request_skips_undo_when_poll_fails(self, mock_bpy, runtime):
        server = runtime.create_server()
        request = {
            "id": "1",
            "command": "object.translate",
            "params": {"name": "Cube", "offset": [1, 2, 3]},
        }

        result = server._process_request(request)

        assert result["success"] is True
        mock_bpy.ops.ed.undo_push.assert_not_called()

    def test_submit_request_runs_through_queue(self, runtime):
        server = runtime.create_server()
        server._running = True
        request = {"id": "abc", "command": "scene.get_info", "params": {}}
        expected = {"id": "abc", "success": True, "result": {"ok": True}}
        response_holder = {}

        with patch.object(server, "_process_request", return_value=expected) as process:
            worker = threading.Thread(
                target=lambda: response_holder.setdefault("response", server._submit_request(request))
            )
            worker.start()
            _wait_until(lambda: server._request_queue)
            server._drain_request_queue()
            worker.join(timeout=1)

        assert response_holder["response"] == expected
        process.assert_called_once_with(request)

    def test_request_queue_timer_is_registered_persistent(self, mock_bpy, runtime):
        server = runtime.create_server()

        server._register_request_queue_timer()

        mock_bpy.app.timers.register.assert_called_once_with(
            server._drain_timer_callback,
            first_interval=0.01,
            persistent=True,
        )

    def test_ensure_server_running_reregisters_timer_for_healthy_server(self, runtime):
        server = runtime.create_server()
        server._running = True
        server._server_socket = object()
        server._thread = MagicMock()
        server._thread.is_alive.return_value = True
        server._register_request_queue_timer = MagicMock()
        runtime.server = server

        result = runtime.ensure_server_running()

        assert result is None
        server._register_request_queue_timer.assert_called_once_with()

    def test_python_execute_does_not_auto_push_undo(self, mock_bpy, runtime):
        server = runtime.create_server()
        request = {
            "id": "2",
            "command": "python.execute",
            "params": {"code": "__result__ = 1"},
        }

        result = server._process_request(request)

        assert result["success"] is True
        mock_bpy.ops.ed.undo_push.assert_not_called()


class TestBridgeProtocolSecurity:
    """Connection-level auth and framing for the TCP bridge."""

    def _serve(self, runtime, payload: bytes, *, max_request_size=16 * 1024 * 1024) -> list[dict]:
        import json
        import socket

        server = runtime.create_server()
        server._running = True
        server._auth_token = "secret"
        server.max_request_size = max_request_size
        client, bridge_side = socket.socketpair()
        with patch.object(
            server, "_submit_request", side_effect=lambda r: {"id": r.get("id"), "success": True, "result": "ran"}
        ):
            worker = threading.Thread(target=server._handle_client, args=(bridge_side,))
            worker.start()
            client.sendall(payload)
            client.shutdown(socket.SHUT_WR)
            worker.join(timeout=2)
        data = b""
        while chunk := client.recv(65536):
            data += chunk
        client.close()
        return [json.loads(line) for line in data.splitlines() if line.strip()]

    def test_authorized_request_is_processed(self, runtime):
        responses = self._serve(runtime, b'{"id": "1", "command": "scene.get_info", "token": "secret"}\n')
        assert responses == [{"id": "1", "success": True, "result": "ran"}]

    def test_missing_or_wrong_token_is_rejected(self, runtime):
        for token_part in (b"", b', "token": "wrong"'):
            payload = b'{"id": "1", "command": "python.execute"' + token_part + b"}\n"
            responses = self._serve(runtime, payload)
            assert len(responses) == 1
            assert responses[0]["success"] is False
            assert "Unauthorized" in responses[0]["error"]

    def test_http_smuggled_command_is_not_executed(self, runtime):
        """A browser POST whose body is a JSON command must never reach the handler."""
        body = b'{"id": "x", "command": "python.execute", "params": {"code": "pass"}, "token": "secret"}\n'
        http = b"POST / HTTP/1.1\r\nHost: 127.0.0.1:9876\r\nContent-Type: text/plain\r\n\r\n" + body
        responses = self._serve(runtime, http)
        assert len(responses) == 1
        assert "Invalid JSON" in responses[0]["error"]

    def test_non_object_request_closes_connection(self, runtime):
        responses = self._serve(runtime, b"[1, 2]\n" + b'{"id": "1", "token": "secret"}\n')
        assert len(responses) == 1
        assert responses[0]["success"] is False

    def test_oversized_request_is_rejected(self, runtime):
        responses = self._serve(runtime, b"x" * 2048, max_request_size=1024)
        assert "exceeds" in responses[0]["error"]

    def test_oversized_complete_frame_is_rejected(self, runtime):
        responses = self._serve(runtime, b"x" * 2048 + b"\n", max_request_size=1024)
        assert len(responses) == 1
        assert "exceeds" in responses[0]["error"]

    def test_oversized_partial_frame_after_valid_request_is_rejected(self, runtime):
        frame = b'{"id":"1","command":"scene.get_info","token":"secret"}\n'
        responses = self._serve(runtime, frame + b"x" * 2048, max_request_size=1024)
        assert responses[0]["success"] is True
        assert "exceeds" in responses[1]["error"]

    def test_size_limit_applies_to_each_frame(self, runtime):
        frame = b'{"id":"1","command":"scene.get_info","token":"secret"}\n'
        responses = self._serve(runtime, frame * 2, max_request_size=len(frame))
        assert len(responses) == 2
        assert all(response["success"] for response in responses)

    def test_token_file_created_private(self, addon_module, monkeypatch, tmp_path):
        monkeypatch.delenv("BLENDER_MCP_TOKEN")
        token_file = tmp_path / "sub" / "token"
        monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(token_file))
        token = addon_module.auth.load_or_create_token()
        assert token_file.read_text() == token
        assert (token_file.stat().st_mode & 0o777) == 0o600
        assert addon_module.auth.load_or_create_token() == token  # reused, not rotated


class TestBridgeRobustness:
    def test_system_exit_in_script_is_contained(self, handler):
        result = handler.handle("python.execute", {"code": "raise SystemExit(3)"})
        assert "SystemExit" in result["error"]

    def test_script_cannot_swallow_timeout(self, handler):
        code = "while True:\n    try:\n        pass\n    except Exception:\n        pass\n"
        result = handler.handle("python.execute", {"code": code, "timeout_seconds": 0.05})
        assert result["timed_out"] is True

    def test_drain_always_answers_waiting_client(self, runtime):
        server = runtime.create_server()
        server._running = True
        with ThreadPoolExecutor() as workers:
            waiting = workers.submit(server._submit_request, {"id": "9", "command": "scene.get_info"})
            _wait_until(lambda: server._request_queue)
            with patch.object(server, "_process_request", side_effect=KeyboardInterrupt()):
                server._drain_request_queue()
            assert waiting.result(timeout=1)["error_details"]["code"] == "command_failed"

    def test_job_commands_bypass_main_thread_queue(self, runtime):
        """job.status/cancel must work while an async job occupies the main thread."""
        server = runtime.create_server()
        job_id = server._handler.handle("python.execute_async", {"code": "pass"})["job_id"]
        response = server._submit_request({"id": "1", "command": "job.cancel", "params": {"job_id": job_id}})
        assert response["success"] is True
        assert not server._request_queue

    def test_finished_jobs_are_pruned_and_released(self, handler, addon_module, runtime):
        manager = runtime.handler.jobs
        job_id = handler.handle("python.execute_async", {"code": "__result__ = 1"})["job_id"]
        manager._execute_job(job_id)
        assert manager._jobs[job_id]["code"] is None
        for _ in range(addon_module.jobs.MAX_FINISHED_JOBS + 20):
            manager._execute_job(handler.handle("python.execute_async", {"code": "pass"})["job_id"])
        assert len(manager._jobs) <= addon_module.jobs.MAX_FINISHED_JOBS

    def test_port_change_marks_server_unhealthy(self, runtime):
        server = runtime.create_server()
        server._running = True
        server._server_socket = object()
        server._thread = MagicMock()
        server._thread.is_alive.return_value = True
        runtime.server = server
        assert runtime.healthy()
        runtime.settings.port = server._port + 1
        assert not runtime.healthy()


def _wait_until(predicate):
    deadline = time.monotonic() + 1
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(0.001)


def test_stalled_queue_is_bounded_and_late_requests_are_not_run(runtime):
    runtime.settings.policy = replace(runtime.settings.policy, queue_capacity=1, queue_timeout=0.15)
    server = runtime.create_server()
    server._running = True
    with ThreadPoolExecutor() as workers:
        waiting = workers.submit(server._submit_request, {"id": "1", "command": "object.delete"})
        _wait_until(lambda: server._request_queue)
        busy = server._submit_request({"id": "2", "command": "scene.get_info"})
        assert busy["error_details"]["code"] == "busy"
        expired = waiting.result(timeout=1)
    assert expired["error_details"]["code"] == "queue_timeout"
    assert expired["error_details"]["details"] == {"started": False}
    with patch.object(server, "_process_request") as process:
        server._drain_request_queue()
    process.assert_not_called()


def test_reload_cancels_queued_request_and_recovers_timer(runtime, mock_bpy):
    server = runtime.create_server()
    server._running = True
    generation = server._generation
    with ThreadPoolExecutor() as workers:
        waiting = workers.submit(server._submit_request, {"id": "1", "command": "scene.get_info"})
        _wait_until(lambda: server._request_queue)
        server.begin_scene_load()
        assert waiting.result(timeout=1)["error_details"]["code"] == "session_changed"
    server.end_scene_load()
    mock_bpy.app.timers.register.assert_called_once()
    assert server._status()["generation"] != generation
    mock_bpy.app.timers.is_registered.return_value = True
    server.end_scene_load()
    mock_bpy.app.timers.register.assert_called_once()


def test_native_operation_can_finish_after_response_deadline(runtime):
    runtime.settings.policy = replace(runtime.settings.policy, command_timeout=0.02)
    server = runtime.create_server()
    server._running = True
    entered = threading.Event()
    finish = threading.Event()

    def slow(_):
        entered.set()
        assert finish.wait(timeout=1)
        return {"success": True}

    with ThreadPoolExecutor() as workers, patch.object(server, "_process_request", side_effect=slow):
        waiting = workers.submit(server._submit_request, {"id": "1", "command": "object.delete"})
        _wait_until(lambda: server._request_queue)
        timer = workers.submit(server._drain_request_queue)
        assert entered.wait(timeout=1)
        expired = waiting.result(timeout=1)
        assert expired["error_details"]["code"] == "execution_timeout"
        assert expired["error_details"]["details"]["outcome_uncertain"]
        finish.set()
        timer.result(timeout=1)
    assert server._active is None
