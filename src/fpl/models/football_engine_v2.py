"""V2 football engine: a fixture ENVIRONMENT, not a single goal rate.

The generalisation of V1's Stage A, and deliberately a generalisation rather than a
replacement. V1 fits one multiplicative attack/defence/venue decomposition to a single measure
(xG rescaled onto the goals scale). V2 fits **one such system per signal** -- goals, xG, xGOT,
shots on target, box touches, big chances, defensive actions -- on the same schedule-adjusted,
time-decayed, prior-shrunk estimator, and blends the signal-specific goal-rate predictions with
weights chosen on a fold-local inner holdout.

`fpl.models.team_goals.fit_ratings` is reused verbatim. That is the point: an ablation whose
candidates differ only in which signals participate attributes a lift to the SIGNAL, not to a
change of functional form. With `signals = ("goals",)` this engine reduces to a single-signal
fit; with `("goals", "expected_goals")` it is V1's behaviour up to the blend replacing V1's
row-level xG substitution.

Three properties fall out of fitting per signal rather than per model:

  * **The environment is free.** The shots-on-target system's prediction IS expected shots on
    target, so GK Saves V2 needs no separate model -- and the same fitted system read with the
    sides swapped gives shots on target FACED, because a club's defence rating in the SOT
    system is exactly how many on-target shots it concedes relative to the league.
  * **Coverage is per signal.** A signal absent from a season simply contributes no training
    rows there, and its predictions come back `None` rather than zero. 2021-22 has no xG at
    all; that is a coverage fact, not a modelling decision.
  * **Degradation is graceful.** An unavailable signal drops out of the blend and the weights
    renormalise over what remains.

Everything here is pure: frames in, ratings and environments out. No database handle, no SQL.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from itertools import product
from typing import Any, Final

import polars as pl

from fpl.artifacts.fixture_environment import (
    SIGNAL_BIG_CHANCES,
    SIGNAL_BOX_TOUCHES,
    SIGNAL_DEFENSIVE_ACTIONS,
    SIGNAL_EXPECTED_GOALS,
    SIGNAL_EXPECTED_GOALS_ON_TARGET,
    SIGNAL_GOALS,
    SIGNAL_SHOTS,
    SIGNAL_SHOTS_ON_TARGET,
    SIGNAL_SHOTS_ON_TARGET_FACED_PROXY,
    FixtureEnvironment,
    TeamEnvironment,
)
from fpl.models.team_goals import Fixture, TeamRatings, fit_ratings, fit_rho
from fpl.validate.metrics import poisson_pmf

NAME: Final[str] = "multisignal_team_environment_v1"

_SECONDS_PER_DAY: Final[float] = 86_400.0


def _as_float(value: object) -> float:
    """Narrow a Polars aggregate to a float. A non-numeric aggregate is a bug, not a zero."""
    if value is None:
        return 0.0
    if isinstance(value, bool):
        raise TypeError(f"expected a numeric aggregate, got a bool: {value!r}")
    if isinstance(value, int | float):
        return float(value)
    raise TypeError(f"expected a numeric aggregate, got {type(value).__name__}: {value!r}")


# Signals whose rating system predicts a quantity a downstream component consumes directly,
# rather than only feeding the goal-rate blend.
ENVIRONMENT_SIGNALS: Final[tuple[str, ...]] = (
    SIGNAL_SHOTS_ON_TARGET,
    SIGNAL_SHOTS,
    SIGNAL_EXPECTED_GOALS_ON_TARGET,
    SIGNAL_BOX_TOUCHES,
    SIGNAL_BIG_CHANCES,
    SIGNAL_DEFENSIVE_ACTIONS,
    SIGNAL_SHOTS_ON_TARGET_FACED_PROXY,
)

# Signals eligible to enter the goal-rate blend. `defensive_actions` is excluded on purpose:
# it measures how much defending a club does, which correlates with being under pressure, so
# blending it into an ATTACKING rate would invert its meaning. It is fitted for the
# environment only. `shots_on_target_allowed_proxy` is likewise environment-only -- it is
# already an opponent-facing measurement, so putting it in a blend of for-side attacking rates
# would double-count the fixture from the wrong end.
BLENDABLE_SIGNALS: Final[frozenset[str]] = frozenset(
    {
        SIGNAL_GOALS,
        SIGNAL_EXPECTED_GOALS,
        SIGNAL_EXPECTED_GOALS_ON_TARGET,
        SIGNAL_SHOTS_ON_TARGET,
        SIGNAL_SHOTS,
        SIGNAL_BOX_TOUCHES,
        SIGNAL_BIG_CHANCES,
    }
)

# Blend weights are searched over a coarse simplex. A finer grid is not free -- every point is
# a full holdout scoring pass -- and with four signals a 0.25 step already gives 35 points,
# which is far more resolution than 6 holdout gameweeks of team-matches can distinguish.
DEFAULT_WEIGHT_STEP: Final[float] = 0.25

# Minimum share of training rows a signal must carry to participate at all. A signal measured
# on 3% of the window contributes a rating fitted almost entirely from its prior, which adds
# noise dressed as evidence.
DEFAULT_MINIMUM_SIGNAL_COVERAGE: Final[float] = 0.25


@dataclass(frozen=True, slots=True)
class SignalSpec:
    """One football signal the engine may fit."""

    name: str
    column: str
    blendable: bool = True

    @property
    def is_environment_output(self) -> bool:
        return self.name in ENVIRONMENT_SIGNALS


# The default ladder, in the order the ablation adds them.
DEFAULT_SIGNALS: Final[tuple[SignalSpec, ...]] = (
    SignalSpec(SIGNAL_GOALS, "goals"),
    SignalSpec(SIGNAL_EXPECTED_GOALS, "expected_goals"),
    SignalSpec(SIGNAL_EXPECTED_GOALS_ON_TARGET, "expected_goals_on_target"),
    SignalSpec(SIGNAL_SHOTS_ON_TARGET, "shots_on_target"),
    SignalSpec(SIGNAL_SHOTS, "shots"),
    SignalSpec(SIGNAL_BOX_TOUCHES, "touches_in_opposition_box"),
    SignalSpec(SIGNAL_BIG_CHANCES, "big_chances_created"),
    SignalSpec(
        SIGNAL_SHOTS_ON_TARGET_FACED_PROXY, "shots_on_target_allowed_proxy", blendable=False
    ),
    SignalSpec(SIGNAL_DEFENSIVE_ACTIONS, "defensive_actions", blendable=False),
)


@dataclass
class FittedSignal:
    """A signal's fitted rating system plus what it took to fit it."""

    spec: SignalSpec
    ratings: TeamRatings
    rows: int
    coverage: float
    # Multiplier putting this signal's predicted rate onto the goals scale. Fitted in-window
    # as mean(goals) / mean(signal) over the rows where BOTH are measured -- never over
    # different row sets, which would fold a coverage difference into the scale.
    goal_scale: float

    def rate(self, team: int, opponent: int, was_home: bool, *, minimum_matches: int = 0) -> float:
        return self.ratings.rate(team, opponent, was_home, minimum_matches=minimum_matches)


