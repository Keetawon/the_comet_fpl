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
    PLAYER_HORIZONS_FILENAME,
    PLAYERS_FILENAME,
    DashboardJsonError,
    _validate_player_horizon_document,
    _validate_player_horizon_generation,
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
        "clean_sheets": 0,
        "goals_conceded": 0,
        "saves": 0,
        "expected_goals_conceded": None,
    }
    row.update(overrides)
    return row


def _optimizer_run_row(
    optimizer_run_id: str,
    decision: str,
    *,
    seed: int = 7,
    plan_origin: str | None = None,
    locked_codes: tuple[int, ...] = (),
    excluded_codes: tuple[int, ...] = (),
    min_bench_appearance: float = 0.0,
) -> dict[str, Any]:
    """A dim_optimizer_run row mirroring the exporter's run-level provenance."""
    search_policy: dict[str, Any] = {
        "beam_width": 8,
        "candidate_pool_per_position": 30,
        "excluded_codes": list(excluded_codes),
        "free_transfer_per_gameweek": 1,
        "hit_cost_points": 4,
        "locked_codes": list(locked_codes),
        "min_bench_appearance": min_bench_appearance,
        "risk_lambda": 0.0,
        "search_method": "bounded deterministic dynamic programme with beam pruning",
        "transfer_depth": 2,
    }
    if plan_origin is not None:
        search_policy["plan_origin"] = plan_origin
    return {
        "optimizer_run_id": optimizer_run_id,
        "decision_sha256": decision,
        "forecast_run_id": RUN_ID,
        "as_of": AS_OF,
        "season": SEASON,
        "gw_from": 1,
        "gw_to": 2,
        "optimizer_commit_sha": "commit-opt",
        "optimizer_worktree_clean": True,
        "forecast_artifact_sha256": "f" * 64,
        "forecast_commit_sha": "commit-forecast",
        "squad_rules_path": "config/squad_2026_27.yaml",
        "squad_rules_contract_version": "1.0",
        "squad_rules_sha256": "r" * 64,
        "solver_name": "CBC",
        "solver_package": "pulp",
        "solver_package_version": "3.0.0",
        "solver_binary_version": "2.10.3",
        "solver_options": '["randomSeed 7"]',
        "solver_seed": seed,
        "solver_status": "Optimal",
        "search_method": "bounded deterministic dynamic programme with beam pruning",
        "optimality_scope": "exact lineups within visited states; path not globally exact",
        "risk_lambda": 0.0,
        "search_policy": json.dumps(search_policy, sort_keys=True),
        "rules_snapshot": json.dumps(
            {
                "budget_tenths": 1000,
                "maximum_per_club": 3,
                "squad_size": 15,
                "season": SEASON,
            },
            sort_keys=True,
        ),
        "assumptions": '["bench points are excluded from the objective"]',
        "status": "development_only_not_a_validated_production_recommendation",
    }


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
                "distribution": (
                    "[0.3, 0, 0, 0, 0, 0, 0, 0.1, 0.6]"
                    if gw == 1
                    else "[0.3, 0, 0, 0, 0, 0, 0.4, 0.3]"
                ),
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
                "distribution": (
                    "[0.75, 0, 0, 0, 0, 0, 0, 0, 0.25]"
                    if gw == 1
                    else "[0.75, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.25]"
                ),
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
                "row_count": 4,
                "roster_size": 2,
                "status": "recorded",
                "component_modes": (
                    '{"appearance_mode": "seasonal", "assists_mode": "coupled", '
                    '"attacking_mode": "v3", "share_signal_kind": "expected_goals"}'
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
                "home_official_fdr": 2,
                "away_official_fdr": 4,
                "pulse_id": None,
                "finished": False,
            }
            for fixture, gw, home, away in ((100, 1, 1, 2), (101, 2, 1, 3), (102, 2, 2, 1))
        ],
        "fact_forecast_team_fixture": team_fixture,
        "fact_forecast_player_gameweek": player_gameweek,
        "fact_forecast_player_fixture": player_fixture,
        "dim_optimizer_run": [
            _optimizer_run_row("opt-1", "dec-1"),
            _optimizer_run_row(
                "opt-2",
                "dec-2",
                seed=11,
                plan_origin="user_custom",
                locked_codes=(1,),
                excluded_codes=(99, 42),
                min_bench_appearance=0.25,
            ),
        ],
        # Finalised outcomes at player-fixture grain. Code 2's fixture 101 is unfinalised
        # (NULL points) and must stay out of every gameweek sum, never read as 0.
        "fact_player_fixture_actual": [
            {
                "season": SEASON,
                "fixture": fixture,
                "code": code,
                "gw": gw,
                "points_under_rules_2026_27": points,
            }
            for fixture, gw, code, points in (
                (100, 1, 1, 6),
                (101, 2, 1, 4),
                (102, 2, 1, 2),
                (100, 1, 2, 1),
                (101, 2, 2, None),  # unknown until finalised
                (102, 2, 2, 2),
            )
        ],
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
                clean_sheets=2,
                goals_conceded=4,
                saves=11,
                expected_goals_conceded=3.4,
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
        "semantic_contract_version": 2,
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


