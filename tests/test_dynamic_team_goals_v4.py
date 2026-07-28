"""Candidate V4: the leakage-safe sequential dynamic team-goals model (development-only).

Each test pins one of the four defects that voided V3's number, plus the point-in-time and
identity invariants the repository enforces everywhere:

  1. nested walk-forward inner selection -- state advances after each holdout gameweek;
  2. every fixture in a holdout gameweek is predicted from the same pre-gameweek state
     (order-invariant, no same-gameweek leakage);
  3. the season transition fires inside the holdout when it crosses a season boundary;
  4. the six-match cold-start prior is used in the fitting residual, not only in prediction;
  5. returning promoted clubs reset their eligible count; incumbents keep declared retention;
  6. the promoted prior is fold-local (earlier cohorts only, current cohort excluded) and
     invariant to future appended rows;
  7. full-database and physically truncated-database agree at the same ``as_of``;
  8. the development report is never a promotion verdict;
  9. V1/V2/V3 records and behaviour are preserved alongside V4.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from fpl.config import Phase1StageACandidateV4Policy, load_phase1_evaluation
from fpl.models.dynamic_team_goals_v4 import (
    LEARNING_RATE,
    RETENTION,
    SEASON_RETENTION,
    DynamicState,
    DynamicTeamGoalsV4,
    MatchRow,
)
from fpl.validate.baselines import TrainingWindow
from fpl.validate.metrics import log_score, poisson_pmf

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
) -> Phase1StageACandidateV4Policy:
    """A single-value-grid policy so the filter can be exercised with known knobs."""
    return Phase1StageACandidateV4Policy(
        name="dynamic_team_goals_v4",
        development_only=True,
        inner_holdout_observed_gameweeks=6,
        minimum_inner_training_observed_gameweeks=12,
        holdout_walk_forward=True,
        cold_start_in_fitting=True,
        returning_promoted_count_reset=True,
        learning_rate=learning_rate,
        retention=retention,
        season_retention=season_retention,
        fallback_learning_rate=learning_rate[0],
        fallback_retention=retention[0],
        fallback_season_retention=season_retention[0],
        promoted_prior_source="fold_local_earlier_cohorts",
        fallback_attack_prior=1.0,
        fallback_defence_prior=1.0,
        promoted_prior_min_matches=6,
        promoted_prior_shrinkage_matches=6.0,
        xg_policy="use_when_measured_scaled_to_goals",
        rate_floor=0.05,
        log_strength_cap=2.0,
    )


def _match_row(
    season: str,
    gw: int,
    kickoff_day: int,
    home_code: int,
    away_code: int,
    home_measure: float,
    away_measure: float,
    fixture: int = 1,
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
# Defect 1: state advances after each inner holdout gameweek (true walk-forward)
# --------------------------------------------------------------------------------------


def test_walk_forward_advances_state_between_holdout_gameweeks() -> None:
    """GW2's prediction must be made from the state GW1's results moved, not the frozen state.

    Team 1 is established (>= 6 inner matches) so its dynamic strength is read. GW1 gives it a
    huge positive residual that boosts its attack; GW2 features team 1 again. A true walk-forward
    therefore scores GW2 differently from a frozen-state (V3) scoring, which would predict GW2
    from the pre-holdout state. The genuine pre-holdout state is snapshotted *before*
    ``_walk_forward_score`` mutates it; the frozen comparator predicts GW1 and GW2 from that
    snapshot with no absorption, so the two disagree iff GW2's prediction moved because GW1 was
    absorbed.
    """
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    # Inner training: team 1 plays six times, scoring 1 each, so its attack is near neutral.
    inner = [_match_row(SEASON, 1, 7 * i, 1, 2, 1.0, 1.0, fixture=100 + i) for i in range(6)] + [
        _match_row(SEASON, 1, 7 * i + 3, 3, 4, 1.0, 1.0, fixture=200 + i) for i in range(6)
    ]
    state, last_season = model._replay(
        inner,
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    # Snapshot the genuine pre-holdout state BEFORE _walk_forward_score mutates it.
    snap_a, snap_d, snap_c = dict(state.attack), dict(state.defence), dict(state.counts)

    # GW1: team 1 scores 6 (large positive residual -> boosts attack[1]); GW2: team 1 plays again.
    gw1 = [_match_row(SEASON, 7, 100, 1, 5, 6.0, 0.0, fixture=301)]
    gw2 = [_match_row(SEASON, 8, 107, 1, 6, 0.0, 0.0, fixture=302)]
    advanced = model._walk_forward_score(
        state,
        last_season,
        [gw1, gw2],
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )

    # Frozen comparator: predict GW1 and GW2 both from the pre-holdout snapshot, no updates.
    frozen = 0.0
    scored = 0
    for batch in (gw1, gw2):
        for match in batch:
            hr = model._side_rate(
                snap_a,
                snap_d,
                snap_c,
                match.home_code,
                match.away_code,
                True,
                match.season,
                1.4,
                1.2,
            )
            ar = model._side_rate(
                snap_a,
                snap_d,
                snap_c,
                match.away_code,
                match.home_code,
                False,
                match.season,
                1.4,
                1.2,
            )
            frozen += log_score(poisson_pmf(hr), match.home_goals)
            frozen += log_score(poisson_pmf(ar), match.away_goals)
            scored += 2
    frozen /= scored

    assert advanced != pytest.approx(frozen, abs=1e-9), (
        "walk-forward score equalled the frozen-state score; GW1 did not advance the state"
    )


# --------------------------------------------------------------------------------------
# Defect 1 (cont.): same pre-gameweek state for all fixtures, order-invariant
# --------------------------------------------------------------------------------------


def test_fixtures_in_one_gameweek_share_one_pre_state_and_are_order_invariant() -> None:
    """Same-GW predictions use one snapshot; absorption is in deterministic kickoff order.

    Club 1 is a double-gameweek club that appears twice in the batch at *different* kickoffs.
    The batch score is order-invariant because every prediction reads the pre-gameweek snapshot,
    but absorption is observable in the resulting state (a club updated twice reads its own
    just-updated strength on the second update), so reversing the input must still yield the
    same resulting state and the same next-gameweek prediction. That holds only because the
    helper sorts each batch by actual kickoff before absorbing; without it, reversing the input
    would change club 1's final strength and every later prediction with it.
    """
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=1)
    inner = [_match_row(SEASON, 1, 0, 1, 2, 1.0, 1.0), _match_row(SEASON, 2, 7, 3, 4, 1.0, 1.0)]
    # Club 1 appears twice: vs 5 at day 14 (earlier) and vs 9 at day 15 (later), plus two
    # independent fixtures. The list is deliberately not in kickoff order.
    batch = [
        _match_row(SEASON, 3, 15, 1, 9, 3.0, 1.0, fixture=313),
        _match_row(SEASON, 3, 14, 1, 5, 2.0, 0.0, fixture=310),
        _match_row(SEASON, 3, 14, 7, 8, 0.0, 2.0, fixture=312),
        _match_row(SEASON, 3, 14, 3, 6, 1.0, 1.0, fixture=311),
    ]
    next_gw = [_match_row(SEASON, 4, 21, 1, 7, 1.0, 1.0, fixture=410)]

    def run(
        batch_order: list[MatchRow],
    ) -> tuple[float, float, dict[int, float], dict[int, float], dict[int, int]]:
        state, last_season = model._replay(
            inner,
            venue_home=1.4,
            venue_away=1.2,
            learning_rate=0.10,
            retention=0.995,
            season_retention=0.75,
        )
        batch_score = model._walk_forward_score(
            state,
            last_season,
            [batch_order],
            venue_home=1.4,
            venue_away=1.2,
            learning_rate=0.10,
            retention=0.995,
            season_retention=0.75,
        )
        # Predict the next gameweek from the state the batch left behind.
        next_score = model._walk_forward_score(
            state,
            last_season,
            [next_gw],
            venue_home=1.4,
            venue_away=1.2,
            learning_rate=0.10,
            retention=0.995,
            season_retention=0.75,
        )
        return batch_score, next_score, dict(state.attack), dict(state.defence), dict(state.counts)

    fwd = run(batch)
    rev = run(list(reversed(batch)))

    # The current batch score is order-invariant (one snapshot).
    assert fwd[0] == pytest.approx(rev[0], abs=1e-12)
    # The resulting state is order-invariant only because absorption is forced into kickoff order.
    for club in set(fwd[2]) | set(rev[2]):
        assert fwd[2][club] == pytest.approx(rev[2][club], abs=1e-12), f"attack[{club}] differs"
        assert fwd[3][club] == pytest.approx(rev[3][club], abs=1e-12), f"defence[{club}] differs"
        assert fwd[4][club] == rev[4][club], f"counts[{club}] differs"
    # So the next gameweek, predicted from that state, is order-invariant too.
    assert fwd[1] == pytest.approx(rev[1], abs=1e-12)


# --------------------------------------------------------------------------------------
# Defect 1 (cont.): season transition fires inside the holdout
# --------------------------------------------------------------------------------------


def test_season_transition_fires_inside_the_holdout() -> None:
    """A holdout crossing a season boundary runs the transition before the batch is predicted.

    Inner training ends in 2024-25. Club 1 is a returning promoted club (counts 8 from 2024-25,
    marked promoted for 2025-26) and club 3 is an incumbent that does not play in the holdout.
    The 2025-26 holdout batch therefore forces the summer transition: club 1 is reset to cold
    (counts 0 -> +1 in the batch), and club 3 is shrunk by season_retention with no further
    update (it is absent from the batch). Both effects are observable only if the transition
    fired inside the holdout before the batch was absorbed.
    """
    model = DynamicTeamGoalsV4(_flat_policy(season_retention=(0.5,)), minimum_team_matches=6)
    model.set_promoted({"2025-26": frozenset({1})})
    model._prior_attack_log = math.log(0.8)
    model._prior_defence_log = math.log(1.2)
    inner = [_match_row("2024-25", 1, 7 * i, 1, 2, 1.0, 1.0, fixture=100 + i) for i in range(8)]
    inner += [
        _match_row("2024-25", 1, 7 * i + 3, 3, 4, 3.0, 0.0, fixture=300 + i) for i in range(8)
    ]
    state, last_season = model._replay(
        inner,
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.5,
    )
    assert last_season == "2024-25"
    incumbent_before = state.attack[3]
    assert incumbent_before > 0.0  # club 3 scored heavily -> positive log-attack

    holdout = [_match_row("2025-26", 1, 700, 1, 9, 1.0, 1.0, fixture=500)]
    model._walk_forward_score(
        state,
        last_season,
        [holdout],
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.5,
    )
    # Returning promoted club 1 was reset at the boundary, then played once -> counts 1, cold.
    assert state.counts[1] == 1
    # Incumbent club 3 was shrunk by 0.5 over the summer and, absent from the batch, not
    # updated afterwards -- so its strength is exactly the transitioned value.
    assert state.attack[3] == pytest.approx(_clip_value(incumbent_before * 0.5), abs=1e-9)
    assert state.counts[3] == 8  # incumbent count retained across the boundary


def _clip_value(value: float, cap: float = 2.0) -> float:
    return max(-cap, min(cap, value))


# --------------------------------------------------------------------------------------
# Outer season-opening fold: fit() crosses the summer boundary the training window does not
# --------------------------------------------------------------------------------------


def test_outer_season_opening_applies_one_summer_transition() -> None:
    """Outer GW1 prediction state must cross the summer the training window did not.

    The training window ends in 2024-25, so the replayed state never crossed into the 2025-26
    prediction season: without an explicit outer transition a returning promoted club stays warm
    (its 2024-25 count retained) and incumbents stay unshrunk. ``fit`` must apply exactly one
    transition into the prediction season -- promoted count -> 0 (cold), incumbent strength *=
    season_retention -- so GW1 predicts from the post-summer state.
    """
    policy = _flat_policy(season_retention=(0.5,))
    model = DynamicTeamGoalsV4(policy, minimum_team_matches=6)
    model.set_promoted({"2025-26": frozenset({1})})
    model.set_prediction_season("2025-26")
    # No 2024-25 promoted cohort is declared, so the fold-local prior is the neutral 1.0/1.0.
    model._prior_attack_log = math.log(1.0)
    model._prior_defence_log = math.log(1.0)
    # Prior-season training only (club 1 returns promoted; club 2 is an incumbent).
    frame = _season_frame(season="2024-25", gameweeks=8, clubs=(1, 2, 3, 4, 5, 6, 7, 8))

    # Pre-transition incumbent strength, from the same replay fit performs.
    rows = model._rows(frame)
    venue_home, venue_away = model._venue_means(frame)
    prior_state, last_season = model._replay(
        rows,
        venue_home=venue_home,
        venue_away=venue_away,
        learning_rate=policy.fallback_learning_rate,
        retention=policy.fallback_retention,
        season_retention=policy.fallback_season_retention,
    )
    assert last_season == "2024-25"
    incumbent_before = prior_state.attack[2]

    model.fit(TrainingWindow(frame))

    # Returning promoted club 1: reset to cold, and with no 2025-26 training its count is 0
    # (it would be 8 if the transition were skipped).
    assert model._state.counts[1] == 0
    # Incumbent club 2 retains its 2024-25 count and is shrunk exactly once (by 0.5).
    assert model._state.counts[2] == 8
    assert model._state.attack[2] == pytest.approx(_clip_value(incumbent_before * 0.5), abs=1e-9)


def test_no_second_transition_when_training_includes_the_prediction_season() -> None:
    """A fold whose training already crossed into the prediction season must not transition again.

    The replay applies the 2024-25 -> 2025-26 transition once, at the first 2025-26 match, so the
    replayed state ends in the prediction season and ``fit`` adds no second transition. An
    incumbent would otherwise be shrunk by ``season_retention`` twice.
    """
    policy = _flat_policy(season_retention=(0.5,))
    model = DynamicTeamGoalsV4(policy, minimum_team_matches=6)
    model.set_prediction_season("2025-26")
    model._prior_attack_log = math.log(1.0)
    model._prior_defence_log = math.log(1.0)
    frame = pl.concat(
        [
            _season_frame(
                season="2024-25",
                gameweeks=8,
                kickoff=datetime(2024, 8, 15, 19, 0, tzinfo=UTC),
                clubs=(1, 2, 3, 4, 5, 6, 7, 8),
            ),
            _season_frame(
                season="2025-26",
                gameweeks=4,
                kickoff=datetime(2025, 8, 15, 19, 0, tzinfo=UTC),
                clubs=(1, 2, 3, 4, 5, 6, 7, 8),
            ),
        ]
    )

    rows = model._rows(frame)
    venue_home, venue_away = model._venue_means(frame)
    single, last_season = model._replay(
        rows,
        venue_home=venue_home,
        venue_away=venue_away,
        learning_rate=policy.fallback_learning_rate,
        retention=policy.fallback_retention,
        season_retention=policy.fallback_season_retention,
    )
    assert last_season == "2025-26"
    # A spurious second transition would shrink every incumbent again.
    double = DynamicState(
        attack=dict(single.attack),
        defence=dict(single.defence),
        counts=dict(single.counts),
        venue_home=single.venue_home,
        venue_away=single.venue_away,
        rate_floor=single.rate_floor,
    )
    model._apply_season_transition(double.attack, double.defence, double.counts, "2025-26", 0.5)

    model.fit(TrainingWindow(frame))

    # fit's state is the single-transition replay, not the double.
    assert model._state.attack[2] == pytest.approx(single.attack[2], abs=1e-9)
    assert model._state.attack[2] != pytest.approx(double.attack[2], abs=1e-9)
    assert model._state.counts[2] == single.counts[2]


# --------------------------------------------------------------------------------------
# Defect 2: cold-start prior used in the fitting residual, not only in prediction
# --------------------------------------------------------------------------------------


def test_the_cold_prior_is_used_in_the_fitting_residual() -> None:
    """A cold club's residual is measured against the prior rate on every match until six.

    Club 9 is promoted and cold. On its second match its dynamic attack has already drifted, but
    the residual rate must still be the prior rate (0.7 = 1.4 * 0.5), never the drifted dynamic
    rate. The resulting attack is hand-computed under that rule; the V3 rule (drifted rate)
    would land elsewhere.
    """
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({"2025-26": frozenset({9})})
    model._prior_attack_log = math.log(0.5)  # prior attack ratio 0.5 -> home prior rate 0.7
    model._prior_defence_log = math.log(1.0)
    matches = [
        _match_row(SEASON, 1, 0, 9, 1, 3.0, 0.0, fixture=100),
        _match_row(SEASON, 2, 7, 9, 1, 3.0, 0.0, fixture=101),
    ]
    state, _ = model._replay(
        matches,
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=0.75,
    )
    # seed a0 = log(0.5); both residuals use the prior rate 0.7 -> residual 2.3 each time.
    a0 = math.log(0.5)
    a1 = a0 * 0.995 + 0.10 * (3.0 - 0.7)
    a2 = a1 * 0.995 + 0.10 * (3.0 - 0.7)
    assert state.attack[9] == pytest.approx(a2, abs=1e-6)
    assert state.counts[9] == 2  # still cold (< 6)


def test_the_cold_prior_is_used_in_prediction() -> None:
    """A cold promoted club's predicted rate is the venue mean times the prior."""
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({"2025-26": frozenset({9})})
    model._prior_attack_log = math.log(0.719)
    model._prior_defence_log = math.log(1.309)
    state = DynamicState(rate_floor=0.05)  # no history -> every club cold
    assert model._match_rate(state, 9, 1, True, "2025-26") == pytest.approx(1.4 * 0.719)
    assert model._match_rate(state, 1, 9, True, "2025-26") == pytest.approx(1.4 * 1.309)


