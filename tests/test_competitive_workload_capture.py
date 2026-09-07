"""Raw-only workload capture tests: synthetic files and HTTP mock transport only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from fpl.config import load_sources, repo_root
from fpl.jobs import capture_competitive_workload as capture
from fpl.jobs import competitive_participation_pilot as pilot


def _json(path: Path, value: Any) -> bytes:
    data = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _retained(tmp_path: Path) -> tuple[Path, Path, dict[str, Any]]:
    root, source = tmp_path / "repo", tmp_path / "original"
    source.mkdir(parents=True)
    contract = capture.load_contract(repo_root())
    records = [
        {
            "matchId": mid,
            "competitionId": 8,
            "season": 2025,
            "kickoff": f"2025-08-{mid + 10:02d}T15:00:00+00:00",
            "period": "FullTime",
            "resultType": "AfterExtraTime" if mid == 2 else "NormalResult",
            "clock": "121",
            "homeTeam": {"id": 3, "score": 1},
            "awayTeam": {"id": 31, "score": 0},
        }
        for mid in (1, 2)
    ]
    responses, requests = [], []

    def response(path: str, params: str, payload: Any, endpoint: str) -> dict[str, Any]:
        seq = len(responses) + 1
        url = f"{contract['provider_base_url']}{path}?{params}"
        raw = json.dumps(payload, sort_keys=True).encode()
        sha = hashlib.sha256(raw).hexdigest()
        raw_file = f"response-{seq:04d}-{sha}.raw"
        (source / raw_file).write_bytes(raw)
        meta = {
            "sequence": seq,
            "url": url,
            "status": 200,
            "sha256": sha,
            "bytes": len(raw),
            "raw_file": raw_file,
            "captured_at_utc": "2026-09-07T01:00:00+00:00",
            "headers": {},
        }
        request = {
            "sequence": seq,
            "url": url,
            "method": "GET",
            "attempted_at_utc": "2026-09-07T00:59:59+00:00",
        }
        _json(source / f"response-{seq:04d}.json", meta)
        _json(source / f"request-{seq:04d}.json", request)
        responses.append(meta)
        requests.append(request)
        return {
            "endpoint": endpoint,
            "path": path,
            "params": {},
            "status": 200,
            "known_at": "2026-09-07T01:00:00.000001+00:00",
            "sha256": sha,
            "bytes": len(raw),
        }

    page = {"data": records, "pagination": {"_next": None}}
    versions = {
        "metadata": response(
            "/api/v2/matches", "competition=8&season=2025&_limit=100", page, "matches"
        )
    }
    # Intentionally uninterpretable lineup: raw capture must not license or repair it.
    for endpoint in contract["endpoints"]:
        versions[endpoint] = response(
            contract["endpoint_paths"][endpoint].format(match_id=1),
            "match_id=1",
            {"uninterpretable": endpoint, "unknown_player": None},
            f"match_{endpoint}",
        )
    _json(
        source / "capture-1.json",
        {"selected_match_record": records[0], "source_versions": versions},
    )
    report = {
        "completed": True,
        "passed": False,
        "http_responses": responses,
        "http_attempts": requests,
        "matches": [],
        "failures": [
            {
                "sdp_match_id": 1,
                "source_versions": versions,
                "error": "previous interpretation failed",
            }
        ],
    }
    report_bytes = _json(root / contract["retained_report"], report)
    contract.update(
        {
            "retained_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "catalogue_records_sha256": capture._hash(records),
            "selected_match_ids_sha256": capture._hash([1, 2]),
            "pl_match_ids_sha256": capture._hash([1, 2]),
            "provider_club_ids": [3, 31],
            "catalogue_counts": {"8": 2},
            "selected_counts": {"8": 2},
            "expected_metadata_pages": 1,
            "expected_catalogue_matches": 2,
            "expected_selected_matches": 2,
            "expected_reused_matches": 1,
            "expected_reused_endpoints": 2,
            "expected_missing_endpoints": 2,
            "maximum_distinct_provider_requests": 2,
            "maximum_consecutive_failed_endpoints": 2,
        }
    )
    return root, source, contract


def _mock_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, handler: Any
) -> tuple[Path, Path, Path, dict[str, Any]]:
    root, retained, contract = _retained(tmp_path)
    output = tmp_path / "new-capture"
    monkeypatch.setattr(capture, "load_contract", lambda _: contract)
    monkeypatch.setattr(capture, "_head", lambda *_: "clean-start")
    monkeypatch.setattr(capture, "_source_fingerprints", lambda _: {"source": "unchanged"})
    source = load_sources().pl_sdp
    assert source is not None
    source = source.model_copy(
        update={
            "min_request_interval_seconds": 0.0,
            "max_retries": 1,
            "retry_backoff_base_seconds": 0.0,
        }
    )
    monkeypatch.setattr(capture, "load_sources", lambda: SimpleNamespace(pl_sdp=source))
    original_client = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        return original_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(capture.httpx, "Client", client)
    monkeypatch.setattr(
        capture.subprocess,
        "run",
        lambda args, **_: SimpleNamespace(
            stdout="?? independent-new-work.py" if "status" in args else "different-ending-head"
        ),
    )
    return root, retained, output, contract


def test_frozen_configuration_and_provider_inventory() -> None:
    contract = capture.load_contract(repo_root())
    assert contract["expected_selected_matches"] == 574
    assert contract["expected_missing_endpoints"] == 1122
    assert len(contract["provider_club_ids"]) == 20
    assert contract["parsing_participation_permitted"] is False


def test_unknown_config_field_refused(tmp_path: Path) -> None:
    path = tmp_path / capture.CONFIG
    path.parent.mkdir(parents=True)
    path.write_bytes((repo_root() / capture.CONFIG).read_bytes() + b"override: true\n")
    with pytest.raises(ValueError, match="contract changed"):
        capture.load_contract(tmp_path)


def test_retained_failed_interpretation_still_reuses_exact_raw_bytes(tmp_path: Path) -> None:
    root, retained, contract = _retained(tmp_path)
    inputs = capture.load_retained(root, retained, contract)
    assert len(inputs.matches) == 2 and len(inputs.reused) == 2
    assert inputs.inventory["missing_endpoints"] == 2
    assert inputs.inventory["raw_status_counts"]["FullTime:AfterExtraTime"] == 1
    assert inputs.reused[1, "lineups"]["known_at"] == "2026-09-07T01:00:00.000001+00:00"
    assert inputs.reused[1, "lineups"]["receipt"]["captured_at_utc"] == "2026-09-07T01:00:00+00:00"
    assert not inputs.inventory["participation_validated"]


@pytest.mark.parametrize("change", ["raw", "request", "response", "bundle", "report"])
def test_modified_original_evidence_refused(tmp_path: Path, change: str) -> None:
    root, retained, contract = _retained(tmp_path)
    paths = {
        "raw": next(retained.glob("*.raw")),
        "request": retained / "request-0001.json",
        "response": retained / "response-0001.json",
        "bundle": retained / "capture-1.json",
        "report": root / contract["retained_report"],
    }
    paths[change].write_text("{}")
    with pytest.raises((ValueError, KeyError)):
        capture.load_retained(root, retained, contract)


@pytest.mark.parametrize(
    "field",
    [
        "catalogue_records_sha256",
        "selected_match_ids_sha256",
        "pl_match_ids_sha256",
        "expected_selected_matches",
        "expected_missing_endpoints",
    ],
)
def test_population_and_request_bound_changes_refused(tmp_path: Path, field: str) -> None:
    root, retained, contract = _retained(tmp_path)
    contract[field] = "different" if "sha256" in field else 999
    with pytest.raises(ValueError, match=r"population|fingerprint|budget"):
        capture.load_retained(root, retained, contract)


def test_capture_fetches_only_missing_endpoints_and_keeps_unrelated_dirty_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert "/matches/2/" in request.url.path
        return httpx.Response(200, json={"not_a_valid_participation_roster": True, "empty": []})

    root, retained, output, _ = _mock_run(tmp_path, monkeypatch, handler)

    def forbidden(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("participation parser must not run")

    monkeypatch.setattr(pilot, "parse_participation", forbidden)
    before = {p.name: p.read_bytes() for p in retained.iterdir()}
    result = capture.run(root=root, retained=retained, results=output)
    assert result["completed"] and result["capture_complete"]
    assert len(calls) == result["distinct_requests"] == 2
    assert result["endpoint_status_counts"] == {"reused": 2, "received": 2}
    assert result["matches_with_both_endpoints_received"] == 2
    assert not result["participation_validated"] and not result["database_opened"]
    assert not result["ending_worktree_clean"]
    assert result["ending_git_head"] == "different-ending-head"
    assert result["postflight_unchanged"]
    assert {p.name: p.read_bytes() for p in retained.iterdir()} == before
    for name, content in before.items():
        assert (output / "inputs" / name).read_bytes() == content
    with pytest.raises(FileExistsError):
        capture.run(root=root, retained=retained, results=output)
    assert len(calls) == 2


def test_retry_responses_all_retained_but_distinct_budget_not_recounted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"limited": True})
        return httpx.Response(200, json={"endpoint": request.url.path, "received": True})

    root, retained, output, _ = _mock_run(tmp_path, monkeypatch, handler)
    result = capture.run(root=root, retained=retained, results=output)
    assert result["capture_complete"]
    assert len(result["http_attempts"]) == len(result["http_responses"]) == 3
    assert result["distinct_requests"] == 2
    assert result["response_status_counts"] == {"429": 1, "200": 2}
    assert len(list((output / "responses").glob("*.raw"))) == 3


def test_egress_failure_stops_and_lists_remaining_endpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ProxyError("synthetic gateway denial", request=request)

    root, retained, output, _ = _mock_run(tmp_path, monkeypatch, handler)
    result = capture.run(root=root, retained=retained, results=output)
    assert not result["completed"] and not result["capture_complete"]
    assert result["execution_failure"]["class"] == "EgressBlockedError"
    assert result["endpoint_status_counts"] == {
        "reused": 2,
        "egress_blocked": 1,
        "not_attempted": 1,
    }
    assert result["missing_or_failed_matches"] == 1
    assert (output / "result.json").is_file()


def test_consecutive_endpoint_failure_circuit_preserves_http_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, retained, output, _ = _mock_run(
        tmp_path, monkeypatch, lambda _: httpx.Response(404, json={"missing": True})
    )
    result = capture.run(root=root, retained=retained, results=output)
    assert not result["completed"]
    assert result["endpoint_status_counts"] == {"reused": 2, "unavailable": 2}
    assert "circuit breaker" in result["execution_failure"]["message"]
    assert len(result["http_responses"]) == 2


def test_source_drift_invalidates_capture_not_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, retained, output, _ = _mock_run(
        tmp_path,
        monkeypatch,
        lambda _: httpx.Response(200, json={"large_enough_valid_json_payload": True}),
    )
    calls = 0

    def fingerprints(_: Path) -> dict[str, str]:
        nonlocal calls
        calls += 1
        return {"source": "before" if calls == 1 else "after"}

    monkeypatch.setattr(capture, "_source_fingerprints", fingerprints)
    result = capture.run(root=root, retained=retained, results=output)
    assert not result["completed"] and not result["capture_complete"]
    assert result["matches_with_both_endpoints_received"] == 2
    assert not result["postflight_unchanged"]
    assert len(list((output / "responses").glob("*.raw"))) == 2


@pytest.mark.parametrize("location", ["repo", "retained"])
def test_output_cannot_modify_original_input_or_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    root, retained, _, _ = _mock_run(
        tmp_path, monkeypatch, lambda _: pytest.fail("no HTTP before output validation")
    )
    output = (root if location == "repo" else retained) / "new"
    with pytest.raises(ValueError, match="external"):
        capture.run(root=root, retained=retained, results=output)
    assert not output.exists()


def test_dirty_start_refused_before_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, retained, output, _ = _mock_run(tmp_path, monkeypatch, lambda _: pytest.fail("no HTTP"))

    def dirty(*_: Any) -> str:
        raise ValueError("dirty implementation")

    monkeypatch.setattr(capture, "_head", dirty)
    with pytest.raises(ValueError, match="dirty"):
        capture.run(root=root, retained=retained, results=output)
    assert not output.exists()


def test_cli_has_only_explicit_input_output_no_database_or_model_flag() -> None:
    with pytest.raises(SystemExit) as result:
        capture.main([])
    assert result.value.code == 2


@pytest.mark.parametrize(
    "defect", ["missing_final_page", "missing_cursor_protocol", "duplicate_match"]
)
def test_catalogue_completeness_is_checked_before_request_plan(tmp_path: Path, defect: str) -> None:
    root, retained, contract = _retained(tmp_path)
    report_path = root / contract["retained_report"]
    report = json.loads(report_path.read_bytes())
    meta = report["http_responses"][0]
    raw_path = retained / meta["raw_file"]
    payload = json.loads(raw_path.read_bytes())
    if defect == "missing_final_page":
        payload["pagination"]["_next"] = "unfetched-cursor"
    elif defect == "missing_cursor_protocol":
        del payload["pagination"]
    else:
        payload["data"].append(payload["data"][0])
    body = _json(raw_path, payload)
    meta["sha256"] = hashlib.sha256(body).hexdigest()
    meta["bytes"] = len(body)
    _json(retained / "response-0001.json", meta)
    report_bytes = _json(report_path, report)
    contract["retained_report_sha256"] = hashlib.sha256(report_bytes).hexdigest()
    with pytest.raises(ValueError, match=r"final page|termination|duplicate catalogue"):
        capture.load_retained(root, retained, contract)


def test_malformed_new_json_is_retained_not_licensed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, retained, output, _ = _mock_run(
        tmp_path,
        monkeypatch,
        lambda _: httpx.Response(
            200, content=b'{"broken": this is intentionally not valid JSON data }'
        ),
    )
    result = capture.run(root=root, retained=retained, results=output)
    assert not result["capture_complete"]
    assert result["endpoint_status_counts"] == {"reused": 2, "unavailable": 2}
    assert len(list((output / "responses").glob("*.raw"))) == 2


def test_request_bound_blocks_new_url_before_an_attempt(tmp_path: Path) -> None:
    recorder = pilot.ResponseRecorder(tmp_path, maximum_requests=1)
    first = httpx.Request("GET", "https://example.test/first")
    recorder.request(first)
    recorder.request(httpx.Request("GET", "https://example.test/first"))
    with pytest.raises(pilot.ParticipationError, match="bound exhausted"):
        recorder.request(httpx.Request("GET", "https://example.test/second"))
    assert len(recorder.urls) == 1 and len(recorder.attempts) == 2
