"""Offline deterministic tests for the read-only SDP fallback attribution audit.

All provider payloads are synthetic; nothing here is evidence about the live provider.
The audit reads the saved artifact's recorded decisions as authoritative and re-derives
the same attribution independently, so every scenario pins both sides plus the
FIXABLE_NOW versus LEGITIMATE_FAIL_CLOSED classification.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from fpl.artifacts.prospective_points import (
    ForecastArtifactManifest,
    ForecastArtifactRow,
    ForecastTeamFixtureRow,
    LiveInputProvenance,
    ProspectivePointsArtifact,
    write_artifact_atomic,
)
from fpl.config import repo_root
from fpl.football_configuration import FootballEnvironmentConfig, load_football_environment
from fpl.jobs.audit_sdp_fallbacks import main as job_main
from fpl.models.sdp_environment import FrozenSdpModel, select_environments
from fpl.storage.db import initialise
from fpl.storage.sdp_diagnostics import (
    CATEGORY_COLD_START,
    CATEGORY_INSUFFICIENT_RECENT_HISTORY,
    CATEGORY_MISSING_REQUIRED_ARTIFACT,
    CATEGORY_OTHER,
    CATEGORY_SDP_DUPLICATE,
    CATEGORY_SDP_IDENTITY,
    CATEGORY_SDP_INCOMPLETE,
    CATEGORY_SDP_INVALID_NUMERIC,
    CATEGORY_SDP_MISSING,
    CATEGORY_SDP_SCHEMA,
    CATEGORY_SDP_SOURCE,
    CATEGORY_SOURCE_NOT_CUTOFF_ELIGIBLE,
    FIXABLE_NOW,
    LEGITIMATE_FAIL_CLOSED,
    _club_history,
    _safe_rows,
    _saved_decisions,
    _team_names,
    audit_fallbacks,
    categorize,
    fixtures_from_artifact,
    metric_issues,
)
from fpl.storage.sdp_runtime import (
    SdpHealthError,
    SdpState,
    SdpStateRow,
    checked_metrics,
    load_sdp_state,
)
from fpl.transform import pl_sdp as sdp
from fpl.validate.metrics import poisson_pmf
from fpl.validate.tactical_state import tactical_values

from .test_pl_sdp_revision_pit import CAPTURED, KICKOFF, SEASON, _raw, _rebuild
from .test_sdp_primary import CUTOFF, METRICS, seed

GW = 5
FIXTURE = 500
PROVENANCE_KEY = "football_environment.provenance"


def _provenance(
    selector: str = "SDP_PRIMARY", fixture: int = FIXTURE, detail: str | None = None
) -> dict[str, Any]:
    decision: dict[str, Any] = {
        "season": SEASON,
        "gw": GW,
        "fixture": fixture,
        "home_team_code": 3,
        "away_team_code": 8,
        "selector": selector,
    }
    if detail is not None:
        decision["detail"] = detail
    return {"schema_version": 1, "primary": "sdp_v2", "decisions": [decision]}


def _artifact(
    *,
    cutoff: datetime = CUTOFF,
    season: str = SEASON,
    fixture: int = FIXTURE,
    selector: str = "SDP_PRIMARY",
    detail: str | None = None,
    with_provenance: bool = True,
) -> ProspectivePointsArtifact:
    kickoff = cutoff + timedelta(days=1)

    def _mean(rate: float) -> float:
        return sum(index * mass for index, mass in enumerate(poisson_pmf(rate)))

    team_rows = [
        ForecastTeamFixtureRow(
            season=season,
            gw=GW,
            fixture=fixture,
            kickoff_time=kickoff,
            team_id=1,
            team_code=3,
            opponent_team_id=2,
            was_home=True,
            lambda_for=_mean(1.3),
            lambda_against=_mean(1.1),
            probability_clean_sheet=0.2,
            goals_for_distribution=poisson_pmf(1.3),
            stage_a_league_average_team=False,
        ),
        ForecastTeamFixtureRow(
            season=season,
            gw=GW,
            fixture=fixture,
            kickoff_time=kickoff,
            team_id=2,
            team_code=8,
            opponent_team_id=1,
            was_home=False,
            lambda_for=_mean(1.1),
            lambda_against=_mean(1.3),
            probability_clean_sheet=0.15,
            goals_for_distribution=poisson_pmf(1.1),
            stage_a_league_average_team=False,
        ),
    ]
    manifest = ForecastArtifactManifest(
        as_of=cutoff,
        season=season,
        schema_version=2,
        gw_from=GW,
        gw_to=GW,
        row_count=1,
        player_fixture_row_count=0,
        team_fixture_row_count=2,
        roster_size=1,
        fixture_count=1,
        monte_carlo_draws=100,
        base_seed=1,
        fixture_points_support_max=0,
        freshness_cold_start=False,
        worktree_clean=True,
        commit_sha="a" * 40,
        database_sha256="b" * 64,
        contracts={},
        component_modes={PROVENANCE_KEY: json.dumps(_provenance(selector, fixture, detail))}
        if with_provenance
        else {},
        live_inputs=LiveInputProvenance(
            bootstrap_capture_id="cap",
            bootstrap_known_at=cutoff,
            bootstrap_payload_sha256="c" * 64,
            schedule_capture_ids=(),
        ),
    )
    row = ForecastArtifactRow(
        season=season,
        gw=GW,
        code=1001,
        web_name=None,
        position="GK",
        team_id=1,
        team_code=3,
        availability_status="available",
        availability_multiplier=1.0,
        fixture_ids=(),
        kickoff_times=(),
        expected_points=0.0,
        availability_adjusted_expected_points=0.0,
        expected_bonus=0.0,
        distribution=(1.0,),
        cold_start_player=False,
        stage_a_league_average_team=False,
        attacking_signal_cold_start=False,
        assist_signal_cold_start=False,
        transferred_no_rescale=False,
    )
    return ProspectivePointsArtifact(
        manifest=manifest, rows=[row], player_fixture_rows=(), team_fixture_rows=tuple(team_rows)
    )


def _audit(
    con: Any, artifact: ProspectivePointsArtifact | None = None, **kwargs: Any
) -> dict[str, Any]:
    return audit_fallbacks(
        con,
        artifact or _artifact(),
        repo=kwargs.pop("repo", repo_root()),
        environment_config=kwargs.pop("environment_config", load_football_environment()),
        **kwargs,
    )


def _real_selector_reason(con: Any) -> str:
    state = load_sdp_state(con, cutoff=CUTOFF, season=SEASON)
    schedule = pl.DataFrame(
        [
            {
                "season": SEASON,
                "fixture": FIXTURE,
                "gw": GW,
                "team_id": 1,
                "opponent_team_id": 2,
                "was_home": True,
                "kickoff_time": CUTOFF + timedelta(days=1),
            }
        ]
    )
    incumbent = {(FIXTURE, code): poisson_pmf(rate) for code, rate in ((3, 1.5), (8, 1.1))}
    model = FrozenSdpModel.load(repo_root(), load_football_environment(), CUTOFF)
    _, report = select_environments(
        state=state,
        model=model,
        model_failure=None,
        cutoff=CUTOFF,
        season=SEASON,
        schedule=schedule,
        team_map={1: 3, 2: 8},
        incumbent=incumbent,
    )
    return report["decisions"][0]["selector"]


def _broken_config() -> FootballEnvironmentConfig:
    return FootballEnvironmentConfig(
        football_environment_primary="sdp_v2",
        football_environment_fallback="trailing_goals_attack_defence",
        shadow_incumbent=False,
        gk_saves_candidate_mode="disabled",
        frozen_parameters="missing_frozen.json",
        frozen_parameters_sha256="0" * 64,
        gk_shadow_parameters="missing_shadow.json",
        gk_shadow_parameters_sha256="0" * 64,
        lookback_days=7,
        workload_competitions=(),
    )


def _state_row(fixture: int, code: int, kickoff: datetime) -> SdpStateRow:
    return SdpStateRow(
        SEASON,
        1,
        fixture,
        code,
        code + 100,
        True,
        kickoff,
        tactical_values(METRICS, METRICS),
        dict(METRICS),
        {"known_at": (kickoff + timedelta(days=1)).isoformat()},
    )


@pytest.mark.parametrize(
    ("reason", "detail", "expected"),
    [
        (None, "", "SDP_PRIMARY"),
        ("SDP_MISSING_FALLBACK", "", "SDP_MISSING"),
        ("SDP_MISSING_FALLBACK", "missing raw version", "SDP_MISSING"),
        ("SDP_INCOMPLETE_FALLBACK", "required field absent: ontargetScoringAtt", "SDP_INCOMPLETE"),
        ("SDP_SCHEMA_FALLBACK", "stats mapping required", "SDP_SCHEMA"),
        ("SDP_SCHEMA_FALLBACK", "raw payload unavailable or hash/status mismatch", "SDP_SCHEMA"),
        ("SDP_SCHEMA_FALLBACK", "invalid field: totalPass", "SDP_INVALID_NUMERIC"),
        ("SDP_SCHEMA_FALLBACK", "nonintegral count: totalPass", "SDP_INVALID_NUMERIC"),
        ("SDP_SCHEMA_FALLBACK", "possession exceeds 100", "SDP_INVALID_NUMERIC"),
        ("SDP_IDENTITY_FALLBACK", "raw/crosswalk/fixture identity mismatch", "SDP_IDENTITY"),
        ("SDP_IDENTITY_FALLBACK", "duplicate provider match record", "SDP_DUPLICATE"),
        ("SDP_SOURCE_FALLBACK", "synthetic HTTP failure", "SDP_SOURCE"),
        (
            "SDP_MISSING_FALLBACK",
            "model was not known at prediction cutoff",
            "SOURCE_NOT_CUTOFF_ELIGIBLE",
        ),
        ("SDP_SCHEMA_FALLBACK", "frozen model artifact hash mismatch", "MISSING_REQUIRED_ARTIFACT"),
        ("SOMETHING_ELSE", "", "OTHER"),
    ],
)
def test_categorize_supports_every_required_category(
    reason: str | None, detail: str, expected: str
) -> None:
    assert categorize(reason, detail) == expected


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("totalPass", float("nan")),
        ("totalPass", -1),
        ("totalPass", True),
        ("totalPass", "broken"),
        ("possessionPercentage", 101),
        ("ontargetScoringAtt", 13),
        ("accuratePass", 421),
    ],
)
def test_metric_issues_mirror_checked_metrics(key: str, value: Any) -> None:
    with pytest.raises(SdpHealthError):
        checked_metrics({**METRICS, key: value})
    issues = metric_issues({**METRICS, key: value})
    assert issues and all(issue["field"] == key for issue in issues)


def test_metric_issues_absent_optional_field_is_not_an_issue() -> None:
    assert metric_issues(METRICS) == []
    assert metric_issues(None)[0]["status"] == "schema"


def test_club_history_missing_match_is_insufficient_never_cold_start() -> None:
    cutoff = CUTOFF
    kickoffs = [datetime(2026, 8, day, tzinfo=UTC) for day in (10, 17, 24)]
    state = SdpState()
    state.expected = {
        (SEASON, fixture, 3): kickoff for fixture, kickoff in zip((1, 2, 3), kickoffs, strict=True)
    }
    state.rows = [_state_row(1, 3, kickoffs[0])]
    safe = _safe_rows(state, cutoff)
    valid_keys = {(row.season, row.fixture, row.team_code) for row in safe}
    block = _club_history(
        state, safe, valid_keys, season=SEASON, code=3, cutoff=cutoff, excluded_gw=GW
    )
    assert block["category"] == CATEGORY_INSUFFICIENT_RECENT_HISTORY
    assert block["expected_completed_matches"] == 3
    assert block["eligible_valid_matches"] == 1
    assert block["frozen_prior"]["requirement_waived"] is False
    assert block["frozen_prior"]["state_estimate_computable"] is True

    empty_block = _club_history(
        SdpState(), [], set(), season=SEASON, code=3, cutoff=cutoff, excluded_gw=GW
    )
    assert empty_block["category"] == CATEGORY_COLD_START


def test_team_names_use_season_qualified_latest_live_versions(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        rows = [
            (SEASON, 1, 3, CAPTURED - timedelta(hours=2), "cap-1", "Coventry", "COV"),
            (SEASON, 2, 8, CAPTURED - timedelta(hours=2), "cap-1", "Hull City", "HUL"),
            # A later capture known only after the cutoff must never be selected.
            (SEASON, 1, 3, CUTOFF + timedelta(days=1), "cap-2", "Future Name", "FUT"),
        ]
        for season, team_id, team_code, known_at, capture_id, name, short in rows:
            con.execute(
                "INSERT INTO stg_live_team_version VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                [season, team_id, team_code, known_at, capture_id, name, short],
            )
        names = _team_names(con, season=SEASON, cutoff=CUTOFF)
        assert names == {3: "Coventry", 8: "Hull City"}


def test_saved_decisions_are_authoritative_and_validated() -> None:
    fixtures, _ = fixtures_from_artifact(_artifact())
    artifact = _artifact()
    saved = _saved_decisions(artifact, fixtures)
    assert saved[FIXTURE]["selector"] == "SDP_PRIMARY"
    with pytest.raises(ValueError, match="environment-disabled"):
        _saved_decisions(_artifact(with_provenance=False), fixtures)
    double = _artifact()
    modes = dict(double.manifest.component_modes)
    modes[PROVENANCE_KEY] = json.dumps(
        {"decisions": [_provenance()["decisions"][0], _provenance()["decisions"][0]]}
    )
    rebuilt = ProspectivePointsArtifact(
        manifest=double.manifest.model_copy(update={"component_modes": modes}),
        rows=double.rows,
        player_fixture_rows=(),
        team_fixture_rows=double.team_fixture_rows,
    )
    with pytest.raises(ValueError, match="multiple decisions"):
        _saved_decisions(rebuilt, fixtures)
    wrong_gw = _artifact()
    modes = dict(wrong_gw.manifest.component_modes)
    decision = dict(_provenance()["decisions"][0])
    decision["gw"] = GW + 1
    modes[PROVENANCE_KEY] = json.dumps({"decisions": [decision]})
    rebuilt = ProspectivePointsArtifact(
        manifest=wrong_gw.manifest.model_copy(update={"component_modes": modes}),
        rows=wrong_gw.rows,
        player_fixture_rows=(),
        team_fixture_rows=wrong_gw.team_fixture_rows,
    )
    with pytest.raises(ValueError, match="identity disagrees"):
        _saved_decisions(rebuilt, fixtures)


def test_fixtures_from_artifact_rebuilds_schedule_and_team_map() -> None:
    fixtures, team_map = fixtures_from_artifact(_artifact())
    assert [entry.fixture for entry in fixtures] == [FIXTURE]
    assert fixtures[0].home_code == 3 and fixtures[0].away_code == 8
    assert team_map == {1: 3, 2: 8}


def test_fixtures_from_artifact_rejects_conflicting_team_map() -> None:
    artifact = _artifact()
    conflicting = artifact.team_fixture_rows[1].model_copy(update={"team_id": 1})
    rebuilt = ProspectivePointsArtifact(
        manifest=artifact.manifest,
        rows=artifact.rows,
        player_fixture_rows=(),
        team_fixture_rows=(artifact.team_fixture_rows[0], conflicting),
    )
    with pytest.raises(ValueError, match="conflicting team codes"):
        fixtures_from_artifact(rebuilt)


def test_primary_saved_when_history_complete(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        report = _audit(con)
        summary = report["summary"]
        assert summary["fallback_fixtures"] == 0
        assert summary["primary_saved_fixtures"] == 1
        assert summary["rederived_agrees_with_saved"] == 1
        entry = report["fixtures"][0]
        assert entry["selector"]["category"] == "SDP_PRIMARY"
        assert entry["rederived"]["category"] == "SDP_PRIMARY"
        assert _real_selector_reason(con) == "SDP_PRIMARY"


def test_incomplete_core_omission_is_missing_never_zero(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con, change=lambda payload: payload[0]["stats"].update(accuratePass=None))
        report = _audit(con, _artifact(selector="SDP_INCOMPLETE_FALLBACK"))
        summary = report["summary"]
        assert summary["fallback_fixtures"] == 1
        assert summary["fallback_categories"] == {CATEGORY_SDP_INCOMPLETE: 1}
        assert summary["fixture_classification"][LEGITIMATE_FAIL_CLOSED] == 1
        entry = report["fixtures"][0]
        assert entry["selector"]["runtime_reason"] == "SDP_INCOMPLETE_FALLBACK"
        assert entry["selector"]["category"] == CATEGORY_SDP_INCOMPLETE
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED
        cause = report["completed_match_failures"][0]
        affected = [
            side
            for side in cause["sides"].values()
            if side["missing_required_fields"] == ["accuratePass"]
        ]
        assert len(affected) == 1
        issue = affected[0]["field_issues"][0]
        assert issue["status"] == "absent_required"
        assert issue["detail"] == "required field absent"
        assert "never zero-fill" in cause["proposed_action"]
        assert cause["latest_eligible_raw_valid"] is False
        for club in entry["clubs"]:
            assert club["category"] == CATEGORY_INSUFFICIENT_RECENT_HISTORY
            assert club["expected_completed_matches"] == 4
            assert club["eligible_valid_matches"] == 3
            assert club["latest_valid_match"] is not None
        assert _real_selector_reason(con) == "SDP_INCOMPLETE_FALLBACK"


def test_deleted_raw_version_is_missing_and_legitimate(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        con.execute(
            "DELETE FROM raw_pl_sdp_payload WHERE endpoint='match_stats' AND sdp_match_id=300103"
        )
        report = _audit(con, _artifact(selector="SDP_MISSING_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["selector"]["category"] == CATEGORY_SDP_MISSING
        cause = report["completed_match_failures"][0]
        assert cause["identity_link"] == "present"
        assert cause["raw_versions"] == []
        assert cause["classification"] == LEGITIMATE_FAIL_CLOSED
        assert "no stats raw version existed at the cutoff" in cause["proposed_action"]
        assert _real_selector_reason(con) == "SDP_MISSING_FALLBACK"


def test_unlinked_completed_match_refuses_fuzzy_attribution(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        kickoff = CUTOFF - timedelta(days=5)
        con.execute(
            """
            INSERT INTO mart_fact_team_match_stats_v2
                (season, gw, fixture, kickoff_time, team_id, team_code,
                 opponent_team_id, opponent_team_code, was_home, provider, known_at)
            VALUES
                (?, 5, 109, ?, 1, 3, 2, 8, TRUE, 'fpl_archive', ?),
                (?, 5, 109, ?, 2, 8, 1, 3, FALSE, 'fpl_archive', ?)
            """,
            [SEASON, kickoff, CAPTURED, SEASON, kickoff, CAPTURED],
        )
        report = _audit(con, _artifact(selector="SDP_MISSING_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["selector"]["category"] == CATEGORY_SDP_MISSING
        assert entry["rederived"]["category"] == CATEGORY_SDP_MISSING
        cause = report["completed_match_failures"][0]
        assert cause["fixture"] == 109
        assert cause["identity_link"] == "absent"
        assert "do not fuzzy-match" in cause["proposed_action"]
        assert _real_selector_reason(con) == "SDP_MISSING_FALLBACK"


def test_latest_valid_but_unstaged_is_fixable_now(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        payload = [
            {"side": side, "team": {"id": team}, "stats": {**METRICS, "totalScoringAtt": 40}}
            for side, team in (("Home", 8), ("Away", 3))
        ]
        sdp.land_payload(
            con,
            _raw("match_stats", payload, CAPTURED + timedelta(hours=1), 300103),
            season=SEASON,
            sdp_match_id=300103,
        )
        report = _audit(con, _artifact(selector="SDP_INCOMPLETE_FALLBACK"))
        summary = report["summary"]
        assert summary["fallback_categories"] == {CATEGORY_SDP_INCOMPLETE: 1}
        assert summary["fixture_classification"][FIXABLE_NOW] == 1
        cause = report["completed_match_failures"][0]
        assert cause["latest_eligible_raw_valid"] is True
        latest = cause["raw_versions"][-1]
        assert latest["valid"] is True
        assert latest["selected_by_runtime"] is False
        assert cause["selected"]["fetched_at"] == CAPTURED.isoformat()
        assert "restage from payload" in cause["proposed_action"]
        entry = report["fixtures"][0]
        assert entry["classification"] == FIXABLE_NOW


def test_multiple_blockers_all_reported_mixed_fixability(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con, change=lambda payload: payload[0]["stats"].update(accuratePass=None))
        good = [
            {"side": side, "team": {"id": team}, "stats": {**METRICS, "totalScoringAtt": 40}}
            for side, team in (("Home", 8), ("Away", 3))
        ]
        sdp.land_payload(
            con,
            _raw("match_stats", good, CAPTURED + timedelta(hours=2), 300102),
            season=SEASON,
            sdp_match_id=300102,
        )
        report = _audit(con, _artifact(selector="SDP_INCOMPLETE_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["selector"]["runtime_reason"] == "SDP_INCOMPLETE_FALLBACK"
        assert entry["rederived"]["reason"] == "SDP_INCOMPLETE_FALLBACK"
        contributing = entry["contributing_failures"]
        blockers = {(item["fixture"], item["team_code"]) for item in contributing}
        assert blockers == {(102, 3), (102, 8), (103, 3), (103, 8)}
        classes = {item["fixture"]: item["classification"] for item in contributing}
        assert classes[102] == FIXABLE_NOW
        assert classes[103] == LEGITIMATE_FAIL_CLOSED
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED
        assert "restage from payload" in entry["proposed_action"]
        assert "fails validation (accuratePass)" in entry["proposed_action"]
        assert report["summary"]["completed_match_root_causes"] == 2
        assert report["summary"]["fixture_classification"][FIXABLE_NOW] == 0


def test_source_or_model_failure_with_resolvable_blockers_stays_legitimate(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        good = [
            {"side": side, "team": {"id": team}, "stats": {**METRICS, "totalScoringAtt": 40}}
            for side, team in (("Home", 8), ("Away", 3))
        ]
        sdp.land_payload(
            con,
            _raw("match_stats", good, CAPTURED + timedelta(hours=1), 300103),
            season=SEASON,
            sdp_match_id=300103,
        )
        report = _audit(con, _artifact(selector="SDP_SOURCE_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["selector"]["category"] == CATEGORY_SDP_SOURCE
        blockers = entry["contributing_failures"]
        assert blockers
        assert all(item["classification"] == FIXABLE_NOW for item in blockers)
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED
        assert "does not resolve" in entry["proposed_action"]
        model_report = audit_fallbacks(
            con,
            _artifact(selector="SDP_SCHEMA_FALLBACK"),
            repo=tmp_path,
            environment_config=_broken_config(),
        )
        model_entry = model_report["fixtures"][0]
        assert model_entry["classification"] == LEGITIMATE_FAIL_CLOSED
        assert "global selector failure" in model_entry["proposed_action"]


def test_older_valid_under_newer_defective_stays_legitimate(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        payload = [
            {"side": side, "team": {"id": team}, "stats": {**METRICS, "accuratePass": None}}
            for side, team in (("Home", 8), ("Away", 3))
        ]
        sdp.land_payload(
            con,
            _raw("match_stats", payload, CAPTURED + timedelta(hours=1), 300103),
            season=SEASON,
            sdp_match_id=300103,
        )
        _rebuild(con)
        report = _audit(con, _artifact(selector="SDP_INCOMPLETE_FALLBACK"))
        summary = report["summary"]
        assert summary["fallback_categories"] == {CATEGORY_SDP_INCOMPLETE: 1}
        assert summary["fixture_classification"][FIXABLE_NOW] == 0
        cause = report["completed_match_failures"][0]
        assert cause["latest_eligible_raw_valid"] is False
        assert "cannot be resurrected" in cause["proposed_action"]
        assert report["completed_match_failures"][0]["later_only_versions"] is None


def test_invalid_numeric_field_is_attributed_not_schema(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con, change=lambda payload: payload[0]["stats"].update(totalPass=-1))
        report = _audit(con, _artifact(selector="SDP_SCHEMA_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["rederived"]["reason"] == "SDP_SCHEMA_FALLBACK"
        assert entry["selector"]["category"] == CATEGORY_SDP_INVALID_NUMERIC
        cause = report["completed_match_failures"][0]
        invalid = [
            side for side in cause["sides"].values() if "totalPass" in side["invalid_fields"]
        ]
        assert len(invalid) == 1
        assert cause["classification"] == LEGITIMATE_FAIL_CLOSED


def test_metadata_identity_revision_stays_legitimate(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        body = con.execute(
            "SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload "
            "WHERE endpoint='matches' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()[0]
        payload = json.loads(body)
        payload["content"][-1]["teams"][0]["team"]["id"] = 999
        sdp.land_payload(con, _raw("matches", payload, CUTOFF - timedelta(hours=1)), season=SEASON)
        report = _audit(con, _artifact(selector="SDP_IDENTITY_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["selector"]["category"] == CATEGORY_SDP_IDENTITY
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED


def test_duplicate_metadata_record_is_its_own_category(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        body = con.execute(
            "SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload "
            "WHERE endpoint='matches' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()[0]
        payload = json.loads(body)
        payload["content"].append(payload["content"][-1])
        sdp.land_payload(con, _raw("matches", payload, CUTOFF - timedelta(hours=1)), season=SEASON)
        report = _audit(con, _artifact(selector="SDP_IDENTITY_FALLBACK"))
        assert report["summary"]["fallback_categories"] == {CATEGORY_SDP_DUPLICATE: 1}
        assert report["completed_match_failures"] == []


def test_tampered_raw_is_schema_and_global(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        body = con.execute(
            "SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload "
            "WHERE endpoint='matches' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()[0]
        payload = json.loads(body)
        for record in payload["content"]:
            record["competitionId"] = 1
        con.execute(
            "UPDATE raw_pl_sdp_payload SET payload=? WHERE endpoint='matches'",
            [json.dumps(payload)],
        )
        report = _audit(con, _artifact(selector="SDP_SCHEMA_FALLBACK"))
        assert report["summary"]["fallback_categories"] == {CATEGORY_SDP_SCHEMA: 1}
        entry = report["fixtures"][0]
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED
        assert "global selector failure" in entry["proposed_action"]
        assert report["completed_match_failures"] == []


def test_saved_source_outage_is_not_cutoff_ineligible(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        report = _audit(con, _artifact(selector="SDP_SOURCE_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["selector"]["category"] == CATEGORY_SDP_SOURCE
        assert entry["selector"]["category"] != CATEGORY_SOURCE_NOT_CUTOFF_ELIGIBLE
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED
        assert "rerun the SDP refresh" in entry["proposed_action"]
        assert entry["rederived"]["category"] == "SDP_PRIMARY"


def test_provider_absent_means_club_cold_start(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        report = _audit(con, _artifact(selector="SDP_MISSING_FALLBACK"))
        entry = report["fixtures"][0]
        assert entry["selector"]["category"] == CATEGORY_SDP_MISSING
        for club in entry["clubs"]:
            assert club["category"] == CATEGORY_COLD_START
            assert club["expected_completed_matches"] == 0
            assert club["eligible_valid_matches"] == 0


def test_model_not_known_at_cutoff_in_rederivation(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        report = audit_fallbacks(
            con,
            _artifact(cutoff=KICKOFF, selector="SDP_SOURCE_FALLBACK"),
            repo=repo_root(),
            environment_config=load_football_environment(),
        )
        assert report["frozen_model"]["available"] is False
        assert report["frozen_model"]["category"] == CATEGORY_SOURCE_NOT_CUTOFF_ELIGIBLE
        entry = report["fixtures"][0]
        assert entry["rederived"]["category"] == CATEGORY_SOURCE_NOT_CUTOFF_ELIGIBLE
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED


def test_missing_frozen_model_artifact_fails_closed(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        report = audit_fallbacks(
            con,
            _artifact(selector="SDP_SCHEMA_FALLBACK"),
            repo=tmp_path,
            environment_config=_broken_config(),
        )
        assert report["frozen_model"]["category"] == CATEGORY_MISSING_REQUIRED_ARTIFACT
        entry = report["fixtures"][0]
        assert entry["rederived"]["category"] == CATEGORY_MISSING_REQUIRED_ARTIFACT
        assert entry["classification"] == LEGITIMATE_FAIL_CLOSED


def test_other_is_reserved_for_unknown_reasons(tmp_path) -> None:
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        report = _audit(con)
        assert categorize("UNRECOGNIZED_REASON") == CATEGORY_OTHER
        assert report["fixtures"][0]["selector"]["category"] == "SDP_PRIMARY"


def test_job_cli_writes_report_then_refuses_clobber(tmp_path) -> None:
    db = tmp_path / "operational.duckdb"
    with initialise(db) as con:
        seed(con)
    artifact_path = tmp_path / "primary.jsonl"
    write_artifact_atomic(artifact_path, _artifact())
    output = tmp_path / "audit.json"
    assert (
        job_main(["--db", str(db), "--artifact", str(artifact_path), "--output", str(output)]) == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["inputs"]["artifact_path"] == str(artifact_path)
    assert len(report["inputs"]["artifact_sha256"]) == 64
    assert report["summary"]["fallback_fixtures"] == 0
    assert report["cutoff"] == CUTOFF.isoformat()
    first = output.read_bytes()
    assert (
        job_main(["--db", str(db), "--artifact", str(artifact_path), "--output", str(output)]) == 2
    )
    assert output.read_bytes() == first