# --------------------------------------------------------------------------------------
# Defect 3: returning-promoted count reset and incumbent retention
# --------------------------------------------------------------------------------------


def test_returning_promoted_club_resets_count_and_incumbent_retains() -> None:
    """A club marked promoted in the new season resets to cold; an incumbent keeps its count.

    Club 1 plays eight 2024-25 matches (counts 8) then is marked promoted for 2025-26 (the
    relegated-and-returned case). At the boundary its count resets to zero, so it is cold again
    in 2025-26. Club 2, an incumbent, keeps its 2024-25 count into 2025-26.
    """
    model = DynamicTeamGoalsV4(_flat_policy(season_retention=(1.0,)), minimum_team_matches=6)
    model.set_promoted({"2025-26": frozenset({1})})
    model._prior_attack_log = math.log(0.8)
    model._prior_defence_log = math.log(1.2)
    rows = [_match_row("2024-25", 1, 7 * i, 1, 2, 1.0, 1.0, fixture=100 + i) for i in range(8)]
    rows += [_match_row("2025-26", 1, 700, 1, 2, 1.0, 1.0, fixture=200)]
    state, _ = model._replay(
        rows,
        venue_home=1.4,
        venue_away=1.2,
        learning_rate=0.10,
        retention=0.995,
        season_retention=1.0,
    )
    # Club 1 was reset at the boundary (counts 0) then played once in 2025-26 -> counts 1, cold.
    assert state.counts[1] == 1
    # Predicted against a fresh, non-promoted opponent (neutral defence) the rate is the prior.
    assert model._match_rate(state, 1, 99, True, "2025-26") == pytest.approx(1.4 * 0.8)
    # Incumbent club 2 retained its 2024-25 count into 2025-26.
    assert state.counts[2] == 8 + 1