def _player_horizons(models: Any, code: int) -> dict[str, Any]:
    return next(p for p in models.player_horizons if p["code"] == code)


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


def test_player_horizons_are_convolved_upstream_with_inclusive_thresholds(
    tmp_path: Path,
) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))

    assert _player_horizons(models, 1) == {
        "run_id": RUN_ID,
        "season": SEASON,
        "code": 1,
        "horizons": [
            {
                "gw_to": 1,
                "xp": 5.5,
                "p_le_2": 0.3,
                "p_ge_2": 0.7,
                "p_ge_4": 0.7,
                "p_ge_6": 0.7,
                "p_ge_10": 0.0,
                "p_ge_15": 0.0,
            },
            {
                "gw_to": 2,
                "xp": 10.0,
                "p_le_2": 0.09,
                "p_ge_2": 0.91,
                "p_ge_4": 0.91,
                "p_ge_6": 0.91,
                "p_ge_10": 0.49,
                "p_ge_15": 0.18,
            },
        ],
    }
    rendered = render_read_model_files(models)
    document = json.loads(rendered[PLAYER_HORIZONS_FILENAME].decode("utf-8"))
    assert document["semantics"] == {
        "grain": ["run_id", "season", "code", "gw_to"],
        "cumulative_from": "dim_forecast_run.gw_from",
        "distribution_combination": "independent-gameweek-convolution-v1",
        "availability": "raw-model-distribution-unadjusted",
        "value_decimal_places": 6,
        "probability_boundary_policy": "preserve-exact-zero-one-v1",
        "thresholds": {"p_le": [2], "p_ge": [2, 4, 6, 10, 15]},
    }
    assert document["horizon_fields"] == [
        "gw_to",
        "xp",
        "p_le_2",
        "p_ge_2",
        "p_ge_4",
        "p_ge_6",
        "p_ge_10",
        "p_ge_15",
    ]
    assert document["players"][0]["horizons"][0] == [1, 5.5, 0.3, 0.7, 0.7, 0.7, 0.0, 0.0]
    for filename, payload in rendered.items():
        assert "distribution" not in _all_keys(json.loads(payload)), filename
    assert sum(len(player["horizons"]) for player in document["players"]) == 4


def test_player_horizon_wire_quantization_is_compact_and_preserves_probability_boundaries(
    tmp_path: Path,
) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    first = models.player_horizons[0]["horizons"][0]
    second = models.player_horizons[0]["horizons"][1]
    first["xp"] = 5.50000049
    first["p_ge_10"] = 0.00000004
    first["p_ge_15"] = 0.00000004
    second["p_ge_2"] = 0.9999996

    document = json.loads(render_read_model_files(models)[PLAYER_HORIZONS_FILENAME])
    first_row, second_row = document["players"][0]["horizons"]
    fields = document["horizon_fields"]
    assert first_row[fields.index("xp")] == 5.5
    assert second_row[fields.index("p_ge_2")] == 0.999999
    assert first_row[fields.index("p_ge_10")] == 0.000001
    assert first_row[fields.index("p_ge_15")] == 0.000001
    _validate_player_horizon_document(document)


