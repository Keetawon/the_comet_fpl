"""Shared DEVELOPMENT diagnostics for the Stage C exposure-weighted candidate runners.

Used by BOTH the goals V4 runner and the assists V2 runner so the covered-season population
reconciliation, the underlying-Poisson-rate conservation report, and the hypothesis cohort slices
share ONE tested implementation. Nothing here is a promotion gate; every output is a DEVELOPMENT
DIAGNOSTIC. The frozen Stage C harness is composed (``run_*_fold`` / ``run_*_harness``), never
modified: per-prediction cohort slices are built from the harness's public per-fold records plus
candidate-independent tags derived from the frozen Stage B minutes baseline and the player's
trailing appeared history, so no frozen harness edit is required.

Candidate vs comparator population reconciliation: the candidate and each architecture comparator
are run on the SAME folds / eligible rows / gate, and their results are asserted to agree on folds
by season, total predictions, the required-baseline score reports, and the season / position /
home-away population counts. A disagreement suppresses the whole result as INVALID / UNPUBLISHABLE.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fpl.validate.attacking_metrics import AttackingScoreReport, score_attacking_predictions

if TYPE_CHECKING:
    from fpl.validate.attacking_assists_harness import AssistsHarnessResult
    from fpl.validate.attacking_harness import AttackingHarnessResult

# Cohort thresholds -- pre-registered diagnostics, documented in the reconciliation record.
# They cut the predicted distribution by candidate-independent exposure signals.
STARTER_MIN_MINUTES = 60.0  # E[minutes] >= 60 -> starter (aligned to the 60-minute bin boundary)
ROTATION_MIN_MINUTES = 15.0  # 15 <= E[minutes] < 60 -> rotation; < 15 -> substitute
LOW_EXPOSURE_MAX_MINUTES = (
    180.0  # trailing appeared minutes < 180 (avg < 36/min over <=5 apps) -> low
)
CONSERVATION_TOLERANCE = (
    1e-9  # |sum(player_lambda) - team_scale| tolerance for the conservation check
)

_COHORT_DIMENSIONS: tuple[str, ...] = (
    "expected_minutes",
    "measured_history",
    "cold_start",
    "transfer",
)


def _json_float(value: float) -> float | None:
    return value if math.isfinite(value) else None


# --------------------------------------------------------------------------------------
# Conservation (per coupled roster: sum(player_lambda) vs the team scale)
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RosterConservation:
    """One coupled roster's rate-conservation record (written during ``prepare``)."""

    season: str
    fixture: int
    team_code: int
    n_rates: int
    sum_rates: float
    team_scale: float
    path: str

    @property
    def abs_error(self) -> float:
        return abs(self.sum_rates - self.team_scale)


