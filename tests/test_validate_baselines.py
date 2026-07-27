"""The five Stage A baselines.

Fitted on hand-built training windows so each property is isolated: shrinkage, multiplicative
combination, null preservation, the cold-start definition. The archive-backed tests at the end
check the two behaviours that only real data can show -- that the xG baseline degenerates in
seasons without xG, and that promotion is applied to the clubs that actually came up.
"""

from __future__ import annotations

import math

import duckdb
import polars as pl
import pytest

from fpl.config import load_phase1_evaluation
from fpl.validate.baselines import (
    PROMOTED_ATTACK_RATIO,
    PROMOTED_DEFENCE_RATIO,
    SHRINKAGE_MATCHES,
    LeagueHomeAwayGoals,
    NaiveFdr,
    PromotedTeamPooledPrior,
    TrailingGoalsAttackDefence,
    TrailingXgAttackDefence,
    TrainingWindow,
    baseline_names,
    build_baselines,
)
from fpl.validate.folds import promoted_team_ids
from fpl.validate.metrics import MAX_GOALS, expected_goals

COLUMNS = (
    "season",
    "gw",
    "fixture",
    "team_id",
    "opponent_team_id",
    "was_home",
    "goals_for",
    "goals_against",
    "team_xg",
    "team_xgc",
    "fdr",
)


def _row(
    *,
    season: str = "2025-26",
    gw: int = 1,
    fixture: int = 1,
    team_id: int = 1,
    opponent_team_id: int = 2,
    was_home: bool = True,
    goals_for: int | None = 1,
    goals_against: int | None = 1,
    team_xg: float | None = 1.0,
    team_xgc: float | None = 1.0,
    fdr: int | None = 3,
) -> dict[str, object]:
    return {
        "season": season,
        "gw": gw,
        "fixture": fixture,
        "team_id": team_id,
        "opponent_team_id": opponent_team_id,
        "was_home": was_home,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "team_xg": team_xg,
        "team_xgc": team_xgc,
        "fdr": fdr,
    }


def _frame(rows: list[dict[str, object]]) -> pl.DataFrame:
    schema = {
        "season": pl.String,
        "gw": pl.Int64,
        "fixture": pl.Int64,
        "team_id": pl.Int64,
        "opponent_team_id": pl.Int64,
        "was_home": pl.Boolean,
        "goals_for": pl.Int64,
        "goals_against": pl.Int64,
        "team_xg": pl.Float64,
        "team_xgc": pl.Float64,
        "fdr": pl.Int64,
    }
    return pl.DataFrame(rows, schema=schema)


def _window(rows: list[dict[str, object]]) -> TrainingWindow:
    return TrainingWindow(_frame(rows))


def _balanced_league(goals_home: int = 2, goals_away: int = 1, teams: int = 4) -> list[dict]:
    """Every team plays every other home and away, all with the same scoreline.

    A deliberately flat league: every attack and defence rating must come out at 1.0, so any
    later test that moves a rating is measuring the thing it changed and nothing else.
    """
    rows = []
    fixture = 0
    for home in range(1, teams + 1):
        for away in range(1, teams + 1):
            if home == away:
                continue
            fixture += 1
            rows.append(
                _row(
                    fixture=fixture,
                    team_id=home,
                    opponent_team_id=away,
                    was_home=True,
                    goals_for=goals_home,
                    goals_against=goals_away,
                    team_xg=float(goals_home),
                    team_xgc=float(goals_away),
                )
            )
            rows.append(
                _row(
                    fixture=fixture,
                    team_id=away,
                    opponent_team_id=home,
                    was_home=False,
                    goals_for=goals_away,
                    goals_against=goals_home,
                    team_xg=float(goals_away),
                    team_xgc=float(goals_home),
                )
            )
    return rows


# --------------------------------------------------------------------------------------
# The contract's roster
# --------------------------------------------------------------------------------------


