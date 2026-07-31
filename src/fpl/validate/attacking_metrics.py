"""Proper scoring rules and calibration diagnostics for Stage C attacking goals.

Stage C predicts a discrete Poisson count distribution over player goals (0..10),
scored with proper scoring rules:
- mean log score (primary)
- mean ranked probability score (CRPS)
- mean Brier score on P(goals >= 1)
- randomised PIT interval 80% coverage
- reliability curve on P(goals >= 1)
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from fpl.models.attacking_baselines import GoalCountDistribution
from fpl.validate.metrics import crps, log_score, randomised_pit, standard_error


@dataclass(frozen=True, slots=True)
class ReliabilityBucket:
    lower: float
    upper: float
    n: int
    mean_predicted: float | None
    observed_rate: float | None


@dataclass(frozen=True, slots=True)
class ReliabilityCurve:
    buckets: tuple[ReliabilityBucket, ...]

    def total_n(self) -> int:
        return sum(bucket.n for bucket in self.buckets)


@dataclass(frozen=True, slots=True)
class AttackingScoreReport:
    predictions: int
    exclusions: int
    cold_starts: int
    uncertainty: float
    mean_log_score: float
    mean_ranked_probability_score: float
    mean_brier_at_least_one_goal: float
    pit_interval_80_coverage: float
    pit_interval_80_error: float
    reliability_at_least_one_goal: ReliabilityCurve


def score_attacking_predictions(
    predictions: Sequence[GoalCountDistribution],
    targets: Sequence[int],
    *,
    cold_starts: int = 0,
    seed: int = 202627,
) -> AttackingScoreReport:
    """Score a population of goal count predictions against observed goal counts."""
    if len(predictions) != len(targets):
        raise ValueError(f"prediction count ({len(predictions)}) != target count ({len(targets)})")

    n = len(predictions)
    if n == 0:
        empty_curve = ReliabilityCurve(
            tuple(
                ReliabilityBucket(
                    lower=round(i / 10.0, 1),
                    upper=round((i + 1) / 10.0, 1),
                    n=0,
                    mean_predicted=None,
                    observed_rate=None,
                )
                for i in range(10)
            )
        )
        return AttackingScoreReport(
            predictions=0,
            exclusions=0,
            cold_starts=0,
            uncertainty=0.0,
            mean_log_score=0.0,
            mean_ranked_probability_score=0.0,
            mean_brier_at_least_one_goal=0.0,
            pit_interval_80_coverage=0.0,
            pit_interval_80_error=0.0,
            reliability_at_least_one_goal=empty_curve,
        )

    log_scores: list[float] = []
    crps_scores: list[float] = []
    brier_scores: list[float] = []
    pit_values: list[float] = []
    rng = random.Random(seed)

    # Reliability setup: 10 buckets
    edges = [round(i / 10.0, 1) for i in range(11)]
    bucket_preds: list[list[float]] = [[] for _ in range(10)]
    bucket_obs: list[list[float]] = [[] for _ in range(10)]

    for dist, obs in zip(predictions, targets, strict=True):
        ls = log_score(dist, obs)
        rs = crps(dist, obs)
        log_scores.append(ls)
        crps_scores.append(rs)

        # P(goals >= 1) = 1.0 - P(goals = 0)
        p_at_least_one = max(0.0, min(1.0, 1.0 - dist[0]))
        y_binary = 1.0 if obs >= 1 else 0.0
        brier = (p_at_least_one - y_binary) ** 2
        brier_scores.append(brier)

        pit = randomised_pit(dist, obs, rng)
        pit_values.append(pit)

        # Assign to reliability bucket
        b_idx = min(int(p_at_least_one * 10), 9)
        bucket_preds[b_idx].append(p_at_least_one)
        bucket_obs[b_idx].append(y_binary)

    mean_log = sum(log_scores) / n
    mean_crps = sum(crps_scores) / n
    mean_brier = sum(brier_scores) / n
    unc = standard_error(log_scores)

    # PIT 80% coverage: in [0.1, 0.9]
    pit_in_band = sum(1 for p in pit_values if 0.1 <= p <= 0.9)
    pit_cov = pit_in_band / n
    pit_err = abs(pit_cov - 0.80)

    # Build reliability buckets
    buckets: list[ReliabilityBucket] = []
    for i in range(10):
        b_preds = bucket_preds[i]
        b_obs = bucket_obs[i]
        b_n = len(b_preds)
        m_pred = sum(b_preds) / b_n if b_n > 0 else None
        o_rate = sum(b_obs) / b_n if b_n > 0 else None
        buckets.append(
            ReliabilityBucket(
                lower=edges[i],
                upper=edges[i + 1],
                n=b_n,
                mean_predicted=m_pred,
                observed_rate=o_rate,
            )
        )

    return AttackingScoreReport(
        predictions=n,
        exclusions=0,
        cold_starts=cold_starts,
        uncertainty=unc,
        mean_log_score=mean_log,
        mean_ranked_probability_score=mean_crps,
        mean_brier_at_least_one_goal=mean_brier,
        pit_interval_80_coverage=pit_cov,
        pit_interval_80_error=pit_err,
        reliability_at_least_one_goal=ReliabilityCurve(tuple(buckets)),
    )
