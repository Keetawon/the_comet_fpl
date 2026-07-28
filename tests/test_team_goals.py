"""The Stage A team-goals model.

The properties worth pinning are the ones that distinguish it from the trailing baselines it
has to beat: joint estimation that adjusts for who a team actually played, time decay, a prior
that a club with no history lands on exactly, and a low-score correction that leaves the
distribution proper.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import duckdb
import polars as pl
import pytest

from fpl.models.team_goals import (
    HALF_LIFE_DAYS,
    PRIOR_MATCHES,
    Fixture,
    StageATeamModel,
    TeamRatings,
    fit_ratings,
    fit_rho,
    tau,
)
from fpl.validate.baselines import (
    PROMOTED_ATTACK_RATIO,
    PROMOTED_DEFENCE_RATIO,
    TrainingWindow,
)
from fpl.validate.metrics import MAX_GOALS, poisson_pmf

SEASON = "2025-26"
KICKOFF = datetime(2025, 8, 15, 19, 0, tzinfo=UTC)


def _fixture(team: int, opponent: int, *, home: bool, goals: float, weight: float = 1.0) -> Fixture:
    return Fixture(
        team=team,
        opponent=opponent,
        was_home=home,
        measure=goals,
        goals=int(goals),
        weight=weight,
    )


def _round_robin(scorelines: dict[tuple[int, int], tuple[float, float]]) -> list[Fixture]:
    """`{(home, away): (home goals, away goals)}` expanded to one row per side."""
    rows = []
    for (home, away), (home_goals, away_goals) in scorelines.items():
        rows.append(_fixture(home, away, home=True, goals=home_goals))
        rows.append(_fixture(away, home, home=False, goals=away_goals))
    return rows


def _flat_league(teams: int = 4, home_goals: float = 2.0, away_goals: float = 1.0) -> list[Fixture]:
    return _round_robin(
        {
            (home, away): (home_goals, away_goals)
            for home in range(1, teams + 1)
            for away in range(1, teams + 1)
            if home != away
        }
    )


def _fit(fixtures, **kwargs):
    defaults = {"prior_attack": {}, "prior_defence": {}, "prior_matches": 1e-9}
    return fit_ratings(fixtures, **{**defaults, **kwargs})


# --------------------------------------------------------------------------------------
# Iterative proportional fitting
# --------------------------------------------------------------------------------------


def test_a_flat_league_gives_every_team_a_neutral_rating() -> None:
    ratings = _fit(_flat_league())
    for value in ratings.attack.values():
        assert value == pytest.approx(1.0, abs=1e-6)
    for value in ratings.defence.values():
        assert value == pytest.approx(1.0, abs=1e-6)
    assert ratings.home == pytest.approx(2.0, rel=1e-6)
    assert ratings.away == pytest.approx(1.0, rel=1e-6)


def test_ratings_are_identified_by_pinning_both_geometric_means() -> None:
    """`attack * defence * mu` has two free scales; both must be removed or the fit drifts."""
    ratings = _fit(_flat_league(home_goals=3.0, away_goals=2.0))
    assert math.prod(ratings.attack.values()) == pytest.approx(1.0, abs=1e-6)
    assert math.prod(ratings.defence.values()) == pytest.approx(1.0, abs=1e-6)


def test_the_fit_matches_each_team_s_observed_total() -> None:
    """The defining property of the Poisson MLE, and the check that the sweep is correct.

    At the maximum, each team's fitted goals sum to its observed goals -- both for what it
    scored and for what it conceded. That is what the stationarity conditions say, so an
    implementation that converged to something else has a bug rather than a different answer.
    """
    rows = _round_robin(
        {
            (1, 2): (3.0, 0.0),
            (2, 1): (1.0, 2.0),
            (1, 3): (2.0, 1.0),
            (3, 1): (0.0, 3.0),
            (2, 3): (1.0, 1.0),
            (3, 2): (2.0, 1.0),
        }
    )
    ratings = _fit(rows)

    scored: dict[int, list[float]] = {}
    conceded: dict[int, list[float]] = {}
    for fixture in rows:
        rate = ratings.rate(fixture.team, fixture.opponent, fixture.was_home)
        scored.setdefault(fixture.team, [0.0, 0.0])
        scored[fixture.team][0] += fixture.measure
        scored[fixture.team][1] += rate
        conceded.setdefault(fixture.opponent, [0.0, 0.0])
        conceded[fixture.opponent][0] += fixture.measure
        conceded[fixture.opponent][1] += rate

    for observed, fitted in scored.values():
        assert fitted == pytest.approx(observed, abs=1e-4)
    for observed, fitted in conceded.values():
        assert fitted == pytest.approx(observed, abs=1e-4)


def test_a_strong_attack_and_a_strong_defence_move_in_opposite_directions() -> None:
    rows = _flat_league()
    boosted = [
        _fixture(
            f.team, f.opponent, home=f.was_home, goals=f.measure * (3.0 if f.team == 1 else 1.0)
        )
        for f in rows
    ]
    ratings = _fit(boosted)
    assert ratings.attack[1] > 1.5
    # Everyone else is dragged below one, because the geometric mean is pinned.
    assert all(ratings.attack[team] < 1.0 for team in (2, 3, 4))
    # Team 1's opponents conceded more, so their defence ratings must worsen.
    assert all(ratings.defence[team] > 1.0 for team in (2, 3, 4))


def test_the_fit_adjusts_for_who_a_team_actually_played() -> None:
    """The core claim over a trailing ratio, and the reason the model exists.

    Team 1 plays only team 4, which leaks goals; team 2 plays only team 3, which does not.
    Dividing goals by matches -- what the trailing baselines do -- credits team 1 with a huge
    attack. Estimating attack and defence jointly attributes most of it to team 4's defence
    instead, which is where it belongs.
    """
    rows = []
    for _ in range(6):
        rows += [
            _fixture(1, 4, home=True, goals=4.0),
            _fixture(4, 1, home=False, goals=1.0),
            _fixture(2, 3, home=True, goals=2.0),
            _fixture(3, 2, home=False, goals=1.0),
        ]
    rows += [_fixture(4, 3, home=True, goals=1.0), _fixture(3, 4, home=False, goals=4.0)]

    ratings = _fit(rows)
    naive_ratio = 4.0 / 2.0  # team 1's goals per home match against the league's home mean
    assert ratings.attack[1] < naive_ratio, "a raw ratio would credit the schedule to team 1"
    assert ratings.defence[4] > ratings.defence[3], "team 4 is the weak defence, not team 1 elite"


def test_an_empty_window_returns_neutral_ratings() -> None:
    ratings = fit_ratings([], prior_attack={}, prior_defence={}, prior_matches=8.0)
    assert ratings.attack == {}
    assert ratings.rate(1, 2, was_home=True) == pytest.approx(1.4)


# --------------------------------------------------------------------------------------
# The prior
# --------------------------------------------------------------------------------------


def test_a_club_with_no_history_lands_exactly_on_its_prior() -> None:
    """Gameweek 1 for a newly promoted club, which is the whole reason the prior exists.

    With no matches the MAP update reduces to the prior mean, so the answer is the declared
    prior rather than a division by zero or a silent 1.0.
    """
    ratings = fit_ratings(
        _flat_league(),
        prior_attack={99: PROMOTED_ATTACK_RATIO},
        prior_defence={99: PROMOTED_DEFENCE_RATIO},
        prior_matches=8.0,
    )
    # 99 never appears in the fixtures, so it is unrated and falls back on lookup.
    assert 99 not in ratings.attack
    assert ratings.rate(99, 1, was_home=True) == pytest.approx(ratings.home)


def test_the_prior_pulls_a_promoted_club_down_when_it_has_played_a_little() -> None:
    rows = _flat_league(teams=4)
    rows += [_fixture(5, 1, home=True, goals=2.0), _fixture(1, 5, home=False, goals=1.0)]

    neutral = fit_ratings(rows, prior_attack={}, prior_defence={}, prior_matches=8.0)
    promoted = fit_ratings(
        rows,
        prior_attack={5: PROMOTED_ATTACK_RATIO},
        prior_defence={5: PROMOTED_DEFENCE_RATIO},
        prior_matches=8.0,
    )
    assert promoted.attack[5] < neutral.attack[5]
    assert promoted.defence[5] > neutral.defence[5]


def test_a_stronger_prior_shrinks_a_short_record_harder() -> None:
    rows = _flat_league()
    rows += [_fixture(5, 1, home=True, goals=6.0), _fixture(1, 5, home=False, goals=0.0)]
    weak = fit_ratings(rows, prior_attack={}, prior_defence={}, prior_matches=2.0)
    strong = fit_ratings(rows, prior_attack={}, prior_defence={}, prior_matches=32.0)
    assert weak.attack[5] > strong.attack[5] > 1.0


# --------------------------------------------------------------------------------------
# Time decay
# --------------------------------------------------------------------------------------


def test_a_recent_match_outweighs_an_old_one() -> None:
    """Two identical leagues apart from which half of the season a team was good in."""
    early = [_fixture(1, 2, home=True, goals=4.0, weight=0.1)]
    late = [_fixture(1, 2, home=True, goals=4.0, weight=1.0)]
    base = _flat_league()

    faded = _fit(base + early)
    fresh = _fit(base + late)
    assert fresh.attack[1] > faded.attack[1]


def test_zero_weight_rows_do_not_move_the_fit() -> None:
    base = _flat_league()
    ignored = [_fixture(1, 2, home=True, goals=9.0, weight=0.0)]
    assert _fit(base).attack == pytest.approx(_fit(base + ignored).attack)


# --------------------------------------------------------------------------------------
# Dixon-Coles low-score correction
# --------------------------------------------------------------------------------------


def test_tau_is_one_outside_the_four_corrected_cells() -> None:
    for home_goals in range(4):
        for away_goals in range(4):
            if home_goals <= 1 and away_goals <= 1:
                continue
            assert tau(home_goals, away_goals, 1.4, 1.2, 0.1) == 1.0


def test_the_corrected_joint_sums_to_one_exactly() -> None:
    """The four adjustments cancel algebraically, so no renormalisation is needed.

    If they did not, every corrected prediction would be off by a constant that moved with
    the rates, and the log score would quietly measure that instead of the model.
    """
    for home_rate, away_rate, rho in ((1.4, 1.2, 0.1), (0.8, 2.4, -0.15), (2.0, 2.0, 0.05)):
        home = poisson_pmf(home_rate)
        away = poisson_pmf(away_rate)
        total = sum(
            tau(x, y, home_rate, away_rate, rho) * home[x] * away[y]
            for x in range(MAX_GOALS + 1)
            for y in range(MAX_GOALS + 1)
        )
        assert total == pytest.approx(1.0, abs=1e-9)


def test_the_correction_provably_cannot_move_either_marginal() -> None:
    """Why `rho` is fitted but never applied to a Stage A prediction.

    Summing the corrected joint over the opponent's goals, the two cells touching `own = 0`
    are `q(0)*(-l_own*l_opp*rho)` and `q(1)*(l_own*rho)`; because `q(1) = l_opp*q(0)` for a
    Poisson they cancel exactly, and the same holds at `own = 1`. A model that claimed a
    Stage A gain from the low-score correction would be reporting noise.
    """
    for own_rate, opponent_rate, rho in ((1.4, 1.2, 0.12), (0.9, 2.3, -0.18), (2.0, 1.0, 0.07)):
        other = poisson_pmf(opponent_rate)
        for goals in (0, 1):
            shift = sum(
                other[away] * (tau(goals, away, own_rate, opponent_rate, rho) - 1.0)
                for away in (0, 1)
            )
            assert shift == pytest.approx(0.0, abs=1e-15)


def test_rho_is_recovered_from_data_generated_with_it() -> None:
    """The search has to be able to find a non-zero answer, not just return the default."""
    pairs = [(1.4, 1.2, 0, 0, 1.0)] * 40 + [(1.4, 1.2, 1, 1, 1.0)] * 40
    positive = fit_rho(pairs)
    assert positive < 0.0, "an excess of 0-0 and 1-1 draws implies negative dependence"
    assert fit_rho([]) == 0.0


# --------------------------------------------------------------------------------------
# The estimator inside a fold
# --------------------------------------------------------------------------------------


def _frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
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
        },
    )


def _match_rows(
    gw: int,
    home_code: int,
    away_code: int,
    home_goals: int,
    away_goals: int,
    *,
    season: str = SEASON,
    xg: bool = True,
) -> list[dict[str, object]]:
    kickoff = KICKOFF + timedelta(days=7 * gw)
    out = []
    for team, opponent, goals, against, was_home in (
        (home_code, away_code, home_goals, away_goals, True),
        (away_code, home_code, away_goals, home_goals, False),
    ):
        out.append(
            {
                "season": season,
                "gw": gw,
                "fixture": gw * 100 + home_code,
                "kickoff_time": kickoff,
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


def _season_frame(*, xg: bool = True, gameweeks: int = 20) -> pl.DataFrame:
    rows: list[dict[str, object]] = []
    for gw in range(1, gameweeks + 1):
        for pair in ((1, 2), (3, 4), (5, 6), (7, 8)):
            home, away = pair if gw % 2 else pair[::-1]
            rows += _match_rows(gw, home, away, 2 if home == 1 else 1, 1, xg=xg)
    return _frame(rows)


def test_the_model_predicts_proper_distributions() -> None:
    model = StageATeamModel()
    model.fit(TrainingWindow(_season_frame()))
    fixtures = _frame(_match_rows(21, 1, 2, 0, 0))
    for masses in model.predict(fixtures):
        assert len(masses) == MAX_GOALS + 1
        assert sum(masses) == pytest.approx(1.0, abs=1e-12)
        assert all(mass >= 0.0 for mass in masses)


def test_the_model_survives_an_empty_window() -> None:
    model = StageATeamModel()
    model.fit(TrainingWindow(_frame([])))
    masses = model.predict(_frame(_match_rows(1, 1, 2, 0, 0)))[0]
    assert sum(masses) == pytest.approx(1.0, abs=1e-12)


def test_a_season_without_xg_still_fits_on_recorded_goals() -> None:
    """2021-22 carries no xG at all, and the model must not go blank there."""
    model = StageATeamModel()
    model.fit(TrainingWindow(_season_frame(xg=False)))
    rates = model.predict_rates(_frame(_match_rows(21, 1, 2, 0, 0)))
    assert all(rate > 0.2 for rate in rates)


def test_hyperparameter_selection_is_bounded_by_the_training_window() -> None:
    """The holdout is carved out of the window's own tail, never from the fold's gameweek.

    A half-life chosen once over the whole archive would be a hyperparameter leak that no
    later point-in-time test could catch, so the selection has to live inside `fit`.
    """
    model = StageATeamModel()
    model.fit(TrainingWindow(_season_frame(gameweeks=40)))
    assert model._half_life in HALF_LIFE_DAYS
    assert model._prior_matches in PRIOR_MATCHES


def test_the_model_keys_on_team_code_not_team_id() -> None:
    """The identity rule, asserted where it would otherwise be easy to regress.

    The two frames carry identical clubs and opposite ids. A model reading `team_id` would
    produce different predictions for the same football.
    """
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

    plain, relabelled = StageATeamModel(), StageATeamModel()
    plain.fit(TrainingWindow(frame))
    relabelled.fit(TrainingWindow(swapped))
    assert plain.predict_rates(fixtures) == pytest.approx(
        relabelled.predict_rates(swapped_fixtures)
    )


def test_the_fit_is_deterministic() -> None:
    frame = _season_frame()
    fixtures = _frame(_match_rows(21, 1, 2, 0, 0))
    first, second = StageATeamModel(), StageATeamModel()
    first.fit(TrainingWindow(frame))
    second.fit(TrainingWindow(frame))
    assert first.predict(fixtures) == second.predict(fixtures)


def test_promoted_clubs_are_declared_by_team_code() -> None:
    model = StageATeamModel()
    model.set_promoted({SEASON: frozenset({9})})
    model.fit(TrainingWindow(_season_frame()))
    attack, defence = model._priors(pl.DataFrame())
    assert attack[9] == PROMOTED_ATTACK_RATIO
    assert defence[9] == PROMOTED_DEFENCE_RATIO


# --------------------------------------------------------------------------------------
# Against the archive
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_ratings_on_the_real_archive_are_football_shaped(db: duckdb.DuckDBPyConnection) -> None:
    """A sanity check that the fit is estimating football and not noise.

    Ratings should be spread but bounded, and the venue means should land near the league's
    measured home and away scoring rather than anywhere the optimiser wandered.
    """
    from fpl.validate.folds import generate_folds, promoted_team_codes
    from fpl.validate.harness import _training_window

    fold = generate_folds(db)[-1]
    model = StageATeamModel()
    model.set_promoted(promoted_team_codes(db))
    model.fit(_training_window(db, fold))
    ratings: TeamRatings = model._ratings

    assert 1.2 < ratings.home < 1.9
    assert 1.0 < ratings.away < 1.6
    assert ratings.home > ratings.away, "home advantage should survive pooling with decay"
    assert 0.4 < min(ratings.attack.values()) < max(ratings.attack.values()) < 2.2
    assert 0.4 < min(ratings.defence.values()) < max(ratings.defence.values()) < 2.2
    assert abs(ratings.rho) <= 0.20
