"""Stage A development candidate V3: a sequential dynamic team-goals model.

Candidate V3 is a **development-only structural probe**, not a promotion candidate. It
exists to test one hypothesis: that team strength is a slowly time-varying latent
quantity, and that estimating it *sequentially* -- carrying each club's strength forward
as a state a single match can move, with mean reversion between matches and explicit
shrinkage between seasons -- adapts to changing strength more honestly than Candidate
V2's batch re-fit on an expanding window, while retaining useful cross-season
information. See `docs/phase1-candidate-v3-design.md` for the full pre-registration.

The model maintains attack and defence strengths in log space and combines them
multiplicatively with the (pooled, fixed) venue means, as V2 and the baselines do:

    lambda(home, away) = mu_home * exp(alpha_home + beta_away)
    lambda(away, home) = mu_away * exp(alpha_away + beta_home)

Matches are processed chronologically. For each match both sides' rates are computed
from the pre-match state *before* either side is updated, so a match's outcome cannot
leak into its own prediction. Each side's touched strength then takes one gradient-ascent
step on the Poisson log-likelihood, `(y - lambda)`, after mean-reverting by the retention
factor. At a season boundary every club is shrunk toward the mean; clubs newly promoted
into the season are reset to the measured promoted prior.

It is deterministic, dependency-light (stdlib `math` plus the existing metrics), produces
an exact Poisson marginal, and is never substituted for V2 by the default harness command.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import polars as pl

from fpl.config import Phase1StageACandidateV3Policy, load_phase1_evaluation
from fpl.validate.baselines import (
    Row,
    StageABaseline,
    TrainingWindow,
    _as_bool,
    _as_int,
    _as_str,
    _series_mean,
)
from fpl.validate.metrics import log_score, poisson_pmf

# Candidate V3's pre-registered grids. The model reads the executable copies from
# `config/phase1_evaluation.yaml` (`stage_a_candidate_v3`); these aliases keep the public
# test surface explicit, mirroring Candidate V2's `HALF_LIFE_DAYS`.
LEARNING_RATE: tuple[float, ...] = (0.05, 0.10, 0.20)
RETENTION: tuple[float, ...] = (0.985, 0.995, 1.0)
SEASON_RETENTION: tuple[float, ...] = (0.5, 0.75, 1.0)

_RATE_FLOOR = 0.05
_LOG_STRENGTH_CAP = 2.0


def _clip(value: float, cap: float) -> float:
    """Bound a log-strength so a runaway state cannot move a rate past the credible range."""
    if value > cap:
        return cap
    if value < -cap:
        return -cap
    return value


@dataclass(frozen=True, slots=True)
class MatchRow:
    """One match reduced to what the chronological filter needs, with both sides paired.

    Pairing the two sides of a fixture is what makes "compute both pre-match rates before
    updating either" expressible as one step, and it is keyed by the season-qualified
    `(season, fixture)` so the same match is never counted twice.
    """

    season: str
    fixture: int
    kickoff: float
    home_code: int
    away_code: int
    home_measure: float
    away_measure: float
    home_goals: int
    away_goals: int


@dataclass
class _MatchBuilder:
    """Mutable accumulator for the two sides of one fixture, built from per-side fact rows."""

    season: str
    fixture: int
    kickoff: float
    home_code: int | None = None
    away_code: int | None = None
    home_measure: float | None = None
    away_measure: float | None = None
    home_goals: int | None = None
    away_goals: int | None = None

    def complete(self) -> MatchRow | None:
        if (
            self.home_code is None
            or self.away_code is None
            or self.home_measure is None
            or self.away_measure is None
        ):
            return None
        return MatchRow(
            season=self.season,
            fixture=self.fixture,
            kickoff=self.kickoff,
            home_code=self.home_code,
            away_code=self.away_code,
            home_measure=self.home_measure,
            away_measure=self.away_measure,
            home_goals=self.home_goals or 0,
            away_goals=self.away_goals or 0,
        )


@dataclass
class DynamicState:
    """A replayed rating set. Keys are `team_code`; `team_id` is season-scoped and unusable.

    Strengths are stored in log space (multiplier = exp(value), centred at 0 = league
    mean). Only the sum `attack[team] + defence[opponent]` ever enters a prediction, so the
    additive split between a club's attack level and defence level is unidentified -- and
    harmlessly so, because predictions are invariant to the `(alpha + c, beta - c)` shift.
    """

    attack: dict[int, float] = field(default_factory=dict)
    defence: dict[int, float] = field(default_factory=dict)
    counts: dict[int, int] = field(default_factory=dict)
    venue_home: float = 1.4
    venue_away: float = 1.2
    rate_floor: float = _RATE_FLOOR


class DynamicTeamGoalsV3(StageABaseline):
    """Candidate V3: a mean-reverting online Poisson filter over team strength.

    Fitting one fold means replaying that fold's training window chronologically through
    the filter and reading off the resulting state. The learning rate, per-match
    retention, and season retention are selected on an inner observed-gameweek holdout
    inside the fold, exactly as Candidate V2 selects its half-life and prior strength.
    """

    def __init__(
        self,
        policy: Phase1StageACandidateV3Policy | None = None,
        *,
        minimum_team_matches: int | None = None,
    ) -> None:
        contract = load_phase1_evaluation()
        resolved = policy if policy is not None else contract.stage_a_candidate_v3
        if resolved is None:
            raise ValueError(
                "Candidate V3 policy is not configured; stage_a_candidate_v3 is absent from "
                "the contract. V3 is development-only and is never the default candidate."
            )
        self._policy: Phase1StageACandidateV3Policy = resolved
        self.name = self._policy.name
        self._minimum_team_matches = (
            minimum_team_matches
            if minimum_team_matches is not None
            else contract.training.minimum_team_matches
        )
        self._promoted: dict[str, frozenset[int]] = {}
        self._prediction_season: str | None = None
        self._state = DynamicState(rate_floor=self._policy.rate_floor)
        self._params: tuple[float, float, float] = self._fallback_params()
        self._selected_inner = False
        self._inner_holdout_gameweeks: tuple[tuple[str, int], ...] = ()
        self._prior_attack_log = math.log(self._policy.promoted_attack_prior)
        self._prior_defence_log = math.log(self._policy.promoted_defence_prior)

    def set_promoted(self, promoted: dict[str, frozenset[int]]) -> None:
        """Season -> `team_code` of clubs newly promoted into the league that season.

        Which clubs came up is known before a ball is kicked, so using it at gameweek 1 is
        reference data rather than leakage. The filter needs every season's promoted set
        because it replays the whole window, not just the prediction season.
        """
        self._promoted = promoted

    def set_prediction_season(self, season: str) -> None:
        """Outer-fold context. V3 resolves cold-start priors per match season, so this is
        retained for interface parity with V2 rather than required for correctness."""
        self._prediction_season = season

    def _fallback_params(self) -> tuple[float, float, float]:
        return (
            self._policy.fallback_learning_rate,
            self._policy.fallback_retention,
            self._policy.fallback_season_retention,
        )

    # -- fitting -----------------------------------------------------------------------

    def fit(self, window: TrainingWindow) -> None:
        frame = window.frame
        if self._prediction_season is None and not frame.is_empty():
            self._prediction_season = str(frame.sort("kickoff_time")["season"][-1])

        if frame.is_empty():
            self._state = DynamicState(rate_floor=self._policy.rate_floor)
            self._params = self._fallback_params()
            self._selected_inner = False
            self._inner_holdout_gameweeks = ()
            return

        venue_home, venue_away = self._venue_means(frame)
        selected = self._select_hyperparameters(frame)
        if selected is None:
            self._params = self._fallback_params()
            self._selected_inner = False
        else:
            self._params = selected
            self._selected_inner = True

        rows = self._rows(frame)
        if not rows:
            self._state = DynamicState(
                venue_home=venue_home, venue_away=venue_away, rate_floor=self._policy.rate_floor
            )
            return
        learning_rate, retention, season_retention = self._params
        self._state = self._filter(
            rows,
            venue_home=venue_home,
            venue_away=venue_away,
            learning_rate=learning_rate,
            retention=retention,
            season_retention=season_retention,
        )

    def _select_hyperparameters(self, frame: pl.DataFrame) -> tuple[float, float, float] | None:
        """Pick (learning rate, retention, season retention) on an inner observed-gameweek holdout.

        Every data-derived transform is fitted within the fold: the xG-to-goals scale comes
        from the inner training subset only, and the three dynamic knobs are chosen by
        predictive log score on the held-out gameweeks, never on the predicted gameweek.
        """
        split = self._inner_holdout(frame)
        if split is None:
            return None
        inner_frame, holdout_frame = split
        inner_scale = self._xg_scale(inner_frame)
        inner_rows = self._rows(inner_frame, xg_scale=inner_scale)
        holdout_rows = self._rows(holdout_frame, xg_scale=inner_scale)
        if not inner_rows or not holdout_rows:
            return None

        inner_venue_home, inner_venue_away = self._venue_means(inner_frame)
        best: tuple[float, float, float] | None = None
        best_score = math.inf
        for learning_rate in self._policy.learning_rate:
            for retention in self._policy.retention:
                for season_retention in self._policy.season_retention:
                    state = self._filter(
                        inner_rows,
                        venue_home=inner_venue_home,
                        venue_away=inner_venue_away,
                        learning_rate=learning_rate,
                        retention=retention,
                        season_retention=season_retention,
                    )
                    score = self._holdout_log_score(holdout_rows, state)
                    if score < best_score:
                        best, best_score = (learning_rate, retention, season_retention), score
        return best

    def _filter(
        self,
        matches: Sequence[MatchRow],
        *,
        venue_home: float,
        venue_away: float,
        learning_rate: float,
        retention: float,
        season_retention: float,
    ) -> DynamicState:
        """Replay matches chronologically, returning the final state.

        Both sides' pre-match rates are computed before either is updated, so a match's own
        outcome cannot affect its own predicted rate (the no-same-match-leakage property).
        At a season boundary every known club is shrunk by `season_retention`, except clubs
        promoted into the new season which are reset to the promoted prior.
        """
        attack: dict[int, float] = {}
        defence: dict[int, float] = {}
        counts: dict[int, int] = {}
        prior_attack = self._prior_attack_log
        prior_defence = self._prior_defence_log
        cap = self._policy.log_strength_cap
        rate_floor = self._policy.rate_floor
        previous_season: str | None = None

        for match in matches:
            if previous_season is not None and match.season != previous_season:
                promoted_now = self._promoted.get(match.season, frozenset())
                for club in attack:
                    if club in promoted_now:
                        attack[club] = prior_attack
                        defence[club] = prior_defence
                    else:
                        attack[club] = _clip(attack[club] * season_retention, cap)
                        defence[club] = _clip(defence[club] * season_retention, cap)
            previous_season = match.season

            home, away = match.home_code, match.away_code
            promoted_now = self._promoted.get(match.season, frozenset())
            for club in (home, away):
                if club not in attack:
                    if club in promoted_now:
                        attack[club] = prior_attack
                        defence[club] = prior_defence
                    else:
                        attack[club] = 0.0
                        defence[club] = 0.0

            # Predict both sides from the pre-match state, before any update.
            home_rate = max(venue_home * math.exp(attack[home] + defence[away]), rate_floor)
            away_rate = max(venue_away * math.exp(attack[away] + defence[home]), rate_floor)

            # Gradient-ascent step on the Poisson log-likelihood, after mean-reverting.
            home_residual = match.home_measure - home_rate
            away_residual = match.away_measure - away_rate
            attack[home] = _clip(attack[home] * retention + learning_rate * home_residual, cap)
            defence[away] = _clip(defence[away] * retention + learning_rate * home_residual, cap)
            attack[away] = _clip(attack[away] * retention + learning_rate * away_residual, cap)
            defence[home] = _clip(defence[home] * retention + learning_rate * away_residual, cap)

            counts[home] = counts.get(home, 0) + 1
            counts[away] = counts.get(away, 0) + 1

        return DynamicState(
            attack=attack,
            defence=defence,
            counts=counts,
            venue_home=venue_home,
            venue_away=venue_away,
            rate_floor=rate_floor,
        )

    def _holdout_log_score(self, holdout: Sequence[MatchRow], state: DynamicState) -> float:
        total = 0.0
        scored = 0
        for match in holdout:
            home_rate = self._match_rate(
                state, match.home_code, match.away_code, True, match.season
            )
            away_rate = self._match_rate(
                state, match.away_code, match.home_code, False, match.season
            )
            total += log_score(poisson_pmf(home_rate), match.home_goals)
            total += log_score(poisson_pmf(away_rate), match.away_goals)
            scored += 2
        return total / max(scored, 1)

    def _inner_holdout(self, frame: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame] | None:
        """Split the last N observed gameweek values, never N kickoff timestamps."""
        gameweeks = (
            frame.group_by(["season", "gw"], maintain_order=True)
            .agg(pl.col("kickoff_time").min().alias("first_kickoff"))
            .sort(["first_kickoff", "season", "gw"])
        )
        holdout_count = self._policy.inner_holdout_observed_gameweeks
        required = holdout_count + self._policy.minimum_inner_training_observed_gameweeks
        if gameweeks.height < required:
            self._inner_holdout_gameweeks = ()
            return None

        holdout_keys = gameweeks.tail(holdout_count).select(["season", "gw"])
        self._inner_holdout_gameweeks = tuple(
            (str(season), int(gw)) for season, gw in holdout_keys.iter_rows()
        )
        first_holdout = gameweeks.tail(holdout_count)["first_kickoff"].min()
        if first_holdout is None:
            return None
        inner = frame.filter(pl.col("kickoff_time") < first_holdout)
        holdout = frame.join(holdout_keys, on=["season", "gw"], how="semi")
        return inner, holdout

    def _rows(self, frame: pl.DataFrame, *, xg_scale: float | None = None) -> list[MatchRow]:
        """Training matches as paired chronological rows, using xG where it was measured.

        The two sides of a fixture are paired by `(season, fixture)` so the filter can
        compute both pre-match rates in one step. xG is rescaled onto the goals mean and
        used per row rather than per season: mixing two response scales in one likelihood
        would bias every rating toward whichever season happened to be measured with which.
        """
        usable = frame.drop_nulls(["goals_for", "team_code", "opponent_team_code"]).sort(
            ["kickoff_time", "season", "fixture", "team_id"]
        )
        if usable.is_empty():
            return []
        scale = xg_scale if xg_scale is not None else self._xg_scale(usable)

        sides: dict[tuple[str, int], _MatchBuilder] = {}
        for row in usable.iter_rows(named=True):
            key = (str(row["season"]), int(row["fixture"]))
            builder = sides.get(key)
            if builder is None:
                builder = _MatchBuilder(key[0], key[1], row["kickoff_time"].timestamp())
                sides[key] = builder
            xg = row["team_xg"]
            measure = float(xg) * scale if xg is not None else float(row["goals_for"])
            goals = int(row["goals_for"])
            if row["was_home"]:
                builder.home_code = int(row["team_code"])
                builder.away_code = int(row["opponent_team_code"])
                builder.home_measure = measure
                builder.home_goals = goals
            else:
                builder.away_code = int(row["team_code"])
                builder.home_code = int(row["opponent_team_code"])
                builder.away_measure = measure
                builder.away_goals = goals

        matches = [match for builder in sides.values() if (match := builder.complete()) is not None]
        matches.sort(key=lambda row: (row.kickoff, row.season, row.fixture))
        return matches

    def _xg_scale(self, frame: pl.DataFrame) -> float:
        """Goals-to-xG ratio over rows that carry both, so xG is denominated in goals."""
        both = frame.drop_nulls(["team_xg", "goals_for"])
        if not both.height:
            return 1.0
        xg_mean = _series_mean(both["team_xg"], fallback=0.0)
        if xg_mean <= 0:
            return 1.0
        return _series_mean(both["goals_for"], fallback=0.0) / xg_mean

    def _venue_means(self, frame: pl.DataFrame) -> tuple[float, float]:
        home = frame.filter(pl.col("was_home"))["goals_for"].drop_nulls()
        away = frame.filter(~pl.col("was_home"))["goals_for"].drop_nulls()
        return _series_mean(home, fallback=1.4), _series_mean(away, fallback=1.2)

    # -- prediction --------------------------------------------------------------------

    def _match_rate(
        self,
        state: DynamicState,
        team: int,
        opponent: int,
        was_home: bool,
        season: str,
    ) -> float:
        """Pre-match rate for one side, applying the six-match cold-start rule.

        A club with fewer than the minimum matches uses the declared prior -- the promoted
        ratio if it was promoted in this match's season, otherwise the neutral mean --
        rather than a strength estimated from too little data. Resolving the prior by the
        match's own season keeps the inner holdout (inside the training window) honest.
        """
        venue = state.venue_home if was_home else state.venue_away
        if state.counts.get(team, 0) >= self._minimum_team_matches:
            attack = state.attack.get(team, 0.0)
        else:
            attack = (
                self._prior_attack_log if team in self._promoted.get(season, frozenset()) else 0.0
            )
        if state.counts.get(opponent, 0) >= self._minimum_team_matches:
            defence = state.defence.get(opponent, 0.0)
        else:
            defence = (
                self._prior_defence_log
                if opponent in self._promoted.get(season, frozenset())
                else 0.0
            )
        return max(venue * math.exp(attack + defence), state.rate_floor)

    def rate_for(self, row: Row) -> float:
        return self._match_rate(
            self._state,
            _as_int(row, "team_code"),
            _as_int(row, "opponent_team_code"),
            _as_bool(row, "was_home"),
            _as_str(row, "season"),
        )

    def is_cold_start(self, row: Row) -> bool:
        return (
            self._state.counts.get(_as_int(row, "team_code"), 0) < self._minimum_team_matches
            or self._state.counts.get(_as_int(row, "opponent_team_code"), 0)
            < self._minimum_team_matches
        )

    def parameters(self) -> dict[str, float | int | str]:
        learning_rate, retention, season_retention = self._params
        return {
            "learning_rate": learning_rate,
            "retention": retention,
            "season_retention": season_retention,
            "inner_holdout_observed_gameweeks": len(self._inner_holdout_gameweeks),
            "used_inner_holdout": self._selected_inner,
        }

    def predict(self, fixtures: pl.DataFrame) -> list[tuple[float, ...]]:
        """Exact Poisson marginal per side. No Monte Carlo: Stage A is analytically scored."""
        return [poisson_pmf(rate) for rate in self.predict_rates(fixtures)]