def test_every_contracted_stage_a_baseline_is_implemented() -> None:
    """The harness may not quietly drop a comparator the contract pinned before fitting."""
    contracted = load_phase1_evaluation().baselines.stage_a
    assert set(contracted) <= baseline_names()


def test_baselines_are_built_in_a_fixed_order_with_unique_names() -> None:
    names = [baseline.name for baseline in build_baselines()]
    assert len(names) == len(set(names))
    assert names == [baseline.name for baseline in build_baselines()]


@pytest.mark.parametrize("baseline", build_baselines(), ids=lambda b: b.name)
def test_every_baseline_returns_proper_distributions(baseline) -> None:
    baseline.fit(_window(_balanced_league()))
    fixtures = _frame([_row(team_id=1, opponent_team_id=2, was_home=True)])
    distributions = baseline.predict(fixtures)
    assert len(distributions) == 1
    masses = distributions[0]
    assert len(masses) == MAX_GOALS + 1
    assert math.isclose(sum(masses), 1.0, rel_tol=1e-12)
    assert all(mass >= 0.0 for mass in masses)


@pytest.mark.parametrize("baseline", build_baselines(), ids=lambda b: b.name)
def test_every_baseline_survives_an_empty_training_window(baseline) -> None:
    """Fold one of a fresh season has no history; a baseline must fall back, not crash."""
    baseline.fit(TrainingWindow(_frame([])))
    distributions = baseline.predict(_frame([_row()]))
    assert math.isclose(sum(distributions[0]), 1.0, rel_tol=1e-12)


# --------------------------------------------------------------------------------------
# League intercept
# --------------------------------------------------------------------------------------


def test_league_baseline_learns_the_home_and_away_means() -> None:
    baseline = LeagueHomeAwayGoals()
    baseline.fit(_window(_balanced_league(goals_home=2, goals_away=1)))
    home, away = baseline.predict_rates(_frame([_row(was_home=True), _row(was_home=False)]))
    assert home == pytest.approx(2.0)
    assert away == pytest.approx(1.0)


def test_league_baseline_gives_every_team_the_same_rate() -> None:
    """It is an intercept: team identity must not enter it at all."""
    baseline = LeagueHomeAwayGoals()
    baseline.fit(_window(_balanced_league()))
    rates = baseline.predict_rates(
        _frame([_row(team_id=t, opponent_team_id=(t % 4) + 1) for t in (1, 2, 3, 4)])
    )
    assert len(set(rates)) == 1


# --------------------------------------------------------------------------------------
# Trailing attack/defence
# --------------------------------------------------------------------------------------


def test_a_flat_league_produces_neutral_ratings() -> None:
    baseline = TrailingGoalsAttackDefence()
    baseline.fit(_window(_balanced_league(goals_home=2, goals_away=1)))
    (rate,) = baseline.predict_rates(_frame([_row(was_home=True)]))
    assert rate == pytest.approx(2.0, rel=1e-9)


def test_a_strong_attack_raises_the_rate_and_a_strong_defence_lowers_it() -> None:
    rows = _balanced_league(goals_home=2, goals_away=1)
    # Team 1 scores four every time it plays at home; team 2 concedes nothing at home.
    for row in rows:
        if row["team_id"] == 1 and row["was_home"]:
            row["goals_for"] = 6
        if row["team_id"] == 2 and row["was_home"]:
            row["goals_against"] = 0

    baseline = TrailingGoalsAttackDefence()
    baseline.fit(_window(rows))
    neutral, strong_attack, strong_defence = baseline.predict_rates(
        _frame(
            [
                _row(team_id=3, opponent_team_id=4, was_home=True),
                _row(team_id=1, opponent_team_id=4, was_home=True),
                _row(team_id=3, opponent_team_id=2, was_home=True),
            ]
        )
    )
    assert strong_attack > neutral
    assert strong_defence < neutral


