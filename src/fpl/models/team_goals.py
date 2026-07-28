"""Stage A: a distribution over the goals each side scores in a fixture.

The model is the classical multiplicative form, which this archive supports over the
subtractive one by a wide margin (`attack x opponent defence` correlates 0.439 with goals
scored, `attack - opponent defence` manages 0.070):

    lambda(team, opponent, venue) = mu_venue * attack_team * defence_opponent

Four things separate it from the `trailing_*` baselines it has to beat:

  * **Schedule adjustment.** The baselines divide a team's goals by its match count, so a
    team that happened to play the weakest defences looks like a good attack. Here attack and
    defence are estimated *jointly*, so each team's rating is conditioned on who it actually
    played.
  * **Time decay.** The baselines weight a match from 2021 exactly like last week's. Here
    every match carries `exp(-ln2 * age / half_life)`, with the half-life chosen inside each
    fold rather than assumed.
  * **A prior with a promoted-club branch.** Ratings shrink toward 1.0, except for clubs that
    were not in the league last season, which shrink toward the measured promoted ratios. A
    club with no Premier League history at all lands exactly on its prior, which is the
    honest answer at gameweek 1.
  * **A fitted Dixon-Coles dependence.** Goals in a match are not independent at 0-0, 1-0,
    0-1 and 1-1, and `rho` is fitted rather than assumed. It deliberately does *not* enter the
    prediction: the correction preserves both marginals exactly, by construction, and Stage A
    is scored on the marginal. See `tau` for the proof. It is fitted and carried because the
    joint is what Stage D needs -- a defender's return depends on his own team scoring *and*
    the opponent not, and those are exactly the cells `rho` governs.

Fitting is iterative proportional fitting -- the closed-form conditional maximiser of the
weighted Poisson likelihood -- rather than a general optimiser. Each sweep is exact, it
converges monotonically, and it needs no new dependency for what is a twenty-team problem.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

import polars as pl

from fpl.validate.baselines import (
    PROMOTED_ATTACK_RATIO,
    PROMOTED_DEFENCE_RATIO,
    Row,
    StageABaseline,
    TrainingWindow,
    _as_bool,
    _as_int,
    _series_mean,
)
from fpl.validate.metrics import Distribution, poisson_pmf

# Candidate half-lives in days, searched inside every fold. 40 days is about six gameweeks;
# 320 is most of a season. The grid deliberately includes a value long enough to be
# effectively no decay, so the fold can decide that decay does not help rather than being
# forced into it.
HALF_LIFE_DAYS: tuple[float, ...] = (40.0, 80.0, 160.0, 320.0)

# Prior strength in matches. A five-match average has a Poisson standard error near 0.541
# goals against a true between-team spread of 0.440, so weak shrinkage is not an option.
PRIOR_MATCHES: tuple[float, ...] = (4.0, 8.0, 16.0)

# Dixon-Coles dependence parameter. Beyond this the low-score correction can drive a cell
# negative at league rates, and the published estimates sit well inside it.
RHO_GRID: tuple[float, ...] = tuple(-0.20 + 0.01 * step for step in range(41))

_MAX_SWEEPS = 60
_TOLERANCE = 1e-10
_RATE_FLOOR = 0.05


@dataclass(frozen=True, slots=True)
class Fixture:
    """One side of one match, reduced to what the fit needs."""

    team: int
    opponent: int
    was_home: bool
    measure: float
    goals: int | None
    weight: float


@dataclass
class TeamRatings:
    """A fitted rating set. Keys are `team_code`; `team_id` is season-scoped and unusable."""

    attack: dict[int, float] = field(default_factory=dict)
    defence: dict[int, float] = field(default_factory=dict)
    home: float = 1.4
    away: float = 1.2
    rho: float = 0.0

    def rate(self, team: int, opponent: int, was_home: bool) -> float:
        venue = self.home if was_home else self.away
        attack = self.attack.get(team, 1.0)
        defence = self.defence.get(opponent, 1.0)
        return max(venue * attack * defence, _RATE_FLOOR)


def _geometric_mean(values: Iterable[float]) -> float:
    collected = [value for value in values if value > 0]
    if not collected:
        return 1.0
    return math.exp(sum(math.log(value) for value in collected) / len(collected))


def fit_ratings(
    fixtures: Sequence[Fixture],
    *,
    prior_attack: dict[int, float],
    prior_defence: dict[int, float],
    prior_matches: float,
) -> TeamRatings:
    """Weighted Poisson MLE by iterative proportional fitting.

    Each sweep solves exactly for one block holding the others fixed. Setting the derivative
    of the weighted log-likelihood with respect to one team's attack to zero gives

        attack_k = sum(w * y) / sum(w * mu_venue * defence_opponent)

    over that team's matches, and symmetrically for defence and for the venue means. Adding a
    Gamma prior with `prior_matches` pseudo-matches at the prior mean turns each into the MAP
    update used below, which is also what makes a club with no history land on its prior
    instead of dividing by zero.
    """
    if not fixtures:
        return TeamRatings()

    teams = sorted(
        {fixture.team for fixture in fixtures} | {fixture.opponent for fixture in fixtures}
    )
    attack = {team: prior_attack.get(team, 1.0) for team in teams}
    defence = {team: prior_defence.get(team, 1.0) for team in teams}

    home_rows = [fixture for fixture in fixtures if fixture.was_home]
    away_rows = [fixture for fixture in fixtures if not fixture.was_home]
    home = _weighted_mean(home_rows, fallback=1.4)
    away = _weighted_mean(away_rows, fallback=1.2)

    previous = 0.0
    for _ in range(_MAX_SWEEPS):
        league = (home + away) / 2.0
        # `prior_matches` counts matches, so it is converted onto the goal scale before being
        # added to sums of goals. Without this the prior's strength would silently depend on
        # how many goals the league happens to score.
        strength = prior_matches * league

        scored: dict[int, float] = dict.fromkeys(teams, 0.0)
        attack_exposure: dict[int, float] = dict.fromkeys(teams, 0.0)
        conceded: dict[int, float] = dict.fromkeys(teams, 0.0)
        defence_exposure: dict[int, float] = dict.fromkeys(teams, 0.0)
        for fixture in fixtures:
            venue = home if fixture.was_home else away
            contribution = fixture.weight * fixture.measure
            scored[fixture.team] += contribution
            attack_exposure[fixture.team] += fixture.weight * venue * defence[fixture.opponent]
            conceded[fixture.opponent] += contribution
            defence_exposure[fixture.opponent] += fixture.weight * venue * attack[fixture.team]

        attack = _normalise(
            {
                team: (scored[team] + strength * prior_attack.get(team, 1.0))
                / (attack_exposure[team] + strength)
                for team in teams
            }
        )
        defence = _normalise(
            {
                team: (conceded[team] + strength * prior_defence.get(team, 1.0))
                / (defence_exposure[team] + strength)
                for team in teams
            }
        )

        home = _venue_update(home_rows, attack, defence, fallback=home)
        away = _venue_update(away_rows, attack, defence, fallback=away)

        level = home + away
        if abs(level - previous) < _TOLERANCE:
            break
        previous = level

    return TeamRatings(attack=attack, defence=defence, home=home, away=away)


def _weighted_mean(rows: Sequence[Fixture], *, fallback: float) -> float:
    total = sum(row.weight for row in rows)
    if total <= 0:
        return fallback
    return sum(row.weight * row.measure for row in rows) / total


def _normalise(ratings: dict[int, float]) -> dict[int, float]:
    """Pin the geometric mean to one.

    Attack and defence are each identified only up to a scale the venue means could absorb;
    fixing both leaves exactly one level, which lives in mu.
    """
    scale = _geometric_mean(ratings.values())
    if scale <= 0:
        return ratings
    return {team: value / scale for team, value in ratings.items()}


def _venue_update(
    rows: Sequence[Fixture],
    attack: dict[int, float],
    defence: dict[int, float],
    *,
    fallback: float,
) -> float:
    numerator = sum(row.weight * row.measure for row in rows)
    denominator = sum(
        row.weight * attack.get(row.team, 1.0) * defence.get(row.opponent, 1.0) for row in rows
    )
    if denominator <= 0:
        return fallback
    return numerator / denominator


# --------------------------------------------------------------------------------------
# Dixon-Coles low-score dependence
# --------------------------------------------------------------------------------------


def tau(home_goals: int, away_goals: int, home_rate: float, away_rate: float, rho: float) -> float:
    """The Dixon-Coles correction factor, 1 everywhere except the four low-score cells.

    Two consequences follow from the algebra, and both matter here.

    The corrected joint still sums to exactly one, so no renormalisation is needed: the four
    adjustments cancel.

    **It also leaves both marginals exactly unchanged**, which is less often stated. Summing
    the corrected joint over the opponent's goals, the two cells that touch `own = 0` are

        q(0) * (-lambda_own * lambda_opp * rho)  +  q(1) * (lambda_own * rho)

    and since `q(1) = lambda_opp * q(0)` for a Poisson, that is
    `q(0) * lambda_own * rho * (lambda_opp - lambda_opp) = 0`. The same cancellation holds at
    `own = 1`. Measured on this implementation the shift is under 3e-17 at league rates.

    So `rho` cannot improve a Stage A score no matter its value, and applying it in `predict`
    would be wasted work dressed up as modelling. It is fitted for the joint, which Stage D
    simulates, and reported on the ratings.
    """
    if home_goals == 0 and away_goals == 0:
        return 1.0 - home_rate * away_rate * rho
    if home_goals == 0 and away_goals == 1:
        return 1.0 + home_rate * rho
    if home_goals == 1 and away_goals == 0:
        return 1.0 + away_rate * rho
    if home_goals == 1 and away_goals == 1:
        return 1.0 - rho
    return 1.0


def fit_rho(pairs: Sequence[tuple[float, float, int, int, float]]) -> float:
    """Choose `rho` by weighted likelihood, holding the rates fixed.

    Only the four corrected cells depend on `rho`, and the Poisson factors do not, so this is
    a one-dimensional search over the correction alone -- cheap enough to run in every fold
    rather than being assumed from the literature.
    """
    if not pairs:
        return 0.0

    best_rho, best_score = 0.0, -math.inf
    for candidate in RHO_GRID:
        score = 0.0
        feasible = True
        for home_rate, away_rate, home_goals, away_goals, weight in pairs:
            factor = tau(home_goals, away_goals, home_rate, away_rate, candidate)
            if factor <= 0:
                feasible = False
                break
            score += weight * math.log(factor)
        if feasible and score > best_score:
            best_rho, best_score = candidate, score
    return best_rho


# --------------------------------------------------------------------------------------
# The estimator the harness scores
# --------------------------------------------------------------------------------------

# Gameweeks held back from the end of the training window to choose the half-life and prior
# strength. They are still strictly before the fold's cutoff, so this is model selection on
# past data rather than a peek at the gameweek being predicted.
INNER_HOLDOUT_GAMEWEEKS = 6

_SECONDS_PER_DAY = 86_400.0


class StageATeamModel(StageABaseline):
    """Dixon-Coles team goals: schedule-adjusted, time-decayed, with a promoted-club prior."""

    name = "dixon_coles_team_goals"

    def __init__(self) -> None:
        self._ratings = TeamRatings()
        self._promoted: dict[str, frozenset[int]] = {}
        self._half_life = HALF_LIFE_DAYS[-1]
        self._prior_matches = PRIOR_MATCHES[1]

    def set_promoted(self, promoted: dict[str, frozenset[int]]) -> None:
        """Season -> `team_code` of clubs newly promoted into the league that season.

        Which clubs came up is known before a ball is kicked, so using it at gameweek 1 is
        reference data rather than leakage.
        """
        self._promoted = promoted

    # -- fitting -----------------------------------------------------------------------

    def fit(self, window: TrainingWindow) -> None:
        frame = window.frame
        if frame.is_empty():
            self._ratings = TeamRatings()
            return

        rows = self._rows(frame)
        if not rows:
            self._ratings = TeamRatings()
            return

        latest = max(kickoff for kickoff, _ in rows)
        self._half_life, self._prior_matches = self._select_hyperparameters(rows, latest)

        priors = self._priors(frame)
        fixtures = self._weighted(rows, latest, self._half_life)
        ratings = fit_ratings(
            fixtures,
            prior_attack=priors[0],
            prior_defence=priors[1],
            prior_matches=self._prior_matches,
        )
        ratings.rho = fit_rho(self._rho_pairs(fixtures, ratings))
        self._ratings = ratings

    def _rows(self, frame: pl.DataFrame) -> list[tuple[float, Fixture]]:
        """Training rows as `(kickoff seconds, fixture)`, using xG where it was measured.

        xG is the better signal wherever it exists but two seasons lack it, so it is rescaled
        onto the goals mean and used per row rather than per season. Rescaling matters: mixing
        two response scales in one likelihood would bias every rating toward whichever season
        happened to be measured with which.
        """
        usable = frame.drop_nulls(["goals_for", "team_code", "opponent_team_code"])
        if usable.is_empty():
            return []

        both = usable.drop_nulls(["team_xg"])
        scale = 1.0
        if both.height:
            xg_mean = _series_mean(both["team_xg"], fallback=0.0)
            if xg_mean > 0:
                scale = _series_mean(both["goals_for"], fallback=0.0) / xg_mean

        out: list[tuple[float, Fixture]] = []
        for row in usable.iter_rows(named=True):
            goals = int(row["goals_for"])
            xg = row["team_xg"]
            measure = float(xg) * scale if xg is not None else float(goals)
            out.append(
                (
                    row["kickoff_time"].timestamp(),
                    Fixture(
                        team=int(row["team_code"]),
                        opponent=int(row["opponent_team_code"]),
                        was_home=bool(row["was_home"]),
                        measure=measure,
                        goals=goals,
                        weight=1.0,
                    ),
                )
            )
        return out

    def _priors(self, frame: pl.DataFrame) -> tuple[dict[int, float], dict[int, float]]:
        """Prior means per club: neutral, except for clubs that were promoted this season.

        The promoted ratios carry a wide measured spread (attack sd 0.157, range 0.466 to
        1.015), which is exactly why they are a prior rather than an estimate -- observed
        matches override them within a few gameweeks.
        """
        attack: dict[int, float] = {}
        defence: dict[int, float] = {}
        for season, codes in self._promoted.items():
            del season
            for code in codes:
                attack[code] = PROMOTED_ATTACK_RATIO
                defence[code] = PROMOTED_DEFENCE_RATIO
        del frame
        return attack, defence

    @staticmethod
    def _weighted(
        rows: Sequence[tuple[float, Fixture]], reference: float, half_life: float
    ) -> list[Fixture]:
        decay = math.log(2.0) / max(half_life, 1e-6)
        out = []
        for kickoff, fixture in rows:
            age_days = max(reference - kickoff, 0.0) / _SECONDS_PER_DAY
            weight = math.exp(-decay * age_days)
            out.append(
                Fixture(
                    team=fixture.team,
                    opponent=fixture.opponent,
                    was_home=fixture.was_home,
                    measure=fixture.measure,
                    goals=fixture.goals,
                    weight=weight,
                )
            )
        return out

    def _select_hyperparameters(
        self, rows: Sequence[tuple[float, Fixture]], latest: float
    ) -> tuple[float, float]:
        """Pick the half-life and prior strength on a holdout inside the training window.

        The contract requires every data-derived transform to be fitted within the fold, and a
        half-life chosen once on the whole archive would be exactly the kind of quiet
        hyperparameter leak that makes a walk-forward result unreproducible out of sample.
        """
        cutoff = self._holdout_cutoff(rows)
        if cutoff is None:
            return HALF_LIFE_DAYS[-1], PRIOR_MATCHES[1]

        inner = [row for row in rows if row[0] < cutoff]
        holdout = [fixture for kickoff, fixture in rows if kickoff >= cutoff]
        if not inner or not holdout:
            return HALF_LIFE_DAYS[-1], PRIOR_MATCHES[1]

        inner_latest = max(kickoff for kickoff, _ in inner)
        attack_prior, defence_prior = self._priors(pl.DataFrame())

        best = (HALF_LIFE_DAYS[-1], PRIOR_MATCHES[1])
        best_score = math.inf
        for half_life in HALF_LIFE_DAYS:
            weighted = self._weighted(inner, inner_latest, half_life)
            for prior_matches in PRIOR_MATCHES:
                ratings = fit_ratings(
                    weighted,
                    prior_attack=attack_prior,
                    prior_defence=defence_prior,
                    prior_matches=prior_matches,
                )
                score = self._holdout_log_score(holdout, ratings)
                if score < best_score:
                    best, best_score = (half_life, prior_matches), score
        del latest
        return best

    @staticmethod
    def _holdout_cutoff(rows: Sequence[tuple[float, Fixture]]) -> float | None:
        """Kickoff at which the inner holdout starts, or None when there is too little data."""
        kickoffs = sorted({kickoff for kickoff, _ in rows})
        # Ten team-fixtures make a gameweek's worth of one side; the holdout is sized in
        # matches rather than days so that a mid-season international break does not empty it.
        needed = INNER_HOLDOUT_GAMEWEEKS * 20
        if len(kickoffs) <= needed or len(rows) < needed * 3:
            return None
        return kickoffs[-needed]

    @staticmethod
    def _holdout_log_score(holdout: Sequence[Fixture], ratings: TeamRatings) -> float:
        total = 0.0
        for fixture in holdout:
            if fixture.goals is None:
                continue
            rate = ratings.rate(fixture.team, fixture.opponent, fixture.was_home)
            masses = poisson_pmf(rate)
            index = min(max(fixture.goals, 0), len(masses) - 1)
            total -= math.log(max(masses[index], 1e-12))
        return total / max(len(holdout), 1)

    @staticmethod
    def _rho_pairs(
        fixtures: Sequence[Fixture], ratings: TeamRatings
    ) -> list[tuple[float, float, int, int, float]]:
        """Home/away rate and goal pairs, keyed so each match is counted once.

        The correction is about the *joint* low-score cells, so it is fitted on recorded goals
        rather than on the xG-blended measure the ratings use -- a fractional 0-0 is not a
        thing that happened.
        """
        by_match: dict[tuple[int, int], dict[str, Fixture]] = {}
        for fixture in fixtures:
            if fixture.goals is None:
                continue
            key = (min(fixture.team, fixture.opponent), max(fixture.team, fixture.opponent))
            side = "home" if fixture.was_home else "away"
            by_match.setdefault(key, {})[side] = fixture

        pairs = []
        for sides in by_match.values():
            home, away = sides.get("home"), sides.get("away")
            if home is None or away is None or home.goals is None or away.goals is None:
                continue
            pairs.append(
                (
                    ratings.rate(home.team, home.opponent, was_home=True),
                    ratings.rate(away.team, away.opponent, was_home=False),
                    home.goals,
                    away.goals,
                    home.weight,
                )
            )
        return pairs

    # -- prediction --------------------------------------------------------------------

    def rate_for(self, row: Row) -> float:
        return self._ratings.rate(
            _as_int(row, "team_code"),
            _as_int(row, "opponent_team_code"),
            _as_bool(row, "was_home"),
        )

    def predict(self, fixtures: pl.DataFrame) -> list[Distribution]:
        """Marginal goals per side.

        The fitted `rho` is deliberately absent: the Dixon-Coles correction preserves the
        marginal exactly (see `tau`), so applying it here would cost time and change nothing.
        """
        return [poisson_pmf(rate) for rate in self.predict_rates(fixtures)]
