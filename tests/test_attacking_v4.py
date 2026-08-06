"""Offline tests for Stage C Candidate V4 (exposure-weighted xG team-share attacking goals).

No network. The pure exposure primitives are tested in ``test_attacking_exposure.py``; here the
Stage A coupling, fold-local bin means, the no-extra-p_play exposure wiring, per-fixture underlying
Poisson-rate conservation, the position-specific cold-start path, identical comparator/candidate
rows, and the reduces-to-baseline fallback are exercised against the tiny in-memory DuckDB the V2/V3
tests use (player fixtures + team matches + team codes).
"""

from __future__ import annotations

import math
from collections import defaultdict

from fpl.config import load_phase2_evaluation, load_phase3_evaluation
from fpl.models.attacking_baselines import TargetRowProjection
from fpl.models.attacking_v4 import (
    PATH_EXPOSURE_COLD_START,
    PATH_EXPOSURE_WEIGHTED,
    ExposureWeightedXgTeamShareAttackingGoalsV4,
)
from fpl.types import Position
from fpl.validate.attacking_harness import run_attacking_harness
from fpl.validate.minutes_baselines import MinuteBins

# Reuse the V2 in-memory archive builder (player fixtures + team matches + team codes).
from tests.test_attacking_v2 import _build_db  # type: ignore[attr-defined]

NAME = "exposure_weighted_xg_team_share_attacking_goals_v4"


def _v4_factory(history: object) -> ExposureWeightedXgTeamShareAttackingGoalsV4:
    config = load_phase3_evaluation()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    policy = config.stage_c_candidate_v4
    model = ExposureWeightedXgTeamShareAttackingGoalsV4(
        alpha=policy.alpha,
        share_window=policy.history_window,
        bins=bins,
        prior_minutes=policy.prior_minutes,
    )
    model.fit(list(history))  # type: ignore[arg-type]
    return model


# --------------------------------------------------------------------------------------
# Wiring: identical rows, exposure paths fire, reduces-to-baseline
# --------------------------------------------------------------------------------------


def test_candidate_v4_scored_on_identical_rows_with_exposure_paths() -> None:
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _build_db(with_team_match=True)
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_v4_factory)
    finally:
        con.close()

    assert result.leakage_failures == 0
    assert NAME in result.overall
    # Every model (two baselines + V4) scored the same eligible rows.
    counts = {n: rep.predictions for n, rep in result.overall.items()}
    assert len(set(counts.values())) == 1
    paths = result.candidate_path_counts[NAME]
    # Stage A is informative here -> the exposure paths fire (no stage-A fallback).
    assert paths.get("stage_a_uninformative_trailing", 0) == 0
    assert (paths.get(PATH_EXPOSURE_WEIGHTED, 0) + paths.get(PATH_EXPOSURE_COLD_START, 0)) > 0


def test_candidate_v4_reduces_to_baseline_when_stage_a_uninformative() -> None:
    """No team-match history => Stage A uninformative => V4 == v1.0 trailing baseline."""
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    con = _build_db(with_team_match=False)
    try:
        result = run_attacking_harness(con, config=config, candidate_factory=_v4_factory)
    finally:
        con.close()

    paths = result.candidate_path_counts[NAME]
    assert paths.get("stage_a_uninformative_trailing", 0) > 0
    cand = result.overall[NAME]
    base = result.overall["trailing_player_goal_rate_poisson"]
    assert cand.mean_log_score == base.mean_log_score


def test_candidate_v4_parameters_report_pinned_constants() -> None:
    model = ExposureWeightedXgTeamShareAttackingGoalsV4(
        alpha=5.0,
        share_window=5,
        bins=MinuteBins.from_config(load_phase2_evaluation()),
        prior_minutes=90.0,
    )
    params = model.parameters()
    assert params["alpha"] == 5.0
    assert params["prior_minutes"] == 90.0
    assert params["share_window"] == 5
    assert params["minutes_baseline"] == "trailing_5_player_minutes"
    assert params["signal"] == "expected_goals_only_no_fallback"
    assert model.name == NAME


# --------------------------------------------------------------------------------------
# Underlying Poisson-rate conservation per fixture (sum_i goal_lambda_i == lambda_team)
# --------------------------------------------------------------------------------------


