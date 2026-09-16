"""Single preregistered retrospective SOT experiment with corroborated omitted zeros.

Reuses the frozen estimator, settings and scoring functions, not the frozen outer result.
All observed values and all older implementation/result files remain unchanged.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field

from fpl.config import V2RealSotRetrospectiveContract, config_dir, repo_root
from fpl.features.pit import AsOf
from fpl.models.football_engine_v2 import SignalSpec
from fpl.storage.db import connect, default_db_path
from fpl.validate import dev_v2_real_sot as prior
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow
from fpl.validate.metrics import poisson_pmf, relative_lift
from fpl.validate.sot_zero_audit import (
    INTERPRETED_COLUMN,
    CorroboratedSotBackfillView,
    build_audit,
    load_policy,
)
from fpl.validate.v2_environment_harness import (
    Prediction,
    load_team_frame,
    observed_folds,
    promoted_team_codes,
)

CONFIG_FILE = "v2_corroborated_zero_sot_evaluation.yaml"
RESULT_FILE = "v2_corroborated_zero_sot_development.json"
CANDIDATE = "retrospective_corroborated_zero_sot_team_environment_v2"
FROZEN_REAL_SOT_SHA = "32a3332dd92e30b160a632d6ad68ee268cbfd3367a27340e365583c2e9ca7e7d"
logger = logging.getLogger(__name__)
_KEYS = ["season", "fixture", "team_code"]


class SotZeroEvaluationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    contract_version: Literal["1.0"]
    candidate: Literal["retrospective_corroborated_zero_sot_team_environment_v2"]
    evidence_class: Literal["retrospective_backfill_development"]
    base_contract: Literal["config/v2_real_sot_retrospective_evaluation.yaml"]
    base_contract_sha256: Literal[
        "73ebf92613b8efb39838079b42b576afea2f2d43c775758372293c4d64edaed0"
    ]
    policy: Literal["config/pl_sdp_sot_zero_interpretation.yaml"]
    policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    coverage_audit: Literal["results/pl_sdp_sot_zero_audit.json"]
    coverage_audit_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    signals: tuple[
        Literal["goals"], Literal["expected_goals"], Literal["shots_on_target_corroborated"]
    ]
    formal_outer_runs: Literal[1]
    retain_fixture_distributions: Literal[True]
    promotion_permitted: Literal[False]


def load_contract(path: Path) -> tuple[SotZeroEvaluationContract, V2RealSotRetrospectiveContract]:
    contract = SotZeroEvaluationContract.model_validate(yaml.safe_load(path.read_bytes()))
    base, digest = prior._load_contract(repo_root() / contract.base_contract)
    if digest != contract.base_contract_sha256:
        raise prior.RetrospectiveEvaluationError("inherited frozen estimator contract changed")
    return contract, base


def validate_audit(
    con: duckdb.DuckDBPyConnection,
    contract: SotZeroEvaluationContract,
    base: V2RealSotRetrospectiveContract,
) -> dict[str, Any]:
    root = repo_root()
    for relative, expected in (
        (contract.policy, contract.policy_sha256),
        (contract.coverage_audit, contract.coverage_audit_sha256),
    ):
        if prior.file_sha256(root / relative) != expected:
            raise prior.RetrospectiveEvaluationError(f"preregistered input changed: {relative}")
    frozen: dict[str, Any] = json.loads((root / contract.coverage_audit).read_bytes())
    current = build_audit(con, load_policy(root / contract.policy))
    if any(frozen.get(k) != value for k, value in current.items()):
        raise prior.RetrospectiveEvaluationError("SOT raw evidence/interpretation changed")
    if frozen["policy_sha256"] != contract.policy_sha256:
        raise prior.RetrospectiveEvaluationError("SOT audit names another interpretation policy")
    if tuple(frozen["eligible_seasons"]) != base.population.eligible_seasons:
        raise prior.RetrospectiveEvaluationError("coverage-selected seasons changed")
    if len(frozen["eligible_seasons"]) < base.population.minimum_eligible_seasons:
        raise prior.RetrospectiveEvaluationError("insufficient coverage-eligible seasons")
    return frozen


def run_walk_forward(
    con: duckdb.DuckDBPyConnection,
    contract: SotZeroEvaluationContract,
    base: V2RealSotRetrospectiveContract,
    audit: Mapping[str, Any],
) -> tuple[dict[str, list[Prediction]], dict[str, prior.RowSlice], list[dict[str, Any]]]:
    frame = load_team_frame(con, provider="fpl_archive")
    promoted = promoted_team_codes(con)
    folds = [
        fold
        for fold in observed_folds(
            frame, minimum_prior_gameweeks=base.walk_forward.minimum_training_observed_gameweeks
        )
        if fold[0] in base.population.eligible_seasons
    ]
    names = (base.baseline, base.control.name, contract.candidate)
    blocks: dict[str, list[Prediction]] = {name: [] for name in names}
    slices: dict[str, prior.RowSlice] = {}
    fold_reports: list[dict[str, Any]] = []
    for index, (season, gw, cutoff) in enumerate(folds, 1):
        logger.info("Fold %s/%s: %s GW%s", index, len(folds), season, gw)
        training = frame.filter(pl.col("kickoff_time") < cutoff)
        target = frame.filter((pl.col("season") == season) & (pl.col("gw") == gw))
        history = CorroboratedSotBackfillView(con, AsOf(cutoff), audit).observed_corroborated_sot()
        if (
            history.filter(pl.col("kickoff_time") >= cutoff).height
            or history.join(target.select(_KEYS), on=_KEYS, how="inner").height
        ):
            raise prior.RetrospectiveEvaluationError(
                "future event or target gameweek entered history"
            )
        candidate_training = training.join(
            history.select([*_KEYS, INTERPRETED_COLUMN]), on=_KEYS, how="left", validate="1:1"
        )
        if candidate_training.height != training.height:
            raise prior.RetrospectiveEvaluationError(
                "SOT interpretation changed training population"
            )
        control = prior._engine(base, prior._CONTROL_SIGNALS)
        candidate = prior._engine(
            base, (*prior._CONTROL_SIGNALS, SignalSpec("shots_on_target", INTERPRETED_COLUMN))
        )
        for engine, data in ((control, training), (candidate, candidate_training)):
            engine.set_promoted(promoted)
            engine.set_prediction_season(season)
            engine.fit(data)
        baseline = TrailingGoalsAttackDefence()
        baseline.set_prediction_season(season)
        baseline.fit(TrainingWindow(prior._baseline_frame(training)))
        baseline_predictions = baseline.predict(prior._baseline_frame(target))
        measured = history.filter(pl.col(INTERPRETED_COLUMN).is_not_null())
        attack_counts = dict(measured.group_by("team_code").len().iter_rows())
        defence_counts = dict(measured.group_by("opponent_team_code").len().iter_rows())
        for row, baseline_pmf in zip(
            target.iter_rows(named=True), baseline_predictions, strict=True
        ):
            if row["goals"] is None or baseline_pmf is None:
                raise prior.RetrospectiveEvaluationError("a preregistered target was not scored")
            team, opponent, was_home = (
                int(row["team_code"]),
                int(row["opponent_team_code"]),
                bool(row["was_home"]),
            )
            key = f"{season}:{row['fixture']}:{team}"
            if key in slices:
                raise prior.RetrospectiveEvaluationError(f"duplicate prediction identity: {key}")
            cold = control.is_cold_start(team, opponent)
            n_history = min(int(attack_counts.get(team, 0)), int(defence_counts.get(opponent, 0)))
            slices[key] = prior.RowSlice(
                season,
                gw,
                was_home,
                team in promoted.get(season, frozenset()),
                gw <= base.reporting.early_season_observed_gameweeks,
                cold,
                prior._sot_history_band(n_history, base.reporting.sot_history_bins),
            )
            pmfs = (
                baseline_pmf,
                poisson_pmf(
                    control.goal_rate(team, opponent, was_home), max_goals=base.engine.maximum_goals
                ),
                poisson_pmf(
                    candidate.goal_rate(team, opponent, was_home),
                    max_goals=base.engine.maximum_goals,
                ),
            )
            for name, pmf in zip(names, pmfs, strict=True):
                if any(not math.isfinite(p) or p < 0 for p in pmf) or not math.isclose(
                    sum(pmf), 1, abs_tol=1e-9
                ):
                    raise prior.RetrospectiveEvaluationError("invalid probability distribution")
                blocks[name].append(
                    Prediction(
                        season=season,
                        gw=gw,
                        key=key,
                        distribution=pmf,
                        observed=int(row["goals"]),
                        was_home=was_home,
                        cold_start=cold,
                        used_engine_signal=name == contract.candidate
                        and candidate.parameters.weights.get("shots_on_target", 0) > 0,
                    )
                )
        identity_columns = [
            *_KEYS,
            "capture_id",
            "source_known_at",
            "payload_sha256",
            "shots_on_target",
            INTERPRETED_COLUMN,
            "sot_interpretation",
        ]
        fold_reports.append(
            {
                "season": season,
                "gw": gw,
                "as_of": cutoff.isoformat(),
                "training_rows": training.height,
                "target_rows": target.height,
                "retrospective_rows": history.height,
                "retrospective_sot_non_null": measured.height,
                "later_known_rows_permitted": history.filter(
                    pl.col("source_known_at") > cutoff
                ).height,
                "sot_interpretation_counts": dict(Counter(history["sot_interpretation"].to_list())),
                "sot_training_identity_sha256": hashlib.sha256(
                    history.select(identity_columns).sort(_KEYS).write_json().encode()
                ).hexdigest(),
                "control_parameters": control.parameters.as_report(),
                "candidate_parameters": candidate.parameters.as_report(),
                "control_signal_fit": prior._fitted_signal_report(control),
                "candidate_signal_fit": prior._fitted_signal_report(candidate),
                "event_time_violations": 0,
                "same_gameweek_overlap": 0,
            }
        )
    sequences = [[p.key for p in block] for block in blocks.values()]
    if not sequences[0] or any(keys != sequences[0] for keys in sequences[1:]):
        raise prior.RetrospectiveEvaluationError(
            "models have different or empty evaluation populations"
        )
    return blocks, slices, fold_reports


def score_run(
    blocks: Mapping[str, list[Prediction]],
    slices: Mapping[str, prior.RowSlice],
    folds: list[dict[str, Any]],
    contract: SotZeroEvaluationContract,
    base: V2RealSotRetrospectiveContract,
) -> dict[str, Any]:
    overall = prior._score_models(blocks, seed=base.random_seed)
    by_slice = prior._slice_reports(blocks, slices, seed=base.random_seed)
    control, candidate = overall[base.control.name], overall[contract.candidate]
    log_lift = relative_lift(control["mean_log_score"], candidate["mean_log_score"])
    crps_lift = relative_lift(control["crps"], candidate["crps"])
    season_checks = {
        season: by_slice[f"season:{season}"][contract.candidate]["mean_log_score"]
        <= by_slice[f"season:{season}"][base.control.name]["mean_log_score"]
        for season in base.population.eligible_seasons
    }
    gate = base.development_gate
    checks = {
        "minimum_relative_log_lift": {
            "pass": log_lift >= gate.minimum_relative_log_lift,
            "actual": log_lift,
            "threshold": gate.minimum_relative_log_lift,
        },
        "maximum_crps_relative_regression": {
            "pass": crps_lift >= -gate.maximum_crps_relative_regression,
            "actual_relative_lift": crps_lift,
            "threshold": gate.maximum_crps_relative_regression,
        },
        "pit_interval_80_maximum_absolute_error": {
            "pass": candidate["pit_interval_80_absolute_error"]
            <= gate.pit_interval_80_maximum_absolute_error,
            "actual": candidate["pit_interval_80_absolute_error"],
            "threshold": gate.pit_interval_80_maximum_absolute_error,
        },
        "no_season_log_score_regression": {
            "pass": all(season_checks.values()),
            "by_season": season_checks,
        },
        "event_time_and_batch_isolation": {
            "pass": all(
                fold["event_time_violations"] == fold["same_gameweek_overlap"] == 0
                for fold in folds
            )
        },
        "identical_population": {"pass": len({len(v) for v in blocks.values()}) == 1},
    }
    passed = all(bool(check["pass"]) for check in checks.values())
    verdict = (
        "SUPPORTED FOR RETROSPECTIVE DEVELOPMENT ONLY"
        if passed
        else ("REFUTED" if log_lift <= 0 else "INCONCLUSIVE")
    )
    cutoffs = {(f["season"], f["gw"]): f["as_of"] for f in folds}
    predictions = []
    for index, row in enumerate(blocks[contract.candidate]):
        predictions.append(
            {
                **asdict(slices[row.key]),
                "key": row.key,
                "as_of": cutoffs[row.season, row.gw],
                "observed_goals": row.observed,
                "distributions": {name: rows[index].distribution for name, rows in blocks.items()},
            }
        )
    by_fold = []
    for fold in folds:
        subset = {
            name: [p for p in rows if (p.season, p.gw) == (fold["season"], fold["gw"])]
            for name, rows in blocks.items()
        }
        by_fold.append(
            {
                "season": fold["season"],
                "gw": fold["gw"],
                "as_of": fold["as_of"],
                "metrics": prior._score_models(subset, seed=base.random_seed),
            }
        )
    return {
        "schema_version": 1,
        "status": "development_only",
        "evidence_class": contract.evidence_class,
        "verdict": verdict,
        "candidate": contract.candidate,
        "control": base.control.name,
        "context_baseline": base.baseline,
        "eligible_seasons": base.population.eligible_seasons,
        "folds": len(folds),
        "rows_scored": len(predictions),
        "overall": overall,
        "by_slice": by_slice,
        "candidate_vs_control": {
            "relative_log_score_lift": log_lift,
            "relative_crps_lift": crps_lift,
            **prior._paired_diagnostics(blocks[base.control.name], blocks[contract.candidate]),
        },
        "development_gate": {"pass": passed, "checks": checks},
        "fold_parameters": folds,
        "by_fold": by_fold,
        "fixture_predictions": predictions,
        "promotion_permitted": False,
        "caveat": (
            "Post-audit retrospective development on already-inspected historical seasons; "
            "not independent confirmation or historical deadline evidence."
        ),
    }


def run_formal_evaluation(
    *, db_path: Path, results_dir: Path, contract_path: Path
) -> dict[str, Any]:
    root = repo_root()
    result_path = results_dir / RESULT_FILE
    if result_path.exists():
        raise prior.RetrospectiveEvaluationError(
            "formal result already exists; this runner is write-once"
        )
    prior.require_clean_worktree(root)
    contract, base = load_contract(contract_path)
    audit_path = root / contract.coverage_audit
    manifest_path = root / "results" / prior.CAPTURE_MANIFEST_FILE
    snapshot = prior._snapshot(
        root=root,
        db_path=db_path,
        config_path=contract_path,
        coverage_path=audit_path,
        manifest_path=manifest_path,
    )
    additional = (
        "src/fpl/validate/dev_v2_corroborated_sot.py",
        "src/fpl/validate/sot_zero_audit.py",
        "src/fpl/ingest/pl_sdp.py",
        "src/fpl/transform/pl_sdp.py",
        "src/fpl/features/pit.py",
        "src/fpl/storage/db.py",
        "src/fpl/storage/schema.sql",
        "config/pl_sdp_metrics.yaml",
        contract.policy,
        contract.base_contract,
        "docs/v2-corroborated-zero-sot-design.md",
        "results/v2_real_sot_development.json",
        "results/v2_team_environment_development.json",
    )
    snapshot = replace(
        snapshot,
        source_sha256={
            **snapshot.source_sha256,
            **{p: prior.file_sha256(root / p) for p in additional},
        },
    )
    if snapshot.source_sha256["results/v2_real_sot_development.json"] != FROZEN_REAL_SOT_SHA:
        raise prior.RetrospectiveEvaluationError("frozen first real-SOT result changed")
    original = json.loads((root / "results/v2_real_sot_development.json").read_bytes())
    for path, expected in original["provenance"]["source_sha256"].items():
        if prior.file_sha256(root / path) != expected:
            raise prior.RetrospectiveEvaluationError(
                f"frozen estimator/control implementation changed: {path}"
            )
    con = connect(db_path, read_only=True)
    try:
        audit = validate_audit(con, contract, base)
        if audit["database_sha256"] != snapshot.database_sha256:
            raise prior.RetrospectiveEvaluationError(
                "database differs from the coverage-only audit"
            )
        if audit["canonical_capture_manifest_sha256"] != snapshot.capture_manifest_sha256:
            raise prior.RetrospectiveEvaluationError("canonical provider versions changed")
        blocks, slices, folds = run_walk_forward(con, contract, base, audit)
    finally:
        con.close()
    expected_rows = sum(audit["seasons"][s]["team_rows"] for s in base.population.eligible_seasons)
    if any(len(rows) != expected_rows for rows in blocks.values()):
        raise prior.RetrospectiveEvaluationError(
            "evaluated row count differs from preregistered coverage"
        )
    report = score_run(blocks, slices, folds, contract, base)
    report["provenance"] = {
        **asdict(snapshot),
        "clean_worktree": True,
        "git_head": snapshot.head,
        "random_seed": base.random_seed,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "evidence_class": contract.evidence_class,
        "sdp_version_selection": base.source.version_selection,
        "interpretation_policy_sha256": contract.policy_sha256,
        "interpretation_policy": "corroborated_omitted_sot_zero_v1",
        "inherited_contract_sha256": contract.base_contract_sha256,
    }
    prior._verify_snapshot(
        snapshot,
        root=root,
        db_path=db_path,
        config_path=contract_path,
        coverage_path=audit_path,
        manifest_path=manifest_path,
    )
    results_dir.mkdir(parents=True, exist_ok=True)
    with result_path.open("xb") as output:
        output.write(prior._json_bytes(report))
    logger.info(
        "%s: %s rows, log lift %.6f%%",
        report["verdict"],
        expected_rows,
        report["candidate_vs_control"]["relative_log_score_lift"] * 100,
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=default_db_path())
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    run_formal_evaluation(
        db_path=args.db,
        results_dir=repo_root() / "results",
        contract_path=config_dir() / CONFIG_FILE,
    )


if __name__ == "__main__":
    main()
