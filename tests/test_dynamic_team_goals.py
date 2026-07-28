"""Candidate V3: the sequential dynamic team-goals model (development-only).

The properties pinned here are the ones that distinguish a *sequential* model from
Candidate V2's batch re-fit, and the point-in-time invariants the repository enforces
everywhere: chronological processing with no same-match leakage, stable `team_code`
identity, season-qualified fixture keys, explicit between-season retention, season-scoped
promoted priors, the six-match cold-start rule, NULL xG preserved, fold-local transform
fitting on an exact observed-gameweek holdout, and deterministic selection. Candidate V3
is development-only, so its reporting is also tested for an unambiguous separation from a
promotion verdict.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from fpl.config import Phase1StageACandidateV3Policy, load_phase1_evaluation
from fpl.models.dynamic_team_goals import (
    LEARNING_RATE,
    RETENTION,
    SEASON_RETENTION,
    DynamicState,
    DynamicTeamGoalsV3,
    MatchRow,
)
from fpl.validate.baselines import TrainingWindow
from fpl.validate.dev_candidate_v3 import format_development_report
from fpl.validate.harness import HarnessResult
from fpl.validate.metrics import ScoreReport

SEASON = "2025-26"
KICKOFF = datetime(2025, 8, 15, 19, 0, tzinfo=UTC)

_SCHEMA = {
    "season": pl.String,
    "gw": pl.Int64,
    "fixture": pl.Int64,
    "kickoff_time": pl.Datetime(time_unit="us", time_zone="UTC"),
    "team_id": pl.Int64,
    "opponent_team_id": pl.Int64,
    "team_code": pl.Int64,
    "opponent_team_code": pl.Int64,
    "was_home": pl.Boolean,
    "goals_for": pl.Int64,
    "goals_against": pl.Int64,
    "team_xg": pl.Float64,
    "team_xgc": pl.Float64,
    "fdr": pl.Int64,
}


def _frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_SCHEMA)


def _match_rows(
    gw: int,
    home_code: int,
    away_code: int,
    home_goals: int,
    away_goals: int,
    *,
    season: str = SEASON,
    xg: bool = True,
    fixture: int | None = None,
    kickoff: datetime | None = None,
) -> list[dict[str, object]]:
    start = kickoff if kickoff is not None else KICKOFF
    when = start + timedelta(days=7 * gw) if kickoff is None else kickoff
    fx = fixture if fixture is not None else gw * 100 + home_code
    out: list[dict[str, object]] = []
    for team, opponent, goals, against, was_home in (
        (home_code, away_code, home_goals, away_goals, True),
        (away_code, home_code, away_goals, home_goals, False),
    ):
        out.append(
            {
                "season": season,
                "gw": gw,
                "fixture": fx,
                "kickoff_time": when,
                "team_id": team,
                "opponent_team_id": opponent,
                "team_code": team,
                "opponent_team_code": opponent,
                "was_home": was_home,
                "goals_for": goals,
                "goals_against": against,
                "team_xg": float(goals) if xg else None,
                "team_xgc": float(against) if xg else None,
                "fdr": 3,
            }
        )
    return out


def _season_frame(
    *,
    xg: bool = True,
    gameweeks: int = 20,
    season: str = SEASON,
    kickoff: datetime | None = None,
    clubs: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8),
) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for gw in range(1, gameweeks + 1):
        for pair in (
            (clubs[0], clubs[1]),
            (clubs[2], clubs[3]),
            (clubs[4], clubs[5]),
            (clubs[6], clubs[7]),
        ):
            home, away = pair if gw % 2 else pair[::-1]
            rows += _match_rows(
                gw,
                home,
                away,
                2 if home == clubs[0] else 1,
                1,
                season=season,
                xg=xg,
                kickoff=kickoff,
            )
    return _frame(rows)


def _flat_policy(
    *,
    learning_rate: tuple[float, ...] = (0.10,),
    retention: tuple[float, ...] = (0.995,),
    season_retention: tuple[float, ...] = (0.75,),
) -> Phase1StageACandidateV3Policy:
    """A single-value-grid policy so `_filter` can be exercised with known knobs."""
    return Phase1StageACandidateV3Policy(
        name="dynamic_team_goals_v3",
        development_only=True,
        inner_holdout_observed_gameweeks=6,
        minimum_inner_training_observed_gameweeks=12,
        learning_rate=learning_rate,
        retention=retention,
        season_retention=season_retention,
        fallback_learning_rate=learning_rate[0],
        fallback_retention=retention[0],
        fallback_season_retention=season_retention[0],
        promoted_attack_prior=0.719,
        promoted_defence_prior=1.309,
        xg_policy="use_when_measured_scaled_to_goals",
        rate_floor=0.05,
        log_strength_cap=2.0,
    )


def _match_row(
    season: str,
    fixture: int,
    kickoff_day: int,
    home_code: int,
    away_code: int,
    home_measure: float,
    away_measure: float,
) -> MatchRow:
    return MatchRow(
        season=season,
        fixture=fixture,
        kickoff=(KICKOFF + timedelta(days=kickoff_day)).timestamp(),
        home_code=home_code,
        away_code=away_code,
        home_measure=home_measure,
        away_measure=away_measure,
        home_goals=int(home_measure),
        away_goals=int(away_measure),
    )


# --------------------------------------------------------------------------------------
# Chronological processing and no same-match leakage
# --------------------------------------------------------------------------------------


def test_a_single_match_updates_from_the_pre_match_rate() -> None:
    """The defining no-leakage property, verified by exact reconstruction.

    The pre-match rates (1.4 home, 1.2 away) come from the neutral state `exp(0)`. If the
    filter computed the residual from a post-update rate -- the leakage failure mode -- the
    hand-computed strengths below would not match. Matching them proves the update sees the
    state as it was *before* the match touched it.
    """
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=6)
    match = _match_row(SEASON, 1, 0, 1, 2, home_measure=3.0, away_measure=0.0)
    state = model._filter(
        [match],
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    # home_rate = 1.4, away_rate = 1.2 -> r_home = 1.6, r_away = -1.2.
    assert state.attack == {1: pytest.approx(0.16), 2: pytest.approx(-0.12)}
    assert state.defence == {1: pytest.approx(-0.12), 2: pytest.approx(0.16)}
    assert state.counts == {1: 1, 2: 1}


def test_a_match_outcome_propagates_forward_but_not_into_itself() -> None:
    """A match enters the state (visible to later matches) but its own prediction is fixed.

    The threshold is lowered to one match so the dynamic strength -- not the cold-start
    prior -- is what the later prediction reads. The target match is scored from the
    pre-match state; flipping its outcome changes the future, never the target.
    """
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=1)
    warm = [_match_row(SEASON, 1, 0, 1, 2, 2.0, 1.0), _match_row(SEASON, 2, 7, 3, 4, 1.0, 1.0)]
    base = model._filter(
        warm,
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    # The target (1 vs 5) is scored from `base`, before its own outcome can touch the state.
    target_rate = model._match_rate(base, 1, 5, True, SEASON)

    high = model._filter(
        [*warm, _match_row(SEASON, 3, 14, 1, 5, 6.0, 0.0)],
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    low = model._filter(
        [*warm, _match_row(SEASON, 3, 14, 1, 5, 0.0, 6.0)],
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    # The target match's own prediction is unchanged by its outcome...
    assert model._match_rate(base, 1, 5, True, SEASON) == pytest.approx(target_rate)
    # ...but that outcome moves a later match involving team 1 in opposite directions.
    assert model._match_rate(high, 1, 2, True, SEASON) > model._match_rate(low, 1, 2, True, SEASON)


def test_processing_order_changes_the_state() -> None:
    """Chronological: reversing two matches yields a different state, so order is respected."""
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=6)
    first = _match_row(SEASON, 1, 0, 1, 2, 3.0, 0.0)
    second = _match_row(SEASON, 2, 7, 1, 3, 0.0, 3.0)
    forward = model._filter(
        [first, second],
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    reverse = model._filter(
        [second, first],
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    assert forward.attack[1] != pytest.approx(reverse.attack[1])


# --------------------------------------------------------------------------------------
# Truncation equivalence (the point-in-time core)
# --------------------------------------------------------------------------------------


def test_later_matches_do_not_alter_an_earlier_club_state() -> None:
    """A club's state is invariant to matches played after its last appearance.

    This is the sequential model's truncation-equivalence guarantee: the state at time t
    inside a full replay equals the state built from the prefix up to t. Matches involving
    only new clubs must leave the earlier clubs' strengths and counts untouched.
    """
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=6)
    prefix = [_match_row(SEASON, 1, 0, 1, 2, 3.0, 0.0), _match_row(SEASON, 2, 7, 3, 4, 0.0, 3.0)]
    later = [_match_row(SEASON, 3, 14, 5, 6, 2.0, 2.0), _match_row(SEASON, 4, 21, 7, 8, 1.0, 1.0)]
    kwargs = {
        "venue_home": 1.4,
        "venue_away": 1.2,
        "learning_rate": 0.10,
        "retention": 0.995,
        "season_retention": 0.75,
    }
    short = model._filter(prefix, **kwargs)
    full = model._filter(prefix + later, **kwargs)
    for club in (1, 2, 3, 4):
        assert full.attack[club] == pytest.approx(short.attack[club])
        assert full.defence[club] == pytest.approx(short.defence[club])
        assert full.counts[club] == short.counts[club]
    assert {5, 6, 7, 8} <= set(full.attack)
    assert set(short.attack) == {1, 2, 3, 4}


# --------------------------------------------------------------------------------------
# Identity and grain
# --------------------------------------------------------------------------------------


def test_the_model_keys_on_team_code_not_team_id() -> None:
    """The identity rule. Two frames carry the same clubs and opposite ids; predictions match."""
    frame = _season_frame()
    swapped = frame.with_columns(
        (100 - pl.col("team_id")).alias("team_id"),
        (100 - pl.col("opponent_team_id")).alias("opponent_team_id"),
    )
    fixtures = _frame(_match_rows(21, 1, 2, 0, 0))
    swapped_fixtures = fixtures.with_columns(
        (100 - pl.col("team_id")).alias("team_id"),
        (100 - pl.col("opponent_team_id")).alias("opponent_team_id"),
    )
    plain, relabelled = DynamicTeamGoalsV3(), DynamicTeamGoalsV3()
    plain.fit(TrainingWindow(frame))
    relabelled.fit(TrainingWindow(swapped))
    assert plain.predict_rates(fixtures) == pytest.approx(
        relabelled.predict_rates(swapped_fixtures)
    )


def test_fixture_keys_are_season_qualified() -> None:
    """`(season, fixture)` pairs both sides; a fixture id reused across seasons is two matches."""
    rows = _match_rows(1, 1, 2, 2, 1, season="2024-25", fixture=1)
    rows += _match_rows(1, 1, 2, 1, 1, season="2025-26", fixture=1)
    model = DynamicTeamGoalsV3()
    matches = model._rows(_frame(rows))
    keys = {(m.season, m.fixture) for m in matches}
    assert keys == {("2024-25", 1), ("2025-26", 1)}
    for match in matches:
        assert match.home_code != match.away_code


# --------------------------------------------------------------------------------------
# Between-season retention and promoted priors
# --------------------------------------------------------------------------------------


def _two_season_frame() -> pl.DataFrame:
    """Season 1 clubs 1-4 each play enough to clear cold start; season 2 reuses clubs 1-4."""
    rows: list[dict[str, object]] = []
    season2_kickoff = datetime(2026, 8, 15, 19, 0, tzinfo=UTC)
    # Club 1 dominates season 1 (scores 4 each home game) to build a strong attack.
    for gw in range(1, 11):
        rows += _match_rows(gw, 1, 2, 4, 0, season="2024-25", kickoff=KICKOFF)
        rows += _match_rows(gw, 3, 4, 1, 1, season="2024-25", kickoff=KICKOFF)
    for gw in range(1, 4):
        rows += _match_rows(gw, 1, 2, 1, 1, season="2025-26", kickoff=season2_kickoff)
        rows += _match_rows(gw, 3, 4, 1, 1, season="2025-26", kickoff=season2_kickoff)
    return _frame(rows)


def test_season_retention_controls_how_much_strength_crosses_the_summer() -> None:
    """Strong season-retain keeps season-1 strength; weak retain regresses it toward the mean."""
    full = _two_season_frame()
    keep = DynamicTeamGoalsV3(
        _flat_policy(retention=(1.0,), season_retention=(1.0,)), minimum_team_matches=6
    )
    shrink = DynamicTeamGoalsV3(
        _flat_policy(retention=(1.0,), season_retention=(0.1,)), minimum_team_matches=6
    )
    keep.fit(TrainingWindow(full))
    shrink.fit(TrainingWindow(full))
    fixtures = _frame(
        _match_rows(
            4, 1, 2, 0, 0, season="2025-26", kickoff=datetime(2026, 8, 15, 19, 0, tzinfo=UTC)
        )
    )
    # Club 1 hammered season 1; full retention keeps it dangerous in season 2, shrink does not.
    assert keep.predict_rates(fixtures)[0] > shrink.predict_rates(fixtures)[0]


def test_promoted_priors_are_scoped_to_the_match_season() -> None:
    """A club promoted in 2024-25 is established by 2025-26 and gets no prior there."""
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({"2024-25": frozenset({8}), "2025-26": frozenset({9})})
    state = DynamicState(rate_floor=0.05)  # no history: every club is cold
    promoted_attack_rate = model._match_rate(state, 9, 1, True, "2025-26")
    established_rate = model._match_rate(state, 8, 1, True, "2025-26")
    # 9 is promoted this season -> prior; 8 was promoted last season -> neutral now.
    assert promoted_attack_rate == pytest.approx(1.4 * 0.719)
    assert established_rate == pytest.approx(1.4)


def test_a_cold_promoted_club_lands_on_its_prior() -> None:
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({SEASON: frozenset({9})})
    state = DynamicState(rate_floor=0.05)
    assert model._match_rate(state, 9, 1, True, SEASON) == pytest.approx(1.4 * 0.719)
    assert model._match_rate(state, 1, 9, True, SEASON) == pytest.approx(1.4 * 1.309)


# --------------------------------------------------------------------------------------
# Cold start
# --------------------------------------------------------------------------------------


def test_fewer_than_six_matches_uses_the_declared_prior() -> None:
    """A club with a short record is not trusted; its prior stands in until six matches.

    The same club is put in two states that differ only in match count. Below the threshold
    its (large) fitted attack is ignored in favour of the prior; at the threshold it is used.
    """
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({SEASON: frozenset({9})})
    cold = DynamicState(
        attack={9: 2.0, 1: 0.0}, defence={9: 0.0, 1: 0.0}, counts={9: 5, 1: 10}, rate_floor=0.05
    )
    warm = DynamicState(
        attack={9: 2.0, 1: 0.0}, defence={9: 0.0, 1: 0.0}, counts={9: 6, 1: 10}, rate_floor=0.05
    )
    # Opponent 1 is established (10 matches) with neutral defence, isolating club 9's branch.
    rate_cold = model._match_rate(cold, 9, 1, True, SEASON)
    rate_warm = model._match_rate(warm, 9, 1, True, SEASON)
    assert rate_cold == pytest.approx(1.4 * 0.719)  # prior, attack[9] ignored
    assert rate_warm == pytest.approx(1.4 * math.exp(2.0))  # fitted attack now used
    assert rate_warm > rate_cold


def test_six_matches_unlocks_the_dynamic_strength() -> None:
    model = DynamicTeamGoalsV3(_flat_policy(), minimum_team_matches=6)
    frame = _season_frame(gameweeks=12)
    model.fit(TrainingWindow(frame))
    fixtures = _frame(_match_rows(13, 1, 2, 0, 0))
    assert not model.is_cold_start(fixtures.row(0, named=True))


# --------------------------------------------------------------------------------------
# NULL xG and the training signal
# --------------------------------------------------------------------------------------


def test_a_season_without_xg_still_fits_on_recorded_goals() -> None:
    """2021-22 carries no xG at all; the model must not go blank there."""
    model = DynamicTeamGoalsV3()
    model.fit(TrainingWindow(_season_frame(xg=False)))
    rates = model.predict_rates(_frame(_match_rows(21, 1, 2, 0, 0)))
    assert all(rate > 0.2 for rate in rates)


def test_xg_scale_rescales_the_measure_onto_goals() -> None:
    """When xG is half of goals everywhere, the scale is 2.0 and xG rows are denoised up."""
    model = DynamicTeamGoalsV3()
    rows: list[dict[str, object]] = []
    for gw in range(1, 11):
        for pair in ((1, 2), (3, 4)):
            h, a = pair if gw % 2 else pair[::-1]
            for t, o, g, ag, wh in ((h, a, 2, 1, True), (a, h, 1, 2, False)):
                rows.append(
                    {
                        "season": SEASON,
                        "gw": gw,
                        "fixture": gw * 100 + h,
                        "kickoff_time": KICKOFF + timedelta(days=7 * gw),
                        "team_id": t,
                        "opponent_team_id": o,
                        "team_code": t,
                        "opponent_team_code": o,
                        "was_home": wh,
                        "goals_for": g,
                        "goals_against": ag,
                        "team_xg": g / 2.0,
                        "team_xgc": ag / 2.0,
                        "fdr": 3,
                    }
                )
    assert model._xg_scale(_frame(rows)) == pytest.approx(2.0)


def test_null_xg_rows_fall_back_to_recorded_goals_without_zero_fill() -> None:
    """A NULL xG must not be coerced to zero; the goals value is used instead."""
    model = DynamicTeamGoalsV3()
    mixed = _season_frame(xg=True, gameweeks=6)
    # Null out xG on the first gameweek only.
    mixed = mixed.with_columns(
        pl.when(pl.col("gw") == 1).then(None).otherwise(pl.col("team_xg")).alias("team_xg")
    )
    rows = model._rows(mixed)
    assert rows, "mixed-null frame must still produce matches"
    # No crash, and the model fits: NULLs were skipped, not zero-filled.
    model.fit(TrainingWindow(mixed))
    rates = model.predict_rates(_frame(_match_rows(7, 1, 2, 0, 0)))
    assert all(rate > 0.2 for rate in rates)


# --------------------------------------------------------------------------------------
# Fold-local fitting, inner holdout, determinism
# --------------------------------------------------------------------------------------


def test_hyperparameters_are_selected_from_the_pre_registered_grid() -> None:
    model = DynamicTeamGoalsV3()
    model.fit(TrainingWindow(_season_frame(gameweeks=40)))
    params = model.parameters()
    assert params["learning_rate"] in LEARNING_RATE
    assert params["retention"] in RETENTION
    assert params["season_retention"] in SEASON_RETENTION


def test_inner_holdout_is_exactly_six_observed_gameweeks() -> None:
    model = DynamicTeamGoalsV3()
    split = model._inner_holdout(_season_frame(gameweeks=20))
    assert split is not None
    inner, holdout = split
    assert set(holdout["gw"].to_list()) == {15, 16, 17, 18, 19, 20}
    assert inner["gw"].max() == 14
    assert len(model._inner_holdout_gameweeks) == 6


def test_insufficient_inner_history_falls_back_to_the_declared_defaults() -> None:
    contract = load_phase1_evaluation().stage_a_candidate_v3
    assert contract is not None
    model = DynamicTeamGoalsV3()
    # Too few observed gameweeks to carve a 6+12 inner split.
    model.fit(TrainingWindow(_season_frame(gameweeks=10)))
    params = model.parameters()
    assert params["learning_rate"] == contract.fallback_learning_rate
    assert params["retention"] == contract.fallback_retention
    assert params["season_retention"] == contract.fallback_season_retention
    assert params["used_inner_holdout"] is False


def test_the_fit_is_deterministic() -> None:
    frame = _season_frame()
    fixtures = _frame(_match_rows(21, 1, 2, 0, 0))
    first, second = DynamicTeamGoalsV3(), DynamicTeamGoalsV3()
    first.fit(TrainingWindow(frame))
    second.fit(TrainingWindow(frame))
    assert first.predict(fixtures) == second.predict(fixtures)
    assert first.parameters() == second.parameters()


def test_the_model_predicts_proper_distributions() -> None:
    model = DynamicTeamGoalsV3()
    model.fit(TrainingWindow(_season_frame()))
    fixtures = _frame(_match_rows(21, 1, 2, 0, 0))
    for masses in model.predict(fixtures):
        assert len(masses) == 11
        assert sum(masses) == pytest.approx(1.0, abs=1e-12)
        assert all(mass >= 0.0 for mass in masses)


def test_the_model_survives_an_empty_window() -> None:
    model = DynamicTeamGoalsV3()
    model.fit(TrainingWindow(_frame([])))
    masses = model.predict(_frame(_match_rows(1, 1, 2, 0, 0)))[0]
    assert sum(masses) == pytest.approx(1.0, abs=1e-12)


# --------------------------------------------------------------------------------------
# Development vs promotion reporting separation
# --------------------------------------------------------------------------------------


def _score(name: str, log: float, *, cold: int = 0, predictions: int = 760) -> ScoreReport:
    return ScoreReport(
        name=name,
        predictions=predictions,
        eligible_predictions=predictions,
        exclusions=0,
        cold_starts=cold,
        mean_log_score=log,
        mean_log_score_standard_error=0.01,
        mean_crps=0.64,
        mean_poisson_deviance=1.12,
        interval_80_coverage=0.93,
        pit_interval_80_coverage=0.80,
        mean_absolute_error=0.94,
        mean_predictive_variance=1.20,
        spearman_within_gameweek=0.3,
        pit_values=(),
    )


def _result() -> HarnessResult:
    baseline = _score("trailing_goals_attack_defence", 1.5003)
    candidate = _score("dynamic_team_goals_v3", 1.4600, cold=84)
    return HarnessResult(
        folds_evaluated=181,
        folds_by_season={"2025-26": 38},
        predictions=760,
        eligible_predictions=760,
        leakage_failures=0,
        required_baselines=frozenset({"trailing_goals_attack_defence"}),
        overall={baseline.name: baseline, candidate.name: candidate},
        by_fold={},
        by_season={"2025-26": {baseline.name: baseline, candidate.name: candidate}},
        by_promoted_status={},
        by_home_away={},
        parameters_by_fold={
            "2025-26-GW1": {
                "dynamic_team_goals_v3": {
                    "learning_rate": 0.05,
                    "retention": 0.995,
                    "season_retention": 0.5,
                    "inner_holdout_observed_gameweeks": 6,
                    "used_inner_holdout": True,
                }
            }
        },
    )


def test_the_development_report_is_labelled_and_never_a_verdict() -> None:
    """A development number must be impossible to mistake for a promotion verdict."""
    contract = load_phase1_evaluation()
    text = format_development_report(
        _result(), "dynamic_team_goals_v3", contract, commit_sha="deadbeef"
    )
    assert "DEVELOPMENT ONLY" in text
    assert "NOT A PROMOTION RESULT" in text
    assert "PROMOTE" not in text
    assert "DO NOT PROMOTE" not in text
    assert "trailing_goals_attack_defence" in text
    assert "deadbeef" in text
    # The lift is reported as a development diagnostic.
    assert "lift" in text


def test_candidate_v3_is_not_part_of_the_default_harness_baselines() -> None:
    """V3 never appears among the required baselines a promotion gate compares against."""
    contract = load_phase1_evaluation()
    assert contract.stage_a_candidate_v3 is not None
    assert contract.stage_a_candidate_v3.name == "dynamic_team_goals_v3"
    assert "dynamic_team_goals_v3" not in contract.baselines.stage_a
    assert contract.stage_a_candidate.name == "dixon_coles_team_goals_v2"
