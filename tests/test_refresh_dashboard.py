from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import duckdb
import pytest

from fpl.jobs import refresh_dashboard as job
from fpl.publish.dashboard_refresh import publication_status


def test_registered_primary_is_selected_by_hash_not_filename_or_newer_unregistered_file(
    tmp_path: Path,
) -> None:
    db = tmp_path / "operation.duckdb"
    source = tmp_path / "unexpected-name.jsonl"
    source.write_bytes(b"original frozen forecast")
    (tmp_path / "newer.jsonl").write_bytes(b"not registered")
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE ledger_forecast_run(run_id VARCHAR, artifact_sha256 VARCHAR)")
        con.execute("""CREATE TABLE ledger_sdp_evidence_pair(primary_artifact_sha256 VARCHAR,
                    season VARCHAR, primary_run_id VARCHAR, as_of VARCHAR, created_at VARCHAR,
                    prediction_id VARCHAR)""")
        con.execute("INSERT INTO ledger_forecast_run VALUES (?, ?)", ["r", job.digest(source)])
        con.execute(
            "INSERT INTO ledger_sdp_evidence_pair VALUES (?, ?, ?, ?, ?, ?)",
            [job.digest(source), "2026-27", "r", "2026-09-14", "2026-09-14", "p"],
        )
    assert job.latest_primary(db, tmp_path) == (source, "2026-27", "r")
    source.write_bytes(b"changed")
    with pytest.raises(ValueError, match="older forecasts cannot substitute"):
        job.latest_primary(db, tmp_path)


def test_freshness_separates_pending_gw_current_plan_and_old_scored_vintage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fpl.publish import dashboard_refresh as refresh

    monkeypatch.setattr(
        refresh,
        "validate_dashboard_json",
        lambda _: {"content_sha256": "manifest", "generated_at": "now"},
    )
    latest: dict[str, Any] = {
        "run_id": "primary",
        "as_of": "2026-09-14",
        "season": "2026-27",
        "gw_from": 5,
        "gw_to": 9,
        "component_modes": {"football_environment.primary": "sdp_v2"},
        "by_gw": [],
    }
    old = {
        **latest,
        "run_id": "old",
        "as_of": "2026-09-03",
        "gw_from": 3,
        "gw_to": 7,
        "by_gw": [{"gw": 3}],
    }
    for scope in ["player", "team"]:
        (tmp_path / f"{scope}_forecast_vs_actual.json").write_text(
            json.dumps({"runs": [old, latest]})
        )
    (tmp_path / "next_gw.json").write_text(
        json.dumps({"plans": [{"plan_kind": "platform_default", "forecast_run_id": "old"}]})
    )
    sidecar = {
        "gameweeks": [
            {
                "season": "2026-27",
                "gw": 3,
                "finished": True,
                "fixtures_completed": 10,
                "fixtures_total": 10,
                "source_known_at": "today",
            },
            {
                "season": "2026-27",
                "gw": 4,
                "finished": False,
                "fixtures_completed": 10,
                "fixtures_total": 10,
                "source_known_at": "today",
            },
        ]
    }
    result = publication_status(tmp_path, sidecar)
    assert result["latest_finalized_gw"] == 3
    assert result["awaiting_finality"] == [
        {"gw": 4, "fixtures_completed": 10, "fixtures_total": 10}
    ]
    assert result["latest_scored_gw"] == {"player": 3, "team": 3}
    assert result["latest_forecast"]["gw_from"] == 5
    assert not result["current_platform_plan"]
    (tmp_path / "next_gw.json").write_text(
        json.dumps({"plans": [{"plan_kind": "platform_default", "forecast_run_id": "primary"}]})
    )
    assert publication_status(tmp_path, sidecar)["current_platform_plan"]
    sidecar["gameweeks"].append({**sidecar["gameweeks"][1], "gw": 6, "fixtures_completed": 0})
    status = publication_status(tmp_path, sidecar)
    assert status["forecast_rollover_required"]
    assert status["next_fixture_gw"] == 6