# --------------------------------------------------------------------------------------
# Defect 4: fold-local promoted prior -- eligibility and future-row invariance
# --------------------------------------------------------------------------------------


def test_promoted_prior_uses_only_earlier_cohorts_and_excludes_the_current_one() -> None:
    """The prior is the mean of earlier promoted clubs' shrunk ratios; the current cohort is out.

    2022-23 promoted club 91 concedes heavily (defence ratio > 1); 2023-24 promoted club 92 is
    frugal (defence ratio < 1). The 2024-25 fold's prior averages 91 and 92 only; club 93
    (promoted in the prediction season 2024-25) is excluded even though its data is in-frame.
    """
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted(
        {"2022-23": frozenset({91}), "2023-24": frozenset({92}), "2024-25": frozenset({93})}
    )
    rows: list[dict[str, object]] = []
    # Six matches each. League mean is ~1.36 goals/match here (hand-checked below).
    # Club 91: concedes 3/match (defence ratio high). Club 92: concedes 0.5/match (low).
    for gw in range(1, 7):
        rows += _match_rows(gw, 91, 1, 1, 3, season="2022-23")  # 91 scores 1, concedes 3
        rows += _match_rows(gw, 2, 3, 1, 1, season="2022-23")  # league filler
        rows += _match_rows(gw, 92, 4, 1, 0, season="2023-24")  # 92 scores 1, concedes 0
        rows += _match_rows(gw, 5, 6, 1, 1, season="2023-24")
        rows += _match_rows(gw, 93, 7, 5, 0, season="2024-25")  # current cohort, must be excluded
        rows += _match_rows(gw, 8, 9, 1, 1, season="2024-25")
    frame = _frame(rows)
    attack_log, defence_log = model._fold_local_promoted_prior(frame, "2024-25")

    # Recompute the expected prior from the eligible cohorts (2022-23, 2023-24) only.
    eligible = frame.filter(pl.col("season").is_in(["2022-23", "2023-24"]))
    mu = {
        s: float(eligible.filter(pl.col("season") == s)["goals_for"].mean())
        for s in ("2022-23", "2023-24")
    }

    def ratio(team: int, season: str, col: str) -> float:
        sub = eligible.filter((pl.col("season") == season) & (pl.col("team_code") == team))
        total = float(sub[col].sum())
        matches = sub.height
        m = mu[season]
        return ((total + 6.0 * m) / (matches + 6.0)) / m

    exp_attack = (ratio(91, "2022-23", "goals_for") + ratio(92, "2023-24", "goals_for")) / 2
    exp_defence = (
        ratio(91, "2022-23", "goals_against") + ratio(92, "2023-24", "goals_against")
    ) / 2
    assert math.exp(attack_log) == pytest.approx(exp_attack, abs=1e-9)
    assert math.exp(defence_log) == pytest.approx(exp_defence, abs=1e-9)


