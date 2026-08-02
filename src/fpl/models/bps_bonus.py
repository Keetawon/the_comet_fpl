"""Hybrid BPS / bonus match-simulator (development-only, exploratory).

FPL awards bonus (3/2/1) to the top-three Bonus Points System (BPS) players in each match. BPS
is an Opta-driven per-player score whose full formula depends on inputs this repository does not
hold (key passes, big chances, crosses, pass-completion %, fouls, dribbles, the CBI inside/outside
split, saves inside/outside the box, big-chance saves). It therefore cannot be reconstructed
exactly. But an archive measurement shows ~96% of awarded bonus goes to players with a goal or
assist (75.5%) or a clean sheet (20.9%) -- components this project already models -- and only
~3.5% is pure hidden Opta. That motivates a HYBRID model:

    simulated BPS  =  exact part  +  empirical residual

* The **exact part** (:func:`exact_bps`) is the sum of the BPS values verified against official
  Premier League sources and stored in ``config/scoring_2026_27.yaml`` under ``bps:`` -- goals by
  position, penalty goals, assists, GK/DEF clean sheets, penalty saves, and CBI at +1 per 3. It is
  computed here from the recorded match components (the box-score events Stages A-C predict); this
  isolates BPS-reconstruction accuracy -- the hidden-Opta residual -- from component-prediction
  error, which is validated separately. A production integration would feed predicted component
  distributions in instead. NULLs are preserved: CBI is unmeasured before 2025-26 and never
  zero-filled, so its contribution folds into the residual on those rows.

* The **empirical residual** is a fold-local, point-in-time model of ``bps - exact_part`` fit from
  proxies (``influence`` -- the all-round/defensive BPS proxy -- ``creativity``, and the player's
  own trailing per-appearance residual profile). It captures the minutes/appearance tiers, saves,
  cards, and hidden Opta the exact part omits. Using ``influence``/``creativity`` as BPS proxies is
  legitimate: BPS is itself an Opta-index construct and the simulator is validated on realised
  bonus, not substituted into a goals model.

Bonus is a WITHIN-MATCH rank, which breaks per-player independence, so a whole fixture's players
are simulated jointly (:func:`simulate_fixture_bonus`): draw every player's BPS, rank, award
3/2/1 with the exact FPL tie-break (:func:`award_bonus`), and repeat over seeded Monte-Carlo draws
to get each player's bonus (0-3) marginal distribution.

This module is development-only and is never consumed by ``calculate_points`` or the Stage D points
composer.
"""

from __future__ import annotations

import bisect
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from fpl.config import BpsRules
from fpl.types import Position

# Bonus is a discrete outcome over {0, 1, 2, 3}. A four-length probability tuple, like the count
# distributions elsewhere, so the existing proper-scoring rules apply directly.
BONUS_OUTCOMES = 4

# Award for the starting rank of a tie-group: rank 1 -> 3, rank 2 -> 2, rank 3 -> 1, else 0. See
# award_bonus for why the whole FPL tie-break reduces to indexing this by the group's start rank.
_SLOT_AWARD: tuple[int, ...] = (3, 2, 1)


# --------------------------------------------------------------------------------------
# Player-fixture row
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlayerRow:
    """One player-fixture's recorded components, plus the BPS proxies and the labels.

    ``clearances_blocks_interceptions`` is ``None`` where unmeasured (before 2025-26); it is never
    read as zero. ``bps`` and ``bonus`` are the realised labels -- used to form the training
    residual and to score, never as a model input for the row being predicted.
    """

    code: int
    position: str
    minutes: int
    goals_scored: int
    assists: int
    clean_sheets: int
    penalties_saved: int
    clearances_blocks_interceptions: int | None
    influence: float
    creativity: float
    bps: int
    bonus: int
    # Sort key for trailing-history order: (kickoff_time epoch seconds, season, fixture).
    order_key: tuple[float, str, int] = (0.0, "", 0)

    @property
    def appeared(self) -> bool:
        return self.minutes > 0


# --------------------------------------------------------------------------------------
# Exact part
# --------------------------------------------------------------------------------------


