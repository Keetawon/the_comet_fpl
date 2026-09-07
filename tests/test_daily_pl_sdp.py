"""Offline operational guardrails; no scheduler registration or network calls."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fpl.ingest.live_snapshot import capture_payload, write_capture
from fpl.ingest.pl_sdp import RawPayload
from fpl.jobs import daily_pl_sdp as job
from fpl.jobs.capture_pl_sdp import CaptureReport
from fpl.storage.db import connect, initialise
from fpl.transform.pl_sdp import land_payload

SEASON = "2026-27"
NOW = datetime(2026, 9, 6, 18, tzinfo=UTC)


def _official(database: Path) -> None:
    bootstrap = {
        "events": [{"id": 1, "name": "GW1", "deadline_time": "2026-08-21T17:30:00Z"}],
        "teams": [
            {"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "code": 9, "name": "Coventry", "short_name": "COV"},
        ],
        "elements": [{"id": 10, "code": 10010, "web_name": "Tester", "element_type": 3, "team": 1}],
    }
    fixtures = [
        {
            "id": fixture,
            "code": 9000 + fixture,
            "event": fixture,
            "finished": fixture == 1,
            "finished_provisional": True,
            "kickoff_time": kickoff,
            "team_h": 1,
            "team_a": 2,
            "team_h_score": 1,
            "team_a_score": 0,
            "pulse_id": 8000 + fixture,
        }
        for fixture, kickoff in ((1, "2026-08-22T14:00:00Z"), (2, "2026-09-05T14:00:00Z"))
    ]
    with initialise(database) as con:
        write_capture(
            con,
            [capture_payload("bootstrap-static", bootstrap), capture_payload("fixtures", fixtures)],
            season=SEASON,
            gw=2,
            mode="daily",
            captured_at=NOW,
        )


def _land(database: Path, *, revision: bool = False, incomplete: bool = False) -> None:
    matches = [
        {
            "matchId": 7000 + fixture,
            "season": 2026,
            "matchWeek": fixture,
            "kickoff": kickoff,
            "resultType": "NormalResult",
            "homeTeam": {"id": 3, "name": "Arsenal", "score": 1},
            "awayTeam": {"id": 9, "name": "Coventry", "score": 0},
        }
        for fixture, kickoff in ((1, "2026-08-22T14:00:00Z"), (2, "2026-09-05T14:00:00Z"))
    ]
    payloads: list[tuple[str, int | None, object]] = [("matches", None, {"data": matches})]
    for identifier in [7002] if revision else [7001, 7002]:
        stats = [
            {"side": "Home", "teamId": 3, "stats": {"ontargetScoringAtt": 5 if revision else 4}},
            {"side": "Away", "teamId": 9, "stats": {"ontargetScoringAtt": 0}},
        ]
        payloads.append(("match_stats", identifier, stats[:1] if incomplete else stats))
    with connect(database) as con:
        for endpoint, identifier, payload in payloads:
            text = json.dumps(payload)
            raw = RawPayload(
                endpoint=endpoint,
                path=f"/{endpoint}/{identifier}",
                params={},
                fetched_at=NOW.replace(minute=1 if revision else 0),
                status_code=200,
                text=text,
                sha256=hashlib.sha256(text.encode()).hexdigest(),
                byte_count=len(text),
                payload=payload,
            )
            land_payload(con, raw, season=SEASON, sdp_match_id=identifier)


def _stub_jobs(monkeypatch: pytest.MonkeyPatch, database: Path) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(job.daily_snapshot, "run", lambda **kwargs: 0)

    def capture(**kwargs: Any) -> CaptureReport:
        calls.append(kwargs)
        _land(database, revision=kwargs["refresh_stats"])
        return CaptureReport(
            season=SEASON, completed=2, stats_fetched=1 if kwargs["refresh_stats"] else 2
        )

    monkeypatch.setattr(job.capture_pl_sdp, "capture", capture)
    return calls


def test_raw_cycle_preserves_backup_versions_and_covers_old_missing_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operational.duckdb"
    _official(database)
    before = job._sha256(database)
    calls = _stub_jobs(monkeypatch, database)
    assert job.run(database=database, runs=tmp_path / "runs", raw_only=True) == 0
    assert [(call["lookback_days"], call["refresh_stats"]) for call in calls] == [
        (None, False),
        (7, True),
    ]
    assert all(call["db_path"] == database for call in calls)
    run = next((tmp_path / "runs").iterdir())
    assert job._sha256(run / "before.duckdb") == before
    report = json.loads((run / "report.json").read_text())
    assert report["mode"] == "raw_only"
    assert report["staging_status"] == "deferred"
    assert not report["consumer_ready"]
    assert "staging_exit_code" not in report
    assert report["freshness"]["retained_complete"] == 2
    assert report["freshness"]["official_provisional_ended"] == 1
    assert report["healthy"]
    with connect(database, read_only=True) as con:
        assert con.execute(
            "SELECT count(*) FROM raw_pl_sdp_payload WHERE endpoint='match_stats'"
        ).fetchone() == (3,)


def test_inventory_distinguishes_incomplete_from_absent(tmp_path: Path) -> None:
    database = tmp_path / "operational.duckdb"
    _official(database)
    _land(database, incomplete=True)
    with connect(database) as con:
        con.execute("DELETE FROM raw_pl_sdp_payload WHERE sdp_match_id = 7002")
        result = job.inventory(con, season=SEASON, now=NOW)
    assert result["missing_match_ids"] == [7001, 7002]
    assert result["incomplete_match_ids"] == [7001]
    assert result["awaiting_stats_match_ids"] == [7002]
    assert not result["healthy"]


def test_inventory_rejects_score_contradiction_and_does_not_assume_pulse_id(tmp_path: Path) -> None:
    database = tmp_path / "operational.duckdb"
    _official(database)
    _land(database)
    with connect(database) as con:
        result = job.inventory(con, season=SEASON, now=NOW)
        assert result["healthy"]  # pulse 8001/8002 != provider 7001/7002
        con.execute("UPDATE stg_live_fixture_version SET team_h_score = 9 WHERE fixture = 1")
        result = job.inventory(con, season=SEASON, now=NOW)
    assert result["unresolved_fixture_ids"] == [1]
    assert len(result["contradictions"]) == 1
    assert not result["healthy"]


def test_stale_sidecar_and_unresolved_wal_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "operational.duckdb"
    initialise(database).close()
    with job.writer_lock(database):
        with pytest.raises(FileExistsError):
            with job.writer_lock(database):
                pytest.fail("overlapping writer admitted")
    wal = job._wal_path(database)
    wal.touch()
    with pytest.raises(RuntimeError, match="unresolved WAL"):
        with job.writer_lock(database):
            pytest.fail("unresolved WAL admitted")
    assert wal.exists()


def test_actual_writer_connection_excludes_noncooperating_process(tmp_path: Path) -> None:
    database = tmp_path / "operational.duckdb"
    initialise(database).close()
    with job.writer_lock(database):
        result = subprocess.run(
            [sys.executable, "-c", "import duckdb,sys; duckdb.connect(sys.argv[1])", str(database)],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    assert result.returncode != 0
    assert "lock" in result.stderr.lower() or "being used" in result.stderr.lower()


def test_default_database_refused_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "fpl.duckdb"
    initialise(database).close()
    monkeypatch.setattr(job, "default_db_path", lambda: database)
    with pytest.raises(ValueError, match="never the default"):
        job.run(database=database, runs=tmp_path / "runs")
    assert not (tmp_path / "runs").exists()


def test_network_failure_retains_partial_raw_and_emits_failure_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operational.duckdb"
    _official(database)
    monkeypatch.setattr(job.daily_snapshot, "run", lambda **kwargs: 0)

    def fail(**kwargs: Any) -> CaptureReport:
        _land(database)
        raise RuntimeError("injected network interruption")

    monkeypatch.setattr(job.capture_pl_sdp, "capture", fail)
    assert job.run(database=database, runs=tmp_path / "runs", raw_only=True) == 1
    report = json.loads(next((tmp_path / "runs").glob("*/report.json")).read_text())
    assert "injected network interruption" in report["failures"][0]
    with connect(database, read_only=True) as con:
        assert con.execute("SELECT count(*) FROM raw_pl_sdp_payload").fetchone() == (3,)
    assert not database.with_name(database.name + ".daily-sdp.lock").exists()


def test_capture_report_failure_is_not_silently_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operational.duckdb"
    _official(database)
    _land(database)
    monkeypatch.setattr(job.daily_snapshot, "run", lambda **kwargs: 0)
    monkeypatch.setattr(
        job.capture_pl_sdp,
        "capture",
        lambda **kwargs: CaptureReport(failures=("match 7001: HTTP 503",)),
    )
    assert job.run(database=database, runs=tmp_path / "runs", raw_only=True) == 1


def test_staging_uses_explicit_database_and_new_report_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fpl.jobs import audit_pl_sdp

    database = tmp_path / "operational.duckdb"
    _official(database)
    _stub_jobs(monkeypatch, database)
    arguments: list[str] = []
    monkeypatch.setattr(audit_pl_sdp, "main", lambda argv: arguments.extend(argv) or 0)
    monkeypatch.setattr(job, "_verify_staging", lambda *args, **kwargs: {"healthy": True})
    assert job.run(database=database, runs=tmp_path / "runs") == 0
    assert arguments[:3] == ["--db", str(database), "--stage"]
    assert Path(arguments[-1]).is_relative_to(tmp_path / "runs")


def test_backup_failure_prevents_every_network_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operational.duckdb"
    _official(database)

    def fail(*args: object) -> None:
        raise OSError("backup disk full")

    monkeypatch.setattr(job, "_prepare_temporary_database", fail)
    monkeypatch.setattr(
        job.daily_snapshot, "run", lambda **kwargs: pytest.fail("network after failed backup")
    )
    assert job.run(database=database, runs=tmp_path / "runs", raw_only=True) == 1
    report = json.loads(next((tmp_path / "runs").glob("*/report.json")).read_text())
    assert report["failures"] == ["OSError: backup disk full"]


def test_staging_failure_preserves_new_raw_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fpl.jobs import audit_pl_sdp

    database = tmp_path / "operational.duckdb"
    _official(database)
    _stub_jobs(monkeypatch, database)

    def fail(argv: list[str]) -> int:
        raise RuntimeError("injected staging failure")

    monkeypatch.setattr(audit_pl_sdp, "main", fail)
    assert job.run(database=database, runs=tmp_path / "runs") == 1
    report_path = next((tmp_path / "runs").glob("*/report.json"))
    report = json.loads(report_path.read_text())
    assert "injected staging failure" in report["failures"][0]
    assert report["freshness"]["retained_complete"] == 2
    assert (report_path.parent / "before.duckdb").exists()
    with connect(database, read_only=True) as con:
        assert con.execute(
            "SELECT count(*) FROM raw_pl_sdp_payload WHERE endpoint='match_stats'"
        ).fetchone() == (3,)


def test_exit_zero_capture_with_missing_stats_fails_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "operational.duckdb"
    _official(database)
    _land(database, incomplete=True)
    monkeypatch.setattr(job.daily_snapshot, "run", lambda **kwargs: 0)
    monkeypatch.setattr(job.capture_pl_sdp, "capture", lambda **kwargs: CaptureReport())
    assert job.run(database=database, runs=tmp_path / "runs", raw_only=True) == 1
    report = json.loads(next((tmp_path / "runs").glob("*/report.json")).read_text())
    assert report["failures"] == []
    assert report["freshness"]["incomplete_match_ids"] == [7001, 7002]


def test_audit_exit_zero_without_pit_rows_is_not_consumer_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fpl.jobs import audit_pl_sdp

    database = tmp_path / "operational.duckdb"
    _official(database)
    _stub_jobs(monkeypatch, database)
    monkeypatch.setattr(audit_pl_sdp, "main", lambda argv: 0)
    assert job.run(database=database, runs=tmp_path / "runs") == 1
    report = json.loads(next((tmp_path / "runs").glob("*/report.json")).read_text())
    assert not report["consumer_ready"]
    assert report["staging_verification"]["missing_or_invalid_match_ids"] == [7001, 7002]


def test_stage_verification_exercises_real_pit_reader(tmp_path: Path) -> None:
    from fpl.jobs import audit_pl_sdp

    database = tmp_path / "operational.duckdb"
    _official(database)
    _land(database)
    assert (
        audit_pl_sdp.main(["--db", str(database), "--stage", "--results", str(tmp_path / "audit")])
        == 0
    )
    with connect(database) as con:
        result = job._verify_staging(
            con, season=SEASON, expected=[7001, 7002], as_of=NOW.replace(hour=23)
        )
    assert result["healthy"]
    assert result["football_rows"] == 4
    assert result["tactical_rows"] == 16
