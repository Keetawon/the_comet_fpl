"""Synthetic-only counterfactual data plumbing; no historical forecast or score."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest

from fpl.config import repo_root
from fpl.football_configuration import load_football_environment
from fpl.models import sdp_environment
from fpl.models.sdp_environment import FrozenSdpModel, select_environments
from fpl.storage.sdp_runtime import SdpState, SdpStateRow
from fpl.validate.metrics import poisson_pmf
from fpl.validate.sdp_counterfactual import (
    EVIDENCE_CLASS,
    SOURCE_PATH,
    SOURCE_SHA256,
    FrozenCounterfactualInputs,
    bind_counterfactual_selector,
    load_counterfactual_inputs,
    select_counterfactual_environments,
)
from fpl.validate.tactical_state import tactical_values

SEASON = "2026-27"
EVIDENCE = datetime(2026, 9, 8, 1, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 8, tzinfo=UTC)
EARLIER = datetime(2026, 9, 6, tzinfo=UTC)
KICKOFF = datetime(2026, 8, 31, tzinfo=UTC)
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


def state(*, known: datetime = datetime(2026, 9, 7, 12, tzinfo=UTC)) -> SdpState:
    return SdpState(
        rows=[
            SdpStateRow(
                SEASON,
                2,
                400,
                code,
                other,
                home,
                KICKOFF,
                tactical_values(METRICS, METRICS),
                dict(METRICS),
                {
                    "known_at": known.isoformat(),
                    "fetched_at": known.isoformat(),
                    "provider": "pl_sdp",
                    "payload_id": "synthetic",
                    "payload_sha256": "a" * 64,
                    "fpl_metadata_known_at": known.isoformat(),
                },
            )
            for code, other, home in ((3, 8, True), (8, 3, False))
        ],
        expected={(SEASON, 400, code): KICKOFF for code in (3, 8)},
    )


def inputs(source: SdpState | None = None) -> FrozenCounterfactualInputs:
    model = FrozenSdpModel.load(repo_root(), load_football_environment(), EVIDENCE)
    return FrozenCounterfactualInputs(
        SEASON, EVIDENCE, state() if source is None else source, model, "b" * 64
    )


def kwargs(source: SdpState, *, cutoff: datetime = CUTOFF) -> dict[str, Any]:
    return {
        "state": source,
        "model": FrozenSdpModel.load(repo_root(), load_football_environment(), EVIDENCE),
        "model_failure": None,
        "cutoff": cutoff,
        "season": SEASON,
        "schedule": pl.DataFrame(
            [
                {
                    "season": SEASON,
                    "fixture": 500,
                    "gw": 3,
                    "team_id": 1,
                    "opponent_team_id": 2,
                    "was_home": True,
                    "kickoff_time": cutoff + timedelta(days=1),
                }
            ]
        ),
        "team_map": {1: 3, 2: 8},
        "incumbent": {(500, code): poisson_pmf(rate) for code, rate in ((3, 1.5), (8, 1.1))},
    }


def select(
    frozen: FrozenCounterfactualInputs,
    args: dict[str, Any],
    gameweeks: dict[int, int] | None = None,
) -> Any:
    return select_counterfactual_environments(
        frozen,
        **args,
        current_fixture_gameweeks={400: 2, 500: 3} if gameweeks is None else gameweeks,
    )


def test_exact_selector_and_frozen_inference_parity_when_already_eligible() -> None:
    source = state()
    args = kwargs(source)
    wanted_pmfs, wanted_report = select_environments(**args)
    actual_pmfs, actual_report = select(inputs(source), args)
    assert actual_pmfs == wanted_pmfs
    assert {k: v for k, v in actual_report.items() if k != "counterfactual"} == wanted_report
    assert actual_report["decisions"][0]["selector"] == "SDP_PRIMARY"


def test_only_declared_source_model_availability_is_waived_without_retimestamping() -> None:
    source = state()
    frozen = inputs(source)
    args = kwargs(
        SdpState(expected=source.expected, global_failure="SDP_MISSING_FALLBACK"), cutoff=EARLIER
    )
    args.update(model=None, model_failure="SDP_MISSING_FALLBACK")
    _, report = select(frozen, args)
    assert report["decisions"][0]["selector"] == "SDP_PRIMARY"
    assert report["cutoff"] == EARLIER.isoformat()
    assert report["model_known_at"] == frozen.model.payload["known_at"]
    assert report["source_versions"][0]["known_at"] == source.rows[0].provenance["known_at"]
    assert report["source_versions"][0]["fpl_metadata_known_at"] > report["cutoff"]
    assert report["counterfactual"]["evidence_class"] == EVIDENCE_CLASS
    assert report["counterfactual"]["later_known_source_versions"] == 1
    assert report["counterfactual"]["strict_model_failure"] == "SDP_MISSING_FALLBACK"
    assert source.rows[0].provenance == frozen.state.rows[0].provenance
    assert report["decisions"][0]["environment"]["provenance"]["cutoff"] == EARLIER.isoformat()


def test_target_match_same_gw_future_gw_and_future_kickoff_never_enter_history() -> None:
    source = state()
    expected = select(inputs(source), kwargs(source))
    extra = [
        replace(r, fixture=fid, gw=gw, kickoff=kickoff, metrics={"expectedGoals": 99999.0})
        for fid, gw, kickoff in (
            (500, 3, KICKOFF),
            (501, 3, KICKOFF),
            (502, 4, KICKOFF),
            (503, 1, CUTOFF),
        )
        for r in source.rows
    ]
    changed = SdpState(
        rows=[*source.rows, *extra],
        expected={
            **source.expected,
            **{r.key: r.kickoff for r in extra},
        },
    )
    actual = select(inputs(changed), kwargs(changed), {400: 2, 500: 3, 501: 3, 502: 4, 503: 1})
    assert actual[0] == expected[0]
    assert actual[1]["source_versions"] == expected[1]["source_versions"]
    assert actual[1]["health"] == expected[1]["health"]


@pytest.mark.parametrize(
    "reason",
    [
        "SDP_INCOMPLETE_FALLBACK",
        "SDP_SCHEMA_FALLBACK",
        "SDP_IDENTITY_FALLBACK",
        "SDP_MISSING_FALLBACK",
    ],
)
def test_health_missing_and_identity_fallbacks_remain_whole_fixture(reason: str) -> None:
    source = state()
    bad = SdpState(expected=source.expected, failures={(SEASON, 400): reason})
    args = kwargs(source)
    chosen, report = select(inputs(bad), args)
    assert chosen == args["incumbent"]
    assert report["decisions"][0]["selector"] == reason


def test_model_schema_failure_is_not_waived() -> None:
    args = kwargs(state())
    args["model_failure"] = "SDP_SCHEMA_FALLBACK"
    chosen, report = select(inputs(), args)
    assert chosen == args["incumbent"]
    assert report["decisions"][0]["selector"] == "SDP_SCHEMA_FALLBACK"


def test_no_history_global_failure_and_unresolved_target_identity_keep_incumbent() -> None:
    for source, team_map, reason in (
        (SdpState(), {1: 3, 2: 8}, "SDP_MISSING_FALLBACK"),
        (SdpState(global_failure="SDP_SCHEMA_FALLBACK"), {1: 3, 2: 8}, "SDP_SCHEMA_FALLBACK"),
        (state(), {1: 3}, "SDP_IDENTITY_FALLBACK"),
    ):
        args = kwargs(source)
        args["team_map"] = team_map
        chosen, report = select(inputs(source), args)
        assert chosen == args["incumbent"]
        assert report["decisions"][0]["selector"] == reason


def test_later_fpl_club_or_kickoff_cannot_replace_cutoff_known_identity() -> None:
    source = state()
    wrong = replace(source.rows[0], opponent_team_code=99)
    bad = SdpState(rows=[wrong, source.rows[1]], expected=source.expected)
    chosen, report = select(inputs(bad), kwargs(source))
    assert chosen == kwargs(source)["incumbent"]
    assert report["decisions"][0]["selector"] == "SDP_IDENTITY_FALLBACK"


def test_exact_current_fixture_gameweek_mismatch_fails_closed() -> None:
    source = state()
    bad = SdpState(rows=[replace(r, gw=1) for r in source.rows], expected=source.expected)
    _, report = select(inputs(bad), kwargs(source))
    assert report["decisions"][0]["selector"] == "SDP_IDENTITY_FALLBACK"
    with pytest.raises(ValueError, match="lacks cutoff-known gameweek"):
        select(inputs(source), kwargs(source), {500: 3})


def test_original_latest_health_policy_never_revives_older_valid_version() -> None:
    source = state()
    rejected_latest = SdpState(
        rows=[],
        expected=source.expected,
        failures={(SEASON, 400): "SDP_INCOMPLETE_FALLBACK"},
    )
    _, report = select(inputs(rejected_latest), kwargs(source))
    assert report["decisions"][0]["selector"] == "SDP_INCOMPLETE_FALLBACK"
    assert not report["source_versions"]
    assert (
        "invalid_latest_never_revives_older_version" in report["counterfactual"]["version_policy"]
    )


def test_last_five_requirement_not_strengthened_to_all_history() -> None:
    source = state()
    historical = [
        replace(r, fixture=400 + n, gw=n, kickoff=CUTOFF - timedelta(days=10 - n))
        for n in range(1, 7)
        for r in source.rows
    ]
    required = {r.key: r.kickoff for r in historical}
    five = SdpState(
        rows=historical[2:], expected=required, failures={(SEASON, 401): "SDP_INCOMPLETE_FALLBACK"}
    )
    args = kwargs(five)
    args["schedule"] = args["schedule"].with_columns(pl.lit(7).alias("gw"))
    wanted = select_environments(**args)
    actual = select(inputs(five), args, {**{400 + n: n for n in range(1, 7)}, 500: 7})
    assert actual[0] == wanted[0]
    assert actual[1]["decisions"] == wanted[1]["decisions"]
    assert actual[1]["decisions"][0]["selector"] == "SDP_PRIMARY"


def test_frozen_state_model_and_source_hash_cannot_change() -> None:
    frozen = inputs()
    frozen.state.rows[0].provenance["known_at"] = CUTOFF.isoformat()
    with pytest.raises(ValueError, match="inputs changed"):
        select(frozen, kwargs(state()))
    frozen = inputs()
    frozen.model.payload["conversion_fit"]["conversion"] = 999
    with pytest.raises(ValueError, match="inputs changed"):
        frozen.verify()
    assert hashlib.sha256((repo_root() / SOURCE_PATH).read_bytes()).hexdigest() == SOURCE_SHA256


def test_model_parameters_cannot_be_overridden_at_adapter_construction() -> None:
    model = FrozenSdpModel.load(repo_root(), load_football_environment(), EVIDENCE)
    model.payload["conversion_fit"]["conversion"] = 999
    with pytest.raises(ValueError, match="unchanged frozen SDP model"):
        FrozenCounterfactualInputs(SEASON, EVIDENCE, state(), model, "b" * 64)


def test_scoped_binding_restored_after_success_and_failure() -> None:
    original = sdp_environment.select_environments
    frozen = inputs()
    with bind_counterfactual_selector(
        frozen, cutoff=CUTOFF, current_fixture_gameweeks={400: 2, 500: 3}
    ):
        assert sdp_environment.select_environments is not original
        result = sdp_environment.select_environments(**kwargs(state()))
        assert result[1]["counterfactual"]["evidence_class"] == EVIDENCE_CLASS
    assert sdp_environment.select_environments is original
    with pytest.raises(RuntimeError, match="test"):
        with bind_counterfactual_selector(
            frozen, cutoff=CUTOFF, current_fixture_gameweeks={400: 2, 500: 3}
        ):
            raise RuntimeError("test")
    assert sdp_environment.select_environments is original


def test_binding_rejects_different_cutoff_and_nonnumeric_identity() -> None:
    with bind_counterfactual_selector(
        inputs(), cutoff=CUTOFF, current_fixture_gameweeks={400: 2, 500: 3}
    ):
        with pytest.raises(ValueError, match="cannot change target cutoff"):
            sdp_environment.select_environments(**kwargs(state(), cutoff=EARLIER))
    with pytest.raises(ValueError, match="positive fixture/gameweek"):
        with bind_counterfactual_selector(
            inputs(), cutoff=CUTOFF, current_fixture_gameweeks={0: 3}
        ):
            pass


def test_factory_is_read_only_and_binds_connection_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fpl.validate import sdp_counterfactual

    db = tmp_path / "source.duckdb"
    duckdb.connect(str(db)).close()
    before = db.read_bytes()
    monkeypatch.setattr(sdp_counterfactual, "load_sdp_state", lambda *a, **k: state())
    with duckdb.connect(str(db), read_only=True) as con:
        frozen = load_counterfactual_inputs(
            con, repo=repo_root(), db_path=db, evidence_as_of=EVIDENCE, season=SEASON
        )
        assert frozen.source_db_sha256 == hashlib.sha256(before).hexdigest()
        with pytest.raises(ValueError, match="does not identify"):
            load_counterfactual_inputs(
                con,
                repo=repo_root(),
                db_path=tmp_path / "wrong.duckdb",
                evidence_as_of=EVIDENCE,
                season=SEASON,
            )
    assert db.read_bytes() == before


def test_future_model_training_frontier_and_evidence_time_rejected() -> None:
    frozen = inputs()
    with pytest.raises(ValueError, match="training frontier"):
        select(frozen, kwargs(state(), cutoff=datetime(2026, 5, 24, 15, tzinfo=UTC)))
    with pytest.raises(ValueError, match="actual past capture"):
        replace(frozen, evidence_as_of=datetime.now(UTC) + timedelta(days=1))


def test_real_player_entrypoint_disabled_and_incumbent_shadow_unchanged_on_synthetic_inputs() -> (
    None
):
    from fpl.jobs.prospective_points_v1 import predict_prospective_points

    from .test_prospective_points_v1 import _basic_db, _fixture, _player

    fixture = {**_fixture(501, 1, 2), "kickoff_time": (CUTOFF + timedelta(days=1)).isoformat()}
    con = _basic_db(
        players=[_player(11, 1001, 1, 1), _player(12, 1002, 4, 2), _player(13, 1003, 1, 2)],
        fixtures=[fixture],
        history=[(1001, "GK", 1, 2, True), (1002, "FWD", 2, 1, False), (1003, "GK", 2, 1, False)],
    )
    historical = [
        replace(
            r,
            season="2025-26",
            team_code=101 if r.was_home else 102,
            opponent_team_code=102 if r.was_home else 101,
            kickoff=datetime(2026, 5, 15, tzinfo=UTC),
        )
        for r in state().rows
    ]
    frozen = inputs(SdpState(rows=historical))
    args = {"as_of": CUTOFF, "season": SEASON, "gw_from": 1, "gw_to": 1, "draws": 200}
    try:
        baseline = predict_prospective_points(con, **args, football_environment_primary="disabled")
        with bind_counterfactual_selector(
            frozen, cutoff=CUTOFF, current_fixture_gameweeks={501: 1}
        ):
            result = predict_prospective_points(con, **args)
            disabled = predict_prospective_points(
                con, **args, football_environment_primary="disabled"
            )
        assert disabled.records == baseline.records
        assert disabled.team_records == baseline.team_records
        assert disabled.football_environment_provenance is None
        assert disabled.shadow_incumbent is None
        assert result.shadow_incumbent is not None
        assert result.shadow_incumbent.records == baseline.records
        assert result.shadow_incumbent.team_records == baseline.team_records
        assert result.records != baseline.records
        assert result.football_environment_provenance is not None
        assert (
            result.football_environment_provenance["counterfactual"]["evidence_class"]
            == EVIDENCE_CLASS
        )
        for component in (
            "minutes",
            "goals",
            "assists",
            "saves",
            "defensive_contribution",
            "bonus",
        ):
            assert result.component_names[component] == baseline.component_names[component]
        for side in result.team_records:
            opposite = next(r for r in result.team_records if r.team_code != side.team_code)
            assert side.probability_clean_sheet == opposite.goals_for_distribution[0]
    finally:
        con.close()