def test_ratings_combine_multiplicatively() -> None:
    """`lambda = mu_venue x attack x defence`, exactly.

    Measured on this archive `attack x opponent defence` correlates 0.439 with goals scored
    against 0.070 for `attack - opponent defence`; subtraction also discards level
    information and can go negative, which inverts anything downstream that multiplies by it.
    """
    rows = _balanced_league(goals_home=2, goals_away=1)
    for row in rows:
        if row["team_id"] == 1 and row["was_home"]:
            row["goals_for"] = 6
        if row["team_id"] == 2 and row["was_home"]:
            row["goals_against"] = 0

    baseline = TrailingGoalsAttackDefence()
    baseline.fit(_window(rows))
    base, attack_only, defence_only, both = baseline.predict_rates(
        _frame(
            [
                _row(team_id=3, opponent_team_id=4, was_home=True),
                _row(team_id=1, opponent_team_id=4, was_home=True),
                _row(team_id=3, opponent_team_id=2, was_home=True),
                _row(team_id=1, opponent_team_id=2, was_home=True),
            ]
        )
    )
    assert both == pytest.approx(base * (attack_only / base) * (defence_only / base), rel=1e-9)


def test_shrinkage_pulls_a_short_record_toward_the_league_mean() -> None:
    """`(n*observed + k*mu) / (n + k)` with k = 6 matches.

    A five-match average has a Poisson standard error near 0.541 goals against a true
    between-team spread of 0.440, so an unshrunk rating is mostly noise. This asserts the
    exact weight rather than just the direction, because the weight is the model.
    """
    rows = _balanced_league(goals_home=2, goals_away=2)
    # Team 5 appears once, scoring six. Its rating must not reflect that.
    rows.append(
        _row(fixture=99, team_id=5, opponent_team_id=1, was_home=True, goals_for=6, goals_against=2)
    )
    rows.append(
        _row(
            fixture=99,
            team_id=1,
            opponent_team_id=5,
            was_home=False,
            goals_for=2,
            goals_against=6,
        )
    )

    baseline = TrailingGoalsAttackDefence()
    baseline.fit(_window(rows))
    (rate,) = baseline.predict_rates(_frame([_row(team_id=5, opponent_team_id=3, was_home=True)]))

    # Arithmetic done here from the rows rather than read off the baseline, so the exact
    # shrinkage weight is pinned and not merely re-derived from the implementation.
    home_mean = (24.0 + 6.0) / 13.0  # 12 balanced home rows at 2 goals, plus team 5's six
    away_mean = (24.0 + 2.0) / 13.0
    league = (home_mean + away_mean) / 2.0
    attack_5 = ((6.0 + SHRINKAGE_MATCHES * league) / (1 + SHRINKAGE_MATCHES)) / league
    defence_3 = ((12.0 + SHRINKAGE_MATCHES * league) / (6 + SHRINKAGE_MATCHES)) / league
    assert rate == pytest.approx(home_mean * attack_5 * defence_3, rel=1e-9)

    # The point of the weight: one six-goal match must not become a rating of three times
    # the league mean. Six notional average matches outvote the single observed one.
    assert 6.0 / league > 2.7
    assert attack_5 < 1.35


def test_an_unseen_team_falls_back_to_a_neutral_rating() -> None:
    baseline = TrailingGoalsAttackDefence()
    baseline.fit(_window(_balanced_league(goals_home=2, goals_away=1)))
    (rate,) = baseline.predict_rates(_frame([_row(team_id=99, opponent_team_id=98, was_home=True)]))
    assert rate == pytest.approx(2.0)


def test_rates_are_floored_above_zero() -> None:
    """A zero rate would make any goal infinitely surprising."""
    rows = _balanced_league(goals_home=2, goals_away=1)
    for row in rows:
        if row["team_id"] == 1:
            row["goals_for"] = 0
        if row["opponent_team_id"] == 1:
            row["goals_against"] = 0
    baseline = TrailingGoalsAttackDefence()
    baseline.fit(_window(rows))
    rates = baseline.predict_rates(_frame([_row(team_id=1, opponent_team_id=2, was_home=True)]))
    assert all(rate >= 0.05 for rate in rates)