@dataclass
class EngineParameters:
    """Everything the engine selected inside the fold, retained for the validation report."""

    half_life_days: float | None = None
    prior_matches: float = 8.0
    weights: dict[str, float] = field(default_factory=dict)
    signals_fitted: tuple[str, ...] = ()
    signals_rejected: dict[str, str] = field(default_factory=dict)
    rho: float = 0.0

    def as_report(self) -> dict[str, float | int | str]:
        report: dict[str, float | int | str] = {
            "half_life_days": (
                self.half_life_days if self.half_life_days is not None else "no_decay"
            ),
            "prior_matches": self.prior_matches,
            "rho": self.rho,
            "signals_fitted": ",".join(self.signals_fitted),
        }
        for name, weight in sorted(self.weights.items()):
            report[f"weight_{name}"] = round(weight, 6)
        for name, reason in sorted(self.signals_rejected.items()):
            report[f"rejected_{name}"] = reason
        return report


def simplex_grid(count: int, *, step: float = DEFAULT_WEIGHT_STEP) -> list[tuple[float, ...]]:
    """Every non-negative weight vector of `count` entries summing to 1 on a `step` lattice."""
    if count <= 0:
        return []
    if count == 1:
        return [(1.0,)]
    steps = round(1.0 / step)
    points: list[tuple[float, ...]] = []
    for combination in product(range(steps + 1), repeat=count - 1):
        used = sum(combination)
        if used > steps:
            continue
        weights = (*combination, steps - used)
        points.append(tuple(value / steps for value in weights))
    return points


