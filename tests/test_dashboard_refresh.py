from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from fpl.publish import dashboard_refresh as refresh


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture(autouse=True)
def empty_fixture_matrix(tmp_path: Path) -> None:
    write(tmp_path / "fixture_matrix.json", {"teams": []})


@pytest.mark.parametrize("provisional", [False, True])
def test_current_observations_cannot_be_replaced_by_a_freshly_dated_old_base(
    tmp_path: Path, provisional: bool
) -> None:
    sidecar: dict[str, Any] = {"gameweeks": [{"season": "2026-27"}]}
    write(tmp_path / "players.json", {"players": [{"season": "2026-27", "code": 3}]})
    for scope, plural, identity in (("team", "teams", "team_code"), ("player", "players", "code")):
        sidecar[f"{scope}_matches"] = [
            {"season": "2026-27", "fixture": 30, identity: 3, "fpl": {"goals": 0}}
        ]
        for suffix in ("actuals", "provisional_actuals"):
            selected = suffix == ("provisional_actuals" if provisional else "actuals")
            rows = [
                {
                    "season": "2026-27",
                    identity: 3,
                    "actuals": [
                        {
                            "fixture": 30,
                            "gw": 3,
                            "kickoff_time": "2026-09-04T19:00:00+00:00",
                            "goals_for": 0,
                            "goals_against": 0,
                            "team_xg": None,
                            "team_xgc": None,
                        }
                    ],
                }
            ]
            write(tmp_path / f"{scope}_{suffix}.json", {plural: rows if selected else []})
    assert (
        refresh.check_observed_freshness(tmp_path, sidecar)["player"]["matched_current_rows"] == 1
    )
    write(
        tmp_path / "fixture_matrix.json",
        {
            "teams": [
                {
                    "season": "2026-27",
                    "team_code": 3,
                    "form": None,
                    "fixtures": [],
                }
            ]
        },
    )
    with pytest.raises(ValueError, match="stale team form"):
        refresh.check_observed_freshness(tmp_path, sidecar)
    matrix = json.loads((tmp_path / "fixture_matrix.json").read_bytes())
    final = json.loads((tmp_path / "team_actuals.json").read_bytes())
    provisional_rows = json.loads((tmp_path / "team_provisional_actuals.json").read_bytes())
    matrix["teams"] = refresh.refresh_team_forms(
        matrix["teams"], final["teams"], provisional_rows["teams"]
    )
    write(tmp_path / "fixture_matrix.json", matrix)
    assert refresh.check_observed_freshness(tmp_path, sidecar)["team_form"]["reconciled_rows"] == 1
    # A new manifest timestamp is not a freshness witness for missing GW3 data.
    for suffix in ("actuals", "provisional_actuals"):
        write(tmp_path / f"player_{suffix}.json", {"players": []})
    with pytest.raises(ValueError, match="stale player actuals"):
        refresh.check_observed_freshness(tmp_path, sidecar)


def test_source_only_new_players_do_not_require_regenerating_frozen_forecasts(
    tmp_path: Path,
) -> None:
    write(tmp_path / "players.json", {"players": [{"season": "2025-26", "code": 7}]})
    for scope, plural in (("player", "players"), ("team", "teams")):
        for suffix in ("actuals", "provisional_actuals"):
            write(tmp_path / f"{scope}_{suffix}.json", {plural: []})
    sidecar = {
        "gameweeks": [{"season": "2026-27"}],
        "team_matches": [],
        "player_matches": [{"season": "2026-27", "fixture": 32, "code": 7, "fpl": {"minutes": 12}}],
    }
    before = json.dumps(sidecar, sort_keys=True)
    report = refresh.check_observed_freshness(tmp_path, sidecar)
    assert report["player"]["matched_current_rows"] == 0
    assert report["player"]["source_only_rows_outside_forecast_population"] == [("2026-27", 32, 7)]
    assert json.dumps(sidecar, sort_keys=True) == before
    assert refresh.check_observed_freshness(tmp_path, sidecar) == report
    # Once the current season's frozen population includes this code, absent
    # observations must still fail closed, regardless of the older season.
    write(tmp_path / "players.json", {"players": [{"season": "2026-27", "code": 7}]})
    with pytest.raises(ValueError, match="stale player actuals"):
        refresh.check_observed_freshness(tmp_path, sidecar)


