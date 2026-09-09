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
    OMITTED_ZERO_POLICY_RECORDED_AT,
    DisplayCorrection,
    DisplayCorrectionPolicy,
    _add_lineups,
    _apply_display_corrections,
    _fpl_rows,
    _omitted_zero_assumptions,
    _partial_current_stats,
    build_sdp_stats,
    export_sdp_stats,
    load_display_corrections,
    metric_value,
    sdp_stats_bytes,
    validate_sdp_stats,
)
from fpl.storage.db import initialise
from fpl.storage.sdp_runtime import load_sdp_state, raw_at
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


def test_omitted_sparse_count_assumption_is_display_only_and_cutoff_safe() -> None:
    metrics = load_sdp_metrics().metrics
    stats = {"totalScoringAtt": 4, "attemptsIbox": 4, "totalPass": 500}
    kwargs = {
        "source_known_at": OMITTED_ZERO_POLICY_RECORDED_AT - timedelta(days=1),
        "provider_match_id": 123,
        "raw_payload_sha256": "a" * 64,
    }
    assert (
        _omitted_zero_assumptions(
            stats,
            metrics,
            cutoff=OMITTED_ZERO_POLICY_RECORDED_AT - timedelta(microseconds=1),
            **kwargs,
        )
        == {}
    )
    assumptions = _omitted_zero_assumptions(
        stats, metrics, cutoff=OMITTED_ZERO_POLICY_RECORDED_AT, **kwargs
    )
    assert assumptions["shots_outside_box"]["value"] == 0
    assert assumptions["shots_outside_box"]["provider_field"].startswith("attemptsObox")
    assert assumptions["offsides"]["evidence_class"] == ("owner_directed_omitted_count_assumption")
    assert "shots_inside_box" not in assumptions
    assert "passes" not in assumptions
    assert "expected_goals_on_target" not in assumptions
    assert stats == {"totalScoringAtt": 4, "attemptsIbox": 4, "totalPass": 500}
    explicit_zero = _omitted_zero_assumptions(
        {**stats, "attemptsObox": 0},
        metrics,
        cutoff=OMITTED_ZERO_POLICY_RECORDED_AT,
        **kwargs,
    )
    assert "shots_outside_box" not in explicit_zero