def test_the_xg_baseline_reads_xg_and_the_goals_baseline_reads_goals() -> None:
    """The two differ in nothing but the measure, which is what makes the comparison clean."""
    rows = _balanced_league(goals_home=2, goals_away=1)
    # Team 1 scores heavily but its xG says otherwise -- the two baselines must disagree.
    for row in rows:
        if row["team_id"] == 1 and row["was_home"]:
            row["goals_for"] = 6
            row["team_xg"] = 2.0

    fixtures = _frame([_row(team_id=1, opponent_team_id=3, was_home=True)])

    goals_baseline = TrailingGoalsAttackDefence()
    goals_baseline.fit(_window(rows))
    xg_baseline = TrailingXgAttackDefence()
    xg_baseline.fit(_window(rows))

    assert goals_baseline.predict_rates(fixtures)[0] > xg_baseline.predict_rates(fixtures)[0]


def test_null_xg_rows_are_dropped_not_treated_as_zero() -> None:
    """`preserve_nulls`. 2021-22 has no xG at all and 2022-23 none before GW16.

    Coercing an unmeasured match to zero invents a goalless performance and drags the team's
    rating down; dropping it leaves the rating to be estimated from what was measured. The
    two give materially different answers, so the distinction is not cosmetic.

    Team 1 plays six, scoring 2 at home and 1 away, and its three away matches lose their xG.
    Under the drop rule its attack is estimated from three matches at 2.0; under a zero
    coercion it is estimated from six averaging 1.0.
    """
    rows = _balanced_league(goals_home=2, goals_away=1)
    with_nulls = [dict(row) for row in rows]
    with_zeros = [dict(row) for row in rows]
    for null_row, zero_row in zip(with_nulls, with_zeros, strict=True):
        if null_row["team_id"] == 1 and not null_row["was_home"]:
            null_row["team_xg"] = None
            null_row["team_xgc"] = None
            zero_row["team_xg"] = 0.0
            zero_row["team_xgc"] = 0.0

    fixtures = _frame([_row(team_id=1, opponent_team_id=3, was_home=True)])
    dropped = TrailingXgAttackDefence()
    dropped.fit(_window(with_nulls))
    zeroed = TrailingXgAttackDefence()
    zeroed.fit(_window(with_zeros))

    league = 1.5  # (2 home + 1 away) / 2; goals_for is untouched, so venue means are too
    attack_from_three = ((6.0 + SHRINKAGE_MATCHES * league) / (3 + SHRINKAGE_MATCHES)) / league
    attack_from_six_with_zeros = (
        (6.0 + SHRINKAGE_MATCHES * league) / (6 + SHRINKAGE_MATCHES)
    ) / league

    assert dropped.predict_rates(fixtures)[0] == pytest.approx(2.0 * attack_from_three, rel=1e-9)
    assert zeroed.predict_rates(fixtures)[0] == pytest.approx(
        2.0 * attack_from_six_with_zeros, rel=1e-9
    )
    assert dropped.predict_rates(fixtures)[0] > zeroed.predict_rates(fixtures)[0]


def test_a_window_with_no_xg_at_all_leaves_ratings_neutral() -> None:
    """2021-22. The xG baseline must degenerate to the venue mean, not to zero goals."""
    rows = [dict(row) for row in _balanced_league(goals_home=2, goals_away=1)]
    for row in rows:
        row["team_xg"] = None
        row["team_xgc"] = None

    baseline = TrailingXgAttackDefence()
    baseline.fit(_window(rows))
    home, away = baseline.predict_rates(_frame([_row(was_home=True), _row(was_home=False)]))
    assert home == pytest.approx(2.0)
    assert away == pytest.approx(1.0)


# --------------------------------------------------------------------------------------
# FDR
# --------------------------------------------------------------------------------------


