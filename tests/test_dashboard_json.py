"""P1.7a dashboard read-model JSON over the published BI Parquet export.

Offline tests hand-build a small Parquet export (the tables the emitter reads, plus a
self-consistent manifest) so no DuckDB and no production database is needed.  The few tests
that exercise the atomic publication itself need the directory-symlink privilege; they skip
where the shell lacks it, exactly like the `tests/test_bi_export.py` publish tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

import duckdb
import polars as pl
import pytest

import fpl.storage.db
from fpl.publish.dashboard_json import (
    DASHBOARD_JSON_SCHEMA_VERSION,
    FIXTURE_MATRIX_FILENAME,
    PLAYERS_FILENAME,
    DashboardJsonError,
    build_dashboard_read_models,
    export_dashboard_json,
    render_read_model_files,
    validate_dashboard_json,
)
from fpl.publish.export import (
    BiExportConcurrentWriterError,
    _canonical_json_bytes,
    _strict_manifest_content_sha256,
    export_bi,
)
from fpl.storage.db import default_db_path
from tests.test_bi_export import _seed_live_database

SEASON = "2026-27"
PRIOR = "2025-26"
OLDER = "2024-25"
RUN_ID = "run-a"
AS_OF = datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
KICKOFFS = {
    100: datetime(2026, 8, 22, 14, tzinfo=UTC),
    101: datetime(2026, 8, 29, 14, tzinfo=UTC),
    102: datetime(2026, 8, 31, 16, tzinfo=UTC),
}
CREATED_AT = datetime(2026, 8, 21, 18, tzinfo=UTC)
DATABASE_SHA = "d" * 64


def _symlinks_available() -> bool:
    with tempfile.TemporaryDirectory() as temporary:
        target = Path(temporary) / "target"
        target.mkdir()
        try:
            os.symlink(target, Path(temporary) / "link", target_is_directory=True)
        except OSError:
            return False
        return True


REQUIRES_SYMLINK = pytest.mark.skipif(
    not _symlinks_available(),
    reason="directory-symlink publication needs a privilege this shell lacks (WinError 1314)",
)


# --------------------------------------------------------------------------------------
# A hand-built source Parquet export
# --------------------------------------------------------------------------------------


def _team_fixture_row(
    fixture: int,
    team_id: int,
    opponent_team_id: int,
    gw: int,
    was_home: bool,
    lambda_for: float,
    lambda_against: float,
    attack: float | None,
    defence: float | None,
    overall: float | None,
    fdr: int | None,
) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "as_of": AS_OF,
        "season": SEASON,
        "fixture": fixture,
        "team_id": team_id,
        "team_code": 100 + team_id,
        "opponent_team_id": opponent_team_id,
        "gw": gw,
        "was_home": was_home,
        "lambda_for": lambda_for,
        "lambda_against": lambda_against,
        "attack_ease_index": attack,
        "defence_ease_index": defence,
        "overall_ease_index": overall,
        "ease_index_formula_version": "fixture-ease-v1",
        "probability_clean_sheet": 0.4,
        "official_fdr": fdr,
        "stage_a_league_average_team": False,
    }


def _team_form_row(
    season: str, gw: int, team_code: int, window: str, **overrides: Any
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "season": season,
        "gw": gw,
        "team_code": team_code,
        "window": window,
        "matches_played": 1,
        "goals_for": 1,
        "goals_against": 0,
        "clean_sheets": 1,
        "wins": 1,
        "draws": 0,
        "losses": 0,
        "team_xg": None,
        "team_xgc": None,
        "goals_for_per_match": 1.0,
        "goals_against_per_match": 0.0,
        "team_xg_per_match": None,
        "team_xgc_per_match": None,
    }
    row.update(overrides)
    return row


def _player_form_row(gw: int, code: int, window: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "season": PRIOR,
        "gw": gw,
        "code": code,
        "window": window,
        "rostered_fixtures": 1,
        "appearances": 1,
        "starts": 1,
        "did_not_play": 0,
        "minutes": 90,
        "goals_scored": 0,
        "assists": 0,
        "bonus": 0,
        "bps": 10,
        "defensive_contribution": None,
        "expected_goals": None,
        "expected_assists": None,
        "expected_goals_per_90": None,
        "expected_assists_per_90": None,
        "points_under_rules_2026_27": 2,
    }
    row.update(overrides)
    return row


def _source_tables() -> dict[str, list[dict[str, Any]]]:
    team_fixture = [
        _team_fixture_row(100, 1, 2, 1, True, 2.0, 1.0, 120.0, 120.0, 120.0, 2),
        _team_fixture_row(100, 2, 1, 1, False, 1.0, 2.0, 80.0, 80.0, 80.0, 4),
        # GW2 is a double gameweek for club 101; fixture 101 has lambda_against = 0 (defence
        # and overall ease NULL by design) and no official FDR.
        _team_fixture_row(101, 1, 3, 2, True, 2.5, 0.0, 140.0, None, None, None),
        _team_fixture_row(101, 3, 1, 2, False, 0.5, 2.5, 60.0, 60.0, 60.0, 3),
        _team_fixture_row(102, 1, 2, 2, False, 1.5, 1.2, 100.0, 100.0, 100.0, 4),
        _team_fixture_row(102, 2, 1, 2, True, 1.2, 1.5, 90.0, 90.0, 90.0, 2),
    ]
    player_gameweek = []
    for gw in (1, 2):
        player_gameweek.append(
            {
                "run_id": RUN_ID,
                "as_of": AS_OF,
                "season": SEASON,
                "gw": gw,
                "code": 1,
                "position": "GK",
                "team_id": 1,
                "team_code": None,  # must resolve season-safely from (season, team_id)
                "now_cost": 55,
                "selected_by_percent": None,
                "availability_status": "a",
                "chance_of_playing": None,
                "availability_multiplier": 1.0,
                "expected_points": 5.5 if gw == 1 else 4.5,
                "cold_start_player": False,
                "stage_a_league_average_team": False,
                "attacking_signal_cold_start": False,
                "assist_signal_cold_start": False,
                "transferred_no_rescale": False,
            }
        )
        player_gameweek.append(
            {
                "run_id": RUN_ID,
                "as_of": AS_OF,
                "season": SEASON,
                "gw": gw,
                "code": 2,
                "position": "MID",
                "team_id": 1,
                "team_code": 101,
                "now_cost": 65,
                "selected_by_percent": 12.5,
                "availability_status": "d",
                "chance_of_playing": 75,
                "availability_multiplier": 0.75,
                "expected_points": 2.0 if gw == 1 else 3.0,
                "cold_start_player": False,
                "stage_a_league_average_team": True,
                "attacking_signal_cold_start": False,
                "assist_signal_cold_start": False,
                "transferred_no_rescale": False,
            }
        )
    player_fixture = [
        {
            "run_id": RUN_ID,
            "as_of": AS_OF,
            "season": SEASON,
            "fixture": fixture,
            "code": code,
            "gw": gw,
            "team_id": 1,
            "opponent_team_id": opponent,
            "was_home": was_home,
            "expected_points": expected,
            "probability_appears": None,
            "probability_sixty_minutes": None,
            "expected_goals": None,
            "expected_assists": None,
            "probability_clean_sheet": None,
        }
        for code, fixture, gw, opponent, was_home, expected in (
            (1, 100, 1, 2, True, 5.5),
            (1, 101, 2, 3, True, 6.0),
            (1, 102, 2, 2, False, 3.0),  # double-gameweek second leg
            (2, 100, 1, 2, True, 2.0),
        )
    ]
    return {
        "dim_forecast_run": [
            {
                "run_id": RUN_ID,
                "as_of": AS_OF,
                "created_at": CREATED_AT,
                "season": SEASON,
                "gw_from": 1,
                "gw_to": 2,
                "status": "recorded",
                "component_modes": (
                    '{"appearance": "seasonal", "assists": "coupled", '
                    '"attacking": "v3", "share_signal": "auto"}'
                ),
            }
        ],
        "dim_player_season": [
            {
                "season": SEASON,
                "code": 1,
                "element_id": 501,
                "web_name": "Vicario",
                "position": "GK",
                "season_end_team_id": 1,
            },
            {
                "season": SEASON,
                "code": 2,
                "element_id": 502,
                "web_name": "Maddison",
                "position": "MID",
                "season_end_team_id": 1,
            },
        ],
        "dim_team_season": [
            {
                "season": SEASON,
                "team_id": team_id,
                "team_code": 100 + team_id,
                "team_name": name,
                "short_name": short,
                "pulse_id": 9000 + team_id,
            }
            for team_id, name, short in (
                (1, "Alpha", "ALP"),
                (2, "Beta", "BET"),
                (3, "Gamma", "GAM"),
            )
        ],
        "dim_fixture": [
            {
                "season": SEASON,
                "fixture": fixture,
                "gw": gw,
                "kickoff_time": KICKOFFS[fixture],
                "home_team_id": home,
                "away_team_id": away,
                "home_team_code": 100 + home,
                "away_team_code": 100 + away,
                "pulse_id": None,
                "finished": False,
            }
            for fixture, gw, home, away in ((100, 1, 1, 2), (101, 2, 1, 3), (102, 2, 2, 1))
        ],
        "fact_forecast_team_fixture": team_fixture,
        "fact_forecast_player_gameweek": player_gameweek,
        "fact_forecast_player_fixture": player_fixture,
        "dim_gameweek": [
            {
                "season": SEASON,
                "gw": gw,
                "deadline_time": None,  # deadlines are not sourced; never fabricated
                "first_kickoff": min(KICKOFFS[f] for f in fixtures_of_gw),
                "last_kickoff": max(KICKOFFS[f] for f in fixtures_of_gw),
                "fixture_count": len(fixtures_of_gw),
                "finished": False,
            }
            for gw, fixtures_of_gw in ((1, (100,)), (2, (101, 102)))
        ],
        # A miniature optimizer decision: two weeks, captain/vice in the XI, the MID
        # transferred in during GW2.  Grained (optimizer_run_id, gw, code).
        "fact_optimizer_plan": [
            {
                "optimizer_run_id": "opt-1",
                "decision_sha256": "dec-1",
                "forecast_run_id": RUN_ID,
                "as_of": AS_OF,
                "season": SEASON,
                "gw": gw,
                "code": code,
                "role": role,
                "bench_order_index": bench,
                "is_captain": code == 1,
                "is_vice_captain": code == 2,
                "now_cost": 55 if code == 1 else 65,
                "transferred_in": gw == 2 and code == 2,
                "transferred_out": False,
                "hit_points_this_gw": 0,
            }
            for gw in (1, 2)
            for code, role, bench in ((1, "starting_xi", None), (2, "starting_xi", None))
        ]
        + [
            {
                "optimizer_run_id": "opt-2",
                "decision_sha256": "dec-2",
                "forecast_run_id": RUN_ID,
                "as_of": AS_OF,
                "season": SEASON,
                "gw": 1,
                "code": 1,
                "role": "starting_xi",
                "bench_order_index": None,
                "is_captain": True,
                "is_vice_captain": False,
                "now_cost": 55,
                "transferred_in": False,
                "transferred_out": False,
                "hit_points_this_gw": 4,
            },
            {
                "optimizer_run_id": "opt-2",
                "decision_sha256": "dec-2",
                "forecast_run_id": RUN_ID,
                "as_of": AS_OF,
                "season": SEASON,
                "gw": 1,
                "code": 2,
                "role": "starting_xi",
                "bench_order_index": None,
                "is_captain": False,
                "is_vice_captain": True,
                "now_cost": 65,
                "transferred_in": False,
                "transferred_out": False,
                "hit_points_this_gw": 4,
            },
        ],
        "fact_team_form": [
            # An older-season row exists: the anchor must be the LATEST (season, gw) pair.
            _team_form_row(OLDER, 38, 101, "last_3", matches_played=3),
            _team_form_row(PRIOR, 38, 101, "last_3", matches_played=3, goals_for=5),
            _team_form_row(PRIOR, 38, 101, "last_5", matches_played=5, team_xgc=4.0),
            _team_form_row(PRIOR, 38, 101, "last_10", matches_played=10),
            _team_form_row(
                PRIOR,
                38,
                101,
                "season_to_date",
                matches_played=38,
                team_xg=48.2,
                team_xg_per_match=1.4,
            ),
            # Club 102 has no observed form: its form must be null, never fabricated.
        ],
        "fact_player_form": [
            _player_form_row(
                38,
                1,
                "last_3",
                rostered_fixtures=3,
                minutes=270,
                starts=3,
                expected_goals=0.9,
                expected_goals_per_90=0.3,
            ),
            _player_form_row(
                38,
                1,
                "last_5",
                rostered_fixtures=5,
                appearances=4,
                starts=None,
                did_not_play=1,
                minutes=260,
                goals_scored=2,
                assists=1,
                bonus=3,
                bps=60,
                expected_assists=0.6,
                expected_assists_per_90=0.2,
                points_under_rules_2026_27=20,
            ),
            _player_form_row(38, 1, "last_10", rostered_fixtures=10, minutes=780),
            _player_form_row(38, 1, "season_to_date", rostered_fixtures=38, minutes=2900),
        ],
    }


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> int:
    pl.DataFrame(rows).write_parquet(path)
    return len(rows)


def _write_manifest(export_dir: Path, tables: dict[str, dict[str, Any]]) -> None:
    manifest: dict[str, Any] = {
        "schema": "fpl.bi-semantic-export",
        "schema_version": 1,
        "semantic_contract_version": 1,
        "created_at": CREATED_AT.isoformat(),
        "database_sha256": DATABASE_SHA,
        "exported_run_ids": [RUN_ID],
        "source_known_at": {"minimum": None, "maximum": None},
        "freshness": {
            "status": "known_at_valid",
            "all_known_at_at_or_before_as_of": True,
            "cold_start_run_ids": [],
            "source_age_seconds": {"minimum": None, "maximum": None},
            "maximum_source_age_seconds": None,
        },
        "tables": tables,
    }
    manifest["content_sha256"] = _strict_manifest_content_sha256(manifest)
    (export_dir / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))


def _build_source_export(root: Path) -> Path:
    export_dir = root / "bi-export"
    export_dir.mkdir()
    tables: dict[str, dict[str, Any]] = {}
    for name, rows in _source_tables().items():
        height = _write_parquet(export_dir / f"{name}.parquet", rows)
        tables[name] = {
            "file": f"{name}.parquet",
            "row_count": height,
            "sha256": hashlib.sha256((export_dir / f"{name}.parquet").read_bytes()).hexdigest(),
        }
    _write_manifest(export_dir, tables)
    return export_dir


def _rewrite_table(export_dir: Path, name: str, rows: list[dict[str, Any]]) -> None:
    """Change one source table and re-seal the manifest, keeping the integrity chain valid."""
    height = _write_parquet(export_dir / f"{name}.parquet", rows)
    manifest_path = export_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tables"][name] = {
        "file": f"{name}.parquet",
        "row_count": height,
        "sha256": hashlib.sha256((export_dir / f"{name}.parquet").read_bytes()).hexdigest(),
    }
    manifest["content_sha256"] = _strict_manifest_content_sha256(manifest)
    manifest_path.write_bytes(_canonical_json_bytes(manifest, indent=2))


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


def _team(models: Any, team_code: int) -> dict[str, Any]:
    return next(t for t in models.teams if t["team_code"] == team_code)


def _player(models: Any, code: int) -> dict[str, Any]:
    return next(p for p in models.players if p["code"] == code)


# --------------------------------------------------------------------------------------
# Read-model content
# --------------------------------------------------------------------------------------


def test_grain_identity_and_season_safe_label_resolution(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))

    assert [team["team_code"] for team in models.teams] == [101, 102, 103]
    alpha = _team(models, 101)
    assert (alpha["run_id"], alpha["season"]) == (RUN_ID, SEASON)
    assert (alpha["team_name"], alpha["short_name"]) == ("Alpha", "ALP")
    assert alpha["as_of"] == AS_OF.isoformat()
    opponents = [(f["opponent_team_code"], f["opponent_short_name"]) for f in alpha["fixtures"]]
    assert opponents == [(102, "BET"), (103, "GAM"), (102, "BET")]

    assert [player["code"] for player in models.players] == [1, 2]
    vicario = _player(models, 1)
    assert vicario["web_name"] == "Vicario"  # from dim_player_season, never dim_player
    assert (vicario["team_code"], vicario["team_short_name"]) == (101, "ALP")  # fallback resolved
    maddison = _player(models, 2)
    assert (maddison["team_code"], maddison["team_short_name"]) == (101, "ALP")
    assert maddison["availability_multiplier"] == 0.75

    # No season-scoped id may survive as a key anywhere in the published JSON.
    documents = render_read_model_files(models)
    for payload in documents.values():
        assert not _all_keys(json.loads(payload.decode("utf-8"))) & {
            "team_id",
            "opponent_team_id",
            "element_id",
        }


def test_unmeasured_values_stay_json_null_never_zero(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    alpha = _team(models, 101)
    by_fixture = {f["fixture"]: f for f in alpha["fixtures"]}

    # lambda_against = 0 forces NULL defence/overall ease; FDR is separately missing.
    assert by_fixture[101]["defence_ease_index"] is None
    assert by_fixture[101]["overall_ease_index"] is None
    assert by_fixture[101]["official_fdr"] is None
    assert by_fixture[101]["attack_ease_index"] == 140.0
    assert by_fixture[101]["ease_index_formula_version"] == "fixture-ease-v1"
    assert by_fixture[101]["lambda_against"] == 0.0

    vicario = _player(models, 1)
    assert vicario["fixtures"][0]["probability_appears"] is None
    assert vicario["fixtures"][0]["expected_goals"] is None
    # the club primitives ride along beside the ease indices: same fixture, same values the
    # team read model publishes, with the player's own CS still separately null
    assert vicario["fixtures"][0]["team_lambda_for"] == 2.0
    assert vicario["fixtures"][0]["team_lambda_against"] == 1.0
    assert vicario["fixtures"][0]["team_probability_clean_sheet"] == 0.4
    assert (
        vicario["fixtures"][0]["team_probability_clean_sheet"]
        != vicario["fixtures"][0]["probability_clean_sheet"]
    )
    by_fixture = {f["fixture"]: f for f in vicario["fixtures"]}
    assert by_fixture[101]["team_lambda_against"] == 0.0  # the NULL-ease leg keeps its primitive
    assert vicario["form"]["windows"]["last_5"]["starts"] is None
    assert vicario["form"]["windows"]["last_5"]["expected_goals"] is None
    assert alpha["form"]["windows"]["last_5"]["team_xg"] is None

    payload = render_read_model_files(models)[FIXTURE_MATRIX_FILENAME].decode("utf-8")
    assert '"defence_ease_index": null' in payload
    assert '"official_fdr": null' in payload


def test_double_gameweek_keeps_both_legs_ordered_by_kickoff(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    alpha = _team(models, 101)
    assert [f["gw"] for f in alpha["fixtures"]] == [1, 2, 2]
    assert [f["fixture"] for f in alpha["fixtures"]] == [100, 101, 102]
    assert [f["was_home"] for f in alpha["fixtures"]] == [True, True, False]
    assert [f["kickoff_time"] for f in alpha["fixtures"]] == [
        KICKOFFS[fixture].isoformat() for fixture in (100, 101, 102)
    ]
    vicario = _player(models, 1)
    assert [f["gw"] for f in vicario["fixtures"]] == [1, 2, 2]
    assert [f["opponent_team_code"] for f in vicario["fixtures"]] == [102, 103, 102]


def test_horizon_is_the_vintage_horizon_and_outside_rows_fail_closed(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    models = build_dashboard_read_models(export_dir)
    assert models.runs[0]["gw_from"] == 1
    assert models.runs[0]["horizon_gameweeks"] == 2
    assert models.ease_index_formula_version == "fixture-ease-v1"

    rows = _source_tables()["fact_forecast_team_fixture"]
    rows[0] = {**rows[0], "gw": 3}  # outside the 1..2 vintage horizon
    _rewrite_table(export_dir, "fact_forecast_team_fixture", rows)
    with pytest.raises(DashboardJsonError, match="horizon"):
        build_dashboard_read_models(export_dir)


def test_form_anchor_is_the_latest_season_then_gameweek(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    alpha = _team(models, 101)
    assert (alpha["form"]["season"], alpha["form"]["as_at_gw"]) == (PRIOR, 38)
    assert alpha["form"]["windows"]["season_to_date"]["matches_played"] == 38
    assert alpha["form"]["windows"]["last_3"]["goals_for"] == 5
    assert _team(models, 102)["form"] is None  # never fabricated

    vicario = _player(models, 1)
    assert (vicario["form"]["season"], vicario["form"]["as_at_gw"]) == (PRIOR, 38)
    assert vicario["avg_minutes_last_5"] == pytest.approx(52.0)  # 260 minutes / 5 rostered
    assert _player(models, 2)["form"] is None
    assert _player(models, 2)["avg_minutes_last_5"] is None


def test_missing_window_at_the_anchor_fails_closed(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_team_form"] + [
        _team_form_row(PRIOR, 38, 103, "last_3")  # only one of four windows
    ]
    _rewrite_table(export_dir, "fact_team_form", rows)
    with pytest.raises(DashboardJsonError, match="missing window"):
        build_dashboard_read_models(export_dir)


def test_source_integrity_chain_fails_closed(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)

    tampered = export_dir / "fact_team_form.parquet"
    tampered.write_bytes(tampered.read_bytes() + b"\x00")
    with pytest.raises(DashboardJsonError, match="SHA-256"):
        build_dashboard_read_models(export_dir)
    _rewrite_table(export_dir, "fact_team_form", _source_tables()["fact_team_form"])

    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    del manifest["tables"]["fact_player_form"]
    (export_dir / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))
    with pytest.raises(DashboardJsonError, match="required table"):
        build_dashboard_read_models(export_dir)

    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    manifest["tables"]["fact_player_form"] = {
        "file": "fact_player_form.parquet",
        "row_count": 4,
        "sha256": "0" * 64,
    }
    (export_dir / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))
    with pytest.raises(DashboardJsonError, match="does not verify"):
        build_dashboard_read_models(export_dir)


def test_render_is_deterministic_for_identical_models(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    first = render_read_model_files(build_dashboard_read_models(export_dir))
    second = render_read_model_files(build_dashboard_read_models(export_dir))
    assert first == second
    assert set(first) == {
        FIXTURE_MATRIX_FILENAME,
        PLAYERS_FILENAME,
        "next_gw.json",
        "summary.json",
    }


def test_next_gw_plans_join_ev_context_and_modes(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    plans = models.next_gw["plans"]
    assert [plan["optimizer_run_id"] for plan in plans] == ["opt-1", "opt-2"]

    plan = plans[0]
    assert (plan["forecast_run_id"], plan["decision_sha256"]) == (RUN_ID, "dec-1")
    assert plan["gw_from"] == 1 and plan["gw_to"] == 2
    # component modes travel with the plan so the UI can label the architecture
    assert plan["component_modes"] == {
        "appearance": "seasonal",
        "assists": "coupled",
        "attacking": "v3",
        "share_signal": "auto",
    }
    week1, week2 = plan["weeks"]
    assert (week1["captain_code"], week1["vice_captain_code"]) == (1, 2)
    assert week1["players"][0]["web_name"] == "Vicario"
    assert week1["players"][0]["team_short_name"] == "ALP"  # season-safe fallback resolved
    assert week1["players"][0]["expected_points"] == 5.5  # joined from the forecast gw row
    assert week1["squad_cost"] == 120
    assert not any(player["transferred_in"] for player in week1["players"])
    assert any(player["transferred_in"] for player in week2["players"])
    # per-gameweek EV for the horizon, keyed by code, later GW included
    assert plan["player_xp"]["1"] == {"1": 5.5, "2": 4.5}
    # ownership/availability overlay and flags from the first forecast gameweek
    assert plan["squad_context"]["2"]["availability_multiplier"] == 0.75
    assert plan["squad_context"]["2"]["stage_a_league_average_team"] is True

    # opt-2 carries the GW1 hit points; its vice differs from opt-1's captain/vice pairing
    assert plans[1]["weeks"][0]["hit_points"] == 4
    assert plans[1]["weeks"][0]["vice_captain_code"] == 2


def test_next_gw_fails_closed_on_unknown_forecast_run(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_optimizer_plan"]
    rows.append({**rows[0], "optimizer_run_id": "opt-3", "forecast_run_id": "run-missing"})
    _rewrite_table(export_dir, "fact_optimizer_plan", rows)
    with pytest.raises(DashboardJsonError, match="absent from"):
        build_dashboard_read_models(export_dir)


def test_summary_snapshots_the_latest_run(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    summary = models.summary
    assert summary["latest_run"]["run_id"] == RUN_ID
    assert summary["latest_run"]["component_modes"]["attacking"] == "v3"
    assert summary["roster"] == {"players": 2, "teams": 3}
    # next gameweek carries kickoffs; the deadline stays null, never fabricated
    assert summary["next_gameweek"]["gw"] == 1
    assert summary["next_gameweek"]["fixture_count"] == 1
    assert summary["next_gameweek"]["first_kickoff"] == KICKOFFS[100].isoformat()

    assert [row["code"] for row in summary["top_xp"]] == [1, 2]  # 5.5 then 2.0 at GW1
    assert summary["top_xp"][0]["team_short_name"] == "ALP"
    # horizon sums GW1+GW2: player 2 (2.0 + 3.0 = 5.0) overtakes player 1 (5.5 + 4.5 = 10.0)
    assert [row["code"] for row in summary["horizon_top_xp"]] == [1, 2]
    assert summary["horizon_top_xp"][1]["expected_points"] == pytest.approx(5.0)
    # only the flagged player (status d) appears in the risk list
    assert [row["code"] for row in summary["flagged_top_xp"]] == [2]

    easiest, hardest = summary["easiest_fixtures"][0], summary["hardest_fixtures"][0]
    assert (easiest["team_short_name"], easiest["overall_ease_index"]) == ("ALP", 120.0)
    assert (hardest["team_short_name"], hardest["overall_ease_index"]) == ("BET", 80.0)

    assert [plan["optimizer_run_id"] for plan in summary["optimizer_plans"]] == [
        "opt-1",
        "opt-2",
    ]
    assert summary["optimizer_plans"][0]["decision_sha256"] == "dec-1"


def test_reads_only_parquet_and_opens_no_duckdb_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    export_dir = _build_source_export(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("the read-model emitter must not open a DuckDB handle")

    monkeypatch.setattr(duckdb, "connect", forbidden)
    monkeypatch.setattr(fpl.storage.db, "connect", forbidden)
    render_read_model_files(build_dashboard_read_models(export_dir))


# --------------------------------------------------------------------------------------
# Atomic publication
# --------------------------------------------------------------------------------------


def test_failed_publish_cleans_the_staging_tree(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    output = tmp_path / "dashboard"

    class SentinelError(Exception):
        pass

    def explode() -> None:
        raise SentinelError()

    # before_publish runs after the staged directory fully validates, so this exercises the
    # whole build/write/validate path and its failure cleanup without needing the symlink.
    with pytest.raises(SentinelError):
        export_dashboard_json(export_dir, output, before_publish=explode)
    assert not list(tmp_path.glob(".dashboard.*.tmp"))
    assert not output.exists()


@REQUIRES_SYMLINK
def test_publication_is_reproducible_and_validates(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    first = export_dashboard_json(
        export_dir, tmp_path / "one", generated_at=datetime(2026, 8, 25, tzinfo=UTC)
    )
    second = export_dashboard_json(
        export_dir, tmp_path / "two", generated_at=datetime(2026, 8, 26, tzinfo=UTC)
    )

    assert first.content_sha256 == second.content_sha256
    for filename in (FIXTURE_MATRIX_FILENAME, PLAYERS_FILENAME):
        assert (first.output_dir / filename).read_bytes() == (
            second.output_dir / filename
        ).read_bytes()
    first_manifest = json.loads((first.output_dir / "manifest.json").read_text(encoding="utf-8"))
    second_manifest = json.loads((second.output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert first_manifest.pop("generated_at") != second_manifest.pop("generated_at")
    assert first_manifest == second_manifest

    manifest = validate_dashboard_json(first.output_dir)
    assert manifest["schema"] == "fpl.dashboard-read-models"
    assert manifest["json_schema_version"] == DASHBOARD_JSON_SCHEMA_VERSION
    assert manifest["run_ids"] == [RUN_ID]
    assert manifest["runs"][0]["horizon_gameweeks"] == 2
    assert manifest["source"]["database_sha256"] == DATABASE_SHA
    assert manifest["ease_index_formula_version"] == "fixture-ease-v1"
    assert manifest["files"][FIXTURE_MATRIX_FILENAME]["row_count"] == first.fixture_matrix_rows
    assert manifest["files"][PLAYERS_FILENAME]["row_count"] == first.players_rows
    assert first.output_dir.is_symlink()


@REQUIRES_SYMLINK
def test_concurrent_writer_is_refused_and_unmanaged_targets_are_never_clobbered(
    tmp_path: Path,
) -> None:
    export_dir = _build_source_export(tmp_path)
    output = tmp_path / "dashboard"
    staged = Event()
    release = Event()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            export_dashboard_json,
            export_dir,
            output,
            generated_at=datetime(2026, 8, 25, tzinfo=UTC),
            before_publish=lambda: (staged.set(), release.wait(timeout=10)),
        )
        assert staged.wait(timeout=10)
        with pytest.raises(BiExportConcurrentWriterError, match="another writer"):
            export_dashboard_json(
                export_dir, output, generated_at=datetime(2026, 8, 26, tzinfo=UTC)
            )
        release.set()
        future.result(timeout=10)
    assert validate_dashboard_json(output)["run_ids"] == [RUN_ID]

    unmanaged = tmp_path / "unmanaged"
    unmanaged.mkdir()
    marker = unmanaged / "keep.txt"
    marker.write_text("operator-owned", encoding="utf-8")
    with pytest.raises(BiExportConcurrentWriterError, match="unmanaged"):
        export_dashboard_json(export_dir, unmanaged)
    assert marker.read_text(encoding="utf-8") == "operator-owned"


@REQUIRES_SYMLINK
def test_tampered_source_leaves_the_published_endpoint_intact(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    output = tmp_path / "dashboard"
    export_dashboard_json(export_dir, output, generated_at=datetime(2026, 8, 25, tzinfo=UTC))
    manifest_before = (output / "manifest.json").read_bytes()

    tampered = export_dir / "fact_forecast_team_fixture.parquet"
    tampered.write_bytes(tampered.read_bytes() + b"\x00")
    with pytest.raises(DashboardJsonError, match="SHA-256"):
        export_dashboard_json(export_dir, output, generated_at=datetime(2026, 8, 26, tzinfo=UTC))
    assert (output / "manifest.json").read_bytes() == manifest_before
    assert not list(tmp_path.glob(".dashboard.*.tmp"))


@pytest.mark.archive
@REQUIRES_SYMLINK
def test_archive_parquet_export_feeds_valid_read_models(tmp_path: Path) -> None:
    """Real-build smoke: export_bi then export_dashboard_json yields both valid read models.

    Self-contained in its forecast vintage: `build_db` records none, so the test seeds a
    synthetic one into a throwaway copy of the built database. The synthetic season is a
    future one no real database carries, so the seed works identically on a machine whose
    dev ledger already holds real vintages and on a fresh CI build with none. Team code 102
    exists in the committed archive, so the synthetic club resolves real cross-season form
    and the form assertion holds; the synthetic player codes carry no form, which the
    players read model permits (form is nullable).
    """
    assert not Path(f"{default_db_path()}.wal").exists(), "dev DB has a WAL; copy would be torn"
    db = tmp_path / "fpl-copy.duckdb"
    shutil.copy2(default_db_path(), db)
    _artifact, run_id = _seed_live_database(db, season="2027-28")

    export_dir = export_bi(
        db, tmp_path / "bi-export", created_at=datetime(2026, 8, 25, tzinfo=UTC)
    ).output_dir
    result = export_dashboard_json(
        export_dir, tmp_path / "dashboard", generated_at=datetime(2026, 8, 25, tzinfo=UTC)
    )
    assert result.fixture_matrix_rows > 0
    assert result.players_rows > 0
    manifest = validate_dashboard_json(result.output_dir)
    assert run_id in manifest["run_ids"]

    teams = json.loads((result.output_dir / FIXTURE_MATRIX_FILENAME).read_text(encoding="utf-8"))[
        "teams"
    ]
    players = json.loads((result.output_dir / PLAYERS_FILENAME).read_text(encoding="utf-8"))[
        "players"
    ]
    assert not _all_keys({"teams": teams, "players": players}) & {
        "team_id",
        "opponent_team_id",
        "element_id",
    }
    synthetic = [team for team in teams if team["season"] == "2027-28"]
    assert synthetic, "the seeded vintage must produce fixture-matrix rows"
    assert all(team["fixtures"] for team in synthetic)
    form_seasons = {team["form"]["season"] for team in synthetic if team["form"] is not None}
    assert form_seasons  # completed seasons are present in the archive
    for player in players:
        assert {"code", "web_name", "position", "team_code", "fixtures"} <= set(player)


def test_stale_fixture_kickoff_orders_after_current_gw(tmp_path: Path) -> None:
    """A postponed fixture from an earlier gw must not order before the current one."""
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_team_fixture"]
    rows.append(_team_fixture_row(103, 1, 3, 1, True, 1.0, 1.0, 100.0, 100.0, 100.0, 2))
    fixture_rows = _source_tables()["dim_fixture"]
    fixture_rows.append(
        {
            "season": SEASON,
            "fixture": 103,
            "gw": 1,
            "kickoff_time": KICKOFFS[102] + timedelta(days=2),  # plays after GW2's last kickoff
            "home_team_id": 1,
            "away_team_id": 3,
            "home_team_code": 101,
            "away_team_code": 103,
            "pulse_id": None,
            "finished": False,
        }
    )
    _rewrite_table(export_dir, "dim_fixture", fixture_rows)
    _rewrite_table(export_dir, "fact_forecast_team_fixture", rows)

    alpha = _team(build_dashboard_read_models(export_dir), 101)
    # gw is the primary sort key; the postponed GW1 fixture stays with GW1 despite its late
    # kickoff, and NULL kickoffs (unscheduled) would order last, never first.
    assert [f["gw"] for f in alpha["fixtures"]] == [1, 1, 2, 2]
