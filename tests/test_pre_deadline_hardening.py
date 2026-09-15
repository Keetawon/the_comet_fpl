"""Offline checks for refresh ordering, reproducible input retention and evidence orchestration."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fpl.jobs import pre_deadline_forecast as job
from fpl.storage.db import connect, initialise


def test_source_snapshot_survives_later_operational_writes(tmp_path):
    database = tmp_path / "operational.duckdb"
    with initialise(database) as con:
        con.execute("CREATE TABLE capture_witness (version INTEGER)")
        con.execute("INSERT INTO capture_witness VALUES (1)")
    snapshot = tmp_path / "forecast-source.duckdb"
    job._snapshot_source(database, snapshot)
    digest = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert digest == hashlib.sha256(database.read_bytes()).hexdigest()
    with connect(database) as con:
        con.execute("INSERT INTO capture_witness VALUES (2)")
    with connect(snapshot, read_only=True) as con:
        assert con.execute("SELECT * FROM capture_witness").fetchall() == [(1,)]
    assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == digest
    with pytest.raises(FileExistsError, match="immutable"):
        job._snapshot_source(database, snapshot)


@pytest.mark.parametrize("evidence_available", [True, False])
def test_pre_deadline_uses_refreshed_copy_and_records_both_outputs(
    tmp_path, monkeypatch, evidence_available
):
    database = tmp_path / "operational.duckdb"
    with initialise(database) as con:
        con.execute("CREATE TABLE capture_witness (version INTEGER)")
    order = []
    monkeypatch.setattr(job.prospective_points_v1, "_git_worktree_clean", lambda *a: True)

    def refresh(**kwargs):
        order.append("refresh")
        with connect(kwargs["database"]) as con:
            con.execute("INSERT INTO capture_witness VALUES (1)")
        receipt_dir = kwargs["runs"] / "capture"
        receipt_dir.mkdir()
        (receipt_dir / "report.json").write_text('{"healthy": true}')
        return 0

    def forecast(argv):
        order.append("predict")
        source = Path(argv[argv.index("--db") + 1])
        assert source != database
        with connect(source, read_only=True) as con:
            assert con.execute("SELECT * FROM capture_witness").fetchall() == [(1,)]
        cutoff = datetime.fromisoformat(argv[argv.index("--as-of") + 1])
        assert cutoff <= datetime.now(UTC)
        assert "--refresh-report" in argv
        output = Path(argv[argv.index("--output") + 1])
        output.write_bytes(b"primary")
        output.with_name(output.stem + ".shadow-incumbent.jsonl").write_bytes(b"shadow")
        return 0

    def record(argv):
        order.append("record")
        assert Path(argv[argv.index("--db") + 1]) == database
        assert Path(argv[argv.index("--primary") + 1]).read_bytes() == b"primary"
        assert Path(argv[argv.index("--shadow") + 1]).read_bytes() == b"shadow"
        if not evidence_available:
            raise OSError("evidence storage unavailable")
        return 0

    monkeypatch.setattr(job.daily_pl_sdp, "run", refresh)
    monkeypatch.setattr(job.prospective_points_v1, "main", forecast)
    monkeypatch.setattr(job.record_sdp_evidence, "main", record)
    assert job.main(
        [
            "--db",
            str(database),
            "--runs",
            str(tmp_path / "runs"),
            "--gw-from",
            "4",
            "--gw-to",
            "8",
            "--output",
            str(tmp_path / "forecast.jsonl"),
        ]
    ) == (0 if evidence_available else 1)
    assert order == ["refresh", "predict", "record"]
    report = json.loads(next((tmp_path / "runs").glob("*/forecast.json")).read_text())
    assert report["primary_artifact_sha256"] == hashlib.sha256(b"primary").hexdigest()
    assert report["shadow_artifact_sha256"] == hashlib.sha256(b"shadow").hexdigest()
    assert report["evidence_exit_code"] == (0 if evidence_available else 1)
    assert report["evidence_failure"] == (
        None if evidence_available else "OSError: evidence storage unavailable"
    )


def test_future_cutoff_refused_before_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(
        job.daily_pl_sdp, "run", lambda **kw: pytest.fail("future cutoff reached capture")
    )
    with pytest.raises(ValueError, match="cannot be in the future"):
        job.main(
            [
                "--db",
                str(tmp_path / "db.duckdb"),
                "--runs",
                str(tmp_path / "runs"),
                "--gw-from",
                "4",
                "--gw-to",
                "8",
                "--output",
                str(tmp_path / "forecast.jsonl"),
                "--as-of",
                (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            ]
        )


@pytest.mark.parametrize("extra", ['{"healthy": false}', "[]", '{"healthy": NaN}'])
def test_refresh_bundle_binds_all_receipts_and_fails_closed(tmp_path, extra):
    capture = tmp_path / "capture"
    capture.mkdir()
    (capture / "report.json").write_text('{"healthy": true}')
    failure = tmp_path / "failed"
    failure.mkdir()
    (failure / "report.json").write_text(extra)
    path, status = job._refresh_receipt(tmp_path, 0)
    report = json.loads(path.read_text())
    assert status == 1
    assert report["healthy"] is False
    assert [row["path"] for row in report["receipts"]] == [
        "capture/report.json",
        "failed/report.json",
    ]
    assert report["receipts"][1]["sha256"] == hashlib.sha256(extra.encode()).hexdigest()


def test_missing_refresh_receipt_cannot_claim_success(tmp_path):
    path, status = job._refresh_receipt(tmp_path, 0)
    assert status == 1
    assert json.loads(path.read_text())["receipts"] == []


def test_snapshot_failure_leaves_durable_failure_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(job.prospective_points_v1, "_git_worktree_clean", lambda *a: True)
    monkeypatch.setattr(job.daily_pl_sdp, "run", lambda **kw: 1)
    monkeypatch.setattr(job.prospective_points_v1, "main", lambda *a: pytest.fail("no stable DB"))
    assert (
        job.main(
            [
                "--db",
                str(tmp_path / "absent.duckdb"),
                "--runs",
                str(tmp_path / "runs"),
                "--gw-from",
                "4",
                "--gw-to",
                "8",
                "--output",
                str(tmp_path / "p.jsonl"),
            ]
        )
        == 1
    )
    receipt = json.loads(next((tmp_path / "runs").glob("*/forecast.json")).read_text())
    assert "FileNotFoundError" in receipt["snapshot_failure"]
    assert receipt["forecast_exit_code"] is None
    assert receipt["prediction_cutoff"] is None
    assert receipt["source_database_sha256"] is None
