"""Stage A Candidate V4: the leakage-safe sequential dynamic team-goals model.

Candidate V4 is the structural successor to the **invalidated** Candidate V3
(`dynamic_team_goals_v3`). It keeps V3's hypothesis -- team strength is a slowly time-varying
latent quantity, estimated *sequentially* by a mean-reverting online Poisson filter in log
space with explicit summer shrinkage -- and fixes the four defects that voided V3's
development number. See `docs/phase1-candidate-v4-design.md` for the pre-registration and
`docs/phase1-candidate-v3-invalidation.md` for the defects.

The four fixes, each enforced by the pre-registered policy in `config/phase1_evaluation.yaml`
(`stage_a_candidate_v4`, amendment 1.5):

1. **Nested walk-forward inner selection.** The inner holdout is a true per-observed-gameweek
   walk-forward: for each chronological holdout gameweek, predict every fixture from the
   pre-gameweek state, score, and only then absorb that gameweek's results before advancing.
   V3 scored all six held-out gameweeks from one frozen state.

2. **Cold-start prior in the fitting residual.** The six-match cold-start prior is applied to
   the rate used in the Poisson-gradient residual *during fitting*, not only at prediction
   time. V3 measured the residual against the raw dynamic rate from match one.

3. **Returning-promoted count reset.** A club's eligible match count is reset to zero for every
   newly promoted season -- including a club relegated and promoted back -- while incumbents
   keep their declared summer retention. V3 never reset counts, so a returning promoted club
   kept its old Premier-League count and was never cold again.

4. **Fold-local promoted priors.** The promoted cold-start prior is estimated from earlier
   promoted cohorts whose matches are inside the fold (seasons strictly before the prediction
   season), the current promoted cohort is excluded from its own prior, and a declared neutral
   ``1.0 / 1.0`` fallback applies when no eligible cohort exists. V3 used full-archive constants
   estimated from seasons future to early folds (target leakage).

Like V3 this model is deterministic and dependency-light (stdlib `math` plus the existing
validation helpers), produces an exact Poisson marginal (no Monte Carlo), keys clubs on stable
``team_code``, pairs matches by the season-qualified ``(season, fixture)`` key, preserves NULL
xG, and is never substituted for V2 by the default harness command. It is pre-registered
before any evaluation; no V4 historical score exists.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

import polars as pl

from fpl.config import Phase1StageACandidateV4Policy, load_phase1_evaluation
from fpl.validate.baselines import (
    Row,
    StageABaseline,
    TrainingWindow,
    _as_bool,
    _as_int,
    _as_str,
    _series_mean,
)
from fpl.validate.metrics import Distribution, log_score, poisson_pmf

# Candidate V4's pre-registered grids. The model reads the executable copies from
# `config/phase1_evaluation.yaml` (`stage_a_candidate_v4`); these aliases keep the public test
# surface explicit, mirroring Candidate V2's `HALF_LIFE_DAYS`.
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


def _shrunk_ratio(
    observed_total: float, matches: int, league_mean: float, shrinkage: float
) -> float:
    """``(n*observed + k*mu) / (n + k)`` as a ratio to the league mean.

    The frozen V4 analogue of the baselines' ``_shrunk_ratio``: the shrinkage weight is the
    pre-registered ``promoted_prior_shrinkage_matches`` (match-units toward neutral), not the
    baselines' hard-coded ``SHRINKAGE_MATCHES``, so a change to V4's shrinkage is an
    amendment-gated config edit rather than a silent code edit.
    """
    if league_mean <= 0:
        return 1.0
    numerator = observed_total + shrinkage * league_mean
    denominator = matches + shrinkage
    return (numerator / denominator) / league_mean


@dataclass(frozen=True, slots=True)
class MatchRow:
    """One match reduced to what the chronological filter needs, with both sides paired.

    Paired by the season-qualified ``(season, fixture)`` key so the same match is never counted
    twice, exactly as the grain rule requires.
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
class _Pair:
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
    """A replayed rating set. Keys are ``team_code``; ``team_id`` is season-scoped and unusable.

    Strengths are stored in log space (multiplier = exp(value), centred at 0 = league mean).
    ``counts`` is the number of eligible completed matches a club has played; it is reset to
    zero for every newly promoted season (fix 3), so a returning promoted club is cold again.
    """

    attack: dict[int, float] = field(default_factory=dict)
    defence: dict[int, float] = field(default_factory=dict)
    counts: dict[int, int] = field(default_factory=dict)
    venue_home: float = 1.4
    venue_away: float = 1.2
    rate_floor: float = _RATE_FLOOR