@dataclass
class FoldDiagnosticsSink:
    """Per-run accumulator wired into a candidate factory (conservation + per-fold exposure tags).

    ``conservation`` accumulates across folds; ``exposure_tags`` is overwritten on each
    ``prepare`` (the runner reads it between folds). A candidate writes here only when a sink is
    supplied, so the default baselines-only / offline-test paths are unchanged.
    """

    conservation: list[RosterConservation] = field(default_factory=list)
    # code -> (E[minutes] from the frozen Stage B baseline, trailing appeared minutes over last 5).
    exposure_tags: dict[int, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class ConservationReport:
    rosters_checked: int
    max_abs_error: float
    failures: int
    tolerance: float
    coupled_paths_included: tuple[str, ...]
    note: str

    def to_record(self, by_roster: Sequence[RosterConservation]) -> dict[str, object]:
        worst = sorted(by_roster, key=lambda r: r.abs_error, reverse=True)[:10]
        return {
            "rosters_checked": self.rosters_checked,
            "maximum_absolute_rate_conservation_error": _json_float(self.max_abs_error),
            "failures": self.failures,
            "tolerance": self.tolerance,
            "coupled_paths_included": list(self.coupled_paths_included),
            "note": self.note,
            "worst_rosters": [
                {
                    "season": r.season,
                    "fixture": r.fixture,
                    "team_code": r.team_code,
                    "n_rates": r.n_rates,
                    "sum_player_lambda": _json_float(r.sum_rates),
                    "team_scale": _json_float(r.team_scale),
                    "absolute_error": _json_float(r.abs_error),
                    "path": r.path,
                }
                for r in worst
            ],
        }


def build_conservation_report(
    sink: Sequence[RosterConservation],
    *,
    coupled_paths: tuple[str, ...],
    note: str,
    tolerance: float = CONSERVATION_TOLERANCE,
) -> ConservationReport:
    """Summarise per-roster conservation records into the asserted/reported aggregate."""
    checked = len(sink)
    max_err = max((r.abs_error for r in sink), default=0.0)
    failures = sum(1 for r in sink if r.abs_error > tolerance)
    return ConservationReport(
        rosters_checked=checked,
        max_abs_error=max_err,
        failures=failures,
        tolerance=tolerance,
        coupled_paths_included=coupled_paths,
        note=note,
    )


# --------------------------------------------------------------------------------------
# Candidate-independent cohort tagging + scoring
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TaggedPrediction:
    """One prediction with its candidate-independent cohort tags, for cohort scoring."""

    model_predictions: Mapping[str, tuple[float, ...]]  # {model_name: GoalCountDistribution}
    outcome: int
    is_cold_start: bool
    expected_minutes: float
    trailing_appeared_minutes: float
    transferred: bool


def cohort_buckets(tagged: TaggedPrediction) -> dict[str, str]:
    """The four cohort dimensions for one tagged prediction (candidate-independent)."""
    e = tagged.expected_minutes
    exp_bucket = (
        "starter"
        if e >= STARTER_MIN_MINUTES
        else "rotation"
        if e >= ROTATION_MIN_MINUTES
        else "substitute"
    )
    if tagged.is_cold_start:
        history_bucket = "cold"
    elif tagged.trailing_appeared_minutes < LOW_EXPOSURE_MAX_MINUTES:
        history_bucket = "low_exposure"
    else:
        history_bucket = "established"
    return {
        "expected_minutes": exp_bucket,
        "measured_history": history_bucket,
        "cold_start": "cold" if tagged.is_cold_start else "not_cold",
        "transfer": "transferred" if tagged.transferred else "not_transferred",
    }


def score_cohorts(
    tagged: Sequence[TaggedPrediction],
    *,
    model_names: Sequence[str],
    seed: int,
) -> dict[str, dict[str, dict[str, AttackingScoreReport]]]:
    """Score every cohort bucket x model: ``{dimension: {bucket: {model: report}}}``.

    Uses the same proper-scoring function the frozen harness uses, applied per cohort bucket.
    A model absent from a bucket is simply absent from that bucket's record.
    """
    buckets_of_tagged = [cohort_buckets(t) for t in tagged]
    # (dimension, bucket) -> model -> list of prediction indices.
    indices: dict[tuple[str, str], dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for idx, buckets in enumerate(buckets_of_tagged):
        for dim, bucket in buckets.items():
            for model in model_names:
                if model in tagged[idx].model_predictions:
                    indices[(dim, bucket)][model].append(idx)
    out: dict[str, dict[str, dict[str, AttackingScoreReport]]] = {
        dim: {} for dim in _COHORT_DIMENSIONS
    }
    for (dim, bucket), model_to_indices in indices.items():
        out[dim].setdefault(bucket, {})
        for model, idxs in model_to_indices.items():
            preds = [tagged[i].model_predictions[model] for i in idxs]
            outcomes = [tagged[i].outcome for i in idxs]
            cold = sum(1 for i in idxs if tagged[i].is_cold_start)
            out[dim][bucket][model] = score_attacking_predictions(
                preds, outcomes, cold_starts=cold, seed=seed
            )
    return out


def cohort_report_to_record(
    cohorts: Mapping[str, Mapping[str, Mapping[str, AttackingScoreReport]]],
    *,
    model_names: Sequence[str],
) -> dict[str, object]:
    """Serialise cohort scores to the reconciliation record shape."""
    record: dict[str, object] = {
        "dimensions": {
            "expected_minutes": {
                "thresholds": {
                    "starter_min_minutes": STARTER_MIN_MINUTES,
                    "rotation_min_minutes": ROTATION_MIN_MINUTES,
                },
                "buckets": ["substitute", "rotation", "starter"],
            },
            "measured_history": {
                "thresholds": {"low_exposure_max_minutes": LOW_EXPOSURE_MAX_MINUTES},
                "buckets": ["cold", "low_exposure", "established"],
            },
            "cold_start": {"buckets": ["not_cold", "cold"]},
            "transfer": {"buckets": ["not_transferred", "transferred"]},
        },
        "slices": {},
    }
    slices = {}
    for dim in _COHORT_DIMENSIONS:
        slices[dim] = {
            bucket: {
                m: _cohort_model_record(cohorts[dim][bucket][m])
                for m in model_names
                if dim in cohorts and bucket in cohorts[dim] and m in cohorts[dim][bucket]
            }
            for bucket in (
                "substitute",
                "rotation",
                "starter",
                "cold",
                "low_exposure",
                "established",
                "not_cold",
                "transferred",
                "not_transferred",
            )
            if dim in cohorts and bucket in cohorts[dim]
        }
    record["slices"] = slices
    return record


def _cohort_model_record(report: AttackingScoreReport) -> dict[str, object]:
    return {
        "predictions": report.predictions,
        "mean_log_score": _json_float(report.mean_log_score),
        "mean_ranked_probability_score": _json_float(report.mean_ranked_probability_score),
        "mean_brier_at_least_one": _json_float(report.mean_brier_at_least_one_goal),
        "cold_starts": report.cold_starts,
    }


def transferred_codes(con: object, season: str) -> set[int]:
    """Codes with >1 stint in ``season`` (a mid-season move), from ``mart_dim_player_stint``.

    Reconstructable without changing any frozen harness; empty if the table is absent.
    """
    try:
        rows = con.execute(  # type: ignore[attr-defined]
            "SELECT code FROM mart_dim_player_stint WHERE season = ? "
            "GROUP BY code HAVING count(*) > 1",
            [season],
        ).fetchall()
    except Exception:
        return set()
    return {int(r[0]) for r in rows}


# --------------------------------------------------------------------------------------
# Candidate-vs-comparator population reconciliation (req 4)
# --------------------------------------------------------------------------------------


def _report_signature(report: AttackingScoreReport) -> tuple[object, ...]:
    """A stable, comparable signature of a baseline score report (scalars + counts only)."""
    return (
        report.predictions,
        report.exclusions,
        report.cold_starts,
        report.mean_log_score,
        report.mean_ranked_probability_score,
        report.mean_brier_at_least_one_goal,
        report.pit_interval_80_coverage,
    )


def assert_population_reconciliation(
    candidate_result: AttackingHarnessResult | AssistsHarnessResult,
    comparator_result: AttackingHarnessResult | AssistsHarnessResult,
    *,
    candidate_name: str,
    comparator_name: str,
    label: str,
) -> None:
    """Raise ``PopulationReconciliationError`` if candidate & comparator runs disagree.

    Checks folds by season, total predictions, the required-baseline overall score reports, and the
    season / position / home-away population counts (a baseline's per-slice prediction count). All
    baselines are deterministic and scored on the identical eligible rows, so these must match.
    """
    if candidate_result.folds_by_season != comparator_result.folds_by_season:
        raise PopulationReconciliationError(
            f"{label}: folds_by_season differ between {candidate_name} and {comparator_name}: "
            f"{candidate_result.folds_by_season} vs {comparator_result.folds_by_season}"
        )
    if candidate_result.total_predictions != comparator_result.total_predictions:
        raise PopulationReconciliationError(
            f"{label}: total predictions differ ({candidate_result.total_predictions} vs "
            f"{comparator_result.total_predictions})"
        )
    baselines = candidate_result.baseline_names
    for baseline in baselines:
        if _report_signature(candidate_result.overall[baseline]) != _report_signature(
            comparator_result.overall[baseline]
        ):
            raise PopulationReconciliationError(
                f"{label}: required baseline {baseline!r} overall report differs between runs"
            )
        for season, cand_map in candidate_result.by_season.items():
            comp_map = comparator_result.by_season[season]
            if cand_map[baseline].predictions != comp_map[baseline].predictions:
                raise PopulationReconciliationError(
                    f"{label}: baseline {baseline!r} season {season} population differs"
                )
        for pos, cand_map in candidate_result.by_position.items():
            comp_map = comparator_result.by_position[pos]
            if cand_map[baseline].predictions != comp_map[baseline].predictions:
                raise PopulationReconciliationError(
                    f"{label}: baseline {baseline!r} position {pos} population differs"
                )
        for ha in ("home", "away"):
            if ha in candidate_result.by_home_away and ha in comparator_result.by_home_away:
                if (
                    candidate_result.by_home_away[ha][baseline].predictions
                    != comparator_result.by_home_away[ha][baseline].predictions
                ):
                    raise PopulationReconciliationError(
                        f"{label}: baseline {baseline!r} {ha} population differs"
                    )


def reconciliation_record(
    candidate_result: AttackingHarnessResult | AssistsHarnessResult,
    comparator_result: AttackingHarnessResult | AssistsHarnessResult,
    *,
    label: str,
    passed: bool,
) -> dict[str, object]:
    """The reconciliation summary stored in the record (counts + parity flag)."""
    return {
        "label": label,
        "passed": passed,
        "candidate_folds_by_season": dict(sorted(candidate_result.folds_by_season.items())),
        "comparator_folds_by_season": dict(sorted(comparator_result.folds_by_season.items())),
        "candidate_total_predictions": candidate_result.total_predictions,
        "comparator_total_predictions": comparator_result.total_predictions,
        "required_baselines": list(candidate_result.baseline_names),
        "folds_match": candidate_result.folds_by_season == comparator_result.folds_by_season,
        "predictions_match": candidate_result.total_predictions
        == comparator_result.total_predictions,
    }


class PopulationReconciliationError(RuntimeError):
    """Candidate and comparator runs did not score the identical population."""