def test_fdr_baseline_learns_a_rate_per_difficulty_and_venue() -> None:
    rows = []
    for index, (fdr, home_goals) in enumerate([(2, 3), (5, 1)], start=1):
        for repeat in range(4):
            rows.append(
                _row(
                    fixture=index * 100 + repeat,
                    team_id=1,
                    opponent_team_id=2,
                    was_home=True,
                    goals_for=home_goals,
                    fdr=fdr,
                )
            )
    baseline = NaiveFdr()
    baseline.fit(_window(rows))
    easy, hard = baseline.predict_rates(
        _frame([_row(fdr=2, was_home=True), _row(fdr=5, was_home=True)])
    )
    assert easy == pytest.approx(3.0)
    assert hard == pytest.approx(1.0)


def test_fdr_baseline_falls_back_when_the_rating_is_missing_or_unseen() -> None:
    baseline = NaiveFdr()
    baseline.fit(_window(_balanced_league(goals_home=2, goals_away=1)))
    missing, unseen = baseline.predict_rates(
        _frame([_row(fdr=None, was_home=True), _row(fdr=1, was_home=True)])
    )
    assert missing == pytest.approx(2.0)
    assert unseen == pytest.approx(2.0)


# --------------------------------------------------------------------------------------
# Promoted-club prior
# --------------------------------------------------------------------------------------


def test_promoted_prior_only_applies_to_clubs_that_actually_came_up() -> None:
    """Not "has few matches so far".

    At gameweek 1 every team has none, so that reading applies the prior to all twenty clubs
    and the attack and defence adjustments largely cancel into noise. That was the first
    implementation and it scored indistinguishably from the plain league baseline, which is
    what exposed it.
    """
    baseline = PromotedTeamPooledPrior(minimum_team_matches=6)
    baseline.set_promoted({"2025-26": frozenset({7})})
    baseline.fit(_window(_balanced_league(goals_home=2, goals_away=1)))

    established, promoted_attack, promoted_opponent = baseline.predict_rates(
        _frame(
            [
                _row(team_id=1, opponent_team_id=2, was_home=True),
                _row(team_id=7, opponent_team_id=2, was_home=True),
                _row(team_id=1, opponent_team_id=7, was_home=True),
            ]
        )
    )
    assert established == pytest.approx(2.0)
    assert promoted_attack == pytest.approx(2.0 * PROMOTED_ATTACK_RATIO)
    assert promoted_opponent == pytest.approx(2.0 * PROMOTED_DEFENCE_RATIO)


def test_promoted_prior_expires_once_the_club_has_played_enough() -> None:
    """The prior is a starting point, not a season-long label.

    The measured spread across promoted clubs is wide -- attack sd 0.157, range 0.466 to
    1.015 -- so observed matches should override it quickly.
    """
    rows = _balanced_league(goals_home=2, goals_away=1)
    for repeat in range(8):
        rows.append(
            _row(fixture=500 + repeat, team_id=7, opponent_team_id=1, was_home=True, goals_for=2)
        )
    baseline = PromotedTeamPooledPrior(minimum_team_matches=6)
    baseline.set_promoted({"2025-26": frozenset({7})})
    baseline.fit(_window(rows))

    (rate,) = baseline.predict_rates(_frame([_row(team_id=7, opponent_team_id=2, was_home=True)]))
    assert rate == pytest.approx(2.0), "eight matches in, the prior should no longer apply"


def test_promotion_is_scoped_to_the_season_it_happened_in() -> None:
    """A club promoted in 2024-25 is not a promoted club in 2025-26."""
    baseline = PromotedTeamPooledPrior(minimum_team_matches=6)
    baseline.set_promoted({"2024-25": frozenset({7}), "2025-26": frozenset()})
    baseline.fit(_window(_balanced_league(goals_home=2, goals_away=1)))
    (rate,) = baseline.predict_rates(
        _frame([_row(season="2025-26", team_id=7, opponent_team_id=1, was_home=True)])
    )
    assert rate == pytest.approx(2.0)