def exact_bps(row: PlayerRow, bps: BpsRules) -> float:
    """The exactly-computable BPS for a player-fixture, from verified values only.

    Everything not covered here -- minutes tiers, saves, cards, own goals, penalties missed,
    goals conceded, the penalty-goal delta, CBI where unmeasured, and all hidden Opta -- is left
    to the residual. ``clearances_blocks_interceptions`` is added only where measured; a NULL
    contributes nothing to the exact part (and its true value is absorbed by the residual),
    which is different from adding zero.
    """
    position = Position(row.position)
    total = 0.0
    # Goals: position-scaled. Penalty goals are a flat 12 in the BPS, but the archive has no
    # penalties-scored flag, so all goals take the positional value and the (open-play - penalty)
    # delta folds into the residual.
    total += bps.goals[position] * row.goals_scored
    total += bps.assists * row.assists
    # Clean sheet: GK/DEF only, and only for a 60+ minute appearance (the FPL clean-sheet gate).
    if row.minutes >= 60 and row.clean_sheets > 0:
        total += bps.clean_sheets.points.get(position, 0)
    total += bps.penalties_saved * row.penalties_saved
    # CBI: +1 per 3, integer division. NULL (unmeasured) is skipped, not zero-filled.
    if row.clearances_blocks_interceptions is not None:
        units = row.clearances_blocks_interceptions // bps.clearances_blocks_interceptions.unit
        total += bps.clearances_blocks_interceptions.points * units
    return total


# --------------------------------------------------------------------------------------
# Bonus award: the exact FPL tie-break
# --------------------------------------------------------------------------------------


def award_bonus(values: Sequence[float]) -> list[int]:
    """Award 3/2/1 bonus to the top-three BPS players in a match, with FPL tie handling.

    The FPL tie rules are:

      * tie for 1st -> all tied get 3, and the next distinct player gets 1 (the 2 is skipped);
      * tie for 2nd -> 1st gets 3, all tied-2nd get 2 (no 1 is awarded);
      * tie for 3rd -> 3, 2, then all tied-3rd get 1.

    Every one of these reduces to a single formula. A tie-group beginning at 1-based rank ``r``
    (i.e. ``r - 1`` players have strictly greater BPS) occupies rank slots ``r, r+1, ...``; each
    member receives the award of the *best* slot in the group, and since the slot awards are
    non-increasing ``[3, 2, 1, 0, ...]`` that is simply the award at rank ``r``. So a player's
    bonus depends only on how many players have strictly greater BPS:

        bonus = 3 if 0 strictly-greater, 2 if exactly 1, 1 if exactly 2, else 0.

    Validated against the archive: this reproduces recorded bonus in 56,271 of 56,272 appeared
    player-rows (1,899 of 1,900 matches). The single exception (2021-22 fixture 8) is FPL's
    finer-grained internal BPS breaking a displayed tie at 28, which the public data cannot see.
    """
    result: list[int] = []
    for value in values:
        strictly_greater = sum(1 for other in values if other > value)
        result.append(_SLOT_AWARD[strictly_greater] if strictly_greater < len(_SLOT_AWARD) else 0)
    return result


# --------------------------------------------------------------------------------------
# Fold-local residual model
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionalResidual:
    """A position's fold-local residual model: a mean plus a ridge line on standardised proxies."""

    mean: float
    influence_mean: float
    influence_sd: float
    creativity_mean: float
    creativity_sd: float
    beta_influence: float
    beta_creativity: float
    sigma: float
    n: int


@dataclass(frozen=True, slots=True)
class ResidualModel:
    """Fold-local residual model: per-position lines, a global fallback, and player histories."""

    by_position: dict[str, PositionalResidual]
    fallback: PositionalResidual
    player_history: dict[int, list[float]]
    prior_strength: float
    trailing_window: int

    def _positional(self, position: str) -> PositionalResidual:
        model = self.by_position.get(position)
        if model is None or model.n < 2:
            return self.fallback
        return model

    def predict_mean(self, row: PlayerRow) -> float:
        """Predicted residual for an appeared target row: player role term + proxy correction."""
        model = self._positional(row.position)
        history = self.player_history.get(row.code, [])
        trailing = history[-self.trailing_window :]
        n = len(trailing)
        # Player role: trailing mean residual shrunk toward the positional mean.
        player_shrunk = (sum(trailing) + self.prior_strength * model.mean) / (
            n + self.prior_strength
        )
        z_influence = (row.influence - model.influence_mean) / model.influence_sd
        z_creativity = (row.creativity - model.creativity_mean) / model.creativity_sd
        return (
            player_shrunk
            + model.beta_influence * z_influence
            + model.beta_creativity * z_creativity
        )

    def sigma(self, position: str) -> float:
        return self._positional(position).sigma