@pytest.mark.parametrize("shared_backup", [False, True])
@pytest.mark.parametrize("with_news", [False, True])
def test_completion_reuses_bound_plan_attaches_before_build_and_never_runs_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shared_backup: bool, with_news: bool
) -> None:
    calls = []
    forecast = tmp_path / "forecast.jsonl"
    forecast.write_bytes(b"frozen")
    plan = tmp_path / "plan.json"
    plan.write_bytes(b"immutable plan")
    recovery = tmp_path / "recovery.duckdb"
    recovery.write_bytes(b"pre-cycle state")
    cycle_backup = (
        {"path": str(recovery), "sha256": job.digest(recovery)} if shared_backup else None
    )
    monkeypatch.setattr(job, "latest_primary", lambda *a: (forecast, "2026-27", "run"))
    monkeypatch.setattr(job, "reusable_plan", lambda p, h: h == job.digest(forecast))

    class Connection:
        def execute(self, _: str) -> None:
            pass

    @contextmanager
    def lock(*a: Any, **kw: Any) -> Any:
        if shared_backup:
            assert kw["backup"] is None
            assert kw["cycle_backup"] == cycle_backup
        else:
            assert kw["backup"].name == "before-outcomes.duckdb"
        yield Connection()

    monkeypatch.setattr(job.daily_pl_sdp, "writer_lock", lock)
    monkeypatch.setattr(
        job, "attach_finalized_outcomes", lambda *a, **kw: calls.append("attach") or {}
    )
    monkeypatch.setattr(job, "asdict", lambda v: v)
    news_store = tmp_path / "news-store" if with_news else None

    def build(*a: Any, **kw: Any) -> dict[str, Any]:
        assert kw["news_store"] == news_store
        calls.append("build")
        return {
            "publication_status": {
                "current_platform_plan": True,
                "latest_forecast": {"run_id": "run"},
            },
            "current_availability": {"matched_player_rows": 15},
        }

    monkeypatch.setattr(job, "build", build)
    from fpl.jobs import build_sdp_dashboard

    monkeypatch.setattr(build_sdp_dashboard, "install_preview", lambda *a: calls.append("install"))
    monkeypatch.setattr(job.shutil, "which", lambda _: "npm")

    def command(args: list[str], **kw: Any) -> None:
        assert args == ["npm", "run", "build"]
        calls.append("frontend")

    monkeypatch.setattr(job.subprocess, "run", command)
    for index in range(2):
        destination = tmp_path / f"repeat-{index}"
        destination.mkdir()
        result = job.complete(
            tmp_path / "db",
            destination,
            tmp_path,
            tmp_path / "public",
            tmp_path / "cache",
            initial_plan=plan,
            cycle_backup=cycle_backup,
            news_store=news_store,
        )
        assert result["plan_reused"]
        assert result["current_availability"] == {"matched_player_rows": 15}
    assert calls == ["attach", "build", "install", "frontend"] * 2
    assert forecast.read_bytes() == b"frozen"
    assert plan.read_bytes() == b"immutable plan"


def test_one_failed_cycle_backup_blocks_another_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _runner_args(tmp_path)

    def failed_capture(**kwargs: Any) -> None:
        raise RuntimeError("capture interrupted after recovery was retained")

    monkeypatch.setattr(job.daily_pl_sdp, "run", failed_capture)
    assert job.main(args) == 1
    backups = list((tmp_path / "runs").glob("dashboard-*/recovery.duckdb"))
    assert len(backups) == 1
    original_hash = job.digest(backups[0])
    monkeypatch.setattr(
        job.daily_pl_sdp, "run", lambda **kwargs: pytest.fail("unresolved run retried")
    )
    assert job.main(args) == 1
    assert list((tmp_path / "runs").glob("dashboard-*/recovery.duckdb")) == backups
    assert job.digest(backups[0]) == original_hash
    reports = [
        json.loads(p.read_text()) for p in (tmp_path / "runs").glob("dashboard-*/receipt.json")
    ]
    assert any("incomplete cycle recovery requires review" in r.get("error", "") for r in reports)