def test_promoted_prior_falls_back_to_neutral_with_no_earlier_cohort() -> None:
    """Earliest folds have no earlier promoted cohort, so the neutral 1.0/1.0 fallback stands."""
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({"2025-26": frozenset({9})})
    frame = _season_frame(season="2025-26", gameweeks=20)
    attack_log, defence_log = model._fold_local_promoted_prior(frame, "2025-26")
    assert math.exp(attack_log) == pytest.approx(1.0)
    assert math.exp(defence_log) == pytest.approx(1.0)


def test_appending_future_rows_does_not_move_an_earlier_fold_prior() -> None:
    """A later season's promoted cohort cannot move a prior for an earlier prediction season."""
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted(
        {"2022-23": frozenset({91}), "2023-24": frozenset({92}), "2024-25": frozenset({93})}
    )
    rows: list[dict[str, object]] = []
    for gw in range(1, 7):
        rows += _match_rows(gw, 91, 1, 1, 2, season="2022-23")
        rows += _match_rows(gw, 2, 3, 1, 1, season="2022-23")
        rows += _match_rows(gw, 92, 4, 1, 1, season="2023-24")
        rows += _match_rows(gw, 5, 6, 1, 1, season="2023-24")
    frame = _frame(rows)
    before = model._fold_local_promoted_prior(frame, "2023-24")
    # Append a whole future (2024-25) promoted cohort; it is after the prediction season.
    future = _frame(
        [_match_rows(gw, 93, 7, 5, 0, season="2024-25")[0] for gw in range(1, 7)]
        + [_match_rows(gw, 8, 9, 1, 1, season="2024-25")[0] for gw in range(1, 7)]
    )
    after = model._fold_local_promoted_prior(pl.concat([frame, future]), "2023-24")
    assert before == pytest.approx(after, abs=1e-12)