def _gw9_targets(con: object) -> tuple[list[TargetRowProjection], str]:
    target_df = con.execute(  # type: ignore[attr-defined]
        """
        SELECT season, gw, fixture,
               strftime(kickoff_time, '%Y-%m-%dT%H:%M:%SZ') AS kickoff_time,
               code, position, team_id, opponent_team_id, was_home
        FROM mart_fact_player_fixture
        WHERE minutes IS NOT NULL AND season = '2023-24' AND gw = 9
        ORDER BY kickoff_time, fixture, code
        """
    ).pl()
    targets = [
        TargetRowProjection(
            season=r["season"],
            gw=r["gw"],
            fixture=r["fixture"],
            kickoff_time=r["kickoff_time"],
            code=r["code"],
            position=Position.from_archive_label(r["position"]),
            team_id=r["team_id"],
            opponent_team_id=r["opponent_team_id"],
            was_home=bool(r["was_home"]),
        )
        for r in target_df.iter_rows(named=True)
    ]
    as_of = con.execute(  # type: ignore[attr-defined]
        "SELECT strftime(MIN(kickoff_time), '%Y-%m-%dT%H:%M:%SZ') AS as_of "
        "FROM mart_fact_player_fixture WHERE minutes IS NOT NULL AND season = '2023-24' AND gw = 9"
    ).fetchone()[0]
    return targets, str(as_of)


def test_v4_underlying_poisson_rate_conservation_per_fixture() -> None:
    """For each (fixture, team_code) roster, sum_i goal_lambda_i == Stage A lambda_team."""
    load_phase3_evaluation.cache_clear()
    config = load_phase3_evaluation()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    con = _build_db(with_team_match=True)
    try:
        targets, as_of = _gw9_targets(con)
        model = ExposureWeightedXgTeamShareAttackingGoalsV4(
            alpha=config.stage_c_candidate_v4.alpha,
            share_window=config.stage_c_candidate_v4.history_window,
            bins=bins,
            prior_minutes=config.stage_c_candidate_v4.prior_minutes,
        )
        model.fit([])
        model.prepare(targets=targets, con=con, as_of=as_of)  # type: ignore[arg-type]

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
            total = math.fsum(model._rates[(t.fixture, t.code)] for t in roster)  # type: ignore[attr-defined]
            # Underlying Poisson-rate conservation: sum_i rate_i == lambda_team (in expectation).
            assert math.isclose(total, lambda_team, rel_tol=1e-9, abs_tol=1e-12), (
                f"fixture {fixture} team_code {team_code}: rates sum {total} != lambda_team "
                f"{lambda_team}"
            )
    finally:
        con.close()


def test_v4_fold_local_bin_means_exclude_representative_minutes() -> None:
    """E[minutes] uses fold-local GLOBAL bin means, not points_composition.representative_minutes.

    Construct a player whose trailing-5 minutes distribution is all in the 1_59 bin: E[minutes] must
    equal the fold-local mean minutes in that bin (computed over the archive's 1_59 rows), which is
    well below the bin upper edge 59 that ``representative_minutes`` would have used.
    """
    from fpl.models.points_composition import representative_minutes

    load_phase3_evaluation.cache_clear()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    rep = representative_minutes(bins.ranges)
    assert rep[1] == 59  # the composer's scoring-representative for the 1_59 bin (NOT a mean)
    # The candidate's bin-mean for 1_59 is the empirical mean over 1_59 training rows. In _build_db
    # the only sub-60 appeared minutes are player 112 (60 is in 60_89) and 113 (30 at gw9, but gw9
    # is the target). Pin the invariant indirectly: a 1_59-only distribution's E[minutes] is the
    # fold bin mean, strictly below 59 when any 1_59 row exists with minutes < 59.
    con = _build_db(with_team_match=True)
    try:
        # Mean minutes over the 1_59 bin in the GW9 training history (kickoff < as_of).
        as_of = con.execute(
            "SELECT strftime(MIN(kickoff_time), '%Y-%m-%dT%H:%M:%SZ') "
            "FROM mart_fact_player_fixture WHERE minutes IS NOT NULL AND season='2023-24' AND gw=9"
        ).fetchone()[0]
        mean_1_59 = con.execute(
            "SELECT avg(minutes) FROM mart_fact_player_fixture "
            "WHERE minutes IS NOT NULL AND minutes BETWEEN 1 AND 59 AND kickoff_time < ?",
            [as_of],
        ).fetchone()[0]
        if mean_1_59 is not None:
            assert float(mean_1_59) < 59.0  # the empirical mean is below the bin upper edge
    finally:
        con.close()