def test_cycle_preflight_budgets_backup_and_exports_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args = _runner_args(tmp_path)
    database = tmp_path / "operational.duckdb"
    before = job.digest(database)
    public = tmp_path / "public"
    public.mkdir()
    (public / "export.json").write_bytes(b"123")
    allocations: list[int] = []

    def space(destination: Path, required_bytes: int) -> dict[str, str]:
        allocations.append(required_bytes)
        if required_bytes:
            raise RuntimeError("projected disk space is below 20 GiB")
        return {"status": "OK"}

    monkeypatch.setattr(job, "check_disk_space", space)
    monkeypatch.setattr(job, "create_recovery", lambda *a: pytest.fail("low space began copy"))
    assert job.main(args) == 1
    assert allocations == [0, database.stat().st_size + 6]
    assert not list((tmp_path / "runs").rglob("*.duckdb"))
    assert job.digest(database) == before


def test_daily_capture_reuses_verified_cycle_copy_without_additional_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fpl.jobs.capture_pl_sdp import CaptureReport

    _runner_args(tmp_path)
    database = tmp_path / "operational.duckdb"
    destination = tmp_path / "cycle"
    destination.mkdir()
    backup = job.create_recovery(database, destination)
    monkeypatch.setattr(
        job.daily_pl_sdp,
        "_prepare_temporary_database",
        lambda *a: pytest.fail("shared cycle made an additional full copy"),
    )
    monkeypatch.setattr(job.daily_pl_sdp, "inventory", lambda *a, **kw: {"healthy": True})
    monkeypatch.setattr(job.daily_pl_sdp.daily_snapshot, "run", lambda **kw: 0)
    monkeypatch.setattr(
        job.daily_pl_sdp.capture_pl_sdp,
        "capture",
        lambda **kw: CaptureReport(season="2026-27"),
    )
    assert (
        job.daily_pl_sdp.run(
            database=database,
            runs=tmp_path / "runs",
            raw_only=True,
            cycle_backup=backup,
        )
        == 0
    )
    assert not list((tmp_path / "runs").rglob("*.duckdb"))
    report = json.loads(next((tmp_path / "runs").glob("*/report.json")).read_text())
    assert report["backup"]["sha256"] == backup["sha256"]
    assert report["backup"]["semantics"] == "pre_cycle"


def test_cycle_backup_current_at_capture_then_stable_after_database_advances(
    tmp_path: Path,
) -> None:
    _runner_args(tmp_path)
    database = tmp_path / "operational.duckdb"
    destination = tmp_path / "cycle"
    destination.mkdir()
    backup = job.create_recovery(database, destination)
    with job.daily_pl_sdp.writer_lock(
        database, cycle_backup=backup, require_current_backup=True
    ) as con:
        con.execute("CREATE TABLE newly_captured(i INTEGER)")
        con.execute("CHECKPOINT")
    assert job.digest(database) != backup["sha256"]
    with job.daily_pl_sdp.writer_lock(database, cycle_backup=backup) as con:
        assert con.execute("SELECT count(*) FROM newly_captured").fetchone() == (0,)
    with pytest.raises(ValueError, match="differs from the current database"):
        with job.daily_pl_sdp.writer_lock(
            database, cycle_backup=backup, require_current_backup=True
        ):
            pytest.fail("outdated pre-capture backup allowed")
    before = job.digest(database)
    Path(backup["path"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="differs from its verified receipt"):
        with job.daily_pl_sdp.writer_lock(database, cycle_backup=backup):
            pytest.fail("tampered backup allowed")
    assert job.digest(database) == before


def test_reusable_plan_rejects_custom_constraints_and_wrong_forecast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    policy = SimpleNamespace(
        plan_origin="platform",
        locked_codes=(),
        excluded_codes=(),
        risk_lambda=0,
        min_bench_appearance=0,
    )
    artifact = SimpleNamespace(
        search_policy=policy,
        manager_context=None,
        provenance=SimpleNamespace(
            forecast=SimpleNamespace(sha256="forecast"), squad_rules=SimpleNamespace(sha256="rules")
        ),
    )
    monkeypatch.setattr(job, "read_optimizer_artifact", lambda _: artifact)
    monkeypatch.setattr(job, "digest", lambda _: "rules")
    assert job.reusable_plan(tmp_path, "forecast")
    assert not job.reusable_plan(tmp_path, "wrong")
    policy.locked_codes = (1,)
    assert not job.reusable_plan(tmp_path, "forecast")


def _runner_args(tmp_path: Path) -> list[str]:
    database = tmp_path / "operational.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE snapshot_capture(mode VARCHAR, captured_at TIMESTAMPTZ)")
    return [
        "--db",
        str(database),
        "--runs",
        str(tmp_path / "runs"),
        "--forecast-dir",
        str(tmp_path / "forecasts"),
        "--preview-public",
        str(tmp_path / "public"),
        "--plan-store",
        str(tmp_path / "plans"),
    ]