def test_promoted_prior_attack_stays_eligible_when_defence_is_null() -> None:
    """A club whose defence went unmeasured keeps its attack ratio; defence falls back alone.

    Club 91 (promoted 2023-24) has measured goals_for but NULL goals_against; club 92 has both.
    The attack prior averages both clubs' attack ratios; the defence prior uses club 92 only, so
    91's missing defence is never zero-filled and never drops 91's attack contribution.
    """
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({"2023-24": frozenset({91, 92}), "2024-25": frozenset({93})})
    rows: list[dict[str, object]] = []
    for gw in range(1, 7):
        rows += _match_rows(gw, 91, 1, 1, 3, season="2023-24")  # 91 scores 1, concedes 3
        rows += _match_rows(gw, 2, 3, 1, 1, season="2023-24")  # league filler
        rows += _match_rows(gw, 92, 4, 1, 1, season="2023-24")  # 92 scores 1, concedes 1
        rows += _match_rows(gw, 5, 6, 1, 1, season="2023-24")  # league filler
    # Defence unmeasured for club 91 only.
    frame = _frame(rows).with_columns(
        pl.when(pl.col("team_code") == 91)
        .then(None)
        .otherwise(pl.col("goals_against"))
        .alias("goals_against")
    )
    attack_log, defence_log = model._fold_local_promoted_prior(frame, "2024-25")

    eligible = frame.filter(pl.col("season") == "2023-24")
    mu = float(eligible["goals_for"].mean())

    def ratio(team: int, col: str) -> float:
        sub = eligible.filter(pl.col("team_code") == team)
        measured = sub[col].drop_nulls()
        total = float(measured.sum())
        n = measured.len()
        return ((total + 6.0 * mu) / (n + 6.0)) / mu

    # Attack averages both clubs (91 and 92); defence uses 92 only.
    exp_attack = (ratio(91, "goals_for") + ratio(92, "goals_for")) / 2
    exp_defence = ratio(92, "goals_against")
    assert math.exp(attack_log) == pytest.approx(exp_attack, abs=1e-9)
    assert math.exp(defence_log) == pytest.approx(exp_defence, abs=1e-9)
    # Defence did not collapse to the neutral fallback: 92 was eligible.
    assert math.exp(defence_log) != pytest.approx(1.0, abs=1e-9)