@pytest.mark.parametrize(
    ("provider_field", "total", "off_target", "blocked"),
    [
        ("ontargetScoringAtt", 6, 6, None),
        ("blockedScoringAtt", 6, 6, None),
        ("ontargetScoringAtt", 11, 3, 8),
        ("expectedGoalsOnTarget", 6, 6, None),
        ("expectedGoalsOnTarget", 11, 3, 8),
    ],
)
def test_owner_display_correction_is_cutoff_safe_and_keeps_raw_null(
    tmp_path: Path,
    monkeypatch: Any,
    provider_field: Any,
    total: int,
    off_target: int,
    blocked: int | None,
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
        provider_field=provider_field,
        raw_payload_sha256="a" * 64,
        source_known_at=source_known,
        owner_confirmation_recorded_at=confirmed,
        display_value=0,
        total_scoring_attempts=total,
        shot_off_target_attempts=off_target,
        blocked_attempts=blocked,
        opponent_goalkeeper_saves=0,
        fpl_goals_scored=0,
    )
    monkeypatch.setattr(
        "fpl.publish.sdp_stats.load_display_corrections",
        lambda: DisplayCorrectionPolicy(
            schema_id="fpl.sdp-dashboard-display-corrections",
            version=3,
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
            "sdp": {
                "shots_on_target": None,
                "shots_on_target_allowed": None,
                "shots_allowed": 6,
                "shots_blocked": None,
                "expected_goals_on_target": None,
            },
            "fpl": {"goals_scored": 0},
            "display_corrections": {},
        },
        ("2026-27", 7, 36): {
            "status": "UNAVAILABLE",
            "sdp": {"shots_on_target": None, "shots_on_target_allowed": None, "shots_allowed": 6},
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
                "stats": {
                    "totalScoringAtt": total,
                    "shotOffTarget": off_target,
                    "goals": 0,
                    "attemptsObox": 4,
                    **({"blockedScoringAtt": blocked} if blocked is not None else {}),
                },
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
        # Outside-box totals never replace the required off-target evidence.
        broken = json.loads(body)
        broken[1]["stats"]["attemptsObox"] = total
        del broken[1]["stats"]["shotOffTarget"]
        with pytest.raises(ValueError, match="shot accounting"):
            _apply_display_corrections(
                con,
                cutoff=confirmed,
                season="2026-27",
                fixtures=fixtures,
                players=players,
                teams=teams,
                raw=[{**raw[0], "body": json.dumps(broken)}],
            )
        if provider_field == "blockedScoringAtt":
            broken = json.loads(body)
            broken[1]["stats"]["ontargetScoringAtt"] = 1
            with pytest.raises(ValueError, match="off-target attempts"):
                _apply_display_corrections(
                    con,
                    cutoff=confirmed,
                    season="2026-27",
                    fixtures=fixtures,
                    players=players,
                    teams=teams,
                    raw=[{**raw[0], "body": json.dumps(broken)}],
                )
        if provider_field == "expectedGoalsOnTarget":
            for field, value, error in [
                ("ontargetScoringAtt", 1, "shots-on-target evidence"),
                ("ontargetScoringAtt", None, "shots-on-target evidence"),
                ("expectedGoalsOnTarget", None, "explicit provider field"),
                ("expectedGoalsOnTarget", 0.2, "explicit provider field"),
            ]:
                broken = json.loads(body)
                broken[1]["stats"][field] = value
                with pytest.raises(ValueError, match=error):
                    _apply_display_corrections(
                        con,
                        cutoff=confirmed,
                        season="2026-27",
                        fixtures=fixtures,
                        players=players,
                        teams=teams,
                        raw=[{**raw[0], "body": json.dumps(broken)}],
                    )
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
    assert direct["sdp"]["shots_on_target"] is mirror["sdp"]["shots_on_target_allowed"] is None
    assert mirror["sdp"]["shots_allowed"] == 6
    assert "shots_allowed" not in mirror["display_corrections"]
    metric = {
        "blockedScoringAtt": "shots_blocked",
        "expectedGoalsOnTarget": "expected_goals_on_target",
    }.get(provider_field, "shots_on_target")
    assert direct["sdp"][metric] is None
    assert direct["display_corrections"][metric]["value"] == 0
    if provider_field != "ontargetScoringAtt":
        assert mirror["display_corrections"] == {}
    else:
        assert (
            mirror["display_corrections"]["shots_on_target_allowed"]["relation"]
            == "opponent_mirror"
        )
    # A later provider value wins without erasing the earlier owner receipt.
    direct["sdp"][metric] = 1
    mirror["sdp"]["shots_on_target_allowed"] = 1
    direct["display_corrections"] = {}
    mirror["display_corrections"] = {}
    with duckdb.connect(str(tmp_path / "later-provider.duckdb")) as later_con:
        later_con.execute(
            "CREATE TABLE stg_pl_sdp_fixture_crosswalk AS SELECT '2026-27' AS season, "
            "7 AS fixture, 2645201 AS sdp_match_id, TRUE AS corroborated_kickoff, "
            "TRUE AS corroborated_teams, ?::TIMESTAMPTZ AS resolved_at",
            [source_known],
        )
        assert (
            _apply_display_corrections(
                later_con,
                cutoff=confirmed,
                season="2026-27",
                fixtures=fixtures,
                players=players,
                teams=teams,
                raw=raw,
            )
            == 0
        )
    assert direct["display_corrections"] == {}
    assert raw == original


def test_committed_display_policy_is_bounded_and_preserves_confirmation_times() -> None:
    policy = load_display_corrections()
    assert policy.version == 3
    assert {(row.fixture, row.team_code, row.provider_field) for row in policy.corrections} == {
        (7, 7, "ontargetScoringAtt"),
        (7, 7, "blockedScoringAtt"),
        (19, 54, "ontargetScoringAtt"),
        (20, 7, "ontargetScoringAtt"),
        (28, 6, "ontargetScoringAtt"),
        (7, 7, "expectedGoalsOnTarget"),
        (19, 54, "expectedGoalsOnTarget"),
        (20, 7, "expectedGoalsOnTarget"),
        (28, 6, "expectedGoalsOnTarget"),
    }
    old = {(7, "ontargetScoringAtt"), (20, "ontargetScoringAtt"), (28, "ontargetScoringAtt")}
    for row in policy.corrections:
        expected = (
            "2026-09-08T14:40:50.135115+00:00"
            if (row.fixture, row.provider_field) in old
            else "2026-09-09T02:12:10+00:00"
        )
        if row.provider_field == "expectedGoalsOnTarget":
            expected = "2026-09-09T07:24:08+00:00"
        assert row.owner_confirmation_recorded_at.isoformat() == expected
        assert row.display_value == 0
    with pytest.raises(ValueError, match="require policy version 2"):
        DisplayCorrectionPolicy(
            schema_id=policy.schema_id,
            version=1,
            corrections=policy.corrections,
        )
    with pytest.raises(ValueError, match="require policy version 3"):
        DisplayCorrectionPolicy(
            schema_id=policy.schema_id, version=2, corrections=policy.corrections
        )


@pytest.mark.parametrize(
    ("metric", "provider_field"),
    [("shots_blocked", "blockedScoringAtt"), ("expected_goals_on_target", "expectedGoalsOnTarget")],
)
def test_public_direct_display_correction_has_no_invented_opponent_mirror(
    tmp_path: Path, metric: str, provider_field: str
) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    document = _load(db)
    row = document["team_matches"][0]
    row["display_corrections"][metric] = {
        "correction_id": "synthetic-blocked-zero",
        "value": 0,
        "evidence_class": "owner_confirmed_display_correction",
        "provider_field": provider_field,
        "provider_field_state": "omitted",
        "corroboration": (
            "owner_confirmed_xgot_with_corroborated_zero_sot"
            if metric == "expected_goals_on_target"
            else "shot_accounting_and_fpl_goalkeeper_proxy_zero"
        ),
        "raw_payload_sha256": "a" * 64,
        "provider_match_id": 123,
        "subject_team_code": row["team_code"],
        "relation": "direct",
        "source_known_at": row["known_at"],
        "owner_confirmation_recorded_at": document["as_of"],
    }
    validate_sdp_stats(document)
    assert row["sdp"][metric] is None
    if metric == "expected_goals_on_target":
        document["json_schema_version"] = 3
        with pytest.raises(ValueError, match="provenance"):
            validate_sdp_stats(document)
        document["json_schema_version"] = 4
    row["display_corrections"][metric]["relation"] = "opponent_mirror"
    with pytest.raises(ValueError, match="relation"):
        validate_sdp_stats(document)


def test_public_omitted_count_assumption_keeps_raw_null_and_fails_closed(
    tmp_path: Path,
) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    document = _load(db)
    policy_time = OMITTED_ZERO_POLICY_RECORDED_AT.isoformat()
    document["as_of"] = policy_time
    row = document["team_matches"][0]
    row["provider_match_id"] = 123
    row["sdp"]["shots_outside_box"] = None
    row["display_assumptions"]["shots_outside_box"] = {
        "value": 0,
        "evidence_class": "owner_directed_omitted_count_assumption",
        "policy_recorded_at": policy_time,
        "source_known_at": row["known_at"],
        "provider_match_id": 123,
        "provider_field": "attemptsObox | attempts_obox | shots_outside_box",
        "provider_field_state": "omitted",
        "raw_payload_sha256": "a" * 64,
    }
    validate_sdp_stats(document)
    assert row["sdp"]["shots_outside_box"] is None
    row["sdp"]["shots_outside_box"] = 0
    with pytest.raises(ValueError, match="omitted-count"):
        validate_sdp_stats(document)


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


@pytest.mark.parametrize(
    "defect", [None, "string_ids", "identity", "corrupt", "future", "impossible", "late_mapping"]
)
def test_partial_display_preserves_measured_goals_and_does_not_promote_core(
    tmp_path: Path, defect: str | None
) -> None:
    cutoff = CAPTURED + timedelta(days=1)
    with initialise(tmp_path / "partial.duckdb") as con:

        def omit_sot(payload: Any) -> None:
            payload[0]["stats"].pop("ontargetScoringAtt")
            payload[1]["stats"]["goals"] = 3

        seed(con, change=omit_sot)  # type: ignore[no-untyped-call]
        # Synthetic contemporaneous crosswalk; an actually later mapping fails.
        if defect != "late_mapping":
            con.execute("UPDATE stg_pl_sdp_fixture_crosswalk SET resolved_at=?", [CAPTURED])
        before = load_sdp_state(con, cutoff=cutoff, season=SEASON)
        assert before.failures[SEASON, 103] == "SDP_INCOMPLETE_FALLBACK"
        raw = raw_at(con, cutoff)
        metadata = next(r for r in raw if r["endpoint"] == "matches")
        record = json.loads(metadata["body"])["content"][-1]
        kickoff = datetime.fromtimestamp(record["kickoff"]["millis"] / 1000, UTC)
        official = {"kickoff": kickoff, "home": 8, "away": 3}
        if defect == "identity":
            official["away"] = 999
        capture = next(
            r for r in raw if r["endpoint"] == "match_stats" and r["sdp_match_id"] == 300103
        )
        if defect == "corrupt":
            capture["sha256"] = "b" * 64
        if defect == "future":
            capture["fetched_at"] = cutoff + timedelta(hours=1)
        if defect == "impossible":
            payload = json.loads(capture["body"])
            payload[0]["stats"]["accuratePass"] = 99999
            capture["body"] = json.dumps(payload)
            capture["sha256"] = hashlib.sha256(capture["body"].encode()).hexdigest()
            capture["byte_count"] = len(capture["body"].encode())
        if defect == "string_ids":
            for source in raw:
                if source["endpoint"] == "matches":
                    body = json.loads(source["body"])
                    for item in body["content"]:
                        item["id"] = str(item["id"])
                        if "competitionId" in item:
                            item["competitionId"] = str(item["competitionId"])
                    source["body"] = json.dumps(body)
                    source["sha256"] = hashlib.sha256(source["body"].encode()).hexdigest()
                    source["byte_count"] = len(source["body"].encode())
        result = _partial_current_stats(
            con, raw, season=SEASON, fixture=103, official=official, cutoff=cutoff
        )
        if defect not in (None, "string_ids"):
            assert result is None
        else:
            assert result is not None
            sides = result[0]
            assert sides["away"]["goals"] == 3
            assert "ontargetScoringAtt" not in sides["home"]
            assert sides["home"]["totalScoringAtt"] == 12
        assert load_sdp_state(con, cutoff=cutoff, season=SEASON) == before


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