def test_startup_failure_is_durable_and_does_not_remove_another_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _runner_args(tmp_path)
    runs = tmp_path / "runs"
    runs.mkdir()
    lock = runs / ".dashboard-refresh.lock"
    original = json.dumps({"pid": job.os.getpid(), "started_at": "original"}).encode()
    lock.write_bytes(original)
    monkeypatch.setattr(job, "complete", lambda *a, **kw: pytest.fail("blocked run executed"))
    assert job.main(args) == 1
    receipt = next(runs.glob("dashboard-*/receipt.json"))
    report = json.loads(receipt.read_text())
    assert report["status"] == "FAILED"
    assert report["phase"] == "acquire_lock"
    assert "FileExistsError" in report["error"]
    assert "Dashboard refresh failed" in (receipt.parent / "refresh.log").read_text()
    assert lock.read_bytes() == original


def test_capture_failure_records_phase_and_releases_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args = _runner_args(tmp_path)

    def fail(**kwargs: Any) -> None:
        receipt = next((tmp_path / "runs").glob("dashboard-*/receipt.json"))
        assert json.loads(receipt.read_text())["phase"] == "capture"
        raise RuntimeError("injected capture failure")

    monkeypatch.setattr(job.daily_pl_sdp, "run", fail)
    assert job.main(args) == 1
    report = json.loads(next((tmp_path / "runs").glob("dashboard-*/receipt.json")).read_text())
    assert report["status"] == "FAILED"
    assert report["phase"] == "capture"
    assert "injected capture failure" in report["error"]
    assert not (tmp_path / "runs" / ".dashboard-refresh.lock").exists()


