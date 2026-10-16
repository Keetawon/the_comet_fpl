"""Public scoping preserves whole forecasts and outcomes, with a bounded browser cost."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from fpl.publish.dashboard_json import validate_dashboard_json
from fpl.publish.dashboard_scope import PUBLIC_PAYLOAD_LIMITS, scope_public_documents
from fpl.publish.public_dashboard import PublicDashboardPackageError, package_public_dashboard

from .test_public_dashboard import _documents, _read_documents, _write_generation


def _mobile_source(path: Path) -> dict[str, dict[str, Any]]:
    documents = _documents()
    runs: list[dict[str, Any]] = []
    for gw in range(1, 10):
        for shadow in (False, True):
            for vintage in range(3):
                run_id = f"gw{gw}-{int(shadow)}-{vintage}"
                runs.append(
                    {
                        "run_id": run_id,
                        "season": "2026-27",
                        "as_of": f"2026-09-{gw:02}T0{vintage}:00:00+00:00",
                        "gw_from": gw,
                        "gw_to": gw + 4,
                        "horizon_gameweeks": 5,
                    }
                )
    runs.sort(key=lambda r: r["run_id"])
    for filename in ("player_forecast_vs_actual.json", "team_forecast_vs_actual.json"):
        documents[filename]["runs"] = [
            {
                **r,
                "component_modes": {
                    "forecast_role": "shadow_incumbent" if "-1-" in r["run_id"] else "primary"
                },
                "coverage": {"scored_rows": 0 if r["gw_from"] == 9 else 2, "pending_rows": 3},
                "overall": {"mae": None if r["gw_from"] == 9 else 1.23456789},
                "observations": [{"gw": r["gw_from"], "actual_points": -1, "forecast_xp": 2.75}],
            }
            for r in runs
        ]
        documents[filename]["has_outcomes"] = True
    latest = next(
        r for r in documents["player_forecast_vs_actual.json"]["runs"] if r["run_id"] == "gw9-0-2"
    )
    documents["summary.json"]["latest_run"] = deepcopy(latest)
    for filename, key in (
        ("next_gw.json", "plans"),
        ("optimizer_audit.json", "plans"),
        ("summary.json", "optimizer_plans"),
    ):
        for plan in documents[filename][key]:
            plan["forecast_run_id"] = (
                "gw1-0-0" if plan["plan_kind"] == "platform_diagnostic" else "gw9-0-2"
            )
    template = documents["players.json"]["players"][0]
    documents["players.json"]["players"] = [
        {
            **template,
            "run_id": r["run_id"],
            "fixtures": [
                {"fixture": 100, "gw": r["gw_from"], "expected_points": 2.75},
                {"fixture": 101, "gw": r["gw_from"], "expected_points": None},
            ],
        }
        for r in runs
    ]
    documents["player_horizons.json"]["players"] = [
        {
            "run_id": r["run_id"],
            "season": r["season"],
            "code": 1,
            "horizons": [
                [gw, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                for gw in range(r["gw_from"], r["gw_to"] + 1)
            ],
        }
        for r in runs
    ]
    documents["fixture_matrix.json"]["teams"] = [
        {"run_id": r["run_id"], "season": r["season"], "team_code": 1} for r in runs
    ]
    _write_generation(path, documents, runs)
    return documents


def test_public_scope_bounds_runs_and_preserves_exact_forecasts_scores_and_history(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    original = _mobile_source(source)
    before = {p.name: p.read_bytes() for p in source.iterdir()}
    package = package_public_dashboard(
        source, tmp_path / "public", tmp_path / "public.zip", mobile_scope=True
    )
    published = _read_documents(package.output_dir)
    manifest = validate_dashboard_json(package.output_dir)
    active = {"gw9-0-2", "gw9-1-2", "gw1-0-0"}
    assert set(manifest["run_ids"]) == active
    assert manifest["json_schema_version"] == 9
    for filename, key in (
        ("players.json", "players"),
        ("player_horizons.json", "players"),
        ("fixture_matrix.json", "teams"),
    ):
        assert published[filename][key] == [
            r for r in original[filename][key] if r["run_id"] in active
        ]
    assert published["summary.json"]["latest_run"] == original["summary.json"]["latest_run"]
    for name in (
        "player_actuals.json",
        "team_actuals.json",
        "player_provisional_actuals.json",
        "team_provisional_actuals.json",
    ):
        assert published[name] == original[name]
    history = {f"gw{gw}-{shadow}-2" for gw in range(3, 9) for shadow in (0, 1)} | active
    for name in ("player_forecast_vs_actual.json", "team_forecast_vs_actual.json"):
        assert published[name]["runs"] == [
            r for r in original[name]["runs"] if r["run_id"] in history
        ]
        assert published[name]["has_outcomes"] is True
    assert {p.name: p.read_bytes() for p in source.iterdir()} == before
    # Repackaging the projection cannot drop more runs or change its identity.
    replay = package_public_dashboard(
        package.output_dir, tmp_path / "again", tmp_path / "again.zip", mobile_scope=True
    )
    assert package.archive_sha256 == replay.archive_sha256
    for name in PUBLIC_PAYLOAD_LIMITS:
        assert (package.output_dir / name).read_bytes().count(b"\n") == 1


@pytest.mark.parametrize(
    "problem", ["missing_default", "missing_plan", "private_old_row", "budget"]
)
def test_scope_failure_is_atomic_and_does_not_hide_private_discarded_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    source = tmp_path / "source"
    _mobile_source(source)
    docs = _read_documents(source)
    manifest = validate_dashboard_json(source)
    if problem == "missing_default":
        docs["summary.json"]["latest_run"] = None
    elif problem == "missing_plan":
        for name, key in (
            ("next_gw.json", "plans"),
            ("optimizer_audit.json", "plans"),
            ("summary.json", "optimizer_plans"),
        ):
            for plan in docs[name][key]:
                if plan["plan_kind"] == "platform_diagnostic":
                    plan["forecast_run_id"] = "absent"
    elif problem == "private_old_row":
        docs["players.json"]["players"][1]["manager_id"] = 123456
    else:
        monkeypatch.setitem(PUBLIC_PAYLOAD_LIMITS, "players.json", 1)
    changed = tmp_path / "changed"
    _write_generation(changed, docs, manifest["runs"])
    before = {p.name: p.read_bytes() for p in changed.iterdir()}
    with pytest.raises(PublicDashboardPackageError):
        package_public_dashboard(
            changed, tmp_path / "public", tmp_path / "public.zip", mobile_scope=True
        )
    assert not (tmp_path / "public").exists()
    assert not (tmp_path / "public.zip").exists()
    assert not list(tmp_path.glob(".*.tmp"))
    assert {p.name: p.read_bytes() for p in changed.iterdir()} == before


def test_monitoring_selection_is_cutoff_safe_not_chosen_by_score(tmp_path: Path) -> None:
    source = tmp_path / "source"
    docs = _mobile_source(source)
    manifest = validate_dashboard_json(source)
    for name in ("player_forecast_vs_actual.json", "team_forecast_vs_actual.json"):
        for r in docs[name]["runs"]:
            if r["run_id"] == "gw8-0-2":
                r["as_of"] = "2030-01-01T00:00:00+00:00"
                next(x for x in manifest["runs"] if x["run_id"] == r["run_id"])["as_of"] = r[
                    "as_of"
                ]
            if r["run_id"] == "gw8-0-1":
                r["overall"]["mae"] = 999.0
    scope_public_documents(docs, manifest)
    rows = docs["player_forecast_vs_actual.json"]["runs"]
    assert "gw8-0-2" not in {r["run_id"] for r in rows}
    assert next(r for r in rows if r["run_id"] == "gw8-0-1")["overall"]["mae"] == 999.0


def test_scope_retains_only_matching_roster_history_in_current_and_previous_season(
    tmp_path: Path,
) -> None:
    docs = _mobile_source(tmp_path / "source")
    manifest = validate_dashboard_json(tmp_path / "source")
    for name, key, identity in (
        ("player_actuals.json", "players", "code"),
        ("team_actuals.json", "teams", "team_code"),
    ):
        row = docs[name][key][0]
        docs[name][key].extend([{**row, "season": "2023-24"}, {**row, identity: 999}])
    scope_public_documents(docs, manifest)
    assert {r["code"] for r in docs["player_actuals.json"]["players"]} == {1}
    assert {r["season"] for r in docs["player_actuals.json"]["players"]} <= {"2025-26", "2026-27"}


def test_pending_only_generation_does_not_invent_outcomes(tmp_path: Path) -> None:
    docs = _mobile_source(tmp_path / "source")
    manifest = validate_dashboard_json(tmp_path / "source")
    for name in ("player_forecast_vs_actual.json", "team_forecast_vs_actual.json"):
        for r in docs[name]["runs"]:
            r["coverage"]["scored_rows"] = 0
    scope_public_documents(docs, manifest)
    assert docs["player_forecast_vs_actual.json"]["has_outcomes"] is False
    assert len(docs["player_forecast_vs_actual.json"]["runs"]) == 3