def test_the_pooled_ratios_point_the_right_way() -> None:
    """Promoted clubs score less and concede more. A sign error here inverts every August."""
    assert 0.0 < PROMOTED_ATTACK_RATIO < 1.0
    assert PROMOTED_DEFENCE_RATIO > 1.0


# --------------------------------------------------------------------------------------
# Against the real archive
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_the_xg_baseline_degenerates_to_the_league_baseline_in_2021_22(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """2021-22 carries no xG, so the xG baseline can only be the venue mean there.

    This is why 2021-22 is the one season the xG baseline does not win: it is not competing.
    """
    frame = db.execute(
        """
        SELECT season, gw, fixture, team_id, opponent_team_id, was_home,
               goals_for, goals_against, team_xg, team_xgc, fdr
        FROM mart_fact_team_match WHERE season = '2021-22'
        """
    ).pl()
    assert frame["team_xg"].null_count() == frame.height, "2021-22 was expected to have no xG"

    window = TrainingWindow(frame)
    xg = TrailingXgAttackDefence()
    xg.fit(window)
    league = LeagueHomeAwayGoals()
    league.fit(window)

    fixtures = frame.head(50)
    assert xg.predict_rates(fixtures) == pytest.approx(league.predict_rates(fixtures))


@pytest.mark.archive
def test_promoted_prior_moves_exactly_the_clubs_that_came_up(
    db: duckdb.DuckDBPyConnection,
) -> None:
    promoted = promoted_team_ids(db)
    frame = db.execute(
        """
        SELECT season, gw, fixture, team_id, opponent_team_id, was_home,
               goals_for, goals_against, team_xg, team_xgc, fdr
        FROM mart_fact_team_match WHERE season < '2025-26'
        """
    ).pl()

    baseline = PromotedTeamPooledPrior(minimum_team_matches=6)
    baseline.set_promoted(promoted)
    baseline.fit(TrainingWindow(frame))

    league = LeagueHomeAwayGoals()
    league.fit(TrainingWindow(frame))

    opening = db.execute(
        """
        SELECT season, gw, fixture, team_id, opponent_team_id, was_home,
               goals_for, goals_against, team_xg, team_xgc, fdr
        FROM mart_fact_team_match WHERE season = '2025-26' AND gw = 1
        ORDER BY fixture, team_id
        """
    ).pl()
    promoted_2025 = promoted["2025-26"]
    assert len(promoted_2025) == 3

    for row, adjusted, neutral in zip(
        opening.iter_rows(named=True),
        baseline.predict_rates(opening),
        league.predict_rates(opening),
        strict=True,
    ):
        involved = row["team_id"] in promoted_2025 or row["opponent_team_id"] in promoted_2025
        if involved:
            assert adjusted != pytest.approx(neutral), row
        else:
            assert adjusted == pytest.approx(neutral), row


@pytest.mark.archive
def test_baseline_rates_stay_inside_a_plausible_football_range(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """A rate outside this band means a rating blew up, not that a team is that good."""
    frame = db.execute(
        """
        SELECT season, gw, fixture, team_id, opponent_team_id, was_home,
               goals_for, goals_against, team_xg, team_xgc, fdr
        FROM mart_fact_team_match WHERE season < '2025-26'
        """
    ).pl()
    fixtures = db.execute(
        """
        SELECT season, gw, fixture, team_id, opponent_team_id, was_home,
               goals_for, goals_against, team_xg, team_xgc, fdr
        FROM mart_fact_team_match WHERE season = '2025-26'
        """
    ).pl()

    promoted = promoted_team_ids(db)
    for baseline in build_baselines():
        setter = getattr(baseline, "set_promoted", None)
        if setter is not None:
            setter(promoted)
        baseline.fit(TrainingWindow(frame))
        for distribution in baseline.predict(fixtures):
            assert 0.2 < expected_goals(distribution) < 5.0, baseline.name
