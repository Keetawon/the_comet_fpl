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


def test_completion_reuses_bound_plan_attaches_before_build_and_never_runs_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    forecast = tmp_path / "forecast.jsonl"
    forecast.write_bytes(b"frozen")
    plan = tmp_path / "plan.json"
    plan.write_bytes(b"immutable plan")
    monkeypatch.setattr(job, "latest_primary", lambda *a: (forecast, "2026-27", "run"))
    monkeypatch.setattr(job, "reusable_plan", lambda p, h: h == job.digest(forecast))

    class Connection:
        def execute(self, _: str) -> None:
            pass

    @contextmanager
    def lock(*a: Any, **kw: Any) -> Any:
        assert kw["backup"].name == "before-outcomes.duckdb"
        yield Connection()

    monkeypatch.setattr(job.daily_pl_sdp, "writer_lock", lock)
    monkeypatch.setattr(
        job, "attach_finalized_outcomes", lambda *a, **kw: calls.append("attach") or {}
    )
    monkeypatch.setattr(job, "asdict", lambda v: v)
    monkeypatch.setattr(
        job,
        "build",
        lambda *a, **kw: (
            calls.append("build")
            or {
                "publication_status": {
                    "current_platform_plan": True,
                    "latest_forecast": {"run_id": "run"},
                }
            }
        ),
    )
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
        assert job.complete(
            tmp_path / "db",
            destination,
            tmp_path,
            tmp_path / "public",
            tmp_path / "cache",
            initial_plan=plan,
        )["plan_reused"]
    assert calls == ["attach", "build", "install", "frontend"] * 2
    assert forecast.read_bytes() == b"frozen"
    assert plan.read_bytes() == b"immutable plan"


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
