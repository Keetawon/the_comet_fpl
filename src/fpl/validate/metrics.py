"""Proper scoring rules and calibration diagnostics for count distributions.

Stage A predicts a distribution over team goals, so it is scored with proper scoring rules
rather than with a point-estimate error. `config/phase1_evaluation.yaml` fixes mean log score
as primary and mean CRPS as the second proper score; RMSE is deliberately absent, because the
quantity of interest is the whole distribution -- clean sheets need `P(conceded = 0)` exactly,
and the concession penalty is a step function at every second goal.

Distributions are plain tuples of probabilities over goals `0..MAX_GOALS`, with all remaining
mass folded into the final bin so they sum to 1. No numpy: the arrays are ten elements long
and adding a dependency for that would not be justified.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass

# Ten goals is far beyond anything observed for one team in a Premier League match; the
# residual mass is folded into the last bin so every distribution is proper.
MAX_GOALS = 10

# Log score is unbounded when a model assigns zero probability to what happened. Rather than
# returning infinity -- which would make one row dominate every aggregate -- the probability
# is floored, and the floor is small enough to remain a severe penalty.
_PROBABILITY_FLOOR = 1e-12

type Distribution = tuple[float, ...]


def poisson_pmf(rate: float, *, max_goals: int = MAX_GOALS) -> Distribution:
    """A Poisson distribution truncated at `max_goals`, with the tail folded into the end."""
    if rate < 0:
        raise ValueError(f"rate must be non-negative, got {rate}")
    rate = max(rate, 1e-9)
    masses = []
    log_rate = math.log(rate)
    for goals in range(max_goals):
        log_p = -rate + goals * log_rate - math.lgamma(goals + 1)
        masses.append(math.exp(log_p))
    masses.append(max(0.0, 1.0 - sum(masses)))
    return tuple(masses)


def normalise(masses: Sequence[float]) -> Distribution:
    total = sum(masses)
    if total <= 0:
        raise ValueError("distribution has no mass")
    return tuple(mass / total for mass in masses)


def cdf(distribution: Distribution) -> tuple[float, ...]:
    running = 0.0
    out = []
    for mass in distribution:
        running += mass
        out.append(min(running, 1.0))
    return tuple(out)


def log_score(distribution: Distribution, observed: int) -> float:
    """Negative log probability of what actually happened. Lower is better."""
    index = min(max(observed, 0), len(distribution) - 1)
    return -math.log(max(distribution[index], _PROBABILITY_FLOOR))


def crps(distribution: Distribution, observed: int) -> float:
    """Ranked probability score, the discrete analogue of CRPS. Lower is better.

    Unlike log score this is sensitive to *how far* a wrong prediction was, so a model that
    puts its mass one goal away scores better than one that puts it four away. Reporting both
    is the contract's way of catching a candidate that games one of them.
    """
    observed = min(max(observed, 0), len(distribution) - 1)
    cumulative = cdf(distribution)
    return sum(
        (cumulative[goals] - (1.0 if observed <= goals else 0.0)) ** 2
        for goals in range(len(distribution))
    )


def randomised_pit(distribution: Distribution, observed: int, generator: random.Random) -> float:
    """Randomised probability integral transform, uniform on [0, 1] iff calibrated.

    A count distribution's plain PIT is discrete and cannot be uniform, which makes the usual
    histogram unreadable. Randomising within the observed bin restores uniformity under
    correct calibration, at the cost of needing a seed -- taken from the contract so a report
    is reproducible.
    """
    observed = min(max(observed, 0), len(distribution) - 1)
    cumulative = cdf(distribution)
    lower = cumulative[observed - 1] if observed > 0 else 0.0
    return lower + generator.random() * distribution[observed]


def central_interval(distribution: Distribution, coverage: float = 0.8) -> tuple[int, int]:
    """Narrowest central interval holding at least `coverage` probability."""
    tail = (1.0 - coverage) / 2.0
    cumulative = cdf(distribution)
    low = next((goals for goals, c in enumerate(cumulative) if c >= tail), 0)
    high = next(
        (goals for goals, c in enumerate(cumulative) if c >= 1.0 - tail),
        len(distribution) - 1,
    )
    return low, high


def interval_covers(distribution: Distribution, observed: int, coverage: float = 0.8) -> bool:
    low, high = central_interval(distribution, coverage)
    return low <= observed <= high


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else float("nan")


def expected_goals(distribution: Distribution) -> float:
    return sum(goals * mass for goals, mass in enumerate(distribution))


def predictive_variance(distribution: Distribution) -> float:
    expected = expected_goals(distribution)
    return sum((goals - expected) ** 2 * mass for goals, mass in enumerate(distribution))


def poisson_deviance(distribution: Distribution, observed: int) -> float:
    """Poisson deviance using the distribution mean as the fitted rate."""
    fitted = max(expected_goals(distribution), _PROBABILITY_FLOOR)
    if observed <= 0:
        return 2.0 * fitted
    return 2.0 * (observed * math.log(observed / fitted) - (observed - fitted))


def standard_error(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    variance = sum((value - average) ** 2 for value in values) / (len(values) - 1)
    return math.sqrt(variance / len(values))


def _average_ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][1] == ordered[index][1]:
            end += 1
        rank = (index + 1 + end) / 2.0
        for original, _ in ordered[index:end]:
            ranks[original] = rank
        index = end
    return ranks


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    if left_scale <= 0.0 or right_scale <= 0.0:
        return None
    return numerator / (left_scale * right_scale)


def spearman_within_groups(
    predictions: Sequence[float], observations: Sequence[int], groups: Sequence[str]
) -> float:
    """Mean Spearman correlation across scoreable gameweek groups."""
    grouped: dict[str, list[tuple[float, int]]] = {}
    for prediction, observation, group in zip(predictions, observations, groups, strict=True):
        grouped.setdefault(group, []).append((prediction, observation))
    correlations = []
    for rows in grouped.values():
        if len(rows) < 2:
            continue
        predicted_ranks = _average_ranks([row[0] for row in rows])
        observed_ranks = _average_ranks([float(row[1]) for row in rows])
        correlation = _pearson(predicted_ranks, observed_ranks)
        if correlation is not None:
            correlations.append(correlation)
    return mean(correlations)


@dataclass(frozen=True, slots=True)
class ScoreReport:
    """Everything the contract requires reported for one population of predictions."""

    name: str
    predictions: int
    eligible_predictions: int
    exclusions: int
    cold_starts: int
    mean_log_score: float
    mean_log_score_standard_error: float
    mean_crps: float
    mean_poisson_deviance: float
    interval_80_coverage: float
    pit_interval_80_coverage: float
    mean_absolute_error: float
    mean_predictive_variance: float
    spearman_within_gameweek: float
    pit_values: tuple[float, ...]

    @property
    def fixture_coverage(self) -> float:
        if self.eligible_predictions <= 0:
            return 0.0
        return self.predictions / self.eligible_predictions

    @property
    def pit_interval_80_absolute_error(self) -> float:
        """The contract's calibration gate, on the PIT coverage. Named for the config key.

        The raw central interval must not be gated, and the reason is sharper than it first
        looks. That interval is `[q0.1, q0.9]` with `q_p = min{g : F(g) >= p}`, so it covers
        `F(q0.9) - F(q0.1 - 1)`, which exceeds 0.80 by construction for any count
        distribution -- the excess is the discreteness of the pmf, not an error the model
        made. Swept over rates 0.1-4.0 a correctly specified Poisson covers 0.813 to 0.983
        and never 0.80.

        The consequence is not that the measure is merely strict but that it points the wrong
        way. At a true rate of 1.80 a correct model covers 0.964, missing 80% by 0.164, while
        a model predicting 2.40 covers 0.798 and misses by 0.0017: gating on the raw figure
        rejects the correct model and promotes one biased 33% high.

        The randomised PIT of a correctly specified model is exactly Uniform(0, 1), so its
        0.1-0.9 band coverage is exactly 0.80 at the truth and falls away from it. That is the
        quantity worth gating, and amendment 1.1 gates it.
        """
        return abs(self.pit_interval_80_coverage - 0.80)

    def as_row(self) -> dict[str, float | int | str]:
        return {
            "baseline": self.name,
            "predictions": self.predictions,
            "eligible_predictions": self.eligible_predictions,
            "exclusions": self.exclusions,
            "cold_starts": self.cold_starts,
            "fixture_coverage": round(self.fixture_coverage, 4),
            "mean_log_score": round(self.mean_log_score, 5),
            "mean_log_score_standard_error": round(self.mean_log_score_standard_error, 5),
            "mean_crps": round(self.mean_crps, 5),
            "poisson_deviance": round(self.mean_poisson_deviance, 5),
            "interval_80_coverage": round(self.interval_80_coverage, 4),
            "pit_interval_80_coverage": round(self.pit_interval_80_coverage, 4),
            "mae_goals": round(self.mean_absolute_error, 4),
            "mean_predictive_variance": round(self.mean_predictive_variance, 4),
            "spearman_within_gameweek": round(self.spearman_within_gameweek, 4),
        }


def score_predictions(
    name: str,
    distributions: Sequence[Distribution],
    observations: Sequence[int],
    *,
    seed: int,
    eligible_predictions: int | None = None,
    cold_starts: Sequence[bool] | None = None,
    rank_groups: Sequence[str] | None = None,
) -> ScoreReport:
    """Score aligned predictions and outcomes. Both sequences must be the same population."""
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

    generator = random.Random(seed)
    log_scores = []
    crps_scores = []
    deviances = []
    covered = 0
    pit_covered = 0
    absolute_errors = []
    predictive_variances = []
    expected = []
    pit = []
    for distribution, observed in zip(distributions, observations, strict=True):
        log_scores.append(log_score(distribution, observed))
        crps_scores.append(crps(distribution, observed))
        deviances.append(poisson_deviance(distribution, observed))
        covered += int(interval_covers(distribution, observed))
        predicted = expected_goals(distribution)
        expected.append(predicted)
        absolute_errors.append(abs(predicted - observed))
        predictive_variances.append(predictive_variance(distribution))
        transformed = randomised_pit(distribution, observed, generator)
        pit.append(transformed)
        pit_covered += int(0.1 <= transformed <= 0.9)

    return ScoreReport(
        name=name,
        predictions=len(distributions),
        eligible_predictions=eligible,
        exclusions=eligible - len(distributions),
        cold_starts=sum(resolved_cold_starts),
        mean_log_score=mean(log_scores),
        mean_log_score_standard_error=standard_error(log_scores),
        mean_crps=mean(crps_scores),
        mean_poisson_deviance=mean(deviances),
        interval_80_coverage=covered / len(distributions),
        pit_interval_80_coverage=pit_covered / len(distributions),
        mean_absolute_error=mean(absolute_errors),
        mean_predictive_variance=mean(predictive_variances),
        spearman_within_gameweek=spearman_within_groups(
            expected, observations, resolved_rank_groups
        ),
        pit_values=tuple(pit),
    )


def relative_lift(baseline: float, candidate: float) -> float:
    """`(baseline - candidate) / abs(baseline)`, exactly as the contract fixes it.

    Positive means the candidate improved on the baseline. Written here rather than inline so
    the promotion gate cannot quietly use a different formula.
    """
    if baseline == 0:
        raise ValueError("baseline score of zero has no defined relative lift")
    return (baseline - candidate) / abs(baseline)
