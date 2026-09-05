"""One clean retrospective-development evaluation of real Premier League SDP SOT.

This runner is intentionally separate from every prospective path. Historical SDP captures
may be used only through :class:`RetrospectiveBackfillView`, whose event-time cutoff is the
first kickoff of each target gameweek. Original capture timestamps remain later-known evidence.

The formal result is write-once and refuses a dirty worktree. Run the coverage-only audit before
committing the pre-registration, then run the outer evaluation exactly once from that clean commit::

    python -m fpl.validate.dev_v2_real_sot --coverage-only
    python -m fpl.validate.dev_v2_real_sot
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import yaml

from fpl.config import (
    V2RealSotRetrospectiveContract,
    config_dir,
    repo_root,
)
from fpl.features.pit import AsOf
from fpl.models.football_engine_v2 import MultiSignalTeamEngine, SignalSpec
from fpl.storage.db import connect, default_db_path
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow
from fpl.validate.metrics import (
    Distribution,
    expected_goals,
    log_score,
    poisson_pmf,
    relative_lift,
    score_predictions,
    standard_error,
)
from fpl.validate.retrospective_sdp import RetrospectiveBackfillView
from fpl.validate.v2_environment_harness import (
    Prediction,
    load_team_frame,
    observed_folds,
    promoted_team_codes,
)

logger = logging.getLogger("fpl.validate.dev_v2_real_sot")

CONFIG_FILE = "v2_real_sot_retrospective_evaluation.yaml"
COVERAGE_FILE = "v2_real_sot_retrospective_coverage.json"
CAPTURE_MANIFEST_FILE = "v2_real_sot_capture_manifest.json"
RESULT_FILE = "v2_real_sot_development.json"
FROZEN_V2_RESULT = "v2_team_environment_development.json"
FROZEN_V2_RESULT_SHA256 = "bb80b26f88a01f8aee803b1e0eff61b55cc1712625357d3444dd73b297bad6ac"

_CONTROL_SIGNALS: tuple[SignalSpec, ...] = (
    SignalSpec("goals", "goals"),
    SignalSpec("expected_goals", "expected_goals"),
)
_CANDIDATE_SIGNALS: tuple[SignalSpec, ...] = (
    *_CONTROL_SIGNALS,
    SignalSpec("shots_on_target", "shots_on_target"),
)


class RetrospectiveEvaluationError(RuntimeError):
    """The run would violate its frozen evidence or provenance contract."""


@dataclass(frozen=True, slots=True)
class RowSlice:
    season: str
    gw: int
    was_home: bool
    promoted: bool
    early_season: bool
    cold_start: bool
    sot_history_band: str


@dataclass(frozen=True, slots=True)
class ProvenanceSnapshot:
    head: str
    config_sha256: str
    database_sha256: str
    coverage_report_sha256: str
    capture_manifest_sha256: str
    source_sha256: Mapping[str, str]
    frozen_v2_result_sha256: str
    started_at_utc: str


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def require_clean_worktree(repo: Path) -> None:
    porcelain = _git(repo, "status", "--porcelain")
    if porcelain:
        raise RetrospectiveEvaluationError(
            "the real-SOT outer evaluation refuses a dirty worktree; commit the exact "
            "implementation and pre-registration before scoring:\n" + porcelain
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def _load_contract(path: Path) -> tuple[V2RealSotRetrospectiveContract, str]:
    raw = path.read_bytes()
    parsed = yaml.safe_load(raw)
    if not isinstance(parsed, dict):
        raise RetrospectiveEvaluationError(f"{path} did not parse to a mapping")
    return V2RealSotRetrospectiveContract.model_validate(parsed), hashlib.sha256(raw).hexdigest()


def _latest_archive_cutoff(frame: pl.DataFrame) -> AsOf:
    latest = frame["kickoff_time"].max()
    if not isinstance(latest, datetime):
        raise RetrospectiveEvaluationError("archive has no timezone-aware kickoff")
    return AsOf(latest + timedelta(microseconds=1))


def _capture_manifest(history: pl.DataFrame) -> dict[str, object]:
    columns = [
        "season",
        "fixture",
        "sdp_match_id",
        "capture_id",
        "source_known_at",
        "payload_sha256",
    ]
    missing = sorted(set(columns) - set(history.columns))
    if missing:
        raise RetrospectiveEvaluationError(f"retrospective history lacks provenance: {missing}")
    captures = (
        history.filter(pl.col("capture_id").is_not_null())
        .select(columns)
        .unique()
        .sort(["season", "fixture", "sdp_match_id", "capture_id"])
    )
    records: list[dict[str, object]] = []
    for row in captures.iter_rows(named=True):
        known_at = row["source_known_at"]
        records.append(
            {
                "season": str(row["season"]),
                "fixture": int(row["fixture"]),
                "sdp_match_id": int(row["sdp_match_id"]),
                "capture_id": str(row["capture_id"]),
                "known_at": (
                    known_at.isoformat() if isinstance(known_at, datetime) else str(known_at)
                ),
                "payload_sha256": str(row["payload_sha256"]),
            }
        )
    return {
        "schema_version": 1,
        "evidence_class": RetrospectiveBackfillView.EVIDENCE_CLASS,
        "provider": RetrospectiveBackfillView.PROVIDER,
        "provider_field": RetrospectiveBackfillView.PROVIDER_FIELD,
        "version_selection": RetrospectiveBackfillView.VERSION_POLICY,
        "capture_id_semantics": "raw_pl_sdp_payload.payload_id",
        "captures": records,
    }


def build_coverage_evidence(
    con: duckdb.DuckDBPyConnection,
    contract: V2RealSotRetrospectiveContract,
) -> tuple[dict[str, object], dict[str, object]]:
    """Measure feature coverage only; no model is instantiated or scored."""
    if contract.source.version_selection != RetrospectiveBackfillView.VERSION_POLICY:
        raise RetrospectiveEvaluationError("reader and contract version-selection policies differ")
    if contract.source.sot_provider_field != RetrospectiveBackfillView.PROVIDER_FIELD:
        raise RetrospectiveEvaluationError("reader and contract SOT field licences differ")
    archive = load_team_frame(con, provider="fpl_archive")
    if archive.is_empty():
        raise RetrospectiveEvaluationError("archive team frame is empty")
    history = RetrospectiveBackfillView(con, _latest_archive_cutoff(archive)).observed_real_sot()
    keys = ["season", "fixture", "team_code"]
    if history.select(keys).n_unique() != history.height:
        raise RetrospectiveEvaluationError("canonical retrospective SOT keys are not unique")
    joined = archive.drop("shots_on_target").join(
        history.select([*keys, "shots_on_target"]), on=keys, how="left", validate="1:1"
    )
    seasons: dict[str, dict[str, int | float | bool]] = {}
    selected: list[str] = []
    threshold = contract.population.minimum_joint_season_coverage
    for season in sorted(joined["season"].unique().to_list()):
        rows = joined.filter((pl.col("season") == season) & pl.col("goals").is_not_null())
        denominator = rows.height
        goals = rows["goals"].is_not_null().sum()
        xg = rows["expected_goals"].is_not_null().sum()
        sot = rows["shots_on_target"].is_not_null().sum()
        joint = rows.select(
            (
                pl.col("goals").is_not_null()
                & pl.col("expected_goals").is_not_null()
                & pl.col("shots_on_target").is_not_null()
            ).sum()
        ).item()
        coverage = float(joint / denominator) if denominator else 0.0
        eligible = bool(denominator and coverage >= threshold)
        if eligible:
            selected.append(str(season))
        seasons[str(season)] = {
            "completed_team_fixture_rows": denominator,
            "target_goals_non_null": int(goals),
            "archive_expected_goals_non_null": int(xg),
            "retrospective_sdp_sot_non_null": int(sot),
            "joint_non_null": int(joint),
            "joint_coverage": round(coverage, 8),
            "eligible": eligible,
        }
    if len(selected) < contract.population.minimum_eligible_seasons:
        raise RetrospectiveEvaluationError(
            f"only {len(selected)} season(s) meet coverage {threshold:.1%}; "
            f"need {contract.population.minimum_eligible_seasons}"
        )
    if tuple(selected) != tuple(contract.population.eligible_seasons):
        raise RetrospectiveEvaluationError(
            "coverage-derived seasons disagree with the pre-registration: "
            f"measured={selected}, frozen={contract.population.eligible_seasons}"
        )
    manifest = _capture_manifest(history)
    capture_rows = history.select("capture_id").n_unique()
    later_known = history.filter(pl.col("source_known_at") > pl.col("kickoff_time")).height
    report: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "audit_type": "coverage_only_no_candidate_scoring",
        "evidence_class": contract.evidence_class,
        "metric": {
            "provider": contract.source.sot_provider,
            "provider_field": contract.source.sot_provider_field,
            "local_field": contract.source.sot_local_field,
        },
        "version_selection": contract.source.version_selection,
        "minimum_joint_season_coverage": threshold,
        "minimum_eligible_seasons": contract.population.minimum_eligible_seasons,
        "seasons": seasons,
        "eligible_seasons": selected,
        "target_rows_in_eligible_seasons": sum(
            int(seasons[season]["completed_team_fixture_rows"]) for season in selected
        ),
        "canonical_captures": capture_rows,
        "retrospective_team_rows": history.height,
        "rows_captured_after_event": later_known,
        "known_at_rewritten": False,
    }
    return report, manifest


def write_coverage_evidence(
    *, db_path: Path, results_dir: Path, contract_path: Path
) -> tuple[Path, Path]:
    contract, _ = _load_contract(contract_path)
    con = connect(db_path, read_only=True)
    try:
        report, manifest = build_coverage_evidence(con, contract)
    finally:
        con.close()
    results_dir.mkdir(parents=True, exist_ok=True)
    coverage_path = results_dir / COVERAGE_FILE
    manifest_path = results_dir / CAPTURE_MANIFEST_FILE
    if coverage_path.exists() or manifest_path.exists():
        raise RetrospectiveEvaluationError(
            "coverage evidence already exists; refusing to overwrite a pre-registration input"
        )
    manifest_bytes = _json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)
    report["capture_manifest"] = {
        "path": str(manifest_path.relative_to(repo_root())).replace("\\", "/"),
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "fields": contract.provenance.sdp_version_manifest_fields,
    }
    coverage_path.write_bytes(_json_bytes(report))
    return coverage_path, manifest_path


def _engine(
    contract: V2RealSotRetrospectiveContract, signals: Sequence[SignalSpec]
) -> MultiSignalTeamEngine:
    policy = contract.engine
    walk = contract.walk_forward
    return MultiSignalTeamEngine(
        signals=signals,
        half_life_days=policy.half_life_days,
        prior_matches=policy.prior_matches,
        minimum_team_matches=walk.minimum_team_matches,
        inner_holdout_gameweeks=walk.inner_holdout_observed_gameweeks,
        minimum_inner_training_gameweeks=walk.minimum_inner_training_observed_gameweeks,
        weight_step=policy.weight_step,
        minimum_signal_coverage=policy.minimum_signal_coverage,
        promoted_attack_prior=policy.promoted_attack_prior,
        promoted_defence_prior=policy.promoted_defence_prior,
        rate_floor=policy.rate_floor,
        maximum_goals=policy.maximum_goals,
    )


def _baseline_frame(frame: pl.DataFrame) -> pl.DataFrame:
    return frame.with_columns(
        pl.col("goals").alias("goals_for"),
        pl.col("goals_allowed").alias("goals_against"),
        pl.col("expected_goals").alias("team_xg"),
        pl.col("expected_goals_conceded_measured").alias("team_xgc"),
        pl.lit(None, dtype=pl.Int32).alias("fdr"),
    )


def _sot_history_band(count: int, labels: Sequence[str]) -> str:
    if tuple(labels) != ("0", "1-2", "3-5", "6+"):
        raise RetrospectiveEvaluationError(f"unexpected SOT history bins: {labels}")
    if count == 0:
        return "0"
    if count <= 2:
        return "1-2"
    if count <= 5:
        return "3-5"
    return "6+"


def _fitted_signal_report(engine: MultiSignalTeamEngine) -> dict[str, dict[str, float | int]]:
    """Expose only fold-local signal coverage and scaling used by the fitted engine."""
    return {
        name: {
            "rows": signal.rows,
            "coverage": signal.coverage,
            "goal_scale": signal.goal_scale,
        }
        for name, signal in sorted(engine.fitted_signals.items())
    }


def run_walk_forward(
    con: duckdb.DuckDBPyConnection,
    contract: V2RealSotRetrospectiveContract,
) -> tuple[
    dict[str, list[Prediction]],
    dict[str, RowSlice],
    list[dict[str, object]],
    dict[str, int],
]:
    """Run baseline/control/candidate, always querying SOT at the fold cutoff."""
    frame = load_team_frame(con, provider=contract.source.target_provider)
    promoted = promoted_team_codes(con)
    eligible = set(contract.population.eligible_seasons)
    folds = [
        fold
        for fold in observed_folds(
            frame,
            minimum_prior_gameweeks=contract.walk_forward.minimum_training_observed_gameweeks,
        )
        if fold[0] in eligible
    ]
    names = (contract.baseline, contract.control.name, contract.candidate.name)
    blocks: dict[str, list[Prediction]] = {name: [] for name in names}
    slices: dict[str, RowSlice] = {}
    fold_reports: list[dict[str, object]] = []
    guards = {"event_time_violations": 0, "same_gameweek_overlap": 0, "identity_violations": 0}

    for season, gw, cutoff in folds:
        archive_training = frame.filter(pl.col("kickoff_time") < cutoff)
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        if archive_training.is_empty() or target.is_empty():
            continue
        retrospective = RetrospectiveBackfillView(con, AsOf(cutoff)).observed_real_sot()
        guards["event_time_violations"] += retrospective.filter(
            pl.col("kickoff_time") >= cutoff
        ).height
        target_keys = target.select(["season", "fixture", "team_code"])
        guards["same_gameweek_overlap"] += retrospective.join(
            target_keys, on=["season", "fixture", "team_code"], how="inner"
        ).height

        sot_columns = [
            "season",
            "fixture",
            "team_code",
            "shots_on_target",
            "capture_id",
            "source_known_at",
            "payload_sha256",
        ]
        candidate_training = archive_training.drop("shots_on_target").join(
            retrospective.select(sot_columns),
            on=["season", "fixture", "team_code"],
            how="left",
            validate="1:1",
        )
        if candidate_training.height != archive_training.height:
            raise RetrospectiveEvaluationError("SOT join changed the training population")

        control = _engine(contract, _CONTROL_SIGNALS)
        candidate = _engine(contract, _CANDIDATE_SIGNALS)
        for engine in (control, candidate):
            engine.set_promoted(promoted)
            engine.set_prediction_season(season)
        control.fit(archive_training)
        candidate.fit(candidate_training)

        baseline = TrailingGoalsAttackDefence()
        baseline.set_prediction_season(season)
        baseline.fit(TrainingWindow(_baseline_frame(archive_training)))
        baseline_distributions = baseline.predict(_baseline_frame(target))

        measured = retrospective.filter(pl.col("shots_on_target").is_not_null())
        attack_counts = dict(measured.group_by("team_code").len().iter_rows())
        defence_counts = dict(measured.group_by("opponent_team_code").len().iter_rows())
        fold_later_known = retrospective.filter(pl.col("source_known_at") > cutoff).height
        before = {name: len(rows) for name, rows in blocks.items()}
        for row, baseline_distribution in zip(
            target.iter_rows(named=True), baseline_distributions, strict=True
        ):
            goals = row["goals"]
            if goals is None or baseline_distribution is None:
                continue
            team = int(row["team_code"])
            opponent = int(row["opponent_team_code"])
            was_home = bool(row["was_home"])
            key = f"{season}:{row['fixture']}:{team}"
            if key in slices:
                raise RetrospectiveEvaluationError(f"duplicate target key {key}")
            control_rate = control.goal_rate(team, opponent, was_home)
            candidate_rate = candidate.goal_rate(team, opponent, was_home)
            cold_start = control.is_cold_start(team, opponent)
            history_matches = min(
                int(attack_counts.get(team, 0)), int(defence_counts.get(opponent, 0))
            )
            slices[key] = RowSlice(
                season=season,
                gw=gw,
                was_home=was_home,
                promoted=team in promoted.get(season, frozenset()),
                early_season=gw <= contract.reporting.early_season_observed_gameweeks,
                cold_start=cold_start,
                sot_history_band=_sot_history_band(
                    history_matches, contract.reporting.sot_history_bins
                ),
            )
            distributions: dict[str, Distribution] = {
                contract.baseline: baseline_distribution,
                contract.control.name: poisson_pmf(
                    control_rate, max_goals=contract.engine.maximum_goals
                ),
                contract.candidate.name: poisson_pmf(
                    candidate_rate, max_goals=contract.engine.maximum_goals
                ),
            }
            for name, distribution in distributions.items():
                if not math.isclose(sum(distribution), 1.0, abs_tol=1e-9):
                    raise RetrospectiveEvaluationError(f"{name} emitted non-unit mass for {key}")
                blocks[name].append(
                    Prediction(
                        season=season,
                        gw=gw,
                        key=key,
                        distribution=distribution,
                        observed=int(goals),
                        was_home=was_home,
                        cold_start=cold_start,
                        used_engine_signal=(
                            name == contract.candidate.name
                            and candidate.parameters.weights.get("shots_on_target", 0.0) > 0.0
                        ),
                    )
                )
        added = {name: len(blocks[name]) - before[name] for name in names}
        if len(set(added.values())) != 1:
            raise RetrospectiveEvaluationError(f"models scored different fold populations: {added}")
        fold_reports.append(
            {
                "season": season,
                "gw": gw,
                "as_of": cutoff.isoformat(),
                "training_rows": archive_training.height,
                "retrospective_rows": retrospective.height,
                "retrospective_sot_non_null": measured.height,
                "later_known_rows_permitted": fold_later_known,
                "target_rows": added[contract.candidate.name],
                "control_parameters": control.parameters.as_report(),
                "candidate_parameters": candidate.parameters.as_report(),
                "control_signal_fit": _fitted_signal_report(control),
                "candidate_signal_fit": _fitted_signal_report(candidate),
            }
        )

    key_sequences = [[row.key for row in blocks[name]] for name in names]
    if not key_sequences[0] or any(keys != key_sequences[0] for keys in key_sequences[1:]):
        raise RetrospectiveEvaluationError(
            "baseline, control, and candidate keys are not identical"
        )
    return blocks, slices, fold_reports, guards


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _sd(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    return math.sqrt(sum((value - average) ** 2 for value in values) / (len(values) - 1))


def _score_block(name: str, rows: Sequence[Prediction], *, seed: int) -> dict[str, Any]:
    report = score_predictions(
        name,
        [row.distribution for row in rows],
        [row.observed for row in rows],
        seed=seed,
        cold_starts=[row.cold_start for row in rows],
        rank_groups=[f"{row.season}:{row.gw}" for row in rows],
    )
    rates = [expected_goals(row.distribution) for row in rows]
    errors = [rate - row.observed for rate, row in zip(rates, rows, strict=True)]
    pit_bins = [0] * 10
    for value in report.pit_values:
        pit_bins[min(int(value * 10), 9)] += 1
    return {
        "model": name,
        "rows": report.predictions,
        "mean_log_score": report.mean_log_score,
        "mean_log_score_standard_error": report.mean_log_score_standard_error,
        "crps": report.mean_crps,
        "rps": report.mean_crps,
        "mean_poisson_deviance": report.mean_poisson_deviance,
        "pit_interval_80_coverage": report.pit_interval_80_coverage,
        "pit_interval_80_absolute_error": report.pit_interval_80_absolute_error,
        "pit_decile_counts": pit_bins,
        "mean_absolute_error": report.mean_absolute_error,
        "mean_error": _mean(errors),
        "mean_predictive_variance": report.mean_predictive_variance,
        "predicted_rate_mean": _mean(rates),
        "predicted_rate_standard_deviation": _sd(rates),
        "spearman_within_gameweek": (
            report.spearman_within_gameweek
            if math.isfinite(report.spearman_within_gameweek)
            else None
        ),
        "cold_starts": report.cold_starts,
    }


def _score_models(
    blocks: Mapping[str, Sequence[Prediction]], *, seed: int
) -> dict[str, dict[str, Any]]:
    return {name: _score_block(name, rows, seed=seed) for name, rows in blocks.items()}


def _filtered_blocks(
    blocks: Mapping[str, Sequence[Prediction]], keys: set[str]
) -> dict[str, list[Prediction]]:
    return {name: [row for row in rows if row.key in keys] for name, rows in blocks.items()}


def _slice_reports(
    blocks: Mapping[str, Sequence[Prediction]], slices: Mapping[str, RowSlice], *, seed: int
) -> dict[str, dict[str, dict[str, Any]]]:
    groups: dict[str, set[str]] = {}
    for key, row in slices.items():
        labels = (
            f"season:{row.season}",
            "venue:home" if row.was_home else "venue:away",
            "promoted:promoted" if row.promoted else "promoted:established",
            "season_phase:early" if row.early_season else "season_phase:later",
            "cold_start:cold_start" if row.cold_start else "cold_start:established",
            f"sot_history:{row.sot_history_band}",
        )
        for label in labels:
            groups.setdefault(label, set()).add(key)
    return {
        label: _score_models(_filtered_blocks(blocks, keys), seed=seed)
        for label, keys in sorted(groups.items())
        if keys
    }


def _pearson(left: Sequence[float], right: Sequence[float]) -> float | None:
    left_mean, right_mean = _mean(left), _mean(right)
    numerator = sum((x - left_mean) * (y - right_mean) for x, y in zip(left, right, strict=True))
    left_scale = math.sqrt(sum((x - left_mean) ** 2 for x in left))
    right_scale = math.sqrt(sum((y - right_mean) ** 2 for y in right))
    return None if left_scale == 0 or right_scale == 0 else numerator / (left_scale * right_scale)


def _paired_diagnostics(
    control: Sequence[Prediction], candidate: Sequence[Prediction]
) -> dict[str, float | None]:
    control_rates = [expected_goals(row.distribution) for row in control]
    candidate_rates = [expected_goals(row.distribution) for row in candidate]
    rate_delta = [
        candidate_rate - control_rate
        for control_rate, candidate_rate in zip(control_rates, candidate_rates, strict=True)
    ]
    loss_delta = [
        log_score(candidate_row.distribution, candidate_row.observed)
        - log_score(control_row.distribution, control_row.observed)
        for control_row, candidate_row in zip(control, candidate, strict=True)
    ]
    by_fold: dict[str, list[float]] = {}
    for row, delta in zip(candidate, loss_delta, strict=True):
        by_fold.setdefault(f"{row.season}:{row.gw}", []).append(delta)
    fold_deltas = [_mean(values) for values in by_fold.values()]
    return {
        "candidate_minus_control_mean_rate": _mean(rate_delta),
        "candidate_control_mean_absolute_rate_delta": _mean([abs(value) for value in rate_delta]),
        "candidate_control_rate_correlation": _pearson(control_rates, candidate_rates),
        "candidate_to_control_rate_sd_ratio": (
            _sd(candidate_rates) / _sd(control_rates) if _sd(control_rates) else None
        ),
        "candidate_minus_control_mean_log_loss": _mean(loss_delta),
        "paired_row_log_loss_standard_error": standard_error(loss_delta),
        "paired_gameweek_log_loss_standard_error": standard_error(fold_deltas),
    }


def _source_paths(root: Path) -> list[Path]:
    return [
        root / "src/fpl/validate/dev_v2_real_sot.py",
        root / "src/fpl/validate/retrospective_sdp.py",
        root / "src/fpl/models/football_engine_v2.py",
        root / "src/fpl/models/team_goals.py",
        root / "src/fpl/validate/baselines.py",
        root / "src/fpl/validate/metrics.py",
        root / "src/fpl/validate/v2_environment_harness.py",
        root / "src/fpl/config.py",
    ]


def _snapshot(
    *, root: Path, db_path: Path, config_path: Path, coverage_path: Path, manifest_path: Path
) -> ProvenanceSnapshot:
    require_clean_worktree(root)
    frozen_path = root / "results" / FROZEN_V2_RESULT
    frozen_sha = file_sha256(frozen_path)
    if frozen_sha != FROZEN_V2_RESULT_SHA256:
        raise RetrospectiveEvaluationError("the immutable prior V2 result artifact changed")
    return ProvenanceSnapshot(
        head=_git(root, "rev-parse", "HEAD"),
        config_sha256=file_sha256(config_path),
        database_sha256=file_sha256(db_path),
        coverage_report_sha256=file_sha256(coverage_path),
        capture_manifest_sha256=file_sha256(manifest_path),
        source_sha256={
            str(path.relative_to(root)).replace("\\", "/"): file_sha256(path)
            for path in _source_paths(root)
        },
        frozen_v2_result_sha256=frozen_sha,
        started_at_utc=datetime.now(UTC).isoformat(),
    )


def _verify_snapshot(
    snapshot: ProvenanceSnapshot,
    *,
    root: Path,
    db_path: Path,
    config_path: Path,
    coverage_path: Path,
    manifest_path: Path,
) -> None:
    require_clean_worktree(root)
    checks = {
        "HEAD": (_git(root, "rev-parse", "HEAD"), snapshot.head),
        "config": (file_sha256(config_path), snapshot.config_sha256),
        "database": (file_sha256(db_path), snapshot.database_sha256),
        "coverage report": (file_sha256(coverage_path), snapshot.coverage_report_sha256),
        "capture manifest": (file_sha256(manifest_path), snapshot.capture_manifest_sha256),
    }
    for label, (actual, expected) in checks.items():
        if actual != expected:
            raise RetrospectiveEvaluationError(f"{label} changed during evaluation")
    for relative, expected in snapshot.source_sha256.items():
        if file_sha256(root / relative) != expected:
            raise RetrospectiveEvaluationError(f"source changed during evaluation: {relative}")


def run_formal_evaluation(
    *, db_path: Path, results_dir: Path, contract_path: Path
) -> dict[str, Any]:
    root = repo_root()
    result_path = results_dir / RESULT_FILE
    coverage_path = results_dir / COVERAGE_FILE
    manifest_path = results_dir / CAPTURE_MANIFEST_FILE
    if result_path.exists():
        raise RetrospectiveEvaluationError(
            f"{result_path} already exists; the formal outer evaluation is write-once"
        )
    contract, parsed_config_sha = _load_contract(contract_path)
    declared_coverage = root / contract.population.coverage_report
    if declared_coverage.resolve() != coverage_path.resolve():
        raise RetrospectiveEvaluationError("runner and contract name different coverage evidence")
    snapshot = _snapshot(
        root=root,
        db_path=db_path,
        config_path=contract_path,
        coverage_path=coverage_path,
        manifest_path=manifest_path,
    )
    if parsed_config_sha != snapshot.config_sha256:
        raise RetrospectiveEvaluationError("parsed config bytes differ from provenance bytes")

    con = connect(db_path, read_only=True)
    try:
        current_coverage, current_manifest = build_coverage_evidence(con, contract)
        frozen_coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        frozen_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if frozen_coverage.get("capture_manifest", {}).get("sha256") != file_sha256(manifest_path):
            raise RetrospectiveEvaluationError("coverage report names a different capture manifest")
        for key in (
            "evidence_class",
            "metric",
            "version_selection",
            "minimum_joint_season_coverage",
            "seasons",
            "eligible_seasons",
            "target_rows_in_eligible_seasons",
            "canonical_captures",
            "retrospective_team_rows",
            "rows_captured_after_event",
            "known_at_rewritten",
        ):
            if frozen_coverage.get(key) != current_coverage.get(key):
                raise RetrospectiveEvaluationError(f"coverage evidence changed at {key}")
        if frozen_manifest != current_manifest:
            raise RetrospectiveEvaluationError("canonical SDP capture manifest changed")
        blocks, slices, fold_reports, guards = run_walk_forward(con, contract)
        if any(guards.values()):
            raise RetrospectiveEvaluationError(
                f"event-time, identity, or same-gameweek isolation failed: {guards}"
            )
        expected_rows = frozen_coverage.get("target_rows_in_eligible_seasons")
        if isinstance(expected_rows, bool) or not isinstance(expected_rows, int):
            raise RetrospectiveEvaluationError("coverage report has no integer target-row count")
        actual_rows = {name: len(rows) for name, rows in blocks.items()}
        if any(rows != expected_rows for rows in actual_rows.values()):
            raise RetrospectiveEvaluationError(
                f"scored population differs from frozen coverage: expected {expected_rows}, "
                f"actual={actual_rows}"
            )
    finally:
        con.close()

    overall = _score_models(blocks, seed=contract.random_seed)
    by_slice = _slice_reports(blocks, slices, seed=contract.random_seed)
    control = overall[contract.control.name]
    candidate = overall[contract.candidate.name]
    log_lift = relative_lift(float(control["mean_log_score"]), float(candidate["mean_log_score"]))
    crps_lift = relative_lift(float(control["crps"]), float(candidate["crps"]))
    season_checks = {
        season: (
            float(by_slice[f"season:{season}"][contract.candidate.name]["mean_log_score"])
            <= float(by_slice[f"season:{season}"][contract.control.name]["mean_log_score"])
        )
        for season in contract.population.eligible_seasons
    }
    gate: dict[str, dict[str, Any]] = {
        "minimum_relative_log_lift": {
            "threshold": contract.development_gate.minimum_relative_log_lift,
            "actual": log_lift,
            "pass": log_lift >= contract.development_gate.minimum_relative_log_lift,
        },
        "maximum_crps_relative_regression": {
            "threshold": contract.development_gate.maximum_crps_relative_regression,
            "actual_relative_lift": crps_lift,
            "pass": crps_lift >= -contract.development_gate.maximum_crps_relative_regression,
        },
        "pit_interval_80_maximum_absolute_error": {
            "threshold": contract.development_gate.pit_interval_80_maximum_absolute_error,
            "actual": candidate["pit_interval_80_absolute_error"],
            "pass": float(candidate["pit_interval_80_absolute_error"])
            <= contract.development_gate.pit_interval_80_maximum_absolute_error,
        },
        "no_season_log_score_regression": {
            "by_season": season_checks,
            "pass": all(season_checks.values()),
        },
        "event_time_and_batch_isolation": {
            "counts": guards,
            "pass": not any(guards.values()),
        },
        "identical_population": {
            "rows": {name: len(rows) for name, rows in blocks.items()},
            "pass": len({len(rows) for rows in blocks.values()}) == 1,
        },
    }
    development_gate_pass = all(bool(check["pass"]) for check in gate.values())
    if development_gate_pass:
        verdict = "SUPPORTED FOR RETROSPECTIVE DEVELOPMENT ONLY"
    elif log_lift <= 0.0:
        verdict = "REFUTED"
    else:
        verdict = "INCONCLUSIVE"
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "development_only",
        "evidence_class": contract.evidence_class,
        "verdict": verdict,
        "not_a_promotion": (
            "Later-captured historical SDP is retrospective development evidence only; "
            "strict prospective confirmation remains mandatory."
        ),
        "candidate": contract.candidate.name,
        "control": contract.control.name,
        "context_baseline": contract.baseline,
        "eligible_seasons": contract.population.eligible_seasons,
        "folds": len(fold_reports),
        "rows_scored": len(next(iter(blocks.values()))),
        "overall": overall,
        "by_slice": by_slice,
        "candidate_vs_control": {
            "relative_log_score_lift": log_lift,
            "relative_crps_lift": crps_lift,
            **_paired_diagnostics(blocks[contract.control.name], blocks[contract.candidate.name]),
        },
        "development_gate": {"pass": development_gate_pass, "checks": gate},
        "fold_parameters": fold_reports,
        "provenance": {
            "clean_worktree": True,
            "git_head": snapshot.head,
            "config_sha256": snapshot.config_sha256,
            "database_sha256": snapshot.database_sha256,
            "coverage_report_sha256": snapshot.coverage_report_sha256,
            "capture_manifest_sha256": snapshot.capture_manifest_sha256,
            "source_sha256": dict(snapshot.source_sha256),
            "frozen_v2_result_sha256": snapshot.frozen_v2_result_sha256,
            "sdp_version_selection": contract.source.version_selection,
            "sdp_capture_count": len(frozen_manifest["captures"]),
            "sdp_capture_manifest_fields": contract.provenance.sdp_version_manifest_fields,
            "random_seed": contract.random_seed,
            "started_at_utc": snapshot.started_at_utc,
            "completed_at_utc": datetime.now(UTC).isoformat(),
        },
    }
    _verify_snapshot(
        snapshot,
        root=root,
        db_path=db_path,
        config_path=contract_path,
        coverage_path=coverage_path,
        manifest_path=manifest_path,
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    with result_path.open("xb") as handle:
        handle.write(_json_bytes(report))
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Coverage audit or write-once retrospective real-SOT development evaluation."
    )
    parser.add_argument("--db", type=Path, default=default_db_path())
    parser.add_argument("--results", type=Path, default=repo_root() / "results")
    parser.add_argument("--coverage-only", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    contract_path = config_dir() / CONFIG_FILE
    if args.coverage_only:
        coverage, manifest = write_coverage_evidence(
            db_path=args.db, results_dir=args.results, contract_path=contract_path
        )
        print(f"coverage: {coverage}")
        print(f"capture manifest: {manifest}")
        return 0
    report = run_formal_evaluation(
        db_path=args.db, results_dir=args.results, contract_path=contract_path
    )
    control = report["overall"][report["control"]]
    candidate = report["overall"][report["candidate"]]
    comparison = report["candidate_vs_control"]
    print(
        f"{report['verdict']}: {report['rows_scored']} rows / {report['folds']} folds; "
        f"control log={control['mean_log_score']:.6f}, "
        f"candidate log={candidate['mean_log_score']:.6f}, "
        f"lift={comparison['relative_log_score_lift']:+.4%}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