def _standard_deviation(values: Sequence[float], mean: float, *, floor: float) -> float:
    if len(values) < 2:
        return floor
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    return max(math.sqrt(variance), floor)


def _fit_positional(
    residuals: Sequence[float],
    influences: Sequence[float],
    creativities: Sequence[float],
    *,
    ridge_lambda: float,
    sigma_floor: float,
    sd_floor: float,
) -> PositionalResidual:
    """Least-squares line of residual on standardised (influence, creativity) with ridge.

    Centring the residual on its mean removes the intercept, leaving a 2x2 ridge system solved
    in closed form. Standardising the two proxies fold-locally keeps the coefficients scale-free
    and the system well-conditioned.
    """
    n = len(residuals)
    mean = sum(residuals) / n if n else 0.0
    influence_mean = sum(influences) / n if n else 0.0
    creativity_mean = sum(creativities) / n if n else 0.0
    influence_sd = _standard_deviation(influences, influence_mean, floor=sd_floor)
    creativity_sd = _standard_deviation(creativities, creativity_mean, floor=sd_floor)

    if n < 2:
        return PositionalResidual(
            mean=mean,
            influence_mean=influence_mean,
            influence_sd=influence_sd,
            creativity_mean=creativity_mean,
            creativity_sd=creativity_sd,
            beta_influence=0.0,
            beta_creativity=0.0,
            sigma=max(sigma_floor, 0.0),
            n=n,
        )

    s11 = ridge_lambda
    s22 = ridge_lambda
    s12 = 0.0
    sy1 = 0.0
    sy2 = 0.0
    z1_values: list[float] = []
    z2_values: list[float] = []
    for residual, influence, creativity in zip(residuals, influences, creativities, strict=True):
        z1 = (influence - influence_mean) / influence_sd
        z2 = (creativity - creativity_mean) / creativity_sd
        y = residual - mean
        s11 += z1 * z1
        s22 += z2 * z2
        s12 += z1 * z2
        sy1 += z1 * y
        sy2 += z2 * y
        z1_values.append(z1)
        z2_values.append(z2)

    determinant = s11 * s22 - s12 * s12
    if abs(determinant) < 1e-12:
        beta_influence = 0.0
        beta_creativity = 0.0
    else:
        beta_influence = (sy1 * s22 - sy2 * s12) / determinant
        beta_creativity = (sy2 * s11 - sy1 * s12) / determinant

    squared_error = 0.0
    for residual, z1, z2 in zip(residuals, z1_values, z2_values, strict=True):
        prediction = mean + beta_influence * z1 + beta_creativity * z2
        squared_error += (residual - prediction) ** 2
    sigma = max(math.sqrt(squared_error / n), sigma_floor)

    return PositionalResidual(
        mean=mean,
        influence_mean=influence_mean,
        influence_sd=influence_sd,
        creativity_mean=creativity_mean,
        creativity_sd=creativity_sd,
        beta_influence=beta_influence,
        beta_creativity=beta_creativity,
        sigma=sigma,
        n=n,
    )


def fit_residual_model(
    training_rows: Sequence[PlayerRow],
    bps: BpsRules,
    *,
    prior_strength: float,
    trailing_window: int,
    ridge_lambda: float,
    sigma_floor: float,
    sd_floor: float,
    minimum_position_rows: int,
) -> ResidualModel:
    """Fit the residual model on appeared prior rows only (the caller enforces the as_of cutoff).

    Every quantity -- positional means, ridge lines, noise scale, and player histories -- is
    computed from the passed rows, so it is fold-local when the caller passes only rows with
    ``kickoff_time < as_of``.
    """
    by_position_rows: dict[str, list[PlayerRow]] = {}
    all_residuals: list[float] = []
    all_influence: list[float] = []
    all_creativity: list[float] = []
    player_history_rows: dict[int, list[PlayerRow]] = {}

    for row in training_rows:
        if not row.appeared:
            continue
        by_position_rows.setdefault(row.position, []).append(row)
        player_history_rows.setdefault(row.code, []).append(row)

    def residual_of(row: PlayerRow) -> float:
        return row.bps - exact_bps(row, bps)

    for row in training_rows:
        if not row.appeared:
            continue
        all_residuals.append(residual_of(row))
        all_influence.append(row.influence)
        all_creativity.append(row.creativity)

    fallback = _fit_positional(
        all_residuals,
        all_influence,
        all_creativity,
        ridge_lambda=ridge_lambda,
        sigma_floor=sigma_floor,
        sd_floor=sd_floor,
    )

    by_position: dict[str, PositionalResidual] = {}
    for position, rows in by_position_rows.items():
        if len(rows) < minimum_position_rows:
            continue
        by_position[position] = _fit_positional(
            [residual_of(row) for row in rows],
            [row.influence for row in rows],
            [row.creativity for row in rows],
            ridge_lambda=ridge_lambda,
            sigma_floor=sigma_floor,
            sd_floor=sd_floor,
        )

    player_history: dict[int, list[float]] = {}
    for code, rows in player_history_rows.items():
        ordered = sorted(rows, key=lambda r: r.order_key)
        player_history[code] = [residual_of(row) for row in ordered]

    return ResidualModel(
        by_position=by_position,
        fallback=fallback,
        player_history=player_history,
        prior_strength=prior_strength,
        trailing_window=trailing_window,
    )


