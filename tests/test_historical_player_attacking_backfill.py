"""Synthetic bounded acquisition and immutable replay; never request real providers."""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml

from fpl.jobs import backfill_historical_player_attacking as job
from fpl.jobs.competitive_participation_pilot import publish_bytes, publish_json


def csv_bytes(rows: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def source_parts(xg: str = "0.1", code: str = "101") -> dict[str, bytes]:
    return {
        "stats": csv_bytes(
            [
                {
                    "element": "1",
                    "fixture": "8",
                    "GW": "1",
                    "position": "DEF",
                    "team": "Home",
                    "kickoff_time": "2023-08-11T19:00:00Z",
                    "opponent_team": "2",
                    "was_home": "True",
                    "minutes": "90",
                    "starts": "1",
                    "expected_goals": xg,
                    "expected_assists": "",
                    "goals_scored": "0",
                    "assists": "0",
                }
            ]
        ),
        "registry": csv_bytes([{"id": "1", "code": code, "element_type": "2", "team": "2"}]),
        "fixtures": csv_bytes(
            [
                {
                    "id": "8",
                    "event": "1.0",
                    "kickoff_time": "2023-08-11T19:00:00Z",
                    "team_h": "1",
                    "team_a": "2",
                    "finished": "True",
                }
            ]
        ),
        "teams": csv_bytes(
            [
                {"id": "1", "code": "10", "name": "Home"},
                {"id": "2", "code": "20", "name": "Away"},
            ]
        ),
    }


def scope(count: int = 2) -> dict[str, Any]:
    return {
        "contract_version": "1.0",
        "study_id": "synthetic_historical_backfill",
        "source_repository": job.SOURCE,
        "season": "2023-24",
        "evidence_class": "ARCHIVED_AS_OF",
        "expected_branch": "v2",
        "cache": {},
        "frozen_inputs": {job.AUDIT_PATH: "f" * 64},
        "gameweeks": list(range(1, 39)),
        "positions": ["DEF", "MID", "FWD"],
        "snapshots": [
            {
                "snapshot_id": f"{i + 1:040x}",
                "commit_sha": f"{i + 1:040x}",
                "tree_sha": "e" * 40,
                "parent_shas": ["d" * 40],
                "source_known_at": f"2023-08-{16 + i:02d}T02:00:00Z",
                "author_date": f"2023-08-{16 + i:02d}T02:00:00Z",
                "committer_date": f"2023-08-{16 + i:02d}T02:00:00Z",
                "audited_source_witness": "f" * 64,
                "paths": dict(job.PATHS),
            }
            for i in range(count)
        ],
        "limits": {
            "maximum_urls": 152,
            "maximum_attempts": 304,
            "maximum_bytes": 192 * 1024 * 1024,
            "minimum_interval_seconds": 1.5,
            "max_retries": 1,
        },
    }


def retained(
    directory: Path,
    frozen: dict[str, Any],
    values: list[str] | None = None,
    codes: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    directory.mkdir()
    index: dict[str, dict[str, Any]] = {}
    for i, snapshot in enumerate(frozen["snapshots"]):
        parts = source_parts((values or ["0.1"] * 4)[i], (codes or ["101"] * 4)[i])
        for role, body in parts.items():
            url = job.source_url(snapshot, role)
            raw, receipt_path = directory / f"{i}-{role}.raw", directory / f"{i}-{role}.json"
            digest = hashlib.sha256(body).hexdigest()
            publish_bytes(raw, body)
            publish_json(
                receipt_path,
                {
                    "url": url,
                    "status": 200,
                    "sha256": digest,
                    "bytes": len(body),
                    "captured_at_utc": "2026-09-08T07:00:00Z",
                    "raw_file": raw.name,
                    "headers": {"content-type": "text/plain"},
                },
            )
            item = {"raw_file": str(raw), "receipt_file": str(receipt_path), "sha256": digest}
            frozen["cache"][url] = item
            index[url] = job.retained_source(url, item)
    return index


def provenance() -> dict[str, Any]:
    return {
        "git_head": "a" * 40,
        "config_sha256": "c" * 64,
        "implementation_sha256": {"parser": "b" * 64},
        "frozen_inputs_sha256": {},
    }


def test_scope_has_exact_immutable_urls(tmp_path: Path) -> None:
    path = tmp_path / "scope.yaml"
    path.write_text(yaml.safe_dump(scope()), encoding="utf8")
    result = job.load_scope(path)
    assert len({job.source_url(s, r) for s in result["snapshots"] for r in job.PATHS}) == 8


@pytest.mark.parametrize(
    "defect",
    [
        "repository",
        "path",
        "duplicate",
        "tree",
        "date",
        "witness",
        "cache",
        "attempts",
        "bytes",
        "retries",
        "pace",
    ],
)
def test_scope_rejects_expansion_or_unproven_availability(tmp_path: Path, defect: str) -> None:
    frozen = scope()
    if defect == "repository":
        frozen["source_repository"] = "other/provider"
    elif defect == "path":
        frozen["snapshots"][0]["paths"]["stats"] = "data/2024-25/gws/merged_gw.csv"
    elif defect == "duplicate":
        frozen["snapshots"][1] = frozen["snapshots"][0]
    elif defect == "tree":
        frozen["snapshots"][0]["tree_sha"] = "unknown"
    elif defect == "date":
        frozen["snapshots"][0]["source_known_at"] = "2023-08-11T19:00:00Z"
    elif defect == "witness":
        frozen["snapshots"][0]["audited_source_witness"] = "d" * 64
    elif defect == "cache":
        frozen["cache"]["https://unapproved.invalid/file"] = {}
    else:
        keys = {
            "attempts": "maximum_attempts",
            "bytes": "maximum_bytes",
            "retries": "max_retries",
            "pace": "minimum_interval_seconds",
        }
        frozen["limits"][keys[defect]] = {
            "attempts": 305,
            "bytes": 201326593,
            "retries": 2,
            "pace": 0,
        }[defect]
    path = tmp_path / "scope.yaml"
    path.write_text(yaml.safe_dump(frozen), encoding="utf8")
    with pytest.raises(
        ValueError, match=r"source|scope|commit|tree|knowledge|witness|allowlist|limits"
    ):
        job.load_scope(path)


def test_unchanged_then_changed_then_reverted_source_preserves_versions(tmp_path: Path) -> None:
    frozen = scope(4)
    sources = retained(tmp_path / "raw", frozen, ["0.1", "0.1", "0.7", "0.1"])
    output = tmp_path / "normalized"
    output.mkdir()
    report = job.normalize_sources(frozen, sources, output, provenance())
    rows = [json.loads(line) for line in (output / "observations.jsonl").read_bytes().splitlines()]
    assert [r["expected_goals"] for r in rows] == [0.1, 0.7, 0.1]
    assert report["normalized_versions"] == 3 and report["unique_player_fixtures"] == 1
    assert report["snapshots"][1]["unchanged_rows"] == 1
    assert [r["available_at"] for r in rows] == [
        "2023-08-16T02:00:00+00:00",
        "2023-08-18T02:00:00+00:00",
        "2023-08-19T02:00:00+00:00",
    ]
    assert all(r["expected_assists"] is None and r["shots"] is None for r in rows)
    assert all(r["fpl_position"] == "DEF" and r["team_code"] == 10 for r in rows)
    assert all(r["capture_known_at"] == "2026-09-08T07:00:00+00:00" for r in rows)


def test_offline_replay_is_identical_and_raw_bytes_remain_immutable(tmp_path: Path) -> None:
    frozen = scope()
    sources = retained(tmp_path / "raw", frozen)
    hashes = {name: job.file_sha256(Path(item["raw_file"])) for name, item in sources.items()}
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    one = job.normalize_sources(frozen, sources, first, provenance())
    two = job.normalize_sources(frozen, sources, second, provenance())
    assert one == two
    assert (first / "observations.jsonl").read_bytes() == (
        second / "observations.jsonl"
    ).read_bytes()
    assert hashes == {
        name: job.file_sha256(Path(item["raw_file"])) for name, item in sources.items()
    }
    with pytest.raises(FileExistsError):
        publish_bytes(first / "observations.jsonl", b"replace")


def test_future_versions_leave_earlier_available_records_unchanged(tmp_path: Path) -> None:
    frozen = scope()
    sources = retained(tmp_path / "raw", frozen, ["0.1", "99.0"])
    complete, truncated = tmp_path / "complete", tmp_path / "truncated"
    complete.mkdir()
    truncated.mkdir()
    job.normalize_sources(frozen, sources, complete, provenance())
    old = {**frozen, "snapshots": frozen["snapshots"][:1]}
    urls = {job.source_url(old["snapshots"][0], role) for role in job.PATHS}
    job.normalize_sources(old, {u: sources[u] for u in urls}, truncated, provenance())
    assert (complete / "observations.jsonl").read_bytes().splitlines()[0] == (
        truncated / "observations.jsonl"
    ).read_bytes().strip()


def test_cross_snapshot_identity_change_fails_closed(tmp_path: Path) -> None:
    frozen = scope()
    sources = retained(tmp_path / "raw", frozen, codes=["101", "999"])
    output = tmp_path / "normalized"
    output.mkdir()
    with pytest.raises(ValueError, match="registry identity contradiction"):
        job.normalize_sources(frozen, sources, output, provenance())
    assert not (output / "observations.jsonl").exists()


def test_raw_hash_and_source_population_are_revalidated(tmp_path: Path) -> None:
    frozen = scope()
    sources = retained(tmp_path / "raw", frozen)
    output = tmp_path / "normalized"
    output.mkdir()
    with pytest.raises(ValueError, match="complete frozen URL"):
        job.normalize_sources(frozen, {}, output, provenance())
    first = next(iter(sources.values()))
    first["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="identity differs"):
        job.normalize_sources(frozen, sources, output, provenance())


def test_shared_claim_is_write_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    common = tmp_path / "common"
    common.mkdir()
    monkeypatch.setattr(job, "git", lambda *_: str(common))
    first = job.reserve_claim(tmp_path, "synthetic_capture", provenance())
    original = first.read_bytes()
    with pytest.raises(FileExistsError):
        job.reserve_claim(tmp_path, "synthetic_capture", provenance())
    assert first.read_bytes() == original


def mock_network(monkeypatch: pytest.MonkeyPatch, handler: Any) -> None:
    original = httpx.Client
    monkeypatch.setattr(
        job.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handler), **kw)
    )
    monkeypatch.setattr("fpl.jobs.competitive_participation_pilot.time.sleep", lambda _: None)


def test_bounded_retry_retains_failure_and_success_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = scope(1)
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(500, content=b"retained provider failure")
        role = next(
            r for r in job.PATHS if str(request.url) == job.source_url(frozen["snapshots"][0], r)
        )
        return httpx.Response(
            200, content=source_parts()[role], headers={"content-type": "text/plain"}
        )

    mock_network(monkeypatch, handle)
    result = job.acquire_sources(frozen, tmp_path)
    assert len(result) == 4 and len(calls) == 5
    receipt = json.loads((tmp_path / "acquisition-receipt.json").read_bytes())
    assert [r["status"] for r in receipt["responses"]] == [500, 200, 200, 200, 200]
    assert len(list(tmp_path.glob("*.raw"))) == 5


@pytest.mark.parametrize(("status", "attempts"), [(404, 1), (503, 2), (429, 2)])
def test_failure_does_not_expand_scope_or_restart_forever(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    attempts: int,
) -> None:
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(status, content=b"source unavailable")

    mock_network(monkeypatch, handle)
    with pytest.raises(ValueError, match=f"HTTP {status}"):
        job.acquire_sources(scope(1), tmp_path)
    assert len(seen) == attempts and len(set(seen)) == 1
    assert (tmp_path / "acquisition-failure.json").exists()
    assert not (tmp_path / "source-index.json").exists()


def test_byte_budget_stops_a_large_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frozen = scope(1)
    frozen["limits"]["maximum_bytes"] = 10
    mock_network(monkeypatch, lambda _: httpx.Response(200, content=b"x" * 100))
    with pytest.raises(ValueError, match="byte budget"):
        job.acquire_sources(frozen, tmp_path)
    assert (tmp_path / "acquisition-failure.json").exists()


def test_complete_run_and_replay_never_refetch_cached_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = scope()
    retained(tmp_path / "raw", frozen)
    config = tmp_path / "scope.yaml"
    config.write_text(yaml.safe_dump(frozen), encoding="utf8")
    monkeypatch.setattr(job, "pinned_inputs", lambda *_: provenance())
    monkeypatch.setattr(job, "git", lambda _, *a: "v2" if a[0] == "branch" else "")
    claims: list[int] = []

    def claim(*_: Any) -> Path:
        claims.append(1)
        return tmp_path / "claim.json"

    monkeypatch.setattr(job, "reserve_claim", claim)

    def no_network(_: httpx.Request) -> httpx.Response:
        raise AssertionError("cached acquisition/offline replay attempted a request")

    mock_network(monkeypatch, no_network)
    original = job.run(config, tmp_path / "run", root=tmp_path)
    replay = job.run(config, tmp_path / "replay", replay=tmp_path / "run", root=tmp_path)
    assert len(claims) == 1
    assert original["normalized_sha256"] == replay["normalized_sha256"]
    assert original["provenance"] == replay["provenance"]
    with pytest.raises(FileExistsError):
        job.run(config, tmp_path / "run", root=tmp_path)


@pytest.mark.parametrize(
    "field", ["tree_sha", "parent_shas", "author_date", "committer_date", "source_known_at"]
)
def test_preflight_binds_metadata_to_designated_independent_audit(
    tmp_path: Path,
    field: str,
) -> None:
    frozen = scope(1)
    audit = tmp_path / job.AUDIT_PATH
    audit.parent.mkdir()
    publish_json(audit, {"commit_history": {"2023-24": {"chronology": frozen["snapshots"]}}})
    digest = job.file_sha256(audit)
    frozen["frozen_inputs"] = {job.AUDIT_PATH: digest}
    frozen["snapshots"][0]["audited_source_witness"] = digest
    replacement: Any = {
        "tree_sha": "a" * 40,
        "parent_shas": ["b" * 40],
        "author_date": "2023-08-15T00:00:00Z",
        "committer_date": "2023-08-15T00:00:00Z",
        "source_known_at": "2023-08-15T00:00:00Z",
    }[field]
    frozen["snapshots"][0][field] = replacement
    config = tmp_path / "scope.yaml"
    config.write_text(yaml.safe_dump(frozen), encoding="utf8")
    with pytest.raises(ValueError, match="independent source audit"):
        job.pinned_inputs(tmp_path, config, frozen)


def test_configured_gameweek_bound_controls_parser(tmp_path: Path) -> None:
    frozen = scope(1)
    sources = retained(tmp_path / "raw", frozen)
    frozen["gameweeks"] = [2]
    output = tmp_path / "normalized"
    output.mkdir()
    with pytest.raises(ValueError, match="gameweek outside frozen scope"):
        job.normalize_sources(frozen, sources, output, provenance())


def test_encoded_response_is_preserved_once_without_double_decoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = scope(1)

    def handle(request: httpx.Request) -> httpx.Response:
        role = next(
            r for r in job.PATHS if str(request.url) == job.source_url(frozen["snapshots"][0], r)
        )
        return httpx.Response(
            200,
            content=gzip.compress(source_parts()[role]),
            headers={"content-type": "text/plain", "content-encoding": "gzip"},
        )

    mock_network(monkeypatch, handle)
    result = job.acquire_sources(frozen, tmp_path)
    for role in job.PATHS:
        source = result[job.source_url(frozen["snapshots"][0], role)]
        assert Path(source["raw_file"]).read_bytes() == source_parts()[role]