class MultiSignalTeamEngine:
    """Fit one attack/defence system per signal; predict a fixture environment.

    `minimum_team_matches` mirrors V1: below it, a club's rating is replaced by its prior, so a
    promoted club at gameweek 1 lands on the measured promoted ratio rather than on a rating
    fitted from nothing.
    """

    name: str = NAME

    def __init__(
        self,
        *,
        signals: Sequence[SignalSpec] = DEFAULT_SIGNALS,
        half_life_days: Sequence[float | None] = (40.0, 80.0, 160.0, 320.0, 640.0, None),
        prior_matches: Sequence[float] = (2.0, 4.0, 8.0, 16.0, 32.0),
        minimum_team_matches: int = 3,
        inner_holdout_gameweeks: int = 6,
        minimum_inner_training_gameweeks: int = 10,
        weight_step: float = DEFAULT_WEIGHT_STEP,
        minimum_signal_coverage: float = DEFAULT_MINIMUM_SIGNAL_COVERAGE,
        promoted_attack_prior: float = 0.719,
        promoted_defence_prior: float = 1.309,
        rate_floor: float = 0.05,
        maximum_goals: int = 10,
    ) -> None:
        self._signals = tuple(signals)
        self._half_lives = tuple(half_life_days)
        self._prior_matches = tuple(prior_matches)
        self._minimum_team_matches = minimum_team_matches
        self._inner_holdout_gameweeks = inner_holdout_gameweeks
        self._minimum_inner_training_gameweeks = minimum_inner_training_gameweeks
        self._weight_step = weight_step
        self._minimum_signal_coverage = minimum_signal_coverage
        self._promoted_attack_prior = promoted_attack_prior
        self._promoted_defence_prior = promoted_defence_prior
        self._rate_floor = rate_floor
        self._maximum_goals = maximum_goals

        self._fitted: dict[str, FittedSignal] = {}
        self._parameters = EngineParameters()
        self._promoted: dict[str, frozenset[int]] = {}
        self._prediction_season: str | None = None

    # -- context -----------------------------------------------------------------------

    def set_promoted(self, promoted: Mapping[str, frozenset[int]]) -> None:
        """Season -> `team_code` of clubs newly promoted. Known before a ball is kicked."""
        self._promoted = dict(promoted)

    def set_prediction_season(self, season: str) -> None:
        self._prediction_season = season

    @property
    def parameters(self) -> EngineParameters:
        return self._parameters

    @property
    def fitted_signals(self) -> Mapping[str, FittedSignal]:
        return dict(self._fitted)

    # -- fitting -----------------------------------------------------------------------

    def fit(self, frame: pl.DataFrame) -> None:
        """Fit every available signal on a training window, then choose the blend.

        `frame` is team-match rows strictly before the fold cutoff, keyed on `team_code`. The
        caller is responsible for that filter; this method never widens it.
        """
        self._fitted = {}
        rejected: dict[str, str] = {}
        if frame.is_empty():
            self._parameters = EngineParameters(signals_rejected={"*": "empty training window"})
            return

        usable = frame.drop_nulls(["team_code", "opponent_team_code", "kickoff_time"]).sort(
            ["kickoff_time", "season", "fixture", "team_code"]
        )
        if usable.is_empty():
            self._parameters = EngineParameters(signals_rejected={"*": "no identified rows"})
            return

        priors = self._priors()
        half_life, prior_matches = self._select_decay_and_prior(usable, priors)

        latest = usable["kickoff_time"].max()
        assert isinstance(latest, datetime)

        for spec in self._signals:
            if spec.column not in usable.columns:
                rejected[spec.name] = "column absent"
                continue
            rows = usable.drop_nulls([spec.column])
            coverage = rows.height / usable.height
            if rows.is_empty():
                rejected[spec.name] = "no measured rows"
                continue
            if coverage < self._minimum_signal_coverage:
                rejected[spec.name] = f"coverage {coverage:.3f} below floor"
                continue
            fixtures = self._weighted_fixtures(rows, spec.column, latest, half_life)
            ratings = fit_ratings(
                fixtures,
                prior_attack=priors[0],
                prior_defence=priors[1],
                prior_matches=prior_matches,
                rate_floor=self._rate_floor,
            )
            self._fitted[spec.name] = FittedSignal(
                spec=spec,
                ratings=ratings,
                rows=rows.height,
                coverage=coverage,
                goal_scale=self._goal_scale(rows, spec.column),
            )

        weights = self._select_weights(usable, priors, half_life, prior_matches)
        rho = self._fit_rho(usable, latest, half_life)
        self._parameters = EngineParameters(
            half_life_days=half_life,
            prior_matches=prior_matches,
            weights=weights,
            signals_fitted=tuple(sorted(self._fitted)),
            signals_rejected=rejected,
            rho=rho,
        )

    def _priors(self) -> tuple[dict[int, float], dict[int, float]]:
        if self._prediction_season is None:
            return {}, {}
        codes = self._promoted.get(self._prediction_season, frozenset())
        return (
            dict.fromkeys(codes, self._promoted_attack_prior),
            dict.fromkeys(codes, self._promoted_defence_prior),
        )

    @staticmethod
    def _goal_scale(rows: pl.DataFrame, column: str) -> float:
        """mean(goals) / mean(signal) over rows where BOTH are measured.

        Restricting to jointly-measured rows matters: computing each mean over its own row set
        would fold the difference in coverage into the scale, so a signal measured only in
        high-scoring seasons would be rescaled as if it were systematically larger.
        """
        both = rows.drop_nulls(["goals", column]) if "goals" in rows.columns else rows.clear()
        if both.is_empty():
            return 1.0
        signal_mean = _as_float(both[column].mean())
        goals_mean = _as_float(both["goals"].mean())
        if signal_mean <= 0.0 or goals_mean <= 0.0:
            return 1.0
        return goals_mean / signal_mean

    def _weighted_fixtures(
        self,
        rows: pl.DataFrame,
        column: str,
        latest: datetime,
        half_life: float | None,
    ) -> list[Fixture]:
        decay = 0.0 if half_life is None else math.log(2.0) / max(half_life, 1e-6)
        reference = latest.timestamp()
        fixtures: list[Fixture] = []
        for row in rows.iter_rows(named=True):
            measure = row[column]
            if measure is None:
                continue
            age_days = max(reference - row["kickoff_time"].timestamp(), 0.0) / _SECONDS_PER_DAY
            goals = row.get("goals")
            fixtures.append(
                Fixture(
                    team=int(row["team_code"]),
                    opponent=int(row["opponent_team_code"]),
                    was_home=bool(row["was_home"]),
                    measure=float(measure),
                    goals=None if goals is None else int(goals),
                    weight=math.exp(-decay * age_days),
                    match_key=(str(row["season"]), int(row["fixture"])),
                )
            )
        return fixtures

    def _inner_split(self, frame: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame] | None:
        """Split off the last N OBSERVED gameweeks, never the last N kickoffs.

        2022-23 has no gameweek 7, so a contiguous assumption misaligns the split for a whole
        season. Both legs of a double gameweek stay together because the split is on the
        `(season, gw)` key, not on a timestamp.
        """
        gameweeks = (
            frame.group_by(["season", "gw"], maintain_order=True)
            .agg(pl.col("kickoff_time").min().alias("first_kickoff"))
            .sort(["first_kickoff", "season", "gw"])
        )
        required = self._inner_holdout_gameweeks + self._minimum_inner_training_gameweeks
        if gameweeks.height < required:
            return None
        holdout_keys = gameweeks.tail(self._inner_holdout_gameweeks).select(["season", "gw"])
        boundary = gameweeks.tail(self._inner_holdout_gameweeks)["first_kickoff"].min()
        if boundary is None:
            return None
        return (
            frame.filter(pl.col("kickoff_time") < boundary),
            frame.join(holdout_keys, on=["season", "gw"], how="semi"),
        )

    def _select_decay_and_prior(
        self, frame: pl.DataFrame, priors: tuple[dict[int, float], dict[int, float]]
    ) -> tuple[float | None, float]:
        """Choose the half-life and prior strength on the GOALS signal, inside the fold.

        Selecting them once on goals rather than jointly with the blend weights is a deliberate
        bound on search cost: a joint search over decay x prior x a 4-signal simplex is 35x
        larger and would be chosen on six gameweeks of team-matches, which cannot resolve it.
        The two stages are nested, both strictly inside the training window, so neither sees
        the fold being predicted.
        """
        split = self._inner_split(frame)
        fallback: tuple[float | None, float] = (160.0, 8.0)
        if split is None or "goals" not in frame.columns:
            return fallback
        inner, holdout = split
        inner = inner.drop_nulls(["goals"])
        holdout = holdout.drop_nulls(["goals"])
        if inner.is_empty() or holdout.is_empty():
            return fallback
        latest = inner["kickoff_time"].max()
        assert isinstance(latest, datetime)

        best: tuple[float | None, float] = fallback
        best_score = math.inf
        for half_life in self._half_lives:
            fixtures = self._weighted_fixtures(inner, "goals", latest, half_life)
            for prior in self._prior_matches:
                ratings = fit_ratings(
                    fixtures,
                    prior_attack=priors[0],
                    prior_defence=priors[1],
                    prior_matches=prior,
                    rate_floor=self._rate_floor,
                )
                score = self._holdout_log_score(holdout, self._single_signal_rate(ratings))
                if score < best_score:
                    best, best_score = (half_life, prior), score
        return best

    def _select_weights(
        self,
        frame: pl.DataFrame,
        priors: tuple[dict[int, float], dict[int, float]],
        half_life: float | None,
        prior_matches: float,
    ) -> dict[str, float]:
        """Choose blend weights over the signals that fitted, on an inner holdout.

        Refitting each signal on the INNER window rather than reusing the full-window fit is
        the difference between honest selection and selecting weights for a model that has
        already seen the holdout. It costs one extra fit per signal per fold.
        """
        blendable = [
            name
            for name, fitted in sorted(self._fitted.items())
            if fitted.spec.blendable and name in BLENDABLE_SIGNALS
        ]
        if not blendable:
            return {}
        if len(blendable) == 1:
            return {blendable[0]: 1.0}

        split = self._inner_split(frame)
        if split is None:
            # Without a holdout, weight equally rather than inventing a preference.
            return dict.fromkeys(blendable, 1.0 / len(blendable))
        inner, holdout = split
        holdout = holdout.drop_nulls(["goals"])
        if inner.is_empty() or holdout.is_empty():
            return dict.fromkeys(blendable, 1.0 / len(blendable))
        latest = inner["kickoff_time"].max()
        assert isinstance(latest, datetime)

        inner_fits: dict[str, FittedSignal] = {}
        for name in blendable:
            spec = self._fitted[name].spec
            rows = inner.drop_nulls([spec.column])
            if rows.is_empty():
                continue
            inner_fits[name] = FittedSignal(
                spec=spec,
                ratings=fit_ratings(
                    self._weighted_fixtures(rows, spec.column, latest, half_life),
                    prior_attack=priors[0],
                    prior_defence=priors[1],
                    prior_matches=prior_matches,
                    rate_floor=self._rate_floor,
                ),
                rows=rows.height,
                coverage=rows.height / inner.height,
                goal_scale=self._goal_scale(rows, spec.column),
            )
        available = [name for name in blendable if name in inner_fits]
        if not available:
            return dict.fromkeys(blendable, 1.0 / len(blendable))
        if len(available) == 1:
            return {available[0]: 1.0}

        best_weights = dict.fromkeys(available, 1.0 / len(available))
        best_score = math.inf
        for point in simplex_grid(len(available), step=self._weight_step):
            weights = dict(zip(available, point, strict=True))
            score = self._holdout_log_score(holdout, self._blended_rate_of(weights, inner_fits))
            if score < best_score:
                best_weights, best_score = weights, score
        return best_weights

    def _blended_rate(
        self,
        row: Mapping[str, object],
        weights: Mapping[str, float],
        fitted: Mapping[str, FittedSignal],
    ) -> float:
        """Weighted mean of each signal's goal-scaled rate, renormalised over what is present.

        Renormalisation is what makes an absent signal degrade rather than deflate: if xG
        carries 40% of the weight and is unavailable for this club, the remaining signals are
        rescaled to sum to one instead of the rate silently losing 40% of its level.
        """
        team = int(row["team_code"])  # type: ignore[call-overload]
        opponent = int(row["opponent_team_code"])  # type: ignore[call-overload]
        was_home = bool(row["was_home"])
        total_weight = 0.0
        total = 0.0
        for name, weight in weights.items():
            if weight <= 0.0:
                continue
            signal = fitted.get(name)
            if signal is None:
                continue
            rate = signal.rate(team, opponent, was_home, minimum_matches=self._minimum_team_matches)
            total += weight * rate * signal.goal_scale
            total_weight += weight
        if total_weight <= 0.0:
            return self._rate_floor
        return max(total / total_weight, self._rate_floor)

    def _single_signal_rate(self, ratings: TeamRatings) -> Callable[[Mapping[str, Any]], float]:
        """A rate function over one fitted rating system, bound for holdout scoring."""

        def rate(row: Mapping[str, Any]) -> float:
            return ratings.rate(
                int(row["team_code"]),
                int(row["opponent_team_code"]),
                bool(row["was_home"]),
                minimum_matches=self._minimum_team_matches,
            )

        return rate

    def _blended_rate_of(
        self, weights: Mapping[str, float], fitted: Mapping[str, FittedSignal]
    ) -> Callable[[Mapping[str, Any]], float]:
        """A rate function over a candidate weight vector, bound for holdout scoring."""

        def rate(row: Mapping[str, Any]) -> float:
            return self._blended_rate(row, weights, fitted)

        return rate

    @staticmethod
    def _holdout_log_score(
        holdout: pl.DataFrame, rate_of: Callable[[Mapping[str, Any]], float]
    ) -> float:
        """Mean Poisson negative log score of a rate function over holdout rows.

        A row with an unmeasured outcome is skipped, not scored as zero: a fold whose holdout
        carries no goals must not silently select the hyperparameters that predict zero best.
        """
        total = 0.0
        count = 0
        for row in holdout.iter_rows(named=True):
            goals = row.get("goals")
            if goals is None:
                continue
            rate = rate_of(row)
            masses = poisson_pmf(float(rate))
            index = min(max(int(goals), 0), len(masses) - 1)
            total -= math.log(max(masses[index], 1e-12))
            count += 1
        return total / max(count, 1)

    def _fit_rho(self, frame: pl.DataFrame, latest: datetime, half_life: float | None) -> float:
        """Dixon-Coles joint dependence, fitted on recorded goals.

        Carried, not applied to the marginal. The correction provably leaves both marginals
        unchanged (see `team_goals.tau`), so applying it in `predict` would cost time and
        change nothing -- but the JOINT is what the bonus simulation needs, because a
        defender's return depends on his side scoring and the opponent not.
        """
        goals_signal = self._fitted.get(SIGNAL_GOALS)
        if goals_signal is None or "goals" not in frame.columns:
            return 0.0
        rows = frame.drop_nulls(["goals"])
        if rows.is_empty():
            return 0.0
        fixtures = self._weighted_fixtures(rows, "goals", latest, half_life)
        by_match: dict[tuple[str, int], dict[str, Fixture]] = {}
        for fixture in fixtures:
            if fixture.match_key is None or fixture.goals is None:
                continue
            by_match.setdefault(fixture.match_key, {})["home" if fixture.was_home else "away"] = (
                fixture
            )
        pairs: list[tuple[float, float, int, int, float]] = []
        for sides in by_match.values():
            home, away = sides.get("home"), sides.get("away")
            if home is None or away is None or home.goals is None or away.goals is None:
                continue
            pairs.append(
                (
                    self._rate_from_blend(home.team, home.opponent, True),
                    self._rate_from_blend(away.team, away.opponent, False),
                    home.goals,
                    away.goals,
                    home.weight,
                )
            )
        return fit_rho(pairs)

    # -- prediction --------------------------------------------------------------------

    def _rate_from_blend(self, team: int, opponent: int, was_home: bool) -> float:
        row = {"team_code": team, "opponent_team_code": opponent, "was_home": was_home}
        weights = self._parameters.weights or {
            name: 1.0 / max(len(self._fitted), 1) for name in self._fitted
        }
        return self._blended_rate(row, weights, self._fitted)

    def goal_rate(self, team_code: int, opponent_team_code: int, was_home: bool) -> float:
        """The blended expected goals for one side of one fixture."""
        return self._rate_from_blend(team_code, opponent_team_code, was_home)

    def is_cold_start(self, team_code: int, opponent_team_code: int) -> bool:
        """Whether either club's rating fell back to its prior for lack of matches."""
        goals = self._fitted.get(SIGNAL_GOALS)
        if goals is None:
            return True
        matches = goals.ratings.matches
        return (
            matches.get(team_code, 0) < self._minimum_team_matches
            or matches.get(opponent_team_code, 0) < self._minimum_team_matches
        )

    def _environment_signal(
        self, name: str, team: int, opponent: int, was_home: bool
    ) -> float | None:
        """A signal's own predicted value for a side, on its own scale (not goal-scaled)."""
        fitted = self._fitted.get(name)
        if fitted is None:
            return None
        return fitted.rate(team, opponent, was_home, minimum_matches=self._minimum_team_matches)

    def _side(self, team: int, opponent: int, *, was_home: bool) -> TeamEnvironment:
        rate = self.goal_rate(team, opponent, was_home)
        against = self.goal_rate(opponent, team, not was_home)
        distribution = poisson_pmf(rate, max_goals=self._maximum_goals)

        def own(name: str) -> float | None:
            return self._environment_signal(name, team, opponent, was_home)

        def faced(name: str) -> float | None:
            """What this side FACES: the opponent's attacking rate against this defence.

            Reading the same fitted system with the sides swapped, rather than fitting a
            second 'allowed' system, is what keeps the two internally consistent: a club's
            defence rating in the shots-on-target system already IS how many on-target shots
            it concedes relative to the league.
            """
            return self._environment_signal(name, opponent, team, not was_home)

        # The direct proxy measurement, where it fitted, is preferred over the mirrored
        # for-side system: it is a measurement of shots faced rather than a rearrangement of
        # a measurement of shots taken.
        sot_faced = own(SIGNAL_SHOTS_ON_TARGET_FACED_PROXY)
        if sot_faced is None:
            sot_faced = faced(SIGNAL_SHOTS_ON_TARGET)

        return TeamEnvironment(
            team_code=team,
            was_home=was_home,
            goal_distribution=distribution,
            expected_goals=sum(index * mass for index, mass in enumerate(distribution)),
            expected_goals_against=against,
            expected_shots_on_target=own(SIGNAL_SHOTS_ON_TARGET),
            expected_shots_on_target_against=sot_faced,
            expected_shots=own(SIGNAL_SHOTS),
            expected_shots_against=faced(SIGNAL_SHOTS),
            expected_goals_on_target_value=own(SIGNAL_EXPECTED_GOALS_ON_TARGET),
            expected_goals_on_target_against=faced(SIGNAL_EXPECTED_GOALS_ON_TARGET),
            expected_box_touches=own(SIGNAL_BOX_TOUCHES),
            expected_box_touches_against=faced(SIGNAL_BOX_TOUCHES),
            expected_big_chances=own(SIGNAL_BIG_CHANCES),
            expected_big_chances_against=faced(SIGNAL_BIG_CHANCES),
            expected_possession=None,
            expected_defensive_actions=own(SIGNAL_DEFENSIVE_ACTIONS),
            cold_start=self.is_cold_start(team, opponent),
            signal_coverage={name: name in self._fitted for name in KNOWN_SIGNAL_NAMES},
        )

    def predict_environment(
        self,
        *,
        season: str,
        fixture: int,
        home_team_code: int,
        away_team_code: int,
        gw: int | None = None,
        kickoff_time: datetime | None = None,
    ) -> FixtureEnvironment:
        """The full football prediction for one fixture."""
        return FixtureEnvironment(
            season=season,
            fixture=fixture,
            gw=gw,
            kickoff_time=kickoff_time,
            home=self._side(home_team_code, away_team_code, was_home=True),
            away=self._side(away_team_code, home_team_code, was_home=False),
            rho=self._parameters.rho,
            engine=self.name,
        )

    def predict_environments(self, fixtures: pl.DataFrame) -> list[FixtureEnvironment]:
        """One environment per fixture. `fixtures` carries one row per SIDE, as the marts do.

        Sides are paired here rather than assumed in order: a frame filtered to one venue, or
        sorted differently, must not silently produce a fixture whose 'away' side is a second
        copy of the home club.
        """
        environments: list[FixtureEnvironment] = []
        for (season, fixture), group in fixtures.group_by(
            ["season", "fixture"], maintain_order=True
        ):
            home = group.filter(pl.col("was_home"))
            away = group.filter(~pl.col("was_home"))
            if home.height != 1 or away.height != 1:
                continue
            environments.append(
                self.predict_environment(
                    season=str(season),
                    fixture=int(fixture),
                    home_team_code=int(home["team_code"][0]),
                    away_team_code=int(away["team_code"][0]),
                    gw=None if home["gw"][0] is None else int(home["gw"][0]),
                    kickoff_time=home["kickoff_time"][0],
                )
            )
        return environments


KNOWN_SIGNAL_NAMES: Final[tuple[str, ...]] = tuple(spec.name for spec in DEFAULT_SIGNALS)