def test_score_two_belongs_to_both_inclusive_probability_events(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_player_gameweek"]
    rows = [
        {**row, "expected_points": 2.0, "distribution": "[0, 0, 1]"}
        if row["code"] == 2 and row["gw"] == 1
        else row
        for row in rows
    ]
    _rewrite_table(export_dir, "fact_forecast_player_gameweek", rows)
    score_two = _player_horizons(build_dashboard_read_models(export_dir), 2)["horizons"][0]
    assert score_two["p_le_2"] == 1.0
    assert score_two["p_ge_2"] == 1.0


def test_horizon_probability_is_not_the_sum_of_gameweek_probabilities(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_player_gameweek"]
    bernoulli = "[0.5, 0, 0, 0, 0, 0, 0.5]"
    rows = [
        {**row, "expected_points": 3.0, "distribution": bernoulli} if row["code"] == 1 else row
        for row in rows
    ]
    _rewrite_table(export_dir, "fact_forecast_player_gameweek", rows)

    horizons = _player_horizons(build_dashboard_read_models(export_dir), 1)["horizons"]
    assert horizons[0]["p_ge_6"] == 0.5
    assert horizons[1]["p_ge_6"] == 0.75
    assert horizons[1]["p_ge_6"] != horizons[0]["p_ge_6"] * 2
    assert horizons[1]["xp"] == 6.0  # xP remains the exact sum: 3.0 + 3.0


def test_blank_gameweek_leaves_the_cumulative_distribution_unchanged(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_player_gameweek"]
    rows = [
        {**row, "expected_points": 0.0, "distribution": "[1]"}
        if row["code"] == 1 and row["gw"] == 2
        else row
        for row in rows
    ]
    _rewrite_table(export_dir, "fact_forecast_player_gameweek", rows)

    first, second = _player_horizons(build_dashboard_read_models(export_dir), 1)["horizons"]
    assert second == {**first, "gw_to": 2}


def test_accepted_pmf_mass_roundoff_cannot_shrink_a_cumulative_tail(
    tmp_path: Path,
) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_player_gameweek"]
    rows = [
        {**row, "expected_points": 2.0, "distribution": "[0, 0, 1]"}
        if row["code"] == 1 and row["gw"] == 1
        else {**row, "expected_points": 0.0, "distribution": "[0.9999999995]"}
        if row["code"] == 1 and row["gw"] == 2
        else row
        for row in rows
    ]
    _rewrite_table(export_dir, "fact_forecast_player_gameweek", rows)

    first, second = _player_horizons(build_dashboard_read_models(export_dir), 1)["horizons"]
    assert first["xp"] == second["xp"] == 2.0
    assert first["p_ge_2"] == second["p_ge_2"] == 1.0


def test_float_roundoff_cannot_make_valid_cumulative_tails_fail_validation(
    tmp_path: Path,
) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_player_gameweek"]
    rows = [
        {
            **row,
            "expected_points": 15.0,
            "distribution": json.dumps([0.0] * 15 + [1.0]),
        }
        if row["code"] == 1 and row["gw"] == 1
        else {
            **row,
            "expected_points": 0.8250543658672808,
            "distribution": "[0.17494563413271938, 0.8250543658672808]",
        }
        if row["code"] == 1 and row["gw"] == 2
        else row
        for row in rows
    ]
    _rewrite_table(export_dir, "fact_forecast_player_gameweek", rows)

    document = json.loads(
        render_read_model_files(build_dashboard_read_models(export_dir))[PLAYER_HORIZONS_FILENAME]
    )
    _validate_player_horizon_document(document)
    first, second = next(row for row in document["players"] if row["code"] == 1)["horizons"]
    p_ge_15_index = document["horizon_fields"].index("p_ge_15")
    assert first[p_ge_15_index] == 1.0
    assert second[p_ge_15_index] == 0.999999


@pytest.mark.parametrize(
    ("distribution", "expected_points", "message"),
    [
        ("[]", 0.0, "non-empty"),
        ("[0.4, 0.4]", 0.4, "sums to"),
        ("[1.1, -0.1]", -0.1, "non-negative"),
        ("[NaN]", 0.0, "finite"),
        ("[1]", 1.0, "does not match"),
    ],
)
def test_player_horizons_fail_closed_on_malformed_or_inconsistent_pmf(
    tmp_path: Path, distribution: str, expected_points: float, message: str
) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_player_gameweek"]
    rows[0] = {
        **rows[0],
        "distribution": distribution,
        "expected_points": expected_points,
    }
    _rewrite_table(export_dir, "fact_forecast_player_gameweek", rows)
    with pytest.raises(DashboardJsonError, match=message):
        build_dashboard_read_models(export_dir)


def test_player_horizons_require_every_declared_player_gameweek(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["fact_forecast_player_gameweek"]
    _rewrite_table(export_dir, "fact_forecast_player_gameweek", rows[:-1])
    with pytest.raises(DashboardJsonError, match="declares 4 rows/2 players"):
        build_dashboard_read_models(export_dir)


def test_player_horizons_reject_an_empty_declared_roster(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["dim_forecast_run"]
    rows[0] = {**rows[0], "row_count": 0, "roster_size": 0}
    _rewrite_table(export_dir, "dim_forecast_run", rows)
    with pytest.raises(DashboardJsonError, match="positive integer"):
        build_dashboard_read_models(export_dir)


def test_player_horizon_generation_reconciles_players_and_exact_endpoints(
    tmp_path: Path,
) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    rendered = render_read_model_files(models)
    documents = {
        PLAYERS_FILENAME: json.loads(rendered[PLAYERS_FILENAME]),
        PLAYER_HORIZONS_FILENAME: json.loads(rendered[PLAYER_HORIZONS_FILENAME]),
    }
    manifest = {"runs": list(models.runs)}

    missing_endpoint = json.loads(json.dumps(documents))
    missing_endpoint[PLAYER_HORIZONS_FILENAME]["players"][0]["horizons"].pop()
    _validate_player_horizon_document(missing_endpoint[PLAYER_HORIZONS_FILENAME])
    with pytest.raises(DashboardJsonError, match="has endpoints"):
        _validate_player_horizon_generation(missing_endpoint, manifest)

    missing_player = json.loads(json.dumps(documents))
    missing_player[PLAYER_HORIZONS_FILENAME]["players"].pop()
    _validate_player_horizon_document(missing_player[PLAYER_HORIZONS_FILENAME])
    with pytest.raises(DashboardJsonError, match="does not reconcile"):
        _validate_player_horizon_generation(missing_player, manifest)

    extra_run = json.loads(json.dumps(manifest))
    extra_run["runs"].append(
        {
            **extra_run["runs"][0],
            "run_id": "run-with-no-player-population",
        }
    )
    with pytest.raises(DashboardJsonError, match="cover every manifest run"):
        _validate_player_horizon_generation(documents, extra_run)

    impossible_overlap = json.loads(json.dumps(documents[PLAYER_HORIZONS_FILENAME]))
    p_le_2_index = impossible_overlap["horizon_fields"].index("p_le_2")
    impossible_overlap["players"][0]["horizons"][0][p_le_2_index] = 0.2
    with pytest.raises(DashboardJsonError, match="inclusive score-2 overlap"):
        _validate_player_horizon_document(impossible_overlap)

    excess_precision = json.loads(json.dumps(documents[PLAYER_HORIZONS_FILENAME]))
    excess_precision["players"][0]["horizons"][0][1] += 0.0000001
    with pytest.raises(DashboardJsonError, match="not ordered cumulative values"):
        _validate_player_horizon_document(excess_precision)

    wrong_fields = json.loads(json.dumps(documents[PLAYER_HORIZONS_FILENAME]))
    wrong_fields["horizon_fields"][1:3] = reversed(wrong_fields["horizon_fields"][1:3])
    with pytest.raises(DashboardJsonError, match="positional horizon field contract"):
        _validate_player_horizon_document(wrong_fields)

    short_row = json.loads(json.dumps(documents[PLAYER_HORIZONS_FILENAME]))
    short_row["players"][0]["horizons"][0].pop()
    with pytest.raises(DashboardJsonError, match="malformed row"):
        _validate_player_horizon_document(short_row)

    malformed_run = json.loads(json.dumps(manifest))
    malformed_run["runs"][0]["run_id"] = []
    with pytest.raises(DashboardJsonError, match="invalid run horizon"):
        _validate_player_horizon_generation(documents, malformed_run)


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
    assert vicario["form"]["windows"]["last_5"]["clean_sheets"] == 2
    assert vicario["form"]["windows"]["last_5"]["goals_conceded"] == 4
    assert vicario["form"]["windows"]["last_5"]["saves"] == 11
    assert vicario["form"]["windows"]["last_5"]["expected_goals_conceded"] == 3.4
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


def test_current_schedule_overlay_extends_without_widening_the_forecast(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    later_kickoff = datetime(2026, 9, 12, 14, tzinfo=UTC)
    fixture_rows = _source_tables()["dim_fixture"] + [
        {
            "season": SEASON,
            "fixture": 103,
            "gw": 3,
            "kickoff_time": later_kickoff,
            "home_team_id": 1,
            "away_team_id": 2,
            "home_team_code": 101,
            "away_team_code": 102,
            "home_official_fdr": 4,
            "away_official_fdr": 2,
            "pulse_id": None,
            "finished": False,
        }
    ]
    _rewrite_table(export_dir, "dim_fixture", fixture_rows)

    models = build_dashboard_read_models(export_dir)
    assert [fixture["fixture"] for fixture in _team(models, 101)["fixtures"]] == [100, 101, 102]
    assert models.schedule["semantics"] == "current_at_export_not_forecast_vintage"
    assert models.schedule["schema_version"] == 2
    assert models.schedule["export_created_at"] == CREATED_AT.isoformat()
    assert models.schedule["database_sha256"] == DATABASE_SHA
    schedule_alpha = next(
        team
        for team in models.schedule["teams"]
        if team["season"] == SEASON and team["team_code"] == 101
    )
    assert [fixture["fixture"] for fixture in schedule_alpha["fixtures"]] == [100, 101, 102, 103]
    later = schedule_alpha["fixtures"][-1]
    assert later == {
        "gw": 3,
        "fixture": 103,
        "kickoff_time": later_kickoff.isoformat(),
        "opponent_team_code": 102,
        "opponent_short_name": "BET",
        "was_home": True,
        "official_fdr": 4,
    }
    assert not set(later) & {
        "lambda_for",
        "lambda_against",
        "probability_clean_sheet",
        "overall_ease_index",
    }
    rendered = json.loads(render_read_model_files(models)[FIXTURE_MATRIX_FILENAME].decode("utf-8"))
    assert rendered["schedule"] == models.schedule


def test_current_schedule_overlay_fails_closed_on_duplicate_fixture(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    fixture_rows = _source_tables()["dim_fixture"]
    fixture_rows.append(dict(fixture_rows[0]))
    _rewrite_table(export_dir, "dim_fixture", fixture_rows)
    with pytest.raises(DashboardJsonError, match="duplicate"):
        build_dashboard_read_models(export_dir)


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


def test_forecast_vs_actual_scores_finalised_gameweeks_only(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    result = models.forecast_vs_actual
    assert result["has_outcomes"] is True
    (run,) = result["runs"]
    assert run["run_id"] == RUN_ID
    # four scored player-gameweeks; the unfinalised fixture row never enters a sum
    assert run["rows"] == 4
    assert run["mean_ev"] == pytest.approx(3.75)
    assert run["mean_actual"] == pytest.approx(3.75)
    assert run["bias"] == pytest.approx(0.0)
    assert run["mae"] == pytest.approx(1.0)
    assert run["crps"] is not None and run["crps"] > 0.0

    positions = {block["position"]: block for block in run["by_position"]}
    assert positions["GK"]["rows"] == 2
    assert positions["GK"]["bias"] == pytest.approx(1.0)  # 5.0 EV against 6.0 actual
    assert positions["MID"]["bias"] == pytest.approx(-1.0)
    gws = {block["gw"]: block for block in run["by_gw"]}
    assert gws[1]["bias"] == pytest.approx(-0.25)
    assert gws[2]["bias"] == pytest.approx(0.25)

    buckets = {block["bucket"]: block for block in run["calibration"]}
    # code 1 predicts P(>=2) = 0.70 in both gameweeks and delivered both times
    assert buckets["0.7-1.0"]["predicted_mean"] == pytest.approx(0.7)
    assert buckets["0.7-1.0"]["observed_rate"] == pytest.approx(1.0)
    # code 2 predicts P(>=2) = 0.25 and delivered once of twice
    assert buckets["0.1-0.3"]["predicted_mean"] == pytest.approx(0.25)
    assert buckets["0.1-0.3"]["observed_rate"] == pytest.approx(0.5)


def test_forecast_vs_actual_without_outcomes_is_an_explicit_empty_state(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = [
        {**row, "points_under_rules_2026_27": None}
        for row in _source_tables()["fact_player_fixture_actual"]
    ]
    _rewrite_table(export_dir, "fact_player_fixture_actual", rows)
    result = build_dashboard_read_models(export_dir).forecast_vs_actual
    assert result == {"has_outcomes": False, "runs": []}


def test_discrete_crps_matches_hand_computed_cases() -> None:
    from fpl.publish.dashboard_json import _discrete_crps

    # A point mass at 0 against an observation of 2 charges exactly 2.
    assert _discrete_crps([1.0], 2.0) == pytest.approx(2.0)
    # Uniform on {0, 1} against 1: E|X-y| = 0.5, spread term 0.5*E|X-X'| = 0.25.
    assert _discrete_crps([0.5, 0.5], 1.0) == pytest.approx(0.25)
    # Negative mass is unmeasured, never a score.
    assert _discrete_crps([-0.1, 1.1], 1.0) is None


def test_optimizer_audit_carries_full_provenance(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    plans = models.optimizer_audit["plans"]
    assert [plan["optimizer_run_id"] for plan in plans] == ["opt-1", "opt-2"]

    plan = plans[0]
    assert plan["decision_sha256"] == "dec-1"
    assert plan["plan_kind"] == "platform_default"
    assert plan["display_label"] == "Platform default \N{EM DASH} v3 goals / coupled assists"
    assert plan["component_modes"]["attacking_mode"] == "v3"  # from its forecast run
    assert plan["provenance"]["optimizer_commit_sha"] == "commit-opt"
    assert plan["provenance"]["optimizer_worktree_clean"] is True
    assert plan["provenance"]["squad_rules_contract_version"] == "1.0"
    assert plan["solver"]["name"] == "CBC"
    assert plan["solver"]["status"] == "Optimal"
    assert plan["solver"]["options"] == ["randomSeed 7"]
    assert plan["solver"]["seed"] == 7
    assert plan["search_policy"]["candidate_pool_per_position"] == 30
    assert plan["search_policy"]["risk_lambda"] == 0.0
    assert plan["rules_snapshot"]["squad_size"] == 15
    assert plan["assumptions"] == ["bench points are excluded from the objective"]
    assert plan["status"] == "development_only_not_a_validated_production_recommendation"
    assert plans[1]["solver"]["seed"] == 11
    assert plans[1]["plan_kind"] == "user_custom"
    assert plans[1]["display_label"] == "Your plan \N{EM DASH} v3 goals / coupled assists"
    assert plans[1]["search_policy"]["plan_origin"] == "user_custom"


def test_optimizer_audit_without_plans_is_empty_not_an_error(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    _rewrite_table(export_dir, "dim_optimizer_run", [])
    _rewrite_table(export_dir, "fact_optimizer_plan", [])
    result = build_dashboard_read_models(export_dir).optimizer_audit
    assert result == {"plans": []}


def test_optimizer_fact_without_run_provenance_fails_closed(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["dim_optimizer_run"]
    _rewrite_table(export_dir, "dim_optimizer_run", rows[1:])

    with pytest.raises(DashboardJsonError, match="absent from dim_optimizer_run"):
        build_dashboard_read_models(export_dir)


def test_plan_classification_uses_origin_then_architecture_not_row_order() -> None:
    from fpl.publish.dashboard_json import _optimizer_plan_metadata

    diagnostic_modes = pl.DataFrame(
        [
            {
                "run_id": RUN_ID,
                "component_modes": json.dumps(
                    {"attacking_mode": "v1", "assists_mode": "v1"}, sort_keys=True
                ),
            }
        ]
    )
    platform = _optimizer_run_row("z-platform", "dec-platform")
    custom = _optimizer_run_row("a-custom", "dec-custom", excluded_codes=(7,))
    explicit_platform = _optimizer_run_row(
        "b-explicit-platform",
        "dec-explicit-platform",
        plan_origin="platform",
        locked_codes=(9,),
    )
    metadata = _optimizer_plan_metadata(
        pl.DataFrame([platform, custom, explicit_platform]), diagnostic_modes
    )

    assert metadata["z-platform"]["plan_kind"] == "platform_diagnostic"
    assert metadata["z-platform"]["display_label"] == (
        "Diagnostic sensitivity \N{EM DASH} v1 goals / v1 assists"
    )
    assert metadata["a-custom"]["plan_kind"] == "user_custom"
    assert metadata["a-custom"]["display_label"] == ("Your plan \N{EM DASH} v1 goals / v1 assists")
    assert metadata["a-custom"]["compact_policy"]["excluded_codes"] == [7]
    assert metadata["a-custom"]["search_policy"]["plan_origin"] == "user_custom"
    assert metadata["b-explicit-platform"]["plan_kind"] == "platform_diagnostic"


def test_plan_classification_fails_closed_on_unknown_origin() -> None:
    from fpl.publish.dashboard_json import _optimizer_plan_metadata

    row = _optimizer_run_row("opt-invalid", "dec-invalid", plan_origin="mystery")
    runs = pl.DataFrame(
        [
            {
                "run_id": RUN_ID,
                "component_modes": json.dumps(
                    {"attacking_mode": "v3", "assists_mode": "coupled"}, sort_keys=True
                ),
            }
        ]
    )
    with pytest.raises(DashboardJsonError, match="plan_origin"):
        _optimizer_plan_metadata(pl.DataFrame([row]), runs)


def test_legacy_custom_origin_survives_artifact_export_and_dashboard(
    tmp_path: Path,
) -> None:
    from fpl.artifacts.optimizer_plan import derive_optimizer_run_id, read_optimizer_artifact
    from fpl.publish.dashboard_json import _build_optimizer_audit
    from fpl.publish.export import _optimizer_run_records
    from tests.test_bi_export import _optimizer_artifact

    forecast, forecast_run_id = _seed_live_database(tmp_path / "legacy.duckdb")
    current = _optimizer_artifact(forecast)
    legacy_policy = current.search_policy.model_copy(
        update={"locked_codes": (1,), "plan_origin": None}
    )
    legacy_run_id = derive_optimizer_run_id(
        current.provenance, legacy_policy, current.solver, current.decision_sha256
    )
    legacy = current.model_copy(update={"search_policy": legacy_policy, "run_id": legacy_run_id})
    payload = legacy.model_dump(mode="json")
    payload["search_policy"].pop("plan_origin")
    path = tmp_path / "legacy-custom.json"
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    parsed = read_optimizer_artifact(path)
    assert parsed.search_policy.plan_origin is None
    records = _optimizer_run_records(((parsed, path, forecast_run_id, forecast.manifest.as_of),))
    exported_policy = json.loads(records[0]["search_policy"])
    assert exported_policy["plan_origin"] is None
    runs = pl.DataFrame(
        [
            {
                "run_id": forecast_run_id,
                "component_modes": json.dumps(
                    {"attacking_mode": "v3", "assists_mode": "coupled"}, sort_keys=True
                ),
            }
        ]
    )

    audit = _build_optimizer_audit(pl.DataFrame(records), runs)
    plan = audit["plans"][0]
    assert plan["plan_kind"] == "user_custom"
    assert plan["display_label"] == ("Your plan \N{EM DASH} v3 goals / coupled assists")
    assert plan["search_policy"]["plan_origin"] == "user_custom"
    assert plan["search_policy"]["locked_codes"] == [1]


def test_optimizer_audit_fails_closed_on_malformed_json_column(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    rows = _source_tables()["dim_optimizer_run"]
    rows[0] = {**rows[0], "search_policy": "not json"}
    _rewrite_table(export_dir, "dim_optimizer_run", rows)
    with pytest.raises(DashboardJsonError, match="not JSON"):
        build_dashboard_read_models(export_dir)


def test_render_is_deterministic_for_identical_models(tmp_path: Path) -> None:
    export_dir = _build_source_export(tmp_path)
    first = render_read_model_files(build_dashboard_read_models(export_dir))
    second = render_read_model_files(build_dashboard_read_models(export_dir))
    assert first == second
    assert set(first) == {
        FIXTURE_MATRIX_FILENAME,
        PLAYER_HORIZONS_FILENAME,
        PLAYERS_FILENAME,
        "next_gw.json",
        "summary.json",
        "forecast_vs_actual.json",
        "optimizer_audit.json",
    }


def test_complete_source_populates_every_page_read_model(tmp_path: Path) -> None:
    """A fully-populated source export must populate all six page read models.

    Guards the regeneration flow in dashboard/README.md: a vintage with team-fixture rows
    feeds the fixture matrix and players pages, a plan per vintage feeds next_gw and the
    optimizer audit, finalised actuals feed forecast-vs-actual, and summary always has a
    latest run. A page's file going empty here means the flow stopped feeding it.
    """
    models = build_dashboard_read_models(_build_source_export(tmp_path))

    assert models.teams, "fixture_matrix has no teams"
    assert models.players, "players is empty"
    assert models.summary["latest_run"] is not None, "summary has no latest run"
    assert models.next_gw["plans"], "next_gw has no plans"
    assert models.optimizer_audit["plans"], "optimizer_audit has no plans"
    assert models.forecast_vs_actual["runs"], "forecast_vs_actual scored nothing"
    assert models.forecast_vs_actual["has_outcomes"] is True


def test_next_gw_plans_join_ev_context_and_modes(tmp_path: Path) -> None:
    models = build_dashboard_read_models(_build_source_export(tmp_path))
    plans = models.next_gw["plans"]
    assert [plan["optimizer_run_id"] for plan in plans] == ["opt-1", "opt-2"]

    plan = plans[0]
    assert (plan["forecast_run_id"], plan["decision_sha256"]) == (RUN_ID, "dec-1")
    assert plan["gw_from"] == 1 and plan["gw_to"] == 2
    # component modes travel with the plan so the UI can label the architecture
    assert plan["component_modes"] == {
        "appearance_mode": "seasonal",
        "assists_mode": "coupled",
        "attacking_mode": "v3",
        "share_signal_kind": "expected_goals",
    }
    assert plan["plan_kind"] == "platform_default"
    assert plan["display_label"] == "Platform default \N{EM DASH} v3 goals / coupled assists"
    assert plan["policy"] == {
        "locked_codes": [],
        "excluded_codes": [],
        "min_bench_appearance": 0.0,
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
    assert plans[1]["plan_kind"] == "user_custom"
    assert plans[1]["display_label"] == "Your plan \N{EM DASH} v3 goals / coupled assists"
    assert plans[1]["policy"] == {
        "locked_codes": [1],
        "excluded_codes": [42, 99],
        "min_bench_appearance": 0.25,
    }


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
    assert summary["latest_run"]["component_modes"]["attacking_mode"] == "v3"
    assert [plan["plan_kind"] for plan in summary["optimizer_plans"]] == [
        "platform_default",
        "user_custom",
    ]
    assert summary["optimizer_plans"][1]["display_label"] == (
        "Your plan \N{EM DASH} v3 goals / coupled assists"
    )
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
    for filename in (
        FIXTURE_MATRIX_FILENAME,
        PLAYERS_FILENAME,
        PLAYER_HORIZONS_FILENAME,
    ):
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
    assert (
        manifest["files"][PLAYER_HORIZONS_FILENAME]["row_count"] == first.player_horizon_rows == 4
    )
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
            "home_official_fdr": 2,
            "away_official_fdr": 4,
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
