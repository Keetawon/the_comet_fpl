"""Observed dashboard semantics: source identity, missingness and immutable exports."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.config import load_sdp_metrics
from fpl.jobs.export_sdp_stats import main
from fpl.publish.sdp_stats import (
    DisplayCorrection,
    DisplayCorrectionPolicy,
    _add_lineups,
    _apply_display_corrections,
    _fpl_rows,
    build_sdp_stats,
    export_sdp_stats,
    load_display_corrections,
    metric_value,
    sdp_stats_bytes,
    validate_sdp_stats,
)
from fpl.storage.db import initialise
from fpl.transform import pl_sdp

from .test_pl_sdp_revision_pit import CAPTURED, SEASON, _raw, _rebuild
from .test_player_attacking_usage_export import CUTOFF, STAMP, _inputs, _write
from .test_sdp_primary import METRICS, seed


def _load(db: Path, *, cutoff: Any = CUTOFF) -> dict[str, Any]:
    with duckdb.connect(str(db), read_only=True) as con:
        return build_sdp_stats(con, as_of=cutoff)


def test_export_is_observed_source_labelled_immutable_read_only(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    before = db.read_bytes()
    first, second = tmp_path / "one.json", tmp_path / "two.json"
    receipt = export_sdp_stats(db, first, as_of=CUTOFF)
    export_sdp_stats(db, second, as_of=CUTOFF)
    assert first.read_bytes() == second.read_bytes()
    assert db.read_bytes() == before
    assert hashlib.sha256(first.read_bytes()).hexdigest() == receipt["sha256"]
    document = json.loads(first.read_bytes())
    row = document["player_matches"][0]
    assert row["fpl"]["expected_goals"] == 0.2
    assert row["sdp"] == {}
    assert row["minutes_sdp"] is None and row["minutes_fpl"] == 90
    assert row["fpl"]["goals_scored"] is None
    assert row["position"] == "DEF"
    assert document["coverage"]["fpl_player_matches"] == 1
    assert document["source_status"]["player_stats"] == "UNAVAILABLE"
    assert len(document["team_matches"]) == 2
    assert all(r["status"] == "UNAVAILABLE" for r in document["team_matches"])
    assert all(v is None for r in document["team_matches"] for v in r["sdp"].values())
    assert all(m["source"] == "fpl" for m in document["metrics"] if m["scope"] == "player")
    assert not {"pmf", "capture_id", "raw_sources", "predicted_xg", "xP"}.intersection(row)
    with pytest.raises(ValueError, match="already exists"):
        export_sdp_stats(db, first, as_of=CUTOFF)
    assert db.read_bytes() == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_goals", None),
        ("expected_goals", True),
        ("expected_goals", -1),
        ("minutes", None),
        ("minutes", True),
        ("minutes", 121),
        ("starts", 2),
    ],
)
def test_missing_or_invalid_never_zero(tmp_path: Path, field: str, value: Any) -> None:
    _, _, summary = _inputs()
    summary["history"][0][field] = value
    db = tmp_path / "source.duckdb"
    _write(db, summary=summary)
    row = _load(db)["player_matches"][0]
    assert row["fpl"][field] is None
    assert _load(db)["coverage"]["fpl_player_matches"] == 1


def test_actual_zero_and_signed_recorded_points_preserved(tmp_path: Path) -> None:
    _, _, summary = _inputs()
    summary["history"][0].update(expected_goals=0, minutes=0, total_points=-2, bps=-1)
    db = tmp_path / "source.duckdb"
    _write(db, summary=summary)
    row = _load(db)["player_matches"][0]
    assert row["fpl"]["expected_goals"] == 0
    assert row["minutes_fpl"] == 0
    assert row["fpl"]["total_points_as_recorded"] == -2
    assert row["fpl"]["bps"] == -1


def test_owner_display_correction_is_cutoff_safe_and_keeps_raw_null(
    tmp_path: Path, monkeypatch: Any
) -> None:
    source_known = datetime(2026, 9, 4, 17, 47, tzinfo=UTC)
    confirmed = datetime(2026, 9, 8, 14, 40, tzinfo=UTC)
    correction = DisplayCorrection(
        correction_id="2026-27-f7-team-7-sot",
        season="2026-27",
        fixture=7,
        team_code=7,
        opponent_team_code=36,
        provider_match_id=2645201,
        provider_side="away",
        provider_field="ontargetScoringAtt",
        raw_payload_sha256="a" * 64,
        source_known_at=source_known,
        owner_confirmation_recorded_at=confirmed,
        display_value=0,
        total_scoring_attempts=6,
        shot_off_target_attempts=6,
        blocked_attempts=None,
        opponent_goalkeeper_saves=0,
        fpl_goals_scored=0,
    )
    monkeypatch.setattr(
        "fpl.publish.sdp_stats.load_display_corrections",
        lambda: DisplayCorrectionPolicy(
            schema_id="fpl.sdp-dashboard-display-corrections",
            version=1,
            corrections=(correction,),
        ),
    )
    fixtures = {
        7: {
            "home": 36,
            "away": 7,
            "home_score": 4,
            "away_score": 0,
        }
    }
    teams = {
        ("2026-27", 7, 7): {
            "status": "UNAVAILABLE",
            "sdp": {"shots_on_target": None, "shots_allowed": None},
            "fpl": {"goals_scored": 0},
            "display_corrections": {},
        },
        ("2026-27", 7, 36): {
            "status": "UNAVAILABLE",
            "sdp": {"shots_on_target": None, "shots_allowed": None},
            "fpl": {"goals_scored": 4},
            "display_corrections": {},
        },
    }
    players = [
        {
            "season": "2026-27",
            "fixture": 7,
            "team_code": 36,
            "position": "GK",
            "minutes_fpl": 90,
            "fpl": {"saves": 0},
        }
    ]
    body = json.dumps(
        [
            {"side": "Home", "team": {"id": 36}, "stats": {"ontargetScoringAtt": 6}},
            {
                "side": "Away",
                "team": {"id": 7},
                "stats": {"totalScoringAtt": 6, "shotOffTarget": 6, "goals": 0},
            },
        ]
    )
    raw = [
        {
            "endpoint": "match_stats",
            "sdp_match_id": 2645201,
            "sha256": "a" * 64,
            "fetched_at": source_known,
            "body": body,
        }
    ]
    db = tmp_path / "source.duckdb"
    with initialise(db) as con:
        con.execute(
            """INSERT INTO stg_pl_sdp_fixture_crosswalk
               (season,fixture,sdp_match_id,match_method,corroborated_kickoff,
                corroborated_teams,resolved_at)
               VALUES ('2026-27',7,2645201,'exact',TRUE,TRUE,?)""",
            [source_known],
        )
        original = deepcopy(raw)
        assert (
            _apply_display_corrections(
                con,
                cutoff=confirmed - timedelta(seconds=1),
                season="2026-27",
                fixtures=fixtures,
                players=players,
                teams=teams,
                raw=raw,
            )
            == 0
        )
        assert teams["2026-27", 7, 7]["display_corrections"] == {}
        assert (
            _apply_display_corrections(
                con,
                cutoff=confirmed,
                season="2026-27",
                fixtures=fixtures,
                players=players,
                teams=teams,
                raw=raw,
            )
            == 1
        )
    assert raw == original
    direct = teams["2026-27", 7, 7]
    mirror = teams["2026-27", 7, 36]
    assert direct["status"] == mirror["status"] == "UNAVAILABLE"
    assert direct["sdp"]["shots_on_target"] is mirror["sdp"]["shots_allowed"] is None
    assert direct["display_corrections"]["shots_on_target"]["value"] == 0
    assert mirror["display_corrections"]["shots_allowed"]["relation"] == "opponent_mirror"


def test_committed_display_policy_is_bounded_and_leaves_fulham_unresolved() -> None:
    policy = load_display_corrections()
    assert {(row.fixture, row.team_code, row.display_value) for row in policy.corrections} == {
        (7, 7, 0),
        (20, 7, 0),
        (28, 6, 0),
    }
    assert all(row.provider_field == "ontargetScoringAtt" for row in policy.corrections)
    assert (19, 54) not in {(row.fixture, row.team_code) for row in policy.corrections}


def test_transfer_uses_fixture_time_club_not_current_club(tmp_path: Path) -> None:
    bootstrap, _, _ = _inputs()
    bootstrap["elements"][0]["team"] = 2
    db = tmp_path / "source.duckdb"
    _write(db, bootstrap=bootstrap)
    row = _load(db)["player_matches"][0]
    assert row["team_code"] == 101 and row["opponent_team_code"] == 102
    assert row["was_home"] is True


def test_later_fpl_revision_never_changes_old_export(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    before = sdp_stats_bytes(_load(db))
    _, _, summary = _inputs()
    summary["history"][0]["expected_goals"] = 3
    _write(db, identity="later", stamp=CUTOFF + timedelta(hours=1), summary=summary)
    assert sdp_stats_bytes(_load(db)) == before
    assert (
        _load(db, cutoff=CUTOFF + timedelta(hours=2))["player_matches"][0]["fpl"]["expected_goals"]
        == 3
    )


@pytest.mark.parametrize("problem", ["duplicate", "opponent", "missing_summary", "raw_hash"])
def test_bad_fpl_source_is_visible_unavailable(tmp_path: Path, problem: str) -> None:
    _, _, summary = _inputs()
    if problem == "duplicate":
        summary["history"].append(dict(summary["history"][0]))
    if problem == "opponent":
        summary["history"][0]["opponent_team"] = 1
    db = tmp_path / "source.duckdb"
    if problem == "opponent":
        with pytest.raises(ValueError, match="opponent mismatch"):
            _write(db, summary=summary)
    else:
        _write(db, summary=summary, omit_summary=problem == "missing_summary")
    if problem == "raw_hash":
        with duckdb.connect(str(db)) as con:
            con.execute("UPDATE snapshot_payload SET sha256='bad'")
    document = _load(db)
    assert document["player_matches"] == []
    assert document["source_status"]["fpl_enrichment"] == "UNAVAILABLE"
    assert any("validation" in note for note in document["source_status"]["notes"])


def test_sdp_core_health_optional_null_and_revision_gate(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    cutoff = CAPTURED + timedelta(days=1)
    with initialise(db) as con:
        seed(con)  # type: ignore[no-untyped-call]
        before = build_sdp_stats(con, as_of=cutoff, season=SEASON)
        assert len(before["team_matches"]) == 8
        assert all(r["sdp"]["shots"] == 12 for r in before["team_matches"])
        assert all(r["sdp"]["big_chances_created"] is None for r in before["team_matches"])
        assert before["player_matches"] == []
        revised = cutoff + timedelta(hours=1)
        payload: list[dict[str, Any]] = [
            {"side": label, "team": {"id": code}, "stats": dict(METRICS)}
            for label, code in (("Home", 8), ("Away", 3))
        ]
        payload[0]["stats"]["accuratePass"] = None
        pl_sdp.land_payload(
            con, _raw("match_stats", payload, revised, 300103), season=SEASON, sdp_match_id=300103
        )
        _rebuild(con)
        assert sdp_stats_bytes(
            build_sdp_stats(con, as_of=cutoff, season=SEASON)
        ) == sdp_stats_bytes(before)
        after = build_sdp_stats(con, as_of=revised + timedelta(seconds=1), season=SEASON)
        failed = [r for r in after["team_matches"] if r["fixture"] == 103]
        assert len(failed) == 2 and all(r["status"] == "UNAVAILABLE" for r in failed)
        assert all(v is None for r in failed for v in r["sdp"].values())
        assert after["coverage"]["team_failures"] == 1


def test_metric_aliases_finite_values_and_semantics() -> None:
    metric = next(m for m in load_sdp_metrics().metrics if m.local_field == "shots")
    assert metric_value({metric.provider_fields[0]: 0}, metric) == 0
    assert metric_value({}, metric) is None
    for value in (True, -1, 0.2, float("nan"), float("inf")):
        assert metric_value({metric.provider_fields[0]: value}, metric) is None
    conflicting = metric.model_copy(update={"provider_fields": ["first", "second"]})
    assert metric_value({"first": 4, "second": 5}, conflicting) is None
    assert metric_value({"first": 4, "second": None}, conflicting) is None
    assert metric_value({"first": 4, "second": "4"}, conflicting) == 4


def _lineup_record() -> dict[str, Any]:
    return {
        "season": "2026-27",
        "competition": 8,
        "provider_match_id": 9001,
        "valid": True,
        "known_at": STAMP.isoformat(),
        "kickoff_time": "2026-08-22T14:00:00+00:00",
        "version_id": "source-version",
        "rows": [
            {
                "provider_player_id": 87654,
                "code": 10010,
                "team_code": 101,
                "identity_errors": [],
                "provider_position": "Defender",
                "started": True,
                "on_bench": False,
                "appeared": True,
                "nominal_minutes": 90,
                "raw_player": {
                    "firstName": "Observed",
                    "lastName": "Player",
                    "subPosition": "Defender",
                },
            }
        ],
    }


@pytest.mark.parametrize("case", ["normal", "unmapped", "cup", "identity", "future_crosswalk"])
def test_lineup_identity_nominal_timing_and_no_allocation(
    tmp_path: Path, monkeypatch: Any, case: str
) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    record = _lineup_record()
    if case == "unmapped":
        record["rows"][0]["code"] = None
    if case == "cup":
        record["competition"] = 1
    if case == "identity":
        record["rows"][0]["team_code"] = 999
    monkeypatch.setattr("fpl.publish.sdp_stats.workload_at", lambda *_: [record])
    with duckdb.connect(str(db)) as con:
        stamp = CUTOFF + timedelta(days=1) if case == "future_crosswalk" else STAMP
        con.execute(
            """INSERT INTO stg_pl_sdp_fixture_crosswalk
            (season,fixture,sdp_match_id,match_method,corroborated_kickoff,corroborated_teams,resolved_at)
            VALUES ('2026-27',501,9001,'exact',TRUE,TRUE,?)""",
            [stamp],
        )
        names: dict[tuple[str, int], tuple[str, str]] = {}
        rows, fixtures, _, _ = _fpl_rows(con, "2026-27", CUTOFF, names)
        count, _ = _add_lineups(con, rows, fixtures, season="2026-27", cutoff=CUTOFF, names=names)
    if case in {"cup", "identity", "future_crosswalk"}:
        assert count == 0 and rows[0]["provider_player_id"] is None
    elif case == "unmapped":
        assert len(rows) == 2 and rows[1]["code"] is None
        assert rows[1]["fpl"]["expected_goals"] is None
    else:
        assert count == 1 and len(rows) == 1
        assert rows[0]["code"] == 10010 and rows[0]["provider_player_id"] == 87654
        assert rows[0]["minutes_sdp"] is None and rows[0]["nominal_minutes_sdp"] == 90
        assert rows[0]["sdp"] == {} and rows[0]["fpl"]["expected_goals"] == 0.2


@pytest.mark.parametrize("field", ["capture_id", "raw_path", "pmf", "predicted_xg"])
def test_public_unknown_private_and_model_fields_rejected(tmp_path: Path, field: str) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    document = _load(db)
    document["player_matches"][0][field] = "private"
    with pytest.raises(ValueError, match="unexpected"):
        validate_sdp_stats(document)


def test_cli_and_duplicate_public_row_rejected(tmp_path: Path, capsys: Any) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    output = tmp_path / "sdp_stats.json"
    assert main(["--db", str(db), "--output", str(output), "--as-of", CUTOFF.isoformat()]) == 0
    assert json.loads(capsys.readouterr().out)["sha256"]
    document = json.loads(output.read_bytes())
    document["player_matches"].append(dict(document["player_matches"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        validate_sdp_stats(document)


def test_official_partial_gw_score_and_discipline_fields(tmp_path: Path) -> None:
    bootstrap, fixtures, summary = _inputs()
    bootstrap["events"][0]["finished"] = False
    fixtures[0].update(team_h_score=2, team_a_score=1)
    fixtures.append(
        {
            **fixtures[0],
            "id": 502,
            "finished": False,
            "kickoff_time": (CUTOFF + timedelta(days=1)).isoformat(),
            "team_h_score": None,
            "team_a_score": None,
        }
    )
    summary["history"][0].update(
        yellow_cards=1, red_cards=0, clean_sheets=0, goals_conceded=1, expected_goals_conceded=0.9
    )
    db = tmp_path / "source.duckdb"
    _write(db, bootstrap=bootstrap, fixtures=fixtures, summary=summary)
    document = _load(db)
    assert document["gameweeks"] == [
        {
            "season": "2026-27",
            "gw": 1,
            "finished": False,
            "fixtures_total": 2,
            "fixtures_completed": 1,
            "source_known_at": STAMP.isoformat(),
        }
    ]
    home, away = document["team_matches"]
    assert home["fpl"] == {"goals_scored": 2, "goals_conceded": 1}
    assert away["fpl"] == {"goals_scored": 1, "goals_conceded": 2}
    assert document["player_matches"][0]["fpl"]["yellow_cards"] == 1
    assert document["player_matches"][0]["fpl"]["expected_goals_conceded"] == 0.9
    assert {m["group"] for m in document["metrics"] if m["scope"] == "player"} >= {
        "attack",
        "creation",
        "defence",
        "GK",
        "discipline",
        "exposure",
    }


def test_boolean_official_score_remains_unavailable(tmp_path: Path) -> None:
    _, fixtures, _ = _inputs()
    fixtures[0].update(team_h_score=True, team_a_score=0)
    db = tmp_path / "source.duckdb"
    _write(db, fixtures=fixtures)
    home, away = _load(db)["team_matches"]
    assert home["fpl"]["goals_scored"] is None
    assert away["fpl"]["goals_conceded"] is None
    assert home["fpl"]["goals_conceded"] == 0


@pytest.mark.parametrize("change", ["future", "private_path", "allocation", "denominator"])
def test_public_semantic_validation(tmp_path: Path, change: str) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    document = _load(db)
    row = document["player_matches"][0]
    if change == "future":
        row["known_at"] = (CUTOFF + timedelta(seconds=1)).isoformat()
    elif change == "private_path":
        row["web_name"] = "D:/private/secret"
    elif change == "allocation":
        row["sdp"]["shots"] = 2
    else:
        row["minutes_sdp"] = 90
    with pytest.raises(ValueError, match=r"future-known|path or URL|SDP metric|denominator"):
        validate_sdp_stats(document)


def test_sdp_lineups_survive_missing_optional_fpl_player_summaries(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db = tmp_path / "source.duckdb"
    _write(db, omit_summary=True)
    monkeypatch.setattr("fpl.publish.sdp_stats.workload_at", lambda *_: [_lineup_record()])
    with duckdb.connect(str(db)) as con:
        con.execute(
            """INSERT INTO stg_pl_sdp_fixture_crosswalk
            (season,fixture,sdp_match_id,match_method,corroborated_kickoff,corroborated_teams,resolved_at)
            VALUES ('2026-27',501,9001,'exact',TRUE,TRUE,?)""",
            [STAMP],
        )
    document = _load(db)
    assert document["source_status"]["fpl_enrichment"] == "UNAVAILABLE"
    assert document["source_status"]["player_lineups"] == "PARTIAL"
    assert document["coverage"]["fpl_player_matches"] == 0
    assert document["coverage"]["sdp_lineup_player_matches"] == 1
    row = document["player_matches"][0]
    assert row["provider_player_id"] == 87654 and row["started"] is True
    assert all(v is None for v in row["fpl"].values())
    assert document["gameweeks"][0]["fixtures_completed"] == 1


def test_failed_publication_leaves_no_partial_final_file(tmp_path: Path, monkeypatch: Any) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    output = tmp_path / "export" / "sdp_stats.json"

    def failed_link(*_: Any) -> None:
        raise OSError("synthetic filesystem failure")

    monkeypatch.setattr("fpl.jobs.competitive_participation_pilot.os.link", failed_link)
    with pytest.raises(OSError, match="synthetic filesystem failure"):
        export_sdp_stats(db, output, as_of=CUTOFF)
    assert not output.exists()
    assert list(output.parent.iterdir()) == []
