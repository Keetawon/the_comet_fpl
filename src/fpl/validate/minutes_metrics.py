"""Proper scoring rules and calibration diagnostics for the Stage B minutes distribution.

Stage B predicts a closed-form four-bin distribution over player minutes
(``0``, ``1_59``, ``60_89``, ``90``), so it is scored with proper scoring rules rather than a
point-estimate error. This slice implements exactly the metrics frozen in
``config/phase2_evaluation.yaml`` (contract 1.0): mean log score with the contract's
log-probability floor, the ranked probability score as the sum of squared ordered-CATEGORY CDF
errors (NOT a physical-minute distance), two Brier binary margins, a randomised PIT, two
reliability curves, and a within-group Spearman ranking of the 60-plus margin.

Every policy value -- the log floor, the PIT seed, the PIT band, and the reliability edges -- is
read from the :class:`~fpl.config.Phase2EvaluationConfig` passed to the scorer and never
hardcoded. There is deliberately NO raw central minute interval: gating a count/multinomial
distribution on ``[q0.1, q0.9]`` is biased by construction (see
``src/fpl/validate/metrics.py``), so only the randomised-PIT band is computed.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

from fpl.config import Phase2EvaluationConfig
from fpl.validate.metrics import (
    cdf,
    mean,
    randomised_pit,
    spearman_within_groups,
    standard_error,
)

# Re-exported so the Stage B harness has one import path; type alias matches minutes_baselines.
type MinutesDistribution = tuple[float, float, float, float]

# The four ordered minute bins are a contract invariant, not a magic number. A distribution that
# is not over exactly these four categories is rejected at validation time.
_N_BINS = 4

# A strict normalisation tolerance: a four-bin distribution must be proper to within float
# epsilon. Loose enough to accept honest count/n rounding, tight enough to catch a dropped bin.
_SUM_TOLERANCE = 1e-12


# --------------------------------------------------------------------------------------
# Frozen report types
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReliabilityBucket:
    """One reliability bucket for a binary margin.

    ``lower``/``upper`` are the contract grid edges; ``n`` is the count of predictions whose
    predicted probability fell in ``[lower, upper)`` (the final bucket is right-closed).
    ``mean_predicted`` and ``observed_rate`` are ``None`` for an empty bucket -- they are never
    fabricated as zero, because an unsampled bucket carries no calibration information.
    """

    lower: float
    upper: float
    n: int
    mean_predicted: float | None
    observed_rate: float | None


@dataclass(frozen=True, slots=True)
class ReliabilityCurve:
    """All ten reliability buckets for one binary margin, always emitted in full."""

    buckets: tuple[ReliabilityBucket, ...]

    def total_n(self) -> int:
        return sum(bucket.n for bucket in self.buckets)


@dataclass(frozen=True, slots=True)
class MinutesScoreReport:
    """Everything contract 1.0 requires reported for one population of minutes predictions."""

    name: str
    predictions: int
    eligible_predictions: int
    exclusions: int
    cold_starts: int
    mean_log_score: float
    mean_log_score_standard_error: float
    mean_ranked_probability_score: float
    mean_brier_any_minutes: float
    mean_brier_60_plus: float
    pit_interval_80_coverage: float
    pit_values: tuple[float, ...]
    reliability_any_minutes: ReliabilityCurve
    reliability_60_plus: ReliabilityCurve
    spearman_p60_within_position_gameweek: float
    prediction_coverage: float

    @property
    def pit_interval_80_absolute_error(self) -> float:
        """The contract's calibration gate metric: ``|pit_interval_80_coverage - 0.80|``.

        Mirrors the Phase 1 property so the promotion gate reads the same name. The raw central
        interval is intentionally absent (see module docstring); only the randomised-PIT band
        coverage is gated.
        """
        return abs(self.pit_interval_80_coverage - 0.80)

    def as_row(self) -> dict[str, float | int | str]:
        return {
            "model": self.name,
            "predictions": self.predictions,
            "eligible_predictions": self.eligible_predictions,
            "exclusions": self.exclusions,
            "cold_starts": self.cold_starts,
            "prediction_coverage": round(self.prediction_coverage, 4),
            "mean_log_score": round(self.mean_log_score, 5),
            "mean_log_score_standard_error": round(self.mean_log_score_standard_error, 5),
            "mean_ranked_probability_score": round(self.mean_ranked_probability_score, 5),
            "mean_brier_any_minutes": round(self.mean_brier_any_minutes, 5),
            "mean_brier_60_plus": round(self.mean_brier_60_plus, 5),
            "pit_interval_80_coverage": round(self.pit_interval_80_coverage, 4),
            "spearman_p60_within_position_gameweek": round(
                self.spearman_p60_within_position_gameweek, 4
            ),
        }


# --------------------------------------------------------------------------------------
# Metric primitives (operate on a single row; floor passed in, not hardcoded)
# --------------------------------------------------------------------------------------


def minutes_log_score(distribution: MinutesDistribution, observed: int, *, floor: float) -> float:
    """Negative log probability of the observed bin, floored so a one-hot zero is finite."""
    return -math.log(max(distribution[observed], floor))


def minutes_ranked_probability_score(distribution: MinutesDistribution, observed: int) -> float:
    """Sum of squared ordered-category CDF errors.

    The four bins are ORDERED CATEGORIES (0 < 1_59 < 60_89 < 90), so this is the ranked
    probability score -- NOT a physical-minute distance. A 0->90 miss is therefore not "90 units
    worse" than a 0->1 miss; both contribute through their CDF displacement only.
    """
    cumulative = cdf(distribution)
    return sum((cumulative[k] - (1.0 if observed <= k else 0.0)) ** 2 for k in range(_N_BINS))


def brier_any_minutes(distribution: MinutesDistribution, observed: int) -> float:
    """Squared error on the any-minutes margin.

    ``p = P(minutes > 0) = 1 - p0`` and ``y = (bin != 0)``.
    """
    probability = 1.0 - distribution[0]
    actual = 1.0 if observed != 0 else 0.0
    return (probability - actual) ** 2


def brier_60_plus(distribution: MinutesDistribution, observed: int) -> float:
    """Squared error on the 60-plus margin.

    ``p = P(minutes >= 60) = p2 + p3`` and ``y = (bin >= 2)``.
    """
    probability = distribution[2] + distribution[3]
    actual = 1.0 if observed >= 2 else 0.0
    return (probability - actual) ** 2


def probability_any_minutes(distribution: MinutesDistribution) -> float:
    """``P(minutes > 0) = 1 - p0`` -- the any-minutes reliability abscissa."""
    return 1.0 - distribution[0]


def probability_60_plus(distribution: MinutesDistribution) -> float:
    """``P(minutes >= 60) = p2 + p3`` -- the 60-plus reliability abscissa and Spearman predictor."""
    return distribution[2] + distribution[3]


# --------------------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------------------


def _validate_distribution(distribution: Sequence[float], index: int) -> None:
    if len(distribution) != _N_BINS:
        raise ValueError(
            f"a minutes distribution must have exactly {_N_BINS} probabilities, "
            f"got {len(distribution)} at row {index}"
        )
    for value in distribution:
        if isinstance(value, bool):
            raise TypeError("a minutes probability must be a non-bool float")
        if not math.isfinite(value):
            raise ValueError(f"a minutes probability must be finite at row {index}, got {value!r}")
        if value < 0.0:
            raise ValueError(
                f"a minutes probability must be non-negative at row {index}, got {value!r}"
            )
    total = math.fsum(distribution)
    if abs(total - 1.0) > _SUM_TOLERANCE:
        raise ValueError(
            f"a minutes distribution must sum to 1.0 within {_SUM_TOLERANCE}, got {total!r} "
            f"at row {index}"
        )


def _validate_observation(observed: object, index: int) -> None:
    if isinstance(observed, bool) or not isinstance(observed, int):
        raise TypeError(
            f"observed bin must be a non-bool int in 0..{_N_BINS - 1}, "
            f"got {observed!r} at row {index}"
        )
    if not 0 <= observed <= _N_BINS - 1:
        raise ValueError(f"observed bin must be in 0..{_N_BINS - 1}, got {observed} at row {index}")


# --------------------------------------------------------------------------------------
# Reliability
# --------------------------------------------------------------------------------------


def _bucket_index(probability: float, edges: Sequence[float]) -> int:
    """Index of the reliability bucket containing ``probability``.

    Buckets are ``[edges[i], edges[i+1])`` left-closed/right-open, except the final bucket which
    is right-closed so a probability of exactly 1.0 lands in it. ``probability`` is clamped into
    ``[edges[0], edges[-1]]`` to absorb float epsilon from validated distributions (a linear
    combination of probabilities that sum to 1.0 may round a hair outside); this never masks a
    malformed distribution because :func:`_validate_distribution` already rejected those.
    """
    clamped = min(max(probability, edges[0]), edges[-1])
    last = len(edges) - 2
    for i in range(len(edges) - 1):
        if i == last:
            if edges[i] <= clamped <= edges[i + 1]:
                return i
        elif edges[i] <= clamped < edges[i + 1]:
            return i
    # Unreachable for a monotone 0..1 grid, but fail closed rather than return a wrong bucket.
    raise ValueError(f"probability {probability!r} did not fall in any reliability bucket")


def _reliability_curve(
    probabilities: Sequence[float], observations: Sequence[int], edges: Sequence[float]
) -> ReliabilityCurve:
    n_buckets = len(edges) - 1
    counts = [0] * n_buckets
    predicted_sum = [0.0] * n_buckets
    observed_sum = [0.0] * n_buckets
    for probability, observed_binary in zip(probabilities, observations, strict=True):
        index = _bucket_index(probability, edges)
        counts[index] += 1
        predicted_sum[index] += probability
        observed_sum[index] += observed_binary
    buckets = []
    for i in range(n_buckets):
        n = counts[i]
        mean_predicted = predicted_sum[i] / n if n else None
        observed_rate = observed_sum[i] / n if n else None
        buckets.append(ReliabilityBucket(edges[i], edges[i + 1], n, mean_predicted, observed_rate))
    return ReliabilityCurve(tuple(buckets))


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def score_minutes_predictions(
    distributions: Sequence[MinutesDistribution],
    observations: Sequence[int],
    *,
    config: Phase2EvaluationConfig,
    eligible_predictions: int | None = None,
    cold_starts: Sequence[bool] | None = None,
    rank_groups: Sequence[str] | None = None,
    name: str = "",
) -> MinutesScoreReport:
    """Score aligned four-bin minutes predictions under the frozen contract.

    ``config`` supplies the log floor, PIT seed, PIT band, and reliability edges -- nothing about
    policy is hardcoded here. ``cold_starts`` and ``rank_groups`` must align with the predictions
    when supplied; ``rank_groups`` is the ``(season, gameweek, position)`` key per row, used for
    the within-group Spearman ranking of the 60-plus margin.
    """
    if len(distributions) != len(observations):
        raise ValueError(
            f"{len(distributions)} distributions against {len(observations)} observations"
        )
    if not distributions:
        raise ValueError("no predictions to score")

    eligible = len(distributions) if eligible_predictions is None else eligible_predictions
    if eligible < len(distributions):
        raise ValueError("eligible prediction count cannot be below scored predictions")

    resolved_cold_starts = [False] * len(distributions) if cold_starts is None else cold_starts
    resolved_rank_groups = ["all"] * len(distributions) if rank_groups is None else rank_groups
    if len(resolved_cold_starts) != len(distributions):
        raise ValueError("cold-start flags must align with predictions")
    if len(resolved_rank_groups) != len(distributions):
        raise ValueError("ranking groups must align with predictions")

    calibration = config.scoring_calibration
    floor = calibration.log_probability_floor
    band_low, band_high = calibration.randomized_pit_band
    edges = calibration.reliability_edges

    generator_seed = calibration.randomized_pit_seed

    log_scores: list[float] = []
    rps_scores: list[float] = []
    brier_any: list[float] = []
    brier_60: list[float] = []
    pit_values: list[float] = []
    pit_in_band = 0
    p_any: list[float] = []
    p_60: list[float] = []
    observed_any: list[int] = []
    observed_60: list[int] = []
    p_60_for_ranking: list[float] = []

    # A single generator, advanced row-by-row in input order: the PIT is reproducible for a fixed
    # row order and the contract seed, and changing either is a visible change to the report.
    generator = random.Random(generator_seed)
    for index, (distribution, observed) in enumerate(zip(distributions, observations, strict=True)):
        _validate_distribution(distribution, index)
        _validate_observation(observed, index)

        log_scores.append(minutes_log_score(distribution, observed, floor=floor))
        rps_scores.append(minutes_ranked_probability_score(distribution, observed))
        brier_any.append(brier_any_minutes(distribution, observed))
        brier_60.append(brier_60_plus(distribution, observed))

        transformed = randomised_pit(distribution, observed, generator)
        pit_values.append(transformed)
        pit_in_band += int(band_low <= transformed <= band_high)

        prob_any = probability_any_minutes(distribution)
        prob_60 = probability_60_plus(distribution)
        p_any.append(prob_any)
        p_60.append(prob_60)
        observed_any.append(1 if observed != 0 else 0)
        observed_60.append(1 if observed >= 2 else 0)
        p_60_for_ranking.append(prob_60)

    reliability_any = _reliability_curve(p_any, observed_any, edges)
    reliability_60 = _reliability_curve(p_60, observed_60, edges)

    spearman = spearman_within_groups(p_60_for_ranking, observed_60, resolved_rank_groups)

    n = len(distributions)
    return MinutesScoreReport(
        name=name,
        predictions=n,
        eligible_predictions=eligible,
        exclusions=eligible - n,
        cold_starts=sum(1 for flag in resolved_cold_starts if flag),
        mean_log_score=mean(log_scores),
        mean_log_score_standard_error=standard_error(log_scores),
        mean_ranked_probability_score=mean(rps_scores),
        mean_brier_any_minutes=mean(brier_any),
        mean_brier_60_plus=mean(brier_60),
        pit_interval_80_coverage=pit_in_band / n,
        pit_values=tuple(pit_values),
        reliability_any_minutes=reliability_any,
        reliability_60_plus=reliability_60,
        spearman_p60_within_position_gameweek=spearman,
        prediction_coverage=(n / eligible if eligible else 0.0),
    )
