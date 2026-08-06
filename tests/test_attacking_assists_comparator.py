"""Offline tests for the Stage C assists DEVELOPMENT DIAGNOSTIC comparator.

No network. The comparator (``raw_per_appearance_xa_team_share_times_p_play``) mirrors the goals V3
architecture applied to assists: mean raw xA per appearance gated by the frozen
``trailing_5_player_minutes`` P(play) and renormalised to ``lambda_team * assist_rate``. We
exercise identical eligible rows, raw weighted / cold-start paths, stage-A-uninformative fallback,
and per-fixture underlying Poisson-rate conservation. The DB builder is shared with
``test_attacking_assists_v2`` (same assists columns).
"""

from __future__ import annotations

import math
from collections import defaultdict

from fpl.config import load_phase2_evaluation, load_phase3_stage_c_assists_evaluation
from fpl.models.attacking_assists_comparator import (
    PATH_RAW_COLD_START,
    PATH_RAW_WEIGHTED,
    RawPerAppearanceXaTeamSharePplayComparator,
)
from fpl.models.attacking_baselines import TargetRowProjection
from fpl.validate.attacking_assists_harness import run_assists_harness
from fpl.validate.minutes_baselines import MinuteBins
from tests.test_attacking_assists_v2 import _build_assists_db, _gw9_targets

NAME = "raw_per_appearance_xa_team_share_times_p_play"


def _comparator_factory(history: object) -> RawPerAppearanceXaTeamSharePplayComparator:
    bins = MinuteBins.from_config(load_phase2_evaluation())
    model = RawPerAppearanceXaTeamSharePplayComparator(
        alpha=5.0,
        share_window=5,
        bins=bins,
    )
    model.fit(list(history))  # type: ignore[arg-type]
    return model


def test_comparator_scored_on_identical_rows_with_raw_paths() -> None:
    load_phase3_stage_c_assists_evaluation.cache_clear()
    config = load_phase3_stage_c_assists_evaluation()
    con = _build_assists_db(with_team_match=True)
    try:
        result = run_assists_harness(con, config=config, candidate_factory=_comparator_factory)
    finally:
        con.close()

    assert result.leakage_failures == 0
    assert NAME in result.overall
    counts = {n: rep.predictions for n, rep in result.overall.items()}
    assert len(set(counts.values())) == 1  # identical eligible rows across all models
    paths = result.candidate_path_counts[NAME]
    assert paths.get("stage_a_uninformative_trailing", 0) == 0
    assert (paths.get(PATH_RAW_WEIGHTED, 0) + paths.get(PATH_RAW_COLD_START, 0)) > 0


def test_comparator_reduces_to_baseline_when_stage_a_uninformative() -> None:
    load_phase3_stage_c_assists_evaluation.cache_clear()
    config = load_phase3_stage_c_assists_evaluation()
    con = _build_assists_db(with_team_match=False)
    try:
        result = run_assists_harness(con, config=config, candidate_factory=_comparator_factory)
    finally:
        con.close()

    paths = result.candidate_path_counts[NAME]
    assert paths.get("stage_a_uninformative_trailing", 0) > 0
    cand = result.overall[NAME]
    base = result.overall["trailing_player_assist_rate_poisson"]
    assert cand.mean_log_score == base.mean_log_score


def test_comparator_parameters_report_pinned_constants() -> None:
    model = RawPerAppearanceXaTeamSharePplayComparator(
        alpha=5.0,
        share_window=5,
        bins=MinuteBins.from_config(load_phase2_evaluation()),
    )
    params = model.parameters()
    assert params["signal"] == "mean_raw_expected_assists_per_appearance_no_creativity_fallback"
    assert params["weight"] == "mean_xa_per_appearance_times_p_play"
    assert model.name == NAME


def test_comparator_underlying_poisson_rate_conservation_per_fixture() -> None:
    """For each roster, sum_i assist_lambda_i == lambda_team * fold_local_assist_rate."""
    load_phase3_stage_c_assists_evaluation.cache_clear()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    con = _build_assists_db(with_team_match=True)
    try:
        targets, as_of = _gw9_targets(con)
        model = RawPerAppearanceXaTeamSharePplayComparator(alpha=5.0, share_window=5, bins=bins)
        model.fit([])
        model.prepare(targets=targets, con=con, as_of=as_of)  # type: ignore[arg-type]

        _, _, _, assist_rate, _ = model._fold_history(con, as_of)  # type: ignore[attr-defined]
        team_code_map = model._team_code_map(con, "2023-24")  # type: ignore[attr-defined]
        stage_a, informative = model._fit_stage_a(con, as_of)  # type: ignore[attr-defined]
        assert informative

        by_team: dict[tuple[int, int], list[TargetRowProjection]] = defaultdict(list)
        for target in targets:
            team_code = team_code_map.get(target.team_id, -1)
            by_team[(target.fixture, team_code)].append(target)

        for (fixture, team_code), roster in by_team.items():
            if team_code < 0:
                continue
            opponent_code = team_code_map.get(roster[0].opponent_team_id, team_code)
            lambda_team = float(
                stage_a.rate_for(
                    {
                        "team_code": team_code,
                        "opponent_team_code": opponent_code,
                        "was_home": roster[0].was_home,
                    }
                )
            )
            team_assist_lambda = lambda_team * assist_rate
            total = math.fsum(model._rates[(t.fixture, t.code)] for t in roster)  # type: ignore[attr-defined]
            assert math.isclose(total, team_assist_lambda, rel_tol=1e-9, abs_tol=1e-12), (
                f"fixture {fixture} team_code {team_code}: assist rates sum {total} != "
                f"team_assist_lambda {team_assist_lambda}"
            )
    finally:
        con.close()