def test_promoted_prior_defence_falls_back_to_neutral_when_all_defence_is_null() -> None:
    """With no eligible defence component, defence falls back to 1.0 while attack is still used."""
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({"2023-24": frozenset({91}), "2024-25": frozenset({93})})
    rows: list[dict[str, object]] = []
    for gw in range(1, 7):
        rows += _match_rows(gw, 91, 1, 2, 3, season="2023-24")  # 91 scores 2, concedes 3
        rows += _match_rows(gw, 2, 3, 1, 1, season="2023-24")  # league filler
    frame = _frame(rows).with_columns(
        pl.when(pl.col("team_code") == 91)
        .then(None)
        .otherwise(pl.col("goals_against"))
        .alias("goals_against")
    )
    attack_log, defence_log = model._fold_local_promoted_prior(frame, "2024-25")

    # Defence has no eligible component -> independent neutral fallback.
    assert math.exp(defence_log) == pytest.approx(1.0, abs=1e-12)
    # Attack still uses club 91's measured ratio (not the fallback).
    eligible = frame.filter(pl.col("season") == "2023-24")
    mu = float(eligible["goals_for"].mean())
    measured = eligible.filter(pl.col("team_code") == 91)["goals_for"]
    total = float(measured.sum())
    n = measured.len()
    exp_attack = ((total + 6.0 * mu) / (n + 6.0)) / mu
    assert math.exp(attack_log) == pytest.approx(exp_attack, abs=1e-9)
    assert math.exp(attack_log) != pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------------------