# --------------------------------------------------------------------------------------
# Incremental sufficient statistics (fast expanding-window refits for the walk-forward)
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class PositionAccumulator:
    """Running sums for one position, so an expanding-window refit is O(1) per fold.

    Each appeared training row is added exactly once as the ``as_of`` cutoff advances; the
    ridge line, standardisation, and noise scale are then reconstructed from these sums,
    yielding the same :class:`PositionalResidual` as a batch fit over the same rows.
    """

    n: int = 0
    sum_r: float = 0.0
    sum_rr: float = 0.0
    sum_i: float = 0.0
    sum_ii: float = 0.0
    sum_c: float = 0.0
    sum_cc: float = 0.0
    sum_ic: float = 0.0
    sum_ir: float = 0.0
    sum_cr: float = 0.0

    def add(self, residual: float, influence: float, creativity: float) -> None:
        self.n += 1
        self.sum_r += residual
        self.sum_rr += residual * residual
        self.sum_i += influence
        self.sum_ii += influence * influence
        self.sum_c += creativity
        self.sum_cc += creativity * creativity
        self.sum_ic += influence * creativity
        self.sum_ir += influence * residual
        self.sum_cr += creativity * residual


def positional_from_accumulator(
    accumulator: PositionAccumulator,
    *,
    ridge_lambda: float,
    sigma_floor: float,
    sd_floor: float,
) -> PositionalResidual:
    """Reconstruct a :class:`PositionalResidual` from running sums (equal to the batch fit)."""
    n = accumulator.n
    mean = accumulator.sum_r / n if n else 0.0
    influence_mean = accumulator.sum_i / n if n else 0.0
    creativity_mean = accumulator.sum_c / n if n else 0.0

    centred_ii = accumulator.sum_ii - n * influence_mean * influence_mean
    centred_cc = accumulator.sum_cc - n * creativity_mean * creativity_mean
    influence_sd = max(math.sqrt(max(centred_ii, 0.0) / (n - 1)), sd_floor) if n >= 2 else sd_floor
    creativity_sd = max(math.sqrt(max(centred_cc, 0.0) / (n - 1)), sd_floor) if n >= 2 else sd_floor

    if n < 2:
        return PositionalResidual(
            mean=mean,
            influence_mean=influence_mean,
            influence_sd=influence_sd,
            creativity_mean=creativity_mean,
            creativity_sd=creativity_sd,
            beta_influence=0.0,
            beta_creativity=0.0,
            sigma=max(sigma_floor, 0.0),
            n=n,
        )

    centred_ic = accumulator.sum_ic - n * influence_mean * creativity_mean
    centred_ir = accumulator.sum_ir - n * influence_mean * mean
    centred_cr = accumulator.sum_cr - n * creativity_mean * mean
    centred_rr = accumulator.sum_rr - n * mean * mean

    sum_z1z1 = centred_ii / (influence_sd * influence_sd)
    sum_z2z2 = centred_cc / (creativity_sd * creativity_sd)
    sum_z1z2 = centred_ic / (influence_sd * creativity_sd)
    sum_z1y = centred_ir / influence_sd
    sum_z2y = centred_cr / creativity_sd

    a11 = sum_z1z1 + ridge_lambda
    a22 = sum_z2z2 + ridge_lambda
    a12 = sum_z1z2
    determinant = a11 * a22 - a12 * a12
    if abs(determinant) < 1e-12:
        beta_influence = 0.0
        beta_creativity = 0.0
    else:
        beta_influence = (sum_z1y * a22 - sum_z2y * a12) / determinant
        beta_creativity = (sum_z2y * a11 - sum_z1y * a12) / determinant

    residual_sum_squares = (
        centred_rr
        - 2.0 * beta_influence * sum_z1y
        - 2.0 * beta_creativity * sum_z2y
        + beta_influence * beta_influence * sum_z1z1
        + beta_creativity * beta_creativity * sum_z2z2
        + 2.0 * beta_influence * beta_creativity * sum_z1z2
    )
    sigma = max(math.sqrt(max(residual_sum_squares, 0.0) / n), sigma_floor)

    return PositionalResidual(
        mean=mean,
        influence_mean=influence_mean,
        influence_sd=influence_sd,
        creativity_mean=creativity_mean,
        creativity_sd=creativity_sd,
        beta_influence=beta_influence,
        beta_creativity=beta_creativity,
        sigma=sigma,
        n=n,
    )


