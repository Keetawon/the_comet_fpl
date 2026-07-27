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


@dataclass(frozen=True, slots=True)
class ScoreReport:
    """Everything the contract requires reported for one population of predictions."""

    name: str
    predictions: int
    mean_log_score: float
    mean_crps: float
    interval_80_coverage: float
    pit_interval_80_coverage: float
    mean_absolute_error: float
    pit_values: tuple[float, ...]

    @property
    def interval_80_absolute_error(self) -> float:
        """Distance from 80% using the *PIT* coverage, which is the attainable one.

        The naive interval measure cannot land on 80% for a count distribution and must not
        be used as a gate. A distribution over whole goals cannot be trimmed to an exact
        quantile, so the narrowest central interval holding *at least* 80% holds more --
        swept over rates 0.1 to 4.0 a perfectly specified Poisson covers 0.813 to 0.983, and
        0.92 to 0.97 across the 1.0-1.8 band where team goals actually sit. The randomised
        PIT restores continuity and lands on 0.798-0.803 for the same models.
        """
        return abs(self.pit_interval_80_coverage - 0.80)

    def as_row(self) -> dict[str, float | int | str]:
        return {
            "baseline": self.name,
            "predictions": self.predictions,
            "mean_log_score": round(self.mean_log_score, 5),
            "mean_crps": round(self.mean_crps, 5),
            "interval_80_coverage": round(self.interval_80_coverage, 4),
            "pit_interval_80_coverage": round(self.pit_interval_80_coverage, 4),
            "mae_goals": round(self.mean_absolute_error, 4),
        }


def score_predictions(
    name: str,
    distributions: Sequence[Distribution],
    observations: Sequence[int],
    *,
    seed: int,
) -> ScoreReport:
    """Score aligned predictions and outcomes. Both sequences must be the same population."""
    if len(distributions) != len(observations):
        raise ValueError(
            f"{len(distributions)} distributions against {len(observations)} observations"
        )
    if not distributions:
        raise ValueError("no predictions to score")

    generator = random.Random(seed)
    log_scores = []
    crps_scores = []
    covered = 0
    pit_covered = 0
    absolute_errors = []
    pit = []
    for distribution, observed in zip(distributions, observations, strict=True):
        log_scores.append(log_score(distribution, observed))
        crps_scores.append(crps(distribution, observed))
        covered += int(interval_covers(distribution, observed))
        absolute_errors.append(abs(expected_goals(distribution) - observed))
        transformed = randomised_pit(distribution, observed, generator)
        pit.append(transformed)
        pit_covered += int(0.1 <= transformed <= 0.9)

    return ScoreReport(
        name=name,
        predictions=len(distributions),
        mean_log_score=mean(log_scores),
        mean_crps=mean(crps_scores),
        interval_80_coverage=covered / len(distributions),
        pit_interval_80_coverage=pit_covered / len(distributions),
        mean_absolute_error=mean(absolute_errors),
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
