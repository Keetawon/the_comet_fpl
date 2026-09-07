"""Production inference and raw/PIT failures; all provider payloads are synthetic."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from fpl.config import repo_root
from fpl.football_configuration import load_football_environment
from fpl.jobs.export_sdp_runtime_parameters import export
from fpl.models.sdp_environment import FrozenSdpModel, select_environments
from fpl.storage.db import initialise
from fpl.storage.sdp_runtime import CORE_FIELDS, SdpHealthError, checked_metrics, load_sdp_state
from fpl.transform import pl_sdp as sdp
from fpl.validate.metrics import poisson_pmf

from .test_pl_sdp_revision_pit import CAPTURED, KICKOFF, SEASON, _raw, _rebuild, _seed_matches

CUTOFF = datetime(2026, 9, 8, tzinfo=UTC)
METRICS = {
    "expectedGoals": 1.2,
    "totalScoringAtt": 12,
    "ontargetScoringAtt": 4,
    "attemptsIbox": 8,
    "touchesInOppBox": 21,
    "possessionPercentage": 50,
    "totalPass": 420,
    "accuratePass": 350,
    "fwdPass": 140,
}


def seed(con, *, change=None, known=CAPTURED):
    _seed_matches(con)
    original = con.execute(
        "SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload WHERE endpoint='matches'"
    ).fetchone()
    metadata = json.loads(original[0])
    for row in metadata["content"]:
        row["competitionId"] = 8
    sdp.land_payload(con, _raw("matches", metadata, known + timedelta(seconds=1)), season=SEASON)
    for index in range(4):
        home, away = (3, 8) if index % 2 == 0 else (8, 3)
        payload = [
            {"side": side, "team": {"id": team}, "stats": dict(METRICS)}
            for side, team in (("Home", home), ("Away", away))
        ]
        if change is not None and index == 3:
            change(payload)
        sdp.land_payload(
            con,
            _raw("match_stats", payload, known, 300100 + index),
            season=SEASON,
            sdp_match_id=300100 + index,
        )
    _rebuild(con)


def selection(con, cutoff=CUTOFF):
    state = load_sdp_state(con, cutoff=cutoff, season=SEASON)
    schedule = pl.DataFrame(
        [
            {
                "season": SEASON,
                "fixture": 500,
                "gw": 5,
                "team_id": 1,
                "opponent_team_id": 2,
                "was_home": True,
                "kickoff_time": cutoff + timedelta(days=1),
            }
        ]
    )
    incumbent = {(500, code): poisson_pmf(rate) for code, rate in ((3, 1.5), (8, 1.1))}
    model = FrozenSdpModel.load(repo_root(), load_football_environment(), CUTOFF)
    return (
        *select_environments(
            state=state,
            model=model,
            model_failure=None,
            cutoff=cutoff,
            season=SEASON,
            schedule=schedule,
            team_map={1: 3, 2: 8},
            incumbent=incumbent,
        ),
        incumbent,
    )


def test_primary_shadow_inputs_and_reproducible_output(tmp_path):
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        primary, report, incumbent = selection(con)
        assert report["decisions"][0]["selector"] == "SDP_PRIMARY"
        assert primary != incumbent
        assert selection(con) == (primary, report, incumbent)
        env = report["decisions"][0]["environment"]
        assert env["home"]["predicted_xg"] is not None
        assert env["home"]["expected_goals_on_target_value"] is None
        assert len(report["source_versions"]) == 4
        for source in report["source_versions"]:
            assert datetime.fromisoformat(source["known_at"]) <= CUTOFF
            assert {
                "provider",
                "competition",
                "season",
                "payload_id",
                "payload_sha256",
                "normalization_version",
                "schema_version",
                "fetched_at",
                "known_at",
            } <= source.keys()


@pytest.mark.parametrize("missing", CORE_FIELDS)
def test_core_null_is_unavailable_never_zero(missing):
    values = {**METRICS, missing: None}
    with pytest.raises(SdpHealthError, match="required field absent"):
        checked_metrics(values)
    assert checked_metrics(METRICS)["expectedGoalsOnTarget"] is None


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
        ("fwdPass", 421),
    ],
)
def test_bad_metrics_fail_closed(key, value):
    with pytest.raises(SdpHealthError):
        checked_metrics({**METRICS, key: value})


def test_missing_provider_preserves_incumbent(tmp_path):
    with initialise(tmp_path / "db.duckdb") as con:
        primary, report, incumbent = selection(con)
        assert primary == incumbent
        assert report["decisions"][0]["selector"] == "SDP_MISSING_FALLBACK"


def test_incomplete_recent_match_falls_back_whole_fixture(tmp_path):
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con, change=lambda payload: payload[0]["stats"].update(accuratePass=None))
        primary, report, incumbent = selection(con)
        assert primary == incumbent
        assert report["decisions"][0]["selector"] == "SDP_INCOMPLETE_FALLBACK"


def test_later_revision_never_changes_old_prediction(tmp_path):
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        before = selection(con)
        payload = [
            {"side": side, "team": {"id": code}, "stats": {**METRICS, "totalScoringAtt": 40}}
            for side, code in (("Home", 8), ("Away", 3))
        ]
        revised = CUTOFF + timedelta(days=1)
        sdp.land_payload(
            con, _raw("match_stats", payload, revised, 300103), season=SEASON, sdp_match_id=300103
        )
        _rebuild(con)
        assert selection(con) == before
        assert selection(con, revised + timedelta(seconds=1))[0] != before[0]
        times = con.execute(
            "SELECT count(DISTINCT fetched_at) FROM raw_pl_sdp_payload WHERE sdp_match_id=300103"
        ).fetchone()
        assert times[0] == 2


def test_raw_tampering_cannot_feed_epl(tmp_path):
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        raw = con.execute(
            "SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload "
            "WHERE endpoint='matches' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()
        payload = json.loads(raw[0])
        for row in payload["content"]:
            row["competitionId"] = 1
        # Same numerical match ids in another competition are not PL evidence.
        con.execute(
            "UPDATE raw_pl_sdp_payload SET payload=? WHERE endpoint='matches'",
            [json.dumps(payload)],
        )
        primary, report, incumbent = selection(con)
        assert primary == incumbent
        assert (
            report["decisions"][0]["selector"] == "SDP_SCHEMA_FALLBACK"
        )  # raw hash detects tampering


def test_export_is_exact_terminal_parameters_without_fitting():
    retained = json.loads((repo_root() / "config/sdp_v2_frozen_parameters.json").read_text())
    assert export(repo_root()) == retained
    assert retained["parameter_fold"]["gw"] == 38
    assert retained["source_research_verdict"] == "INCONCLUSIVE"


def test_frozen_model_cannot_travel_back_before_its_capture():
    with pytest.raises(SdpHealthError, match="not known"):
        FrozenSdpModel.load(repo_root(), load_football_environment(), KICKOFF)


def test_real_points_pipeline_primary_fallback_shadow_and_disabled(monkeypatch):
    from dataclasses import replace

    from fpl.jobs.prospective_points_v1 import (
        build_prospective_artifact,
        predict_prospective_points,
    )
    from fpl.storage import sdp_runtime
    from fpl.storage.sdp_runtime import SdpState, SdpStateRow
    from fpl.validate.tactical_state import tactical_values

    from .test_prospective_points_v1 import _basic_db, _fixture, _player

    fixture = {**_fixture(501, 1, 2), "kickoff_time": (CUTOFF + timedelta(days=1)).isoformat()}
    con = _basic_db(
        players=[_player(11, 1001, 1, 1), _player(12, 1002, 4, 2)],
        fixtures=[fixture],
        history=[(1001, "GK", 1, 2, True), (1002, "FWD", 2, 1, False)],
    )
    rows = [
        SdpStateRow(
            "2026-27",
            2,
            400,
            club,
            opp,
            home,
            CUTOFF - timedelta(days=3),
            tactical_values(METRICS, METRICS),
            dict(METRICS),
            {
                "known_at": (CUTOFF - timedelta(days=2)).isoformat(),
                "provider": "pl_sdp",
                "payload_id": "synthetic",
                "payload_sha256": "a" * 64,
            },
        )
        for club, opp, home in ((101, 102, True), (102, 101, False))
    ]
    monkeypatch.setattr(sdp_runtime, "load_sdp_state", lambda *a, **k: SdpState(rows=rows))
    kwargs = {"as_of": CUTOFF, "season": "2026-27", "gw_from": 1, "gw_to": 1, "draws": 200}
    try:
        primary = predict_prospective_points(con, **kwargs)
        disabled = predict_prospective_points(
            con, **kwargs, football_environment_primary="disabled"
        )
        assert primary.shadow_incumbent is not None
        assert primary.shadow_incumbent.records == disabled.records
        assert primary.shadow_incumbent.team_records == disabled.team_records
        assert primary.records != disabled.records
        assert disabled.football_environment_provenance is None
        assert disabled.shadow_incumbent is None
        for component in (
            "minutes",
            "goals",
            "assists",
            "saves",
            "defensive_contribution",
            "bonus",
        ):
            assert primary.component_names[component] == disabled.component_names[component]
        for side in primary.team_records:
            opponent = next(r for r in primary.team_records if r.team_code != side.team_code)
            assert side.probability_clean_sheet == opponent.goals_for_distribution[0]
        provenance = primary.football_environment_provenance
        assert provenance["decisions"][0]["selector"] == "SDP_PRIMARY"
        assert provenance["gk_saves_shadow"][0]["mode"] == "shadow_only"
        assert provenance["gk_saves_shadow"][0]["conditional_saves_pmf"] is not None
        repeated = predict_prospective_points(con, **kwargs)
        assert repeated.records == primary.records
        fail = predict_prospective_points(
            con, **kwargs, sdp_refresh_failure="synthetic HTTP failure"
        )
        assert fail.records == disabled.records
        assert (
            fail.football_environment_provenance["decisions"][0]["selector"]
            == "SDP_SOURCE_FALLBACK"
        )
        artifact = build_prospective_artifact(
            replace(primary, worktree_clean=True, commit_sha="a" * 40, archive_sha256="b" * 64)
        )
        retained = json.loads(artifact.manifest.component_modes["football_environment.provenance"])
        assert retained["fpl_snapshot_known_at"] <= CUTOFF.isoformat()
        assert retained["model_sha256"] == load_football_environment().frozen_parameters_sha256
    finally:
        con.close()


@pytest.mark.parametrize("change", ["cup", "club", "duplicate"])
def test_real_identity_revision_falls_back_without_fuzzy_resolution(tmp_path, change):
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        body = con.execute(
            "SELECT CAST(payload AS VARCHAR) FROM raw_pl_sdp_payload "
            "WHERE endpoint='matches' ORDER BY fetched_at DESC LIMIT 1"
        ).fetchone()[0]
        payload = json.loads(body)
        if change == "cup":
            for match in payload["content"]:
                match["competitionId"] = 1
        elif change == "club":
            payload["content"][-1]["teams"][0]["team"]["id"] = 999
        else:
            payload["content"].append(payload["content"][-1])
        sdp.land_payload(con, _raw("matches", payload, CUTOFF - timedelta(hours=1)), season=SEASON)
        primary, report, incumbent = selection(con)
        assert primary == incumbent
        assert report["decisions"][0]["selector"] == "SDP_IDENTITY_FALLBACK"


def test_malformed_latest_source_does_not_resurrect_older_valid_stats(tmp_path):
    with initialise(tmp_path / "db.duckdb") as con:
        seed(con)
        sdp.land_payload(
            con,
            _raw("match_stats", {"broken": []}, CUTOFF - timedelta(hours=1), 300103),
            season=SEASON,
            sdp_match_id=300103,
        )
        primary, report, incumbent = selection(con)
        assert primary == incumbent
        assert report["decisions"][0]["selector"] == "SDP_INCOMPLETE_FALLBACK"


def test_pre_deadline_refresh_exception_still_attempts_incumbent(monkeypatch, tmp_path):
    from fpl.jobs import pre_deadline_forecast as job

    monkeypatch.setattr(job.prospective_points_v1, "_git_worktree_clean", lambda *a: True)

    def offline(**kwargs):
        raise OSError("synthetic unavailable SDP")

    calls = []
    monkeypatch.setattr(job.daily_pl_sdp, "run", offline)
    monkeypatch.setattr(job.prospective_points_v1, "main", lambda args: calls.append(args) or 0)
    assert (
        job.main(
            [
                "--db",
                str(tmp_path / "operational.duckdb"),
                "--runs",
                str(tmp_path / "runs"),
                "--gw-from",
                "4",
                "--gw-to",
                "8",
                "--output",
                str(tmp_path / "points.jsonl"),
            ]
        )
        == 0
    )
    assert "--sdp-refresh-failure" in calls[0]
    assert "--refresh-report" in calls[0]
