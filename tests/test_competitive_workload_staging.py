"""Synthetic operational staging safeguards; no network, real DB writes or real replay."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.jobs import stage_competitive_workload as job
from fpl.storage.competitive_workload import (
    TABLES,
    append_match,
    append_receipt,
    append_report,
    apply_workload_schema,
)
from fpl.storage.db import FEATURE_READABLE_TABLES, connect
from fpl.validate.competitive_workload_view import ObservedPlayerIdentity

KICKOFF = datetime(2025, 9, 14, 15, tzinfo=UTC)
CAPTURE = datetime(2026, 9, 7, 8, tzinfo=UTC)


def synthetic() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    match = {
        "matchId": "1",
        "season": "2025",
        "competitionId": "8",
        "kickoff": KICKOFF.isoformat(),
        "period": "FullTime",
        "resultType": "NormalResult",
        "clock": "96",
        "homeTeam": {"id": "3", "score": 1},
        "awayTeam": {"id": "31", "score": 0},
    }
    lineups = {}
    events = {}
    for label, node, team, shift in (("home", "homeTeam", 3, 0), ("away", "awayTeam", 31, 100)):
        lineups[label + "_team"] = {
            "teamId": str(team),
            "formation": {
                "teamId": str(team),
                "lineup": [[str(i + shift) for i in range(1, 12)]],
                "subs": [str(12 + shift)],
            },
            "players": [
                {
                    "id": str(i + shift),
                    "position": "Midfielder" if i < 12 else "Substitute",
                    "subPosition": "Midfielder",
                }
                for i in range(1, 13)
            ],
        }
        events[node] = {"id": str(team), "subs": [], "cards": [], "goals": []}
    reference = {
        "season": "2025-26",
        "database_sha256": "d" * 64,
        "identity_observed_at_utc": (CAPTURE + timedelta(minutes=1)).isoformat(),
        "registry": [
            {"season": "2025-26", "code": i + 1000, "opta_code": f"p{i}"} for i in range(1, 13)
        ],
        "crosswalk": {"1": {"fixture": 77}},
        "fixture_gw": {77: 4},
        "facts": [],
    }
    return match, {"lineups": lineups, "events": events}, reference


def interpreted(**changes: Any) -> dict[str, Any]:
    match, payloads, reference = synthetic()
    args = {
        "record": match,
        "payloads": payloads,
        "reference": reference,
        "clubs": {3: 303, 31: 3131},
        "sources": {
            e: {"known_at": CAPTURE.isoformat(), "sha256": e}
            for e in ("metadata", "lineups", "events")
        },
        "receipts": ["a", "b", "c"],
        "interpreted_at": CAPTURE + timedelta(minutes=2),
        "parser_sha256": "p" * 64,
        "errors": [],
    }
    args.update(changes)
    return job.interpreted_record(**args)


def test_append_only_whole_versions_and_typed_nullable_rows() -> None:
    with duckdb.connect(":memory:") as con:
        apply_workload_schema(con)
        record = interpreted()
        assert record["interpretation_valid"]
        assert append_match(con, record)
        duplicate = deepcopy(record)
        duplicate["interpretation_known_at"] = (CAPTURE + timedelta(days=1)).isoformat()
        assert not append_match(con, duplicate)
        assert con.execute("SELECT count(*) FROM dev_competitive_match_version").fetchone() == (1,)
        assert con.execute(
            "SELECT count(*) FROM dev_competitive_participation_version WHERE code IS NULL"
        ).fetchone() == (12,)
        revised = interpreted(receipts=["new", "b", "c"])
        assert append_match(con, revised)
        assert con.execute("SELECT count(*) FROM dev_competitive_match_version").fetchone() == (2,)
        collision = deepcopy(record)
        collision["semantic_sha256"] = "changed"
        with pytest.raises(ValueError, match="semantic hash"):
            append_match(con, collision)
        assert con.execute(
            "SELECT count(*) FROM dev_competitive_participation_version"
        ).fetchone() == (48,)


def test_unassigned_roster_and_foreign_identity_remain_null() -> None:
    _, payloads, _ = synthetic()
    payloads["lineups"]["away_team"]["players"].append({"id": "900", "position": "Goalkeeper"})
    result = interpreted(payloads=payloads, clubs={3: 303})
    row = next(r for r in result["rows"] if r["provider_player_id"] == 900)
    assert row["code"] is None and row["team_code"] is None
    assert row["started"] is None and row["appeared"] is None and row["nominal_minutes"] is None
    assert row["membership"] == "unassigned_roster"


def test_bad_interpretation_retains_complete_raw_version_and_failure() -> None:
    _, payloads, _ = synthetic()
    payloads["lineups"]["home_team"]["formation"]["lineup"] = [["1"] * 11]
    result = interpreted(payloads=payloads)
    assert result["capture_complete"] and not result["interpretation_valid"]
    assert result["errors"] and result["rows"] == []
    assert result["source_versions"] and len(result["receipt_ids"]) == 3


def test_missing_endpoint_is_not_an_empty_complete_fixture() -> None:
    _, payloads, _ = synthetic()
    result = interpreted(
        payloads={"lineups": payloads["lineups"]},
        sources={e: {"known_at": CAPTURE.isoformat()} for e in ("metadata", "lineups")},
        errors=["events:unavailable:404"],
    )
    assert not result["capture_complete"] and not result["interpretation_valid"]
    assert result["rows"] == [] and result["errors"] == ["events:unavailable:404"]


def test_no_global_schema_or_prospective_allowlist_change() -> None:
    assert not TABLES & FEATURE_READABLE_TABLES
    assert not any(t.startswith("mart_") for t in TABLES)


def test_copy_is_byte_identical_preserves_original_and_refuses_existing_destination(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.duckdb"
    dest = tmp_path / "operational.duckdb"
    with connect(source) as con:
        con.execute("CREATE TABLE unchanged(i INT)")
        con.execute("INSERT INTO unchanged VALUES (7)")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    assert job.consistent_copy(source, dest, before) == before
    assert source.read_bytes() == dest.read_bytes()
    with pytest.raises(FileExistsError):
        job.consistent_copy(source, dest, before)
    with connect(dest) as con:
        apply_workload_schema(con)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("case", ["wal", "hash", "same"])
def test_copy_guards(tmp_path: Path, case: str) -> None:
    source = tmp_path / "source.duckdb"
    dest = tmp_path / "op.duckdb"
    with connect(source) as con:
        con.execute("CREATE TABLE untouched(i INT)")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    if case == "wal":
        Path(str(source) + ".wal").touch()
    if case == "hash":
        before = "0" * 64
    if case == "same":
        dest = source
    with pytest.raises(ValueError, match=r"source|destination"):
        job.consistent_copy(source, dest, before)
    if case != "same":
        assert not dest.exists()


def receipt(body: bytes = b"{}") -> dict[str, Any]:
    return {
        "url": "https://sdp-prem-prod.premier-league-prod.pulselive.com/api/v1/matches/1/events?match_id=1",
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "status": 200,
        "captured_at_utc": CAPTURE.isoformat(),
    }


def test_receipt_raw_bytes_idempotency_and_provider_revisions() -> None:
    with duckdb.connect(":memory:") as con:
        apply_workload_schema(con)
        first = append_receipt(con, receipt=receipt(), body=b"{}", source_path="persistent/old.raw")
        assert (
            append_receipt(con, receipt=receipt(), body=b"{}", source_path="copied/old.raw")
            == first
        )
        second = append_receipt(
            con,
            receipt=receipt(b'{"revision":1}'),
            body=b'{"revision":1}',
            source_path="persistent/new.raw",
        )
        assert second != first
        assert con.execute("SELECT count(*) FROM dev_competitive_raw_receipt").fetchone() == (2,)
        with pytest.raises(ValueError, match="byte identity"):
            append_receipt(con, receipt=receipt(), body=b"false", source_path="invalid")


def test_append_report_collision_and_unlicensed_table_denial() -> None:
    with duckdb.connect(":memory:") as con:
        apply_workload_schema(con)
        append_report(con, "dev_competitive_ingestion", "run", {"a": 1})
        append_report(con, "dev_competitive_ingestion", "run", {"a": 1})
        with pytest.raises(ValueError, match="collision"):
            append_report(con, "dev_competitive_ingestion", "run", {"a": 2})
        with pytest.raises(ValueError, match="development"):
            append_report(con, "mart_fact_player_fixture", "run", {})


def test_rollback_leaves_no_partial_versions() -> None:
    with duckdb.connect(":memory:") as con:
        apply_workload_schema(con)
        con.execute("BEGIN TRANSACTION")
        append_match(con, interpreted())
        con.execute("ROLLBACK")
        assert con.execute("SELECT count(*) FROM dev_competitive_match_version").fetchone() == (0,)
        assert con.execute(
            "SELECT count(*) FROM dev_competitive_participation_version"
        ).fetchone() == (0,)


def test_persistent_version_roundtrip_to_observed_view_keeps_earliest_capture() -> None:
    first = interpreted()
    second = interpreted(
        receipts=["later", "b", "c"],
        sources={
            e: {"known_at": (CAPTURE + timedelta(seconds=1)).isoformat()}
            for e in ("metadata", "lineups", "events")
        },
    )
    second["rows"][0]["nominal_minutes"] = 1
    view = job.workload_view([second, first], {3: 303, 31: 3131}, "catalogue", CAPTURE)
    result = view.observed_participation_snapshot(
        identity=ObservedPlayerIdentity(1001, 1, "exact", CAPTURE),
        scope_team_codes=frozenset({303, 3131}),
        as_of=KICKOFF + timedelta(days=2),
        excluded_target_gw_fixtures=frozenset(),
    )
    assert result.windows[0].nominal_minutes_lower_bound == 90
    assert result.exact_player_rest_hours is None
    # Full provenance is ordinary JSON, never default=str collapsing typed sets/dataclasses.
    encoded = json.dumps(result, default=job._json_default)
    assert json.loads(encoded)["windows"][0]["witnessed_fixtures"][0]["match_id"] == 1


def test_missing_positive_fpl_appearance_is_retained_in_reconciliation() -> None:
    _, _, reference = synthetic()
    reference["facts"] = [
        {"fixture": 77, "code": 9999, "minutes": 90, "starts": 1, "team_code": 303}
    ]
    audit = job.participation_audit([interpreted()], reference, {3: 303, 31: 3131})
    assert audit["pl_recorded_appearance_without_source_pair"] == reference["facts"]


@pytest.mark.parametrize("relative", ["../outside.raw", "C:/outside.raw", "missing.raw"])
def test_source_path_failclosed(tmp_path: Path, relative: str) -> None:
    with pytest.raises(ValueError, match="retained"):
        job.safe_file(tmp_path, relative)


def endpoint_source(directory: Path, endpoint: str, payload: Any) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    version = 3 if endpoint == "lineups" else 1
    path = f"/api/v{version}/matches/1/{endpoint}"
    relative = f"responses/{endpoint}.raw"
    (directory / relative).parent.mkdir(parents=True, exist_ok=True)
    (directory / relative).write_bytes(body)
    receipt_meta = {
        **receipt(body),
        "url": f"https://sdp-prem-prod.premier-league-prod.pulselive.com{path}?match_id=1",
    }
    return {
        "receipt": receipt_meta,
        "copied_raw_file": relative,
        "sha256": receipt_meta["sha256"],
        "bytes": len(body),
        "status": 200,
        "known_at": CAPTURE.isoformat(),
        "endpoint": f"match_{endpoint}",
        "path": path,
        "params": {"match_id": "1"},
        "reused": False,
    }


@pytest.mark.parametrize(
    ("field", "bad"),
    [
        ("status", 404),
        ("sha256", "f" * 64),
        ("params", {"match_id": "2"}),
        ("known_at", "2025-01-01T00:00:00+00:00"),
        ("known_at", "2026-09-07T08:00:00"),
    ],
)
def test_verified_body_rejects_identity_and_time_mismatch(
    tmp_path: Path, field: str, bad: Any
) -> None:
    source = endpoint_source(tmp_path, "events", {})
    source[field] = bad
    with pytest.raises(ValueError, match=r"identity|knowledge|receipt"):
        job.verified_body(tmp_path, source, 1, "events")


def test_verified_body_preserves_distinct_receipt_and_client_capture_times(tmp_path: Path) -> None:
    source = endpoint_source(tmp_path, "events", {})
    source["known_at"] = (CAPTURE + timedelta(milliseconds=2)).isoformat()
    path, body, record = job.verified_body(tmp_path, source, 1, "events")
    assert path.read_bytes() == body == b"{}"
    assert record["source_known_at"] == source["known_at"]
    assert record["captured_at_utc"] == CAPTURE.isoformat()


def test_synthetic_end_to_end_stages_new_copy_and_reads_it_without_default_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    captured = tmp_path / "capture"
    results = tmp_path / "new-report"
    database = tmp_path / "operational.duckdb"
    source_db = tmp_path / "frozen.duckdb"
    root.mkdir()
    captured.mkdir()
    (captured / "inputs").mkdir()
    with connect(source_db) as con:
        con.execute(
            "CREATE TABLE mart_fact_team_match(season VARCHAR,fixture INT,gw INT,was_home BOOLEAN)"
        )
        con.execute("INSERT INTO mart_fact_team_match VALUES ('2025-26',77,4,TRUE)")
    source_hash = hashlib.sha256(source_db.read_bytes()).hexdigest()
    match, payloads, reference = synthetic()
    meta_body = json.dumps({"matches": [match]}).encode()
    (captured / "inputs/meta.raw").write_bytes(meta_body)
    meta = {**receipt(meta_body), "raw_file": "meta.raw"}
    states = {
        e: {"status": "received", "source": endpoint_source(captured, e, payloads[e])}
        for e in payloads
    }
    manifest = {
        "sdp_match_id": 1,
        "selected_match_record": match,
        "metadata_receipt": meta,
        "endpoints": states,
    }
    (captured / "capture-1.json").write_text(json.dumps(manifest))
    (captured / "result.json").write_text(
        json.dumps(
            {
                "completed": True,
                "postflight_unchanged": True,
                "endpoint_inventory": [
                    {"sdp_match_id": 1, "endpoint": e, **s} for e, s in states.items()
                ],
            }
        )
    )
    pilot = tmp_path / "pilot.json"
    pilot.write_text(json.dumps({"completed": True, "passed": True}))
    parser = root / "src/fpl/transform/competitive_participation_v2.py"
    parser.parent.mkdir(parents=True)
    parser.write_text("synthetic fixed parser fingerprint")
    config = {
        "season": "2025-26",
        "branch": "synthetic",
        "expected_selected_matches": 1,
        "source_database_sha256": source_hash,
        "parser_sha256": job.file_sha256(parser),
        "revised_pilot_sha256": job.file_sha256(pilot),
        "completed_capture_report_sha256": job.file_sha256(captured / "result.json"),
    }
    (root / "config").mkdir()
    (root / job.CONFIG).write_text(json.dumps(config))
    reference["database_sha256"] = source_hash
    monkeypatch.setattr(job, "SOURCE_FILES", (job.CONFIG,))
    monkeypatch.setattr(job.capture, "_head", lambda *_: "synthetic-clean-sha")
    monkeypatch.setattr(job.capture, "load_contract", lambda *_: {})
    monkeypatch.setattr(
        job.capture,
        "load_retained",
        lambda *_: job.capture.RetainedInputs(
            {1: match}, {1: meta}, {}, {}, {}, {"scope": "synthetic-only"}
        ),
    )
    monkeypatch.setattr(job, "reference_data", lambda *_: reference)
    monkeypatch.setattr(job, "club_crosswalk", lambda *_: {3: 303, 31: 3131})
    report = job.run(
        root=root,
        source_db=source_db,
        database=database,
        captured=captured,
        pilot_result=pilot,
        results=results,
    )
    assert report["completed"] and report["source_database_preserved"]
    assert report["counts"]["dev_competitive_match_version"] == 1
    assert report["counts"]["dev_competitive_participation_version"] == 24
    assert report["observed_view_access_check"]["windows"][0]["nominal_minutes_lower_bound"] == 90
    assert report["observed_view_access_check"]["exact_player_rest_hours"] is None
    assert hashlib.sha256(source_db.read_bytes()).hexdigest() == source_hash
    assert json.loads((results / "result.json").read_text())["completed"]
    assert not Path(str(database) + ".wal").exists()
    with connect(source_db, read_only=True) as con:
        assert con.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name LIKE 'dev_competitive_%'"
        ).fetchone() == (0,)


def test_second_real_parse_at_later_time_is_idempotent_but_stale_hash_not_accepted() -> None:
    first = interpreted()
    later = interpreted(interpreted_at=CAPTURE + timedelta(days=1))
    assert first["version_id"] == later["version_id"]
    assert first["semantic_sha256"] == later["semantic_sha256"]
    with duckdb.connect(":memory:") as con:
        apply_workload_schema(con)
        assert append_match(con, first)
        assert not append_match(con, later)
        changed = deepcopy(later)
        changed["rows"][0]["nominal_minutes"] = 5
        with pytest.raises(ValueError, match="semantic hash"):
            append_match(con, changed)
        stored = json.loads(
            con.execute(
                "SELECT CAST(record_json AS VARCHAR) FROM dev_competitive_match_version"
            ).fetchone()[0]
        )
        assert stored["interpretation_known_at"] == first["interpretation_known_at"]


def test_interpretation_cannot_precede_identity_evidence() -> None:
    with pytest.raises(ValueError, match="identity evidence"):
        interpreted(interpreted_at=CAPTURE)


def test_racing_destination_creation_never_overwrites_other_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.duckdb"
    destination = tmp_path / "new.duckdb"
    with connect(source) as con:
        con.execute("CREATE TABLE original(i INT)")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    copy = job._prepare_temporary_database

    def competing_copy(src: Path, tmp: Path) -> str | None:
        destination.write_bytes(b"other writer's data")
        return copy(src, tmp)

    monkeypatch.setattr(job, "_prepare_temporary_database", competing_copy)
    with pytest.raises(FileExistsError):
        job.consistent_copy(source, destination, before)
    assert destination.read_bytes() == b"other writer's data"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


def test_structured_failure_is_retained_only_in_new_owned_report_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**kwargs: Any) -> dict[str, Any]:
        raise ValueError("synthetic malformed raw fixture")

    monkeypatch.setattr(job, "_run", fail)
    arguments = {
        "root": tmp_path / "repo",
        "source_db": tmp_path / "source.duckdb",
        "database": tmp_path / "op.duckdb",
        "captured": tmp_path / "capture",
        "pilot_result": tmp_path / "pilot.json",
        "results": tmp_path / "new-results",
    }
    with pytest.raises(ValueError, match="malformed"):
        job.run(**arguments)
    failure = arguments["results"] / "failure.json"
    before = failure.read_bytes()
    record = json.loads(before)
    assert record["completed"] is False and record["model_fitting"] is False
    assert record["failure_class"] == "ValueError"
    assert record["operational_database_exists"] is False
    with pytest.raises(ValueError, match="new external"):
        job.run(**arguments)
    assert failure.read_bytes() == before
