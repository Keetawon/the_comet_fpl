"""Offline contract tests for the local interactive plan server.

The server is a trigger, not a new solver: these tests pin the request contract, the
same-machine origin rule, the single-flight serialization, the fail-closed pre-checks
(dirty worktree, missing forecast), and the HTTP surface on a real loopback socket with
the pipeline monkeypatched -- never solving a real squad and never touching the network
beyond the loopback interface the server itself listens on.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from fpl.jobs import plan_server
from fpl.jobs.plan_server import (
    RequestError,
    ServerState,
    _allowed_origin,
    make_handler,
    run_plan,
    summarize_artifact,
    validate_request,
)


class TestValidateRequest:
    def test_parses_sorts_and_dedupes_locks_and_defaults_the_gate(self) -> None:
        assert validate_request({"locks": [5, 1, 5]}) == ([1, 5], 0.0)

    def test_accepts_a_bench_gate_fraction(self) -> None:
        assert validate_request({"locks": [], "min_bench_appearance": 0.5}) == ([], 0.5)

    def test_rejects_more_than_five_locks(self) -> None:
        with pytest.raises(RequestError, match="at most 5"):
            validate_request({"locks": [1, 2, 3, 4, 5, 6]})

    def test_rejects_non_integer_locks(self) -> None:
        with pytest.raises(RequestError, match="list of player codes"):
            validate_request({"locks": ["1"]})

    def test_rejects_out_of_range_bench_gate(self) -> None:
        for bad in (0, 1, -0.5, "0.5"):
            with pytest.raises(RequestError, match="min_bench_appearance"):
                validate_request({"locks": [], "min_bench_appearance": bad})


class TestAllowedOrigin:
    def test_non_browser_requests_pass(self) -> None:
        assert _allowed_origin(None) is True

    def test_loopback_origins_pass(self) -> None:
        assert _allowed_origin("http://localhost:5173") is True
        assert _allowed_origin("http://127.0.0.1:4173") is True

    def test_other_sites_are_refused(self) -> None:
        assert _allowed_origin("https://evil.example") is False


class TestSummarizeArtifact:
    def test_maps_the_fields_the_ui_greets_with(self, tmp_path: Path) -> None:
        artifact = {
            "run_id": "r" * 64,
            "decision_sha256": "d" * 64,
            "plan": {
                "expected_points_after_hits": 317.2,
                "hit_points": 0,
                "weeks": [
                    {
                        "gw": 1,
                        "expected_points": 60.7,
                        "squad_cost_tenths": 995,
                        "captain": {"web_name": "Gibbs-White"},
                        "vice_captain": {"web_name": "O'Reilly"},
                    }
                ],
            },
        }
        path = tmp_path / "plan-x.json"
        path.write_text(json.dumps(artifact), encoding="utf-8")
        summary = summarize_artifact(path)
        assert summary["optimizer_run_id"] == "r" * 64
        assert summary["gw_expected_points"] == 60.7
        assert summary["captain"] == "Gibbs-White"


class TestRunPlanPreChecks:
    def test_busy_server_refuses_a_second_run(self) -> None:
        state = ServerState(Path("unused"))
        assert state.run_lock.acquire(blocking=False)
        try:
            with pytest.raises(RequestError, match="already in progress"):
                run_plan(state, [], 0.0)
        finally:
            state.run_lock.release()

    def test_missing_forecast_fails_closed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
        state = ServerState(tmp_path)
        with pytest.raises(RequestError, match="forecast artifact missing"):
            run_plan(state, [], 0.0)

    def test_dirty_worktree_is_refused_before_solving(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: False)
        (tmp_path / plan_server.FORECAST_NAME).write_text("{}", encoding="utf-8")
        state = ServerState(tmp_path)
        with pytest.raises(RequestError, match="worktree is dirty"):
            run_plan(state, [], 0.0)


@pytest.fixture
def loopback_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ThreadingHTTPServer:
    """A real server on an ephemeral loopback port with the pipeline monkeypatched out."""
    monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)
    monkeypatch.setattr(
        plan_server,
        "run_plan",
        lambda state, locks, bench: {
            "optimizer_run_id": "r" * 64,
            "decision_sha256": "d" * 64,
            "captain": "Stub",
            "locks_seen": locks,
            "bench_seen": bench,
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ServerState(tmp_path)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()


class TestHttpSurface:
    def _request(
        self,
        server: ThreadingHTTPServer,
        path: str,
        *,
        method: str = "GET",
        body: bytes | None = None,
        origin: str | None = None,
    ) -> tuple[int, dict[str, str], str]:
        url = f"http://127.0.0.1:{server.server_address[1]}{path}"
        request = urllib.request.Request(url, data=body, method=method)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if origin is not None:
            request.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = response.read().decode("utf-8")
                return response.status, dict(response.headers), payload
        except urllib.error.HTTPError as exc:
            payload = exc.read().decode("utf-8")
            return exc.code, dict(exc.headers), payload

    def test_status_reports_the_server_state(self, loopback_server: ThreadingHTTPServer) -> None:
        status, _, payload = self._request(loopback_server, "/status")
        body = json.loads(payload)
        assert status == 200
        assert body["busy"] is False
        assert body["worktree_clean"] is True
        assert body["forecast_ready"] is False

    def test_plan_posts_through_to_the_pipeline(self, loopback_server: ThreadingHTTPServer) -> None:
        status, _, payload = self._request(
            loopback_server,
            "/plan",
            method="POST",
            body=json.dumps({"locks": [7, 3], "min_bench_appearance": 0.25}).encode("utf-8"),
        )
        body = json.loads(payload)
        assert status == 200
        assert body["ok"] is True
        assert body["locks_seen"] == [3, 7]
        assert body["bench_seen"] == 0.25

    def test_bad_body_is_a_409_with_a_safe_message(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        status, _, payload = self._request(
            loopback_server,
            "/plan",
            method="POST",
            body=json.dumps({"locks": "no"}).encode("utf-8"),
        )
        assert status == 409
        assert "list of player codes" in json.loads(payload)["error"]

    def test_a_crashing_pipeline_returns_a_reason_not_a_dead_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reported ERR_EMPTY_RESPONSE: an uncaught solver exception must still answer."""
        monkeypatch.setattr(plan_server, "_git_worktree_clean", lambda repo: True)

        def boom(state: object, locks: list[int], bench: float) -> dict[str, object]:
            raise RuntimeError(
                "initial squad lineup violates min_bench_appearance before transfer planning"
            )

        monkeypatch.setattr(plan_server, "run_plan", boom)
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(ServerState(tmp_path)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            status, _, payload = self._request(
                server, "/plan", method="POST", body=json.dumps({"locks": []}).encode("utf-8")
            )
            body = json.loads(payload)
            assert status == 500
            assert "infeasible together" in body["error"]
            assert "min_bench_appearance" in body["error"]
        finally:
            server.shutdown()
            server.server_close()

    def test_foreign_origin_is_refused(self, loopback_server: ThreadingHTTPServer) -> None:
        url = f"http://127.0.0.1:{loopback_server.server_address[1]}/status"
        request = urllib.request.Request(url, headers={"Origin": "https://evil.example"})
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(request, timeout=10)
        assert excinfo.value.code == 403

    def test_same_machine_origin_is_echoed_for_cors(
        self, loopback_server: ThreadingHTTPServer
    ) -> None:
        status, headers, _ = self._request(
            loopback_server,
            "/plan",
            method="POST",
            body=json.dumps({"locks": []}).encode("utf-8"),
            origin="http://localhost:5173",
        )
        assert status == 200
        assert headers.get("Access-Control-Allow-Origin") == "http://localhost:5173"