# Defect 4 (cont.): point-in-time truncation equivalence on the real archive
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_full_database_equals_truncated_database_at_the_same_as_of(db) -> None:  # type: ignore[no-untyped-def]
    """V4's prediction at a fold is identical whether the DB is full (future filtered) or
    physically truncated to ``as_of``. The truncated side also drops future-season dimension
    rows, so a fold-local prior or promoted set that read a future-season dimension row would
    diverge. This is a property check only -- it compares predicted rates, no performance metric."""
    from fpl.validate.folds import generate_folds, promoted_team_codes
    from fpl.validate.harness import _fold_fixtures, _training_window
    from tests.conftest import make_truncated_db

    contract = load_phase1_evaluation()
    policy = contract.stage_a_candidate_v4
    folds = generate_folds(db)
    fold = folds[len(folds) // 2]
    promoted = promoted_team_codes(db)
    fixtures = _fold_fixtures(db, fold)

    full = DynamicTeamGoalsV4(policy, minimum_team_matches=contract.training.minimum_team_matches)
    full.set_promoted(promoted)
    full.set_prediction_season(fold.season)
    full.fit(_training_window(db, fold))
    rates_full = full.predict_rates(fixtures)

    truncated = make_truncated_db(fold.as_of, truncate_future_season_dimensions=True)
    trunc = DynamicTeamGoalsV4(policy, minimum_team_matches=contract.training.minimum_team_matches)
    trunc.set_promoted(promoted_team_codes(truncated))
    trunc.set_prediction_season(fold.season)
    trunc.fit(_training_window(truncated, fold))
    rates_trunc = trunc.predict_rates(fixtures)

    assert rates_full == pytest.approx(rates_trunc, abs=1e-12)


# --------------------------------------------------------------------------------------
# Identity, grain, cold start, NULL xG, determinism (parity with the V3 surface)
# --------------------------------------------------------------------------------------


def test_the_model_keys_on_team_code_not_team_id() -> None:
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
    plain, relabelled = DynamicTeamGoalsV4(), DynamicTeamGoalsV4()
    plain.fit(TrainingWindow(frame))
    relabelled.fit(TrainingWindow(swapped))
    assert plain.predict_rates(fixtures) == pytest.approx(
        relabelled.predict_rates(swapped_fixtures)
    )


def test_fixture_keys_are_season_qualified() -> None:
    rows = _match_rows(1, 1, 2, 2, 1, season="2024-25", fixture=1)
    rows += _match_rows(1, 1, 2, 1, 1, season="2025-26", fixture=1)
    model = DynamicTeamGoalsV4()
    matches = model._rows(_frame(rows))
    keys = {(m.season, m.fixture) for m in matches}
    assert keys == {("2024-25", 1), ("2025-26", 1)}


def test_fewer_than_six_matches_uses_the_declared_prior() -> None:
    model = DynamicTeamGoalsV4(_flat_policy(), minimum_team_matches=6)
    model.set_promoted({"2025-26": frozenset({9})})
    model._prior_attack_log = math.log(0.719)
    cold = DynamicState(
        attack={9: 2.0, 1: 0.0}, defence={9: 0.0, 1: 0.0}, counts={9: 5, 1: 10}, rate_floor=0.05
    )
    warm = DynamicState(
        attack={9: 2.0, 1: 0.0}, defence={9: 0.0, 1: 0.0}, counts={9: 6, 1: 10}, rate_floor=0.05
    )
    assert model._match_rate(cold, 9, 1, True, "2025-26") == pytest.approx(1.4 * 0.719)
    assert model._match_rate(warm, 9, 1, True, "2025-26") == pytest.approx(1.4 * math.exp(2.0))


def test_a_season_without_xg_still_fits_on_recorded_goals() -> None:
    model = DynamicTeamGoalsV4()
    model.fit(TrainingWindow(_season_frame(xg=False)))
    rates = model.predict_rates(_frame(_match_rows(21, 1, 2, 0, 0)))
    assert all(rate > 0.2 for rate in rates)


def test_null_xg_rows_fall_back_to_recorded_goals_without_zero_fill() -> None:
    model = DynamicTeamGoalsV4()
    mixed = _season_frame(xg=True, gameweeks=6).with_columns(
        pl.when(pl.col("gw") == 1).then(None).otherwise(pl.col("team_xg")).alias("team_xg")
    )
    assert model._rows(mixed)
    model.fit(TrainingWindow(mixed))
    rates = model.predict_rates(_frame(_match_rows(7, 1, 2, 0, 0)))
    assert all(rate > 0.2 for rate in rates)


def test_hyperparameters_are_selected_from_the_pre_registered_grid() -> None:
    model = DynamicTeamGoalsV4()
    model.fit(TrainingWindow(_season_frame(gameweeks=40)))
    params = model.parameters()
    assert params["learning_rate"] in LEARNING_RATE
    assert params["retention"] in RETENTION
    assert params["season_retention"] in SEASON_RETENTION
    assert params["holdout_walk_forward"] is True
    assert params["cold_start_in_fitting"] is True
    assert params["returning_promoted_count_reset"] is True
    assert params["promoted_prior_source"] == "fold_local_earlier_cohorts"


def test_inner_holdout_is_exactly_six_observed_gameweeks() -> None:
    model = DynamicTeamGoalsV4()
    split = model._inner_holdout(_season_frame(gameweeks=20))
    assert split is not None
    _, _, keys = split
    assert len(keys) == 6
    assert {gw for _, gw in keys} == {15, 16, 17, 18, 19, 20}


def test_insufficient_inner_history_falls_back_to_the_declared_defaults() -> None:
    contract = load_phase1_evaluation().stage_a_candidate_v4
    assert contract is not None
    model = DynamicTeamGoalsV4()
    model.fit(TrainingWindow(_season_frame(gameweeks=10)))
    params = model.parameters()
    assert params["learning_rate"] == contract.fallback_learning_rate
    assert params["retention"] == contract.fallback_retention
    assert params["season_retention"] == contract.fallback_season_retention
    assert params["used_inner_holdout"] is False


def test_the_fit_is_deterministic() -> None:
    frame = _season_frame()
    fixtures = _frame(_match_rows(21, 1, 2, 0, 0))
    first, second = DynamicTeamGoalsV4(), DynamicTeamGoalsV4()
    first.fit(TrainingWindow(frame))
    second.fit(TrainingWindow(frame))
    assert first.predict(fixtures) == second.predict(fixtures)
    assert first.parameters() == second.parameters()


def test_the_model_predicts_proper_distributions() -> None:
    model = DynamicTeamGoalsV4()
    model.fit(TrainingWindow(_season_frame()))
    for masses in model.predict(_frame(_match_rows(21, 1, 2, 0, 0))):
        assert len(masses) == 11
        assert sum(masses) == pytest.approx(1.0, abs=1e-12)
        assert all(mass >= 0.0 for mass in masses)


def test_the_model_survives_an_empty_window() -> None:
    model = DynamicTeamGoalsV4()
    model.fit(TrainingWindow(_frame([])))
    masses = model.predict(_frame(_match_rows(1, 1, 2, 0, 0)))[0]
    assert sum(masses) == pytest.approx(1.0, abs=1e-12)