class DynamicTeamGoalsV4(StageABaseline):
    """Candidate V4: the leakage-safe mean-reverting online Poisson filter.

    Fitting one fold means (a) estimating the fold-local promoted prior from earlier cohorts,
    (b) selecting the three dynamic knobs on a true per-gameweek inner walk-forward holdout,
    and (c) replaying the full training window chronologically to the final prediction state.

    ``_prior_attack_log`` / ``_prior_defence_log`` hold the active promoted prior (log space).
    They are set to the full-frame prior in ``fit`` and temporarily swapped to the
    inner-training prior inside ``_select_hyperparameters`` (under ``try/finally``), so the
    helpers below read one instance attribute rather than threading the prior through every
    call.
    """

    def __init__(
        self,
        policy: Phase1StageACandidateV4Policy | None = None,
        *,
        minimum_team_matches: int | None = None,
    ) -> None:
        contract = load_phase1_evaluation()
        self._policy: Phase1StageACandidateV4Policy = (
            policy if policy is not None else contract.stage_a_candidate_v4
        )
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
        self._prior_attack_log = math.log(self._policy.fallback_attack_prior)
        self._prior_defence_log = math.log(self._policy.fallback_defence_prior)

    def set_promoted(self, promoted: dict[str, frozenset[int]]) -> None:
        """Season -> ``team_code`` of clubs newly promoted into the league that season.

        Which clubs came up is known before a ball is kicked, so using it at gameweek 1 is
        reference data rather than leakage. The filter needs every season's promoted set
        because it replays the whole window and applies the summer reset at each boundary.
        """
        self._promoted = promoted

    def set_prediction_season(self, season: str) -> None:
        self._prediction_season = season

    def _fallback_params(self) -> tuple[float, float, float]:
        return (
            self._policy.fallback_learning_rate,
            self._policy.fallback_retention,
            self._policy.fallback_season_retention,
        )

    # -- rate logic (shared by fitting and prediction) -------------------------------

    def _side_rate(
        self,
        attack: dict[int, float],
        defence: dict[int, float],
        counts: dict[int, int],
        team: int,
        opponent: int,
        was_home: bool,
        season: str,
        venue_home: float,
        venue_away: float,
    ) -> float:
        """Pre-match rate for one side, applying the six-match cold-start rule.

        A club with fewer than the minimum eligible matches uses the declared prior -- the
        fold-local promoted ratio if it was promoted in this match's season, otherwise the
        neutral mean -- rather than a strength estimated from too little data. The same rule
        is applied to the fitting residual (fix 2), not only to prediction.
        """
        venue = venue_home if was_home else venue_away
        if counts.get(team, 0) >= self._minimum_team_matches:
            attack_log = attack.get(team, 0.0)
        else:
            attack_log = (
                self._prior_attack_log if team in self._promoted.get(season, frozenset()) else 0.0
            )
        if counts.get(opponent, 0) >= self._minimum_team_matches:
            defence_log = defence.get(opponent, 0.0)
        else:
            defence_log = (
                self._prior_defence_log
                if opponent in self._promoted.get(season, frozenset())
                else 0.0
            )
        return max(venue * math.exp(attack_log + defence_log), self._policy.rate_floor)

    def _ensure_club(
        self,
        attack: dict[int, float],
        defence: dict[int, float],
        counts: dict[int, int],
        club: int,
        season: str,
    ) -> None:
        """First appearance of a club seeds its log-strength and zero count."""
        if club not in counts:
            if club in self._promoted.get(season, frozenset()):
                attack[club] = self._prior_attack_log
                defence[club] = self._prior_defence_log
            else:
                attack[club] = 0.0
                defence[club] = 0.0
            counts[club] = 0

    def _apply_season_transition(
        self,
        attack: dict[int, float],
        defence: dict[int, float],
        counts: dict[int, int],
        new_season: str,
        season_retention: float,
    ) -> None:
        """Shrink every known club over the summer; reset every newly promoted club to cold.

        A club in the new season's promoted set -- never seen before, or relegated and back --
        is reset to the promoted prior with a zero eligible count (fix 3). Incumbents keep
        their count and shrink their strength by ``season_retention`` (declared retention).
        """
        promoted_now = self._promoted.get(new_season, frozenset())
        cap = self._policy.log_strength_cap
        for club in list(attack.keys()):
            if club in promoted_now:
                attack[club] = self._prior_attack_log
                defence[club] = self._prior_defence_log
                counts[club] = 0
            else:
                attack[club] = _clip(attack[club] * season_retention, cap)
                defence[club] = _clip(defence[club] * season_retention, cap)

    # -- chronological replay (build a state from a match sequence) ------------------

    def _replay(
        self,
        matches: Sequence[MatchRow],
        *,
        venue_home: float,
        venue_away: float,
        learning_rate: float,
        retention: float,
        season_retention: float,
    ) -> tuple[DynamicState, str | None]:
        """Replay matches chronologically, returning the final state and its last season.

        Both sides' pre-match rates are computed before either is updated, so a match's own
        outcome cannot affect its own predicted rate. The residual uses the cold-start rate
        (fix 2) and the summer transition resets promoted counts (fix 3). ``last_season`` is
        returned so a caller can chain a walk-forward holdout across a season boundary.
        """
        attack: dict[int, float] = {}
        defence: dict[int, float] = {}
        counts: dict[int, int] = {}
        cap = self._policy.log_strength_cap
        previous_season: str | None = None

        for match in matches:
            if previous_season is not None and match.season != previous_season:
                self._apply_season_transition(
                    attack, defence, counts, match.season, season_retention
                )
            previous_season = match.season
            home, away = match.home_code, match.away_code
            self._ensure_club(attack, defence, counts, home, match.season)
            self._ensure_club(attack, defence, counts, away, match.season)

            home_rate = self._side_rate(
                attack, defence, counts, home, away, True, match.season, venue_home, venue_away
            )
            away_rate = self._side_rate(
                attack, defence, counts, away, home, False, match.season, venue_home, venue_away
            )
            home_residual = match.home_measure - home_rate
            away_residual = match.away_measure - away_rate
            attack[home] = _clip(attack[home] * retention + learning_rate * home_residual, cap)
            defence[away] = _clip(defence[away] * retention + learning_rate * home_residual, cap)
            attack[away] = _clip(attack[away] * retention + learning_rate * away_residual, cap)
            defence[home] = _clip(defence[home] * retention + learning_rate * away_residual, cap)
            counts[home] = counts.get(home, 0) + 1
            counts[away] = counts.get(away, 0) + 1

        state = DynamicState(
            attack=attack,
            defence=defence,
            counts=counts,
            venue_home=venue_home,
            venue_away=venue_away,
            rate_floor=self._policy.rate_floor,
        )
        return state, previous_season

    # -- per-gameweek walk-forward holdout scoring (the inner selection core) --------

    def _walk_forward_score(
        self,
        state: DynamicState,
        previous_season: str | None,
        batches: Sequence[Sequence[MatchRow]],
        *,
        venue_home: float,
        venue_away: float,
        learning_rate: float,
        retention: float,
        season_retention: float,
    ) -> float:
        """Score holdout gameweeks by a true walk-forward (fix 1), returning mean log score.

        Each batch is one observed gameweek. For each batch: apply the summer transition if the
        season changed, snapshot the pre-gameweek state, predict *every* fixture in the batch
        from that snapshot, score them, and only then absorb the whole gameweek's results before
        advancing counts and state to the next batch.

        Same-gameweek predictions and residuals all use the one pre-gameweek snapshot, so the
        batch's *scores* are order-invariant. Absorption occurs afterward, and because a
        double-gameweek club appears more than once the absorption order is observable in the
        resulting state: it is therefore enforced here in deterministic actual kickoff order
        (then season/fixture/stable team-code tie-breakers) rather than assumed from the caller.
        A double-gameweek club still receives one sequential update (and one retention) per
        appearance -- this fixes the order, it does not aggregate the appearances.
        """
        attack, defence, counts = state.attack, state.defence, state.counts
        cap = self._policy.log_strength_cap
        total = 0.0
        scored = 0
        current_season = previous_season

        for batch in batches:
            # Enforce actual chronological order so absorption (unlike prediction) does not
            # depend on the order the caller passed the fixtures in.
            ordered = sorted(
                batch, key=lambda m: (m.kickoff, m.season, m.fixture, m.home_code, m.away_code)
            )
            batch_season = ordered[0].season
            if current_season is not None and batch_season != current_season:
                self._apply_season_transition(
                    attack, defence, counts, batch_season, season_retention
                )
            current_season = batch_season
            for match in ordered:
                self._ensure_club(attack, defence, counts, match.home_code, batch_season)
                self._ensure_club(attack, defence, counts, match.away_code, batch_season)

            # Snapshot taken after seeding so first appearances use the cold prior.
            snapshot_attack = dict(attack)
            snapshot_defence = dict(defence)
            snapshot_counts = dict(counts)
            pending: list[tuple[MatchRow, float, float]] = []
            for match in ordered:
                home_rate = self._side_rate(
                    snapshot_attack,
                    snapshot_defence,
                    snapshot_counts,
                    match.home_code,
                    match.away_code,
                    True,
                    batch_season,
                    venue_home,
                    venue_away,
                )
                away_rate = self._side_rate(
                    snapshot_attack,
                    snapshot_defence,
                    snapshot_counts,
                    match.away_code,
                    match.home_code,
                    False,
                    batch_season,
                    venue_home,
                    venue_away,
                )
                total += log_score(poisson_pmf(home_rate), match.home_goals)
                total += log_score(poisson_pmf(away_rate), match.away_goals)
                scored += 2
                pending.append((match, home_rate, away_rate))

            # Absorb the whole gameweek at once: updates use the snapshot-computed residuals,
            # so a fixture's update never depends on another fixture in the same gameweek.
            for match, home_rate, away_rate in pending:
                home_residual = match.home_measure - home_rate
                away_residual = match.away_measure - away_rate
                attack[match.home_code] = _clip(
                    attack[match.home_code] * retention + learning_rate * home_residual, cap
                )
                defence[match.away_code] = _clip(
                    defence[match.away_code] * retention + learning_rate * home_residual, cap
                )
                attack[match.away_code] = _clip(
                    attack[match.away_code] * retention + learning_rate * away_residual, cap
                )
                defence[match.home_code] = _clip(
                    defence[match.home_code] * retention + learning_rate * away_residual, cap
                )
                counts[match.home_code] = counts.get(match.home_code, 0) + 1
                counts[match.away_code] = counts.get(match.away_code, 0) + 1

        return total / max(scored, 1)

    # -- fitting ---------------------------------------------------------------------

    def fit(self, window: TrainingWindow) -> None:
        frame = window.frame
        if self._prediction_season is None and not frame.is_empty():
            self._prediction_season = str(frame.sort("kickoff_time")["season"][-1])

        if frame.is_empty():
            self._state = DynamicState(rate_floor=self._policy.rate_floor)
            self._params = self._fallback_params()
            self._selected_inner = False
            self._inner_holdout_gameweeks = ()
            self._prior_attack_log = math.log(self._policy.fallback_attack_prior)
            self._prior_defence_log = math.log(self._policy.fallback_defence_prior)
            return

        venue_home, venue_away = self._venue_means(frame)
        # Final fold-local prior from the full training window: earlier promoted cohorts only,
        # current cohort excluded, neutral fallback when none are eligible (fix 4).
        self._prior_attack_log, self._prior_defence_log = self._fold_local_promoted_prior(
            frame, self._prediction_season
        )

        selected = self._select_hyperparameters(frame)
        if selected is None:
            self._params = self._fallback_params()
            self._selected_inner = False
        else:
            self._params = selected
            self._selected_inner = True

        rows = self._rows(frame)
        learning_rate, retention, season_retention = self._params
        if rows:
            self._state, last_season = self._replay(
                rows,
                venue_home=venue_home,
                venue_away=venue_away,
                learning_rate=learning_rate,
                retention=retention,
                season_retention=season_retention,
            )
            # Outer season-opening fold: the training window ends in a prior season, so the
            # replayed state never crossed the summer boundary into the prediction season. Apply
            # exactly one transition into the prediction season now -- returning promoted clubs
            # reset to cold and incumbents take their declared summer retention -- so GW1
            # predicts from the post-summer state. A fold whose training already includes the
            # prediction season ends with ``last_season == prediction_season`` and takes no
            # second transition (the replay already crossed the boundary once).
            if (
                last_season is not None
                and self._prediction_season is not None
                and last_season != self._prediction_season
            ):
                self._apply_season_transition(
                    self._state.attack,
                    self._state.defence,
                    self._state.counts,
                    self._prediction_season,
                    season_retention,
                )
        else:
            self._state = DynamicState(
                venue_home=venue_home, venue_away=venue_away, rate_floor=self._policy.rate_floor
            )

    def _select_hyperparameters(self, frame: pl.DataFrame) -> tuple[float, float, float] | None:
        """Pick (learning rate, retention, season retention) on a per-gameweek inner holdout.

        Every data-derived transform is fitted within the fold: the xG-to-goals scale comes
        from the inner training subset, the fold-local prior used during selection is estimated
        from the inner training subset only (so the holdout cannot move the prior), and the
        three knobs are chosen by predictive log score under a true walk-forward over the
        held-out gameweeks -- never on the predicted gameweek and never from one frozen state.
        """
        split = self._inner_holdout(frame)
        if split is None:
            return None
        inner_frame, holdout_frame, holdout_keys = split

        inner_scale = self._xg_scale(inner_frame)
        inner_rows = self._rows(inner_frame, xg_scale=inner_scale)
        if not inner_rows:
            return None

        inner_venue_home, inner_venue_away = self._venue_means(inner_frame)
        batches: list[list[MatchRow]] = []
        for season, gw in holdout_keys:
            sub = holdout_frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
            rows = self._rows(sub, xg_scale=inner_scale)
            if rows:
                batches.append(rows)
        if not batches:
            return None

        # Selection uses the inner-training prior; swap it in for the grid loop, then restore
        # the full-frame prior so the caller's prediction reads the right value.
        saved_prior = (self._prior_attack_log, self._prior_defence_log)
        selection_prior = self._fold_local_promoted_prior(inner_frame, self._prediction_season)
        self._prior_attack_log, self._prior_defence_log = selection_prior
        try:
            best: tuple[float, float, float] | None = None
            best_score = math.inf
            for learning_rate in self._policy.learning_rate:
                for retention in self._policy.retention:
                    for season_retention in self._policy.season_retention:
                        state, last_season = self._replay(
                            inner_rows,
                            venue_home=inner_venue_home,
                            venue_away=inner_venue_away,
                            learning_rate=learning_rate,
                            retention=retention,
                            season_retention=season_retention,
                        )
                        score = self._walk_forward_score(
                            state,
                            last_season,
                            batches,
                            venue_home=inner_venue_home,
                            venue_away=inner_venue_away,
                            learning_rate=learning_rate,
                            retention=retention,
                            season_retention=season_retention,
                        )
                        if score < best_score:
                            best, best_score = (
                                (
                                    learning_rate,
                                    retention,
                                    season_retention,
                                ),
                                score,
                            )
        finally:
            self._prior_attack_log, self._prior_defence_log = saved_prior
        return best

    def _inner_holdout(
        self, frame: pl.DataFrame
    ) -> tuple[pl.DataFrame, pl.DataFrame, tuple[tuple[str, int], ...]] | None:
        """Split the last N observed gameweek values, never N kickoff timestamps.

        Returns the inner-training frame, the holdout frame, and the holdout gameweek keys in
        chronological order so the caller can batch the holdout by observed gameweek.
        """
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

        holdout_keys_df = gameweeks.tail(holdout_count).select(["season", "gw"])
        holdout_keys = tuple(
            (str(row["season"]), int(row["gw"])) for row in holdout_keys_df.iter_rows(named=True)
        )
        self._inner_holdout_gameweeks = holdout_keys
        first_holdout = gameweeks.tail(holdout_count)["first_kickoff"].min()
        if first_holdout is None:
            return None
        inner = frame.filter(pl.col("kickoff_time") < first_holdout)
        holdout = frame.join(holdout_keys_df, on=["season", "gw"], how="semi")
        return inner, holdout, holdout_keys

    def _rows(self, frame: pl.DataFrame, *, xg_scale: float | None = None) -> list[MatchRow]:
        """Training matches as paired chronological rows, using xG where it was measured."""
        usable = frame.drop_nulls(["goals_for", "team_code", "opponent_team_code"]).sort(
            ["kickoff_time", "season", "fixture", "team_id"]
        )
        if usable.is_empty():
            return []
        scale = xg_scale if xg_scale is not None else self._xg_scale(usable)

        sides: dict[tuple[str, int], _Pair] = {}
        for row in usable.iter_rows(named=True):
            key = (str(row["season"]), int(row["fixture"]))
            pair = sides.get(key)
            if pair is None:
                pair = _Pair(key[0], key[1], row["kickoff_time"].timestamp())
                sides[key] = pair
            xg = row["team_xg"]
            measure = float(xg) * scale if xg is not None else float(row["goals_for"])
            goals = int(row["goals_for"])
            if row["was_home"]:
                pair.home_code = int(row["team_code"])
                pair.away_code = int(row["opponent_team_code"])
                pair.home_measure = measure
                pair.home_goals = goals
            else:
                pair.away_code = int(row["team_code"])
                pair.home_code = int(row["opponent_team_code"])
                pair.away_measure = measure
                pair.away_goals = goals

        matches = [match for pair in sides.values() if (match := pair.complete()) is not None]
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

    # -- fold-local promoted prior (fix 4) -------------------------------------------

    def _fold_local_promoted_prior(
        self, frame: pl.DataFrame, prediction_season: str | None
    ) -> tuple[float, float]:
        """Estimate the promoted cold-start prior from earlier cohorts inside the frame.

        Eligible cohorts are promoted clubs in seasons strictly before the prediction season
        whose matches appear in ``frame`` (so for the outer fold, only data with
        ``kickoff_time < as_of``; for inner selection, only inner-training data). The current
        promoted cohort is excluded from its own prior. Each cohort club contributes a
        shrinkage-weighted attack and defence ratio (mean of per-club ratios, not a ratio of
        pooled means); the prior is the cohort mean. With no eligible cohort the declared
        neutral fallback ``1.0 / 1.0`` applies. Appending later seasons cannot move an earlier
        fold's prior, because those rows are outside this frame.

        Attack and defence are counted separately by their *measured* (non-null) observations:
        ``promoted_prior_min_matches`` is a per-component threshold, not a row count. A club
        whose defence went unmeasured keeps its attack contribution and simply omits a defence
        ratio; it is never zero-filled. The two sides therefore fall back independently when no
        eligible component reaches the minimum.
        """
        fallback_attack = self._policy.fallback_attack_prior
        fallback_defence = self._policy.fallback_defence_prior
        if prediction_season is None or frame.is_empty():
            return math.log(fallback_attack), math.log(fallback_defence)

        min_matches = self._policy.promoted_prior_min_matches
        shrinkage = self._policy.promoted_prior_shrinkage_matches
        eligible_seasons = sorted(
            season for season in set(frame["season"].to_list()) if season < prediction_season
        )
        attack_ratios: list[float] = []
        defence_ratios: list[float] = []
        if eligible_seasons:
            usable = frame.drop_nulls(["goals_for"]).filter(
                pl.col("season").is_in(eligible_seasons)
            )
            if usable.height:
                league = usable.group_by("season", maintain_order=True).agg(
                    pl.col("goals_for").mean().alias("mu")
                )
                league_mean = {
                    str(row["season"]): float(row["mu"]) for row in league.iter_rows(named=True)
                }
                for season in eligible_seasons:
                    cohort = self._promoted.get(season, frozenset())
                    if not cohort:
                        continue
                    season_rows = usable.filter(pl.col("season") == season)
                    if season_rows.is_empty():
                        continue
                    per_club = (
                        season_rows.filter(pl.col("team_code").is_in(list(cohort)))
                        .group_by("team_code", maintain_order=True)
                        .agg(
                            pl.col("goals_for").drop_nulls().sum().alias("goals_for"),
                            pl.col("goals_for").is_not_null().sum().alias("goals_for_n"),
                            pl.col("goals_against").drop_nulls().sum().alias("goals_against"),
                            pl.col("goals_against").is_not_null().sum().alias("goals_against_n"),
                        )
                    )
                    for row in per_club.iter_rows(named=True):
                        mu = league_mean.get(season)
                        if mu is None or mu <= 0:
                            continue
                        attack_n = int(row["goals_for_n"])
                        defence_n = int(row["goals_against_n"])
                        # A component contributes only its own measured observations; a missing
                        # defence never drops the attack ratio nor is it read as zero.
                        if attack_n >= min_matches:
                            attack_ratios.append(
                                _shrunk_ratio(float(row["goals_for"]), attack_n, mu, shrinkage)
                            )
                        if defence_n >= min_matches:
                            defence_ratios.append(
                                _shrunk_ratio(float(row["goals_against"]), defence_n, mu, shrinkage)
                            )

        prior_attack = sum(attack_ratios) / len(attack_ratios) if attack_ratios else fallback_attack
        prior_defence = (
            sum(defence_ratios) / len(defence_ratios) if defence_ratios else fallback_defence
        )
        return math.log(prior_attack), math.log(prior_defence)

    # -- prediction ------------------------------------------------------------------

    def _match_rate(
        self, state: DynamicState, team: int, opponent: int, was_home: bool, season: str
    ) -> float:
        return self._side_rate(
            state.attack,
            state.defence,
            state.counts,
            team,
            opponent,
            was_home,
            season,
            state.venue_home,
            state.venue_away,
        )

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
            "holdout_walk_forward": self._policy.holdout_walk_forward,
            "cold_start_in_fitting": self._policy.cold_start_in_fitting,
            "returning_promoted_count_reset": self._policy.returning_promoted_count_reset,
            "promoted_prior_source": self._policy.promoted_prior_source,
            "promoted_prior_attack": math.exp(self._prior_attack_log),
            "promoted_prior_defence": math.exp(self._prior_defence_log),
        }

    def predict(self, fixtures: pl.DataFrame) -> list[Distribution]:
        """Exact Poisson marginal per side. No Monte Carlo: Stage A is analytically scored."""
        return [poisson_pmf(rate) for rate in self.predict_rates(fixtures)]