def test_only_existing_plan_blocks_are_carried_into_the_fresh_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh, old, output = (tmp_path / name for name in ("fresh", "old", "output"))
    files = {"player_actuals.json": {}, "team_actuals.json": {}}
    for name, key in (
        ("next_gw.json", "plans"),
        ("optimizer_audit.json", "plans"),
        ("summary.json", "optimizer_plans"),
    ):
        files[name] = {}
        write(
            old / name,
            {
                key: [
                    {
                        "optimizer_run_id": "old-plan",
                        "forecast_run_id": "frozen",
                        "as_of": "original",
                    }
                ]
            },
        )
        write(
            fresh / name,
            {
                key: [],
                "fresh_context": "GW3",
                "component_modes": {
                    "football_environment.provenance": '{"pmf":[0.1,0.9]}',
                    "player_history.provenance": '{"live_captures":["private-source"]}',
                    "player_history.contract": "prospective_archive_live_player_history/v1",
                },
            },
        )
    for name in ("player_actuals.json", "team_actuals.json"):
        write(fresh / name, {"gw": 3})
        write(old / name, {"gw": 2})
    manifest = {
        "runs": [{"run_id": "frozen", "as_of": "original"}],
        "files": files,
        "content_sha256": "h",
        "generated_at": "now",
    }
    monkeypatch.setattr(
        refresh, "validate_dashboard_json", lambda _: json.loads(json.dumps(manifest))
    )
    monkeypatch.setattr(refresh, "_manifest_content_sha256", lambda _: "hash")
    monkeypatch.setattr(refresh, "_file_row_count", lambda *a: 1)
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    report = refresh.retain_existing_plans(fresh, old, output)
    assert report["forecasts_regenerated"] is False
    for name in ("player_actuals.json", "team_actuals.json"):
        assert (output / name).read_bytes() == (fresh / name).read_bytes()
    assert json.loads((output / "summary.json").read_bytes())["fresh_context"] == "GW3"
    modes = json.loads((output / "summary.json").read_bytes())["component_modes"]
    assert modes == {
        "football_environment.provenance_sha256": hashlib.sha256(b'{"pmf":[0.1,0.9]}').hexdigest(),
        "player_history.provenance_sha256": hashlib.sha256(
            b'{"live_captures":["private-source"]}'
        ).hexdigest(),
        "player_history.contract": "prospective_archive_live_player_history/v1",
    }
    assert (
        '"pmf"'
        in json.loads((fresh / "summary.json").read_bytes())["component_modes"][
            "football_environment.provenance"
        ]
    )
    assert {p.name: p.read_bytes() for p in old.iterdir()} == before
    assert "private-source" not in (output / "summary.json").read_text()
    assert "private-source" in (fresh / "summary.json").read_text()
    write(old / "next_gw.json", {"plans": [{"forecast_run_id": "different"}]})
    with pytest.raises(ValueError, match="exact forecast vintage"):
        refresh.retain_existing_plans(fresh, old, tmp_path / "refused")


def test_latest_platform_plan_reaches_all_pages_without_replacing_forecasts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fresh, old, output = (tmp_path / name for name in ("fresh", "old", "output"))
    documents = {
        "next_gw.json": "plans",
        "optimizer_audit.json": "plans",
        "summary.json": "optimizer_plans",
    }
    previous = {
        "optimizer_run_id": "old-plan",
        "forecast_run_id": "gw3",
        "plan_kind": "platform_default",
        "as_of": "2026-09-03",
    }
    current = {
        "optimizer_run_id": "new-plan",
        "forecast_run_id": "gw5",
        "plan_kind": "platform_default",
        "as_of": "2026-09-14",
    }
    diagnostic = {**previous, "optimizer_run_id": "diagnostic", "plan_kind": "platform_diagnostic"}
    for name, key in documents.items():
        write(old / name, {key: [previous, diagnostic]})
        write(fresh / name, {key: [current]})
    write(fresh / "players.json", {"frozen": [1, 2, 3]})
    manifest = {
        "runs": [{"run_id": r} for r in ("gw3", "gw5")],
        "files": {k: {} for k in (*documents, "players.json")},
        "content_sha256": "hash",
        "generated_at": "now",
    }
    monkeypatch.setattr(
        refresh, "validate_dashboard_json", lambda _: json.loads(json.dumps(manifest))
    )
    monkeypatch.setattr(refresh, "_manifest_content_sha256", lambda _: "hash")
    monkeypatch.setattr(refresh, "_file_row_count", lambda *a: 1)
    original = {p.name: p.read_bytes() for p in old.iterdir()}
    refresh.retain_existing_plans(fresh, old, output)
    for name, key in documents.items():
        plans = json.loads((output / name).read_bytes())[key]
        assert {p["optimizer_run_id"] for p in plans} == {"new-plan", "diagnostic"}
        assert next(p for p in plans if p["plan_kind"] == "platform_default") == current
    assert (output / "players.json").read_bytes() == (fresh / "players.json").read_bytes()
    assert {p.name: p.read_bytes() for p in old.iterdir()} == original
    repeat = tmp_path / "repeat"
    refresh.retain_existing_plans(fresh, output, repeat)
    assert {p.name: p.read_bytes() for p in repeat.iterdir()} == {
        p.name: p.read_bytes() for p in output.iterdir()
    }
    write(fresh / "next_gw.json", {"plans": [{**previous, "as_of": "changed"}]})
    with pytest.raises(ValueError, match="immutable optimizer plan changed"):
        refresh.retain_existing_plans(fresh, old, tmp_path / "collision")


def test_republication_recognizes_sanitized_plan_and_rejects_changed_digest() -> None:
    body = '{"retained_source":"identity"}'
    original = {
        "optimizer_run_id": "immutable",
        "forecast_run_id": "forecast",
        "component_modes": {"football_environment.provenance": body},
        "provenance": {
            "squad_rules_path": "D:/private/config/squad_2026_27.yaml",
            "squad_rules_sha256": "rules",
        },
        "decision_sha256": "decision",
    }
    public = json.loads(json.dumps(original))
    public["component_modes"] = {
        "football_environment.provenance_sha256": hashlib.sha256(body.encode()).hexdigest()
    }
    public["provenance"]["squad_rules_path"] = "config/squad_2026_27.yaml"
    before = json.dumps(original, sort_keys=True)
    assert refresh._public_plan_identity(original) == refresh._public_plan_identity(public)
    assert json.dumps(original, sort_keys=True) == before
    public["decision_sha256"] = "changed"
    assert refresh._public_plan_identity(original) != refresh._public_plan_identity(public)
    original["component_modes"]["football_environment.provenance_sha256"] = "wrong"
    with pytest.raises(ValueError, match="source provenance digest mismatch"):
        refresh._public_plan_identity(original)
