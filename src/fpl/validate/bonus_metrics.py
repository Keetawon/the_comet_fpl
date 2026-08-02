"""Scoring the bonus (0-3) marginal distribution against realised bonus.

The label is the recorded ``bonus`` (0-3), a component, never ``total_points`` (R1). The bonus
distribution is a four-length probability tuple over an ordered outcome, so the existing proper
scoring rules apply: mean log score (primary) and mean ranked probability score (the ordinal
CRPS analogue). Alongside the proper scores this reports the two decision-relevant accuracies the
deliverable exists to answer:

* **bonus points correctly assigned** -- the share of realised bonus points the model places on
  the players who actually earned them. Expected form: ``sum_p min(E[bonus_p], realised_p) /
  sum_p realised_p``. This is the literal "~X% accurate" number.
* **top-3 hit rate** -- did the predicted top-three (by expected bonus) match the actual bonus
  recipients, and did the predicted single best player win the 3-point award.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fpl.validate.metrics import crps, log_score, mean, standard_error


@dataclass(frozen=True, slots=True)
class BonusRecord:
    """One scored player-fixture bonus prediction."""

    season: str
    fixture: int
    code: int
    position: str
    distribution: tuple[float, float, float, float]
    expected_bonus: float
    realised_bonus: int


@dataclass(frozen=True, slots=True)
class BonusScoreReport:
    label: str
    predictions: int
    fixtures: int
    mean_log_score: float
    mean_log_score_standard_error: float
    mean_ranked_probability_score: float
    bonus_points_correctly_assigned: float
    bonus_points_correctly_assigned_hard: float
    total_realised_bonus: float
    top1_hit_rate: float
    top3_overlap_rate: float
    exact_podium_rate: float
    # The fixture-level rank metrics (hard assignment, top-1, top-3 overlap, exact podium) are only
    # meaningful when the records form COMPLETE fixtures. A per-position slice does not: it would
    # rank goalkeepers only against goalkeepers. When False those four fields are omitted.
    fixture_metrics_valid: bool = True

    def as_row(self) -> dict[str, float | int | str]:
        row: dict[str, float | int | str] = {
            "slice": self.label,
            "predictions": self.predictions,
            "fixtures": self.fixtures,
            "mean_log_score": round(self.mean_log_score, 5),
            "mean_log_score_se": round(self.mean_log_score_standard_error, 5),
            "mean_rps": round(self.mean_ranked_probability_score, 5),
            "bonus_correctly_assigned": round(self.bonus_points_correctly_assigned, 5),
            "total_realised_bonus": round(self.total_realised_bonus, 1),
        }
        if self.fixture_metrics_valid:
            row["bonus_correctly_assigned_hard"] = round(
                self.bonus_points_correctly_assigned_hard, 5
            )
            row["top1_hit_rate"] = round(self.top1_hit_rate, 5)
            row["top3_overlap_rate"] = round(self.top3_overlap_rate, 5)
            row["exact_podium_rate"] = round(self.exact_podium_rate, 5)
        return row


def _hard_podium_awards(records: Sequence[BonusRecord]) -> dict[int, int]:
    """Award 3/2/1 to the three highest expected-bonus players (deterministic tie-break)."""
    ordered = sorted(
        records,
        key=lambda r: (-r.expected_bonus, -r.distribution[3], -r.distribution[2], r.code),
    )
    awards: dict[int, int] = {}
    for rank, record in enumerate(ordered[:3]):
        awards[record.code] = 3 - rank
    return awards


def _fixture_metrics(records: Sequence[BonusRecord]) -> tuple[float, float, float, float]:
    """Per-fixture: matched-expected bonus, matched-hard bonus, top1 hit, top3 overlap, podium.

    Returns aggregatable sums, not rates: (matched_hard, top1_hit, top3_overlap, exact_podium).
    The expected-overlap numerator is summed at record grain by the caller.
    """
    recipients = {r.code for r in records if r.realised_bonus > 0}
    three_pointers = {r.code for r in records if r.realised_bonus == 3}

    ordered = sorted(
        records,
        key=lambda r: (-r.expected_bonus, -r.distribution[3], -r.distribution[2], r.code),
    )
    predicted_top3 = [record.code for record in ordered[:3]]

    top1_hit = 1.0 if predicted_top3 and predicted_top3[0] in three_pointers else 0.0
    overlap = len(set(predicted_top3) & recipients) / 3.0 if recipients else 0.0

    hard_awards = _hard_podium_awards(records)
    matched_hard = 0.0
    for record in records:
        matched_hard += min(hard_awards.get(record.code, 0), record.realised_bonus)

    # Exact podium: predicted (3,2,1) recipients match a realised (3,2,1) player exactly.
    exact = 0.0
    realised_awards = {r.code: r.realised_bonus for r in records}
    if all(
        realised_awards.get(code, 0) == 3 - rank for rank, code in enumerate(predicted_top3[:3])
    ):
        exact = 1.0
    return matched_hard, top1_hit, overlap, exact


def score_bonus_predictions(
    records: Sequence[BonusRecord],
    *,
    label: str,
    seed: int,
    include_fixture_metrics: bool = True,
) -> BonusScoreReport:
    """Score a population of bonus predictions. ``seed`` is accepted for interface parity.

    ``include_fixture_metrics`` must be False for slices that are not complete fixtures (per
    position), where a within-fixture rank would rank a position against itself.
    """
    if not records:
        return BonusScoreReport(
            label=label,
            predictions=0,
            fixtures=0,
            mean_log_score=0.0,
            mean_log_score_standard_error=0.0,
            mean_ranked_probability_score=0.0,
            bonus_points_correctly_assigned=0.0,
            bonus_points_correctly_assigned_hard=0.0,
            total_realised_bonus=0.0,
            top1_hit_rate=0.0,
            top3_overlap_rate=0.0,
            exact_podium_rate=0.0,
            fixture_metrics_valid=include_fixture_metrics,
        )

    log_scores: list[float] = []
    rps_scores: list[float] = []
    matched_expected = 0.0
    total_realised = 0.0
    for record in records:
        log_scores.append(log_score(record.distribution, record.realised_bonus))
        rps_scores.append(crps(record.distribution, record.realised_bonus))
        matched_expected += min(record.expected_bonus, float(record.realised_bonus))
        total_realised += record.realised_bonus

    fixtures: dict[tuple[str, int], list[BonusRecord]] = {}
    for record in records:
        fixtures.setdefault((record.season, record.fixture), []).append(record)

    matched_hard_total = 0.0
    top1_hits: list[float] = []
    top3_overlaps: list[float] = []
    podiums: list[float] = []
    if include_fixture_metrics:
        for fixture_records in fixtures.values():
            matched_hard, top1_hit, overlap, exact = _fixture_metrics(fixture_records)
            matched_hard_total += matched_hard
            top1_hits.append(top1_hit)
            top3_overlaps.append(overlap)
            podiums.append(exact)

    assigned = matched_expected / total_realised if total_realised > 0 else 0.0
    assigned_hard = matched_hard_total / total_realised if total_realised > 0 else 0.0

    return BonusScoreReport(
        label=label,
        predictions=len(records),
        fixtures=len(fixtures),
        mean_log_score=mean(log_scores),
        mean_log_score_standard_error=standard_error(log_scores),
        mean_ranked_probability_score=mean(rps_scores),
        bonus_points_correctly_assigned=assigned,
        bonus_points_correctly_assigned_hard=assigned_hard,
        total_realised_bonus=total_realised,
        top1_hit_rate=mean(top1_hits) if include_fixture_metrics else 0.0,
        top3_overlap_rate=mean(top3_overlaps) if include_fixture_metrics else 0.0,
        exact_podium_rate=mean(podiums) if include_fixture_metrics else 0.0,
        fixture_metrics_valid=include_fixture_metrics,
    )