# --------------------------------------------------------------------------------------
# Fixture bonus simulation
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlayerBonusPrediction:
    code: int
    position: str
    distribution: tuple[float, float, float, float]
    expected_bonus: float
    exact_part: float
    predicted_bps_mean: float
    realised_bonus: int

    @property
    def probability_any_bonus(self) -> float:
        return 1.0 - self.distribution[0]


@dataclass(frozen=True, slots=True)
class BpsSimConfig:
    monte_carlo_draws: int = 500
    trailing_window: int = 10
    prior_strength: float = 10.0
    ridge_lambda: float = 1.0
    sigma_floor: float = 2.0
    sd_floor: float = 1e-6
    minimum_position_rows: int = 30
    seed: int = 202627
    residual_floor_at_no_appearance: bool = True


@dataclass(frozen=True, slots=True)
class FixtureSimulation:
    predictions: list[PlayerBonusPrediction] = field(default_factory=list)


def simulate_fixture_bonus(
    fixture_rows: Sequence[PlayerRow],
    model: ResidualModel,
    bps: BpsRules,
    config: BpsSimConfig,
    *,
    fixture_seed: int,
) -> FixtureSimulation:
    """Jointly simulate every appeared player's bonus in one match.

    Only appeared players (``minutes > 0``) can earn bonus, so the ranking population is the
    appeared rows. Each player's simulated BPS is ``exact_part + predicted_residual + N(0, sigma)``
    rounded to an integer (BPS is integer, and integer draws exercise the tie-break realistically).
    Over ``monte_carlo_draws`` seeded draws the players are ranked jointly and awarded 3/2/1 with
    :func:`award_bonus`; the per-player bonus marginal is the award frequency across draws.

    The RNG is seeded per fixture from a fixed base, and the players are processed in a fixed
    order (by ``code``), so the whole simulation is reproducible.
    """
    appeared = sorted((row for row in fixture_rows if row.appeared), key=lambda r: r.code)
    if not appeared:
        return FixtureSimulation(predictions=[])

    exact_parts = [exact_bps(row, bps) for row in appeared]
    means = [model.predict_mean(row) for row in appeared]
    sigmas = [model.sigma(row.position) for row in appeared]
    predicted_bps = [exact_parts[i] + means[i] for i in range(len(appeared))]

    draws = config.monte_carlo_draws
    player_count = len(appeared)
    counts = [[0, 0, 0, 0] for _ in appeared]
    rng = random.Random(fixture_seed)
    for _ in range(draws):
        rounded = [round(predicted_bps[i] + rng.gauss(0.0, sigmas[i])) for i in range(player_count)]
        # Award via strictly-greater count, identical to award_bonus but O(n log n): sort once,
        # then a bisect gives each player's number of strictly-greater draws.
        ordered = sorted(rounded)
        for index, value in enumerate(rounded):
            strictly_greater = player_count - bisect.bisect_right(ordered, value)
            award = _SLOT_AWARD[strictly_greater] if strictly_greater < len(_SLOT_AWARD) else 0
            counts[index][award] += 1

    predictions: list[PlayerBonusPrediction] = []
    for index, row in enumerate(appeared):
        distribution = tuple(count / draws for count in counts[index])
        expected = sum(bonus * probability for bonus, probability in enumerate(distribution))
        predictions.append(
            PlayerBonusPrediction(
                code=row.code,
                position=row.position,
                distribution=(distribution[0], distribution[1], distribution[2], distribution[3]),
                expected_bonus=expected,
                exact_part=exact_parts[index],
                predicted_bps_mean=predicted_bps[index],
                realised_bonus=row.bonus,
            )
        )
    return FixtureSimulation(predictions=predictions)