@pytest.mark.parametrize("with_news", [False, True])
def test_full_cycle_orders_capture_export_r2_retention_and_repeats_without_console(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    with_news: bool,
) -> None:
    from datetime import UTC, datetime

    from fpl.publish import r2_dashboard

    args = [*_runner_args(tmp_path), "--r2-config", str(tmp_path / "publication.json")]
    news_store = tmp_path / "captured-news" if with_news else None
    if news_store is not None:
        args += ["--news-store", str(news_store)]
    calls: list[str] = []

    def capture(**kwargs: Any) -> int:
        assert kwargs["include_workload"] and kwargs["player_history"]
        assert "news_store" not in kwargs  # Export wiring never activates provider capture.
        backup = kwargs["cycle_backup"]
        assert job.digest(Path(backup["path"])) == backup["sha256"]
        assert backup["sha256"] == job.digest(kwargs["database"])
        calls.append("capture")
        with duckdb.connect(str(kwargs["database"])) as con:
            con.execute(
                "INSERT INTO snapshot_capture VALUES (?, ?)", ["player-history", datetime.now(UTC)]
            )
        return 1  # Existing provider gaps must not mask a complete FPL capture.

    def complete(*a: Any, **kw: Any) -> dict[str, Any]:
        assert Path(kw["cycle_backup"]["path"]).exists()
        assert kw["news_store"] == news_store
        calls.append("dashboard")
        return {"forecast_regenerated": False}

    def publish(*a: Any, **kw: Any) -> dict[str, Any]:
        receipt = next(
            p
            for p in (tmp_path / "runs").glob("dashboard-*/receipt.json")
            if json.loads(p.read_text())["phase"] == "r2_publication"
        )
        assert json.loads(receipt.read_text())["public_publication"]["status"] == "RUNNING"
        calls.append("r2")
        return {"status": "COMPLETE"}

    original_recovery = job.create_recovery

    def recovery(database: Path, destination: Path) -> dict[str, str]:
        assert (tmp_path / "runs" / ".dashboard-refresh.lock").exists()
        report = json.loads((destination / "receipt.json").read_text())
        assert report["phase"] == "recovery_backup"
        assert report["backup_semantics"] == "pre_cycle"
        calls.append("recovery")
        return original_recovery(database, destination)

    def retention(*a: Any, **kw: Any) -> dict[str, str]:
        assert job.digest(kw["recovery"]) == kw["recovery_sha"]
        assert kw["archive_pins"] is True
        calls.append("retention")
        return {"status": "COMPLETE"}

    monkeypatch.setattr(job.daily_pl_sdp, "run", capture)
    monkeypatch.setattr(job, "complete", complete)
    monkeypatch.setattr(r2_dashboard, "publish_r2_dashboard", publish)
    monkeypatch.setattr(job, "create_recovery", recovery)
    monkeypatch.setattr(job, "prune_runs", retention)
    monkeypatch.setattr(job.sys, "stdout", None)
    for _ in range(2):
        assert job.main(args) == 0
    assert calls == ["recovery", "capture", "dashboard", "r2", "retention"] * 2
    reports = [
        json.loads(p.read_text()) for p in (tmp_path / "runs").glob("dashboard-*/receipt.json")
    ]
    assert len(reports) == 2
    assert all(r["status"] == "COMPLETE" and r["phase"] == "finished" for r in reports)
    assert len(list((tmp_path / "runs").rglob("*.duckdb"))) == 2
    assert not (tmp_path / "runs" / ".dashboard-refresh.lock").exists()


def test_failed_publication_skips_retention_and_returns_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fpl.publish import r2_dashboard

    args = [*_runner_args(tmp_path), "--skip-capture", "--r2-config", str(tmp_path / "r2.json")]
    monkeypatch.setattr(job, "complete", lambda *a, **kw: {"forecast_regenerated": False})
    monkeypatch.setattr(r2_dashboard, "publish_r2_dashboard", lambda *a, **kw: {"status": "FAILED"})
    monkeypatch.setattr(
        job, "prune_runs", lambda *a, **kw: pytest.fail("failed publication pruned")
    )
    assert job.main(args) == 1
    assert not (tmp_path / "runs" / ".dashboard-refresh.lock").exists()


def test_proven_dead_cycle_and_database_locks_recover_without_changing_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess
    import sys

    args = [*_runner_args(tmp_path), "--skip-capture"]
    exited = subprocess.Popen([sys.executable, "-c", "pass"])
    exited.wait(timeout=20)
    original = json.dumps({"pid": exited.pid, "started_at": "preserved original"}).encode()
    runs = tmp_path / "runs"
    runs.mkdir()
    db = tmp_path / "operational.duckdb"
    before = job.digest(db)
    locks = [runs / ".dashboard-refresh.lock", Path(str(db) + ".daily-sdp.lock")]
    for lock in locks:
        lock.write_bytes(original)

    def complete(*a: Any, **kw: Any) -> dict[str, Any]:
        with job.daily_pl_sdp.writer_lock(db) as con:
            assert con.execute("SELECT count(*) FROM snapshot_capture").fetchone() == (0,)
        return {"forecast_regenerated": False}

    monkeypatch.setattr(job, "complete", complete)
    monkeypatch.setattr(job, "prune_runs", lambda *a, **kw: {"status": "COMPLETE"})
    assert job.main(args) == 0
    assert job.digest(db) == before
    for lock in locks:
        assert not lock.exists()
        evidence = list(lock.with_name(lock.name + ".recovered").glob("*/original.lock"))
        assert len(evidence) == 1 and evidence[0].read_bytes() == original
