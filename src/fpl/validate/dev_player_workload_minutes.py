"""One registered workload-role minutes experiment; never a production entry point."""

from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import traceback
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml

from fpl.config import Phase2EvaluationConfig, load_phase2_evaluation, repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256, git_clean_head, publish_json
from fpl.storage.db import connect
from fpl.validate.dev_minutes_candidate_v1 import compute_development_diagnostics
from fpl.validate.dev_v2_tactical_matchup import _clustered
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.development_reference_components import (
    EXPECTED_COUNTS,
    MANIFEST_SHA256,
    ValidatedMinutesControlFold,
)
from fpl.validate.minutes_baselines import (
    STAGE_B_BASELINE_ORDER,
    HistoryRow,
    MinuteBins,
    MinutesDistribution,
    TeamCodeMap,
    build_minutes_baselines,
    validate_minutes_inputs,
)
from fpl.validate.minutes_harness import (
    MinutesHarnessResult,
    _cohort,
    _prior_by_code,
    _transfer_status,
    player_fixture_history,
    team_code_map,
)
from fpl.validate.minutes_metrics import (
    MinutesScoreReport,
    minutes_log_score,
    score_minutes_predictions,
)
from fpl.validate.player_role_cache import RESULT_SHA256
from fpl.validate.player_workload_inputs import (
    DATABASE_SHA256,
    STAGE_SHA256,
    WorkloadProgramInputs,
    build_workload_inputs,
)
from fpl.validate.player_workload_minutes import (
    EVIDENCE_CLASS,
    GRADIENT_TOLERANCE,
    MAX_ITERATIONS,
    MINIMUM_PRIOR_BATCHES,
    MINIMUM_PRIOR_ROWS,
    NAME,
    RIDGE,
    STAGE_B_MINIMUM_FOLDS,
    STEP_SIZE,
    VOLUME_CAP_MINUTES,
    WORKLOAD_HOURS,
    WorkloadMinutesObservation,
    fit_minutes_correction,
    predict_minutes_batch,
)
from fpl.validate.retrospective_minutes_proxy import NAME as CONTROL_NAME

CONFIG = "config/player_workload_minutes_evaluation.yaml"
CONFIG_SHA256 = "UNREGISTERED"
COVERAGE_SHA256 = "770206f0c151694501cc06b95631b554b172b956e8cfe10363481f474f3cf982"
ARCHIVE_SHA256 = "0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
ARMS = ("current_control", *STAGE_B_BASELINE_ORDER, "candidate")
logger = logging.getLogger(__name__)
FIXED_POLICY: dict[str, Any] = {
    "candidate": NAME,
    "evidence_class": EVIDENCE_CLASS,
    "control": CONTROL_NAME,
    "seasons": ["2023-24", "2024-25", "2025-26"],
    "folds": 114,
    "rows": 86755,
    "price_proxy_rows": 821,
    "workload_season": "2025-26",
    "workload_folds": 38,
    "feature_active_rows": 9551,
    "role_arm": "frozen_transition_candidate",
    "target": "unchanged_four_minutes_bins_include_DNP",
    "cutoff": "complete_GW_first_kickoff_proxy",
    "completion_margin_hours": 6,
    "same_gw": "whole_target_season_gw_excluded",
    "features": (
        "min(observed_positive_nominal_minutes_168h/180,1)*four_transition_role_probabilities"
    ),
    "ridge_on_mean_loss": 1.0,
    "step_size": 2 / 3,
    "max_iterations": 200,
    "gradient_tolerance": 1e-10,
    "minimum_prior_batches": 8,
    "minimum_prior_rows": 200,
    "parameters_selected": "none_fixed_strong_ridge",
    "seed": 202627,
    "minimum_relative_log_lift_vs_current": 0.01,
    "stage_b_gate": "unchanged_phase2_v1.4_best_metric_and_ranking_181_folds",
    "current_guardrails": "RPS_Brier_any_Brier_60_Spearman_and_each_season_no_regression",
    "slices": [
        "season",
        "position",
        "venue",
        "early_later",
        "cold_start",
        "price_proxy",
        "transfer_status",
        "player_history_cohort",
        "feature_active",
    ],
    "population_rule": "all114_reference_folds_86755_rows_no_feature_based_exclusion",
    "full_gate_eligible": False,
    "promotion_permitted": False,
    "synthesis_eligible": False,
    "one_run": "shared_git_common_dir_claim_before_any_candidate_fit_no_retry",
}


def load_contract(root: Path) -> dict[str, Any]:
    if CONFIG_SHA256 == "UNREGISTERED" or file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("workload minutes preregistration is absent or changed")
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    if set(contract) != {"policy", "pins"} or contract["policy"] != FIXED_POLICY:
        raise ValueError("workload minutes exact frozen policy differs")
    pins = {
        "database_sha256": DATABASE_SHA256,
        "archive_database_sha256": ARCHIVE_SHA256,
        "stage_report_sha256": STAGE_SHA256,
        "role_result_sha256": RESULT_SHA256,
        "minutes_manifest_sha256": MANIFEST_SHA256,
        "coverage_report_sha256": COVERAGE_SHA256,
        "model_source_sha256": file_sha256(root / "src/fpl/validate/player_workload_minutes.py"),
        "stage_b_contract_sha256": file_sha256(root / "config/phase2_evaluation.yaml"),
    }
    if contract["pins"] != pins:
        raise ValueError("workload minutes exact source/config/database pins differ")
    if (
        RIDGE != 1
        or STEP_SIZE != 2 / 3
        or MAX_ITERATIONS != 200
        or GRADIENT_TOLERANCE != 1e-10
        or MINIMUM_PRIOR_BATCHES != 8
        or MINIMUM_PRIOR_ROWS != 200
        or WORKLOAD_HOURS != 168
        or VOLUME_CAP_MINUTES != 180
        or STAGE_B_MINIMUM_FOLDS != 181
    ):
        raise ValueError("workload minutes fixed algorithm constants changed")
    return contract


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def snapshot(root: Path, paths: dict[str, Path]) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    if branch != BRANCH:
        raise ValueError("formal workload experiment requires the exact V2 branch")
    contract = load_contract(root)
    for key, path in paths.items():
        if not path.is_file() or path.is_symlink() or file_sha256(path) != contract["pins"][key]:
            raise ValueError(f"formal workload pinned input differs: {key}")
        if (
            key in {"database_sha256", "archive_database_sha256"}
            and Path(str(path) + ".wal").exists()
        ):
            raise ValueError("formal workload database has unresolved WAL")
    files = sorted(
        {
            *root.glob("src/**/*.py"),
            *root.glob("tests/**/*.py"),
            *root.glob("config/*.yaml"),
            *root.glob("results/*.json"),
            *root.glob("docs/*.md"),
            root / "AGENTS.md",
            root / "DEV-ROADMAP.md",
        }
    )
    return {
        "git_head": head,
        "clean_worktree": True,
        "branch": branch,
        "candidate": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "config_sha256": CONFIG_SHA256,
        "source_sha256": {p.relative_to(root).as_posix(): file_sha256(p) for p in files},
        "input_sha256": {str(p.resolve()): file_sha256(p) for p in paths.values()},
        "seed": 202627,
        "known_at_rewritten": False,
        "historical_deadline_validity": False,
        "promotion_permitted": False,
        "synthesis_eligible": False,
    }


def verify_population(
    inputs: WorkloadProgramInputs, targets: Sequence[HistoryRow]
) -> dict[str, Any]:
    """Labels are held here, outside all model predictors; PMFs reproduce cache exactly."""
    target_map = {(r.season, r.fixture, r.code): r for r in targets}
    if len(target_map) != len(targets):
        raise ValueError("duplicate archive target identity")
    expected = set()
    counts: Counter[str] = Counter()
    for fold in inputs.reference.folds:
        batch = inputs.batches[fold.season, fold.gw]
        if len(batch) != len(fold.rows):
            raise ValueError("minutes target batch lost roster rows")
        for row, item in zip(fold.rows, batch, strict=True):
            target = row.target
            key = target.season, target.fixture, target.code
            actual = target_map.get(key)
            if actual is None:
                raise ValueError("reference target minute outcome is unavailable")
            if any(
                getattr(actual, field) != getattr(target, field)
                for field in target.__dataclass_fields__
            ):
                raise ValueError("reference/archive target projection changed")
            if (
                item.control.probabilities != row.minutes
                or item.control.price_proxy_dependent != row.price_proxy_dependent
            ):
                raise ValueError("current incumbent PMF/proxy reproduction is not exact")
            expected.add(key)
            counts[fold.season] += 1
            counts["rows"] += 1
            counts["price_proxy_rows"] += row.price_proxy_dependent
    if set(target_map) != expected or dict(counts) != EXPECTED_COUNTS:
        raise ValueError("fixed all-roster reference population differs")
    return {
        "counts": dict(counts),
        "folds": len(inputs.reference.folds),
        "maximum_pmf_difference": 0.0,
        "method": "exact_every_row_frozen_current_selector_PMF_not_V3_refit",
        "missing_targets": 0,
    }


def baseline_predictions(
    history: Sequence[HistoryRow],
    fold: ValidatedMinutesControlFold,
    *,
    bins: MinuteBins,
    teams: TeamCodeMap,
) -> dict[str, tuple[MinutesDistribution, ...]]:
    """Unchanged four baselines; cache only mathematically identical prediction keys."""
    targets = tuple(r.target for r in fold.rows)
    valid, _ = validate_minutes_inputs(
        history, targets, as_of=fold.as_of, team_codes=teams, bins=bins
    )
    if any((r.season, r.gw) == (fold.season, fold.gw) for r in valid):
        raise ValueError("target GW entered baseline history")
    output = {}
    for baseline in build_minutes_baselines(valid, as_of=fold.as_of, team_codes=teams, bins=bins):
        cached: dict[tuple[Any, ...], MinutesDistribution] = {}
        values = []
        for target in targets:
            key = (
                (target.position,)
                if baseline.name == STAGE_B_BASELINE_ORDER[0]
                else (
                    (target.team_id, target.position)
                    if baseline.name == STAGE_B_BASELINE_ORDER[3]
                    else (target.code, target.position)
                )
            )
            if key not in cached:
                cached[key] = baseline.predict(target)
            values.append(cached[key])
        output[baseline.name] = tuple(values)
    return output


def _reports(
    rows: list[dict[str, Any]], config: Phase2EvaluationConfig
) -> dict[str, MinutesScoreReport]:
    return {
        arm: score_minutes_predictions(
            [tuple(r["pmfs"][arm]) for r in rows],
            [r["observed_bin"] for r in rows],
            config=config,
            cold_starts=[r["cold_start"] for r in rows],
            rank_groups=[f"{r['season']}:{r['gw']}:{r['position']}" for r in rows],
            name=arm,
        )
        for arm in ARMS
    }


def summarize(
    rows: list[dict[str, Any]], config: Phase2EvaluationConfig, *, fold_count: int
) -> dict[str, Any]:
    overall = _reports(rows, config)
    sliced: dict[str, dict[str, dict[str, MinutesScoreReport]]] = {}
    for dimension in FIXED_POLICY["slices"]:
        groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[str(row[dimension])].append(row)
        sliced[dimension] = {key: _reports(value, config) for key, value in groups.items()}
    harness = MinutesHarnessResult(
        fold_count,
        dict(Counter(season for season, _ in {(r["season"], r["gw"]) for r in rows})),
        len(rows),
        len(rows),
        0,
        frozenset(STAGE_B_BASELINE_ORDER),
        overall,
        {},
        sliced["season"],
        sliced["position"],
        sliced["venue"],
        sliced["transfer_status"],
        sliced["player_history_cohort"],
    )
    legacy = compute_development_diagnostics(harness, "candidate", config)
    candidate, control = overall["candidate"], overall["current_control"]
    lift = (control.mean_log_score - candidate.mean_log_score) / abs(control.mean_log_score)
    current_gate = {
        "log_lift_at_least_1pct": lift >= 0.01,
        "rps_no_regression": candidate.mean_ranked_probability_score
        <= control.mean_ranked_probability_score,
        "brier_any_no_regression": candidate.mean_brier_any_minutes
        <= control.mean_brier_any_minutes,
        "brier_60_no_regression": candidate.mean_brier_60_plus <= control.mean_brier_60_plus,
        "starter_ranking_no_regression": math.isfinite(
            candidate.spearman_p60_within_position_gameweek
        )
        and candidate.spearman_p60_within_position_gameweek
        >= control.spearman_p60_within_position_gameweek,
        "each_season_log_no_regression": all(
            block["candidate"].mean_log_score <= block["current_control"].mean_log_score
            for block in sliced["season"].values()
        ),
    }

    def scalar(report: MinutesScoreReport) -> dict[str, Any]:
        values = asdict(report)
        del values["pit_values"]
        values["pit_interval_80_absolute_error"] = report.pit_interval_80_absolute_error
        return values

    floor = config.scoring_calibration.log_probability_floor
    delta = [
        minutes_log_score(tuple(r["pmfs"]["candidate"]), r["observed_bin"], floor=floor)
        - minutes_log_score(tuple(r["pmfs"]["current_control"]), r["observed_bin"], floor=floor)
        for r in rows
    ]
    active = [r for r in rows if r["season"] == "2025-26"]
    active_delta = [d for d, r in zip(delta, rows, strict=True) if r["season"] == "2025-26"]
    return cast(
        dict[str, Any],
        _plain(
            {
                "overall": {arm: scalar(report) for arm, report in overall.items()},
                "slices": {
                    dimension: {
                        key: {arm: scalar(report) for arm, report in values.items()}
                        for key, values in groups.items()
                    }
                    for dimension, groups in sliced.items()
                },
                "stage_b_frozen_gate_diagnostics": asdict(legacy),
                "current_control_gate": current_gate,
                "relative_mean_log_lift_vs_current": lift,
                "paired_vs_current": _clustered(delta, rows, candidate=NAME),
                "paired_workload_season_only": _clustered(active_delta, active, candidate=NAME),
                "full_stage_b_gate_eligible": False,
                "minimum_folds": 181,
                "nominal_folds": fold_count,
                "verdict": "REFUTED" if lift < -0.01 else "INCONCLUSIVE",
                "ineligibility_reason": "114_nominal_and38_workload_folds_do_not_satisfy_frozen181",
                "synthesis_eligible": False,
                "promotion_permitted": False,
            }
        ),
    )


def run(
    *,
    root: Path,
    database: Path,
    archive_database: Path,
    minutes_directory: Path,
    role_result: Path,
    stage_report: Path,
    coverage_report: Path,
    output: Path,
) -> dict[str, Any]:
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(root.resolve()):
        raise ValueError("new external write-once workload output directory required")
    paths = {
        "database_sha256": database,
        "archive_database_sha256": archive_database,
        "minutes_manifest_sha256": minutes_directory / "manifest.json",
        "role_result_sha256": role_result,
        "stage_report_sha256": stage_report,
        "coverage_report_sha256": coverage_report,
    }
    provenance = snapshot(root, paths)
    inputs = build_workload_inputs(
        root=root,
        database=database,
        archive_database=archive_database,
        minutes_directory=minutes_directory,
        role_result=role_result,
        stage_report=stage_report,
    )
    if inputs.coverage != json.loads(coverage_report.read_bytes()):
        raise ValueError("coverage-only prerequisite no longer reproduces exactly")
    config = load_phase2_evaluation()
    bins = MinuteBins.from_config(config)
    with connect(archive_database, read_only=True) as con:
        frame = con.execute("""SELECT season,gw,fixture,kickoff_time,code,position,team_id,
               opponent_team_id,was_home,minutes FROM mart_fact_player_fixture
               WHERE season IN ('2023-24','2024-25','2025-26') AND minutes IS NOT NULL
               ORDER BY kickoff_time,season,fixture,code""").pl()
        from fpl.validate.minutes_harness import _history_rows

        targets = _history_rows(frame)
        teams = team_code_map(con)
    reproduction = verify_population(inputs, targets)
    target_map = {(t.season, t.fixture, t.code): t for t in targets}
    if snapshot(root, paths) != provenance:
        raise ValueError("pre-claim workload provenance changed")
    claim = reserve_program_claim(root, NAME, provenance)
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(UTC).isoformat()
    folds: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []
    history: list[WorkloadMinutesObservation] = []
    try:
        publish_json(output / "provenance.json", provenance)
        publish_json(output / "coverage.json", inputs.coverage)
        publish_json(output / "source_versions.json", inputs.source_versions)
        with connect(archive_database, read_only=True) as con:
            for fold in inputs.reference.folds:
                key = fold.season, fold.gw
                batch = inputs.batches[key]
                # Historical role forecasts stay out-of-event-time; no role fit occurs here.
                fitted = fit_minutes_correction(
                    history, season=fold.season, gw=fold.gw, as_of=fold.as_of
                )
                predicted = predict_minutes_batch(fitted, batch)
                prior = player_fixture_history(con, as_of=fold.as_of)
                baselines = baseline_predictions(prior, fold, bins=bins, teams=teams)
                prior_codes = _prior_by_code(prior)
                rows = []
                for index, (cached, item, prediction) in enumerate(
                    zip(fold.rows, batch, predicted, strict=True)
                ):
                    t = cached.target
                    source = target_map[t.season, t.fixture, t.code]
                    observed = bins.index_of(source.minutes)
                    expected = inputs.evidence[t.season, t.fixture, t.code]
                    if prediction.feature_evidence != expected:
                        raise ValueError(
                            "prediction feature evidence differs from coverage-only audit"
                        )
                    if (
                        t.season != "2025-26" or not prediction.correction_applied
                    ) and prediction.probabilities != cached.minutes:
                        raise ValueError("fallback no longer reproduces exact incumbent PMF")
                    row = {
                        "season": t.season,
                        "gw": t.gw,
                        "fixture": t.fixture,
                        "code": t.code,
                        "team_code": cached.team_code,
                        "position": t.position.value,
                        "venue": "home" if t.was_home else "away",
                        "kickoff": t.kickoff_time.isoformat(),
                        "as_of": fold.as_of.isoformat(),
                        "observed_minutes": source.minutes,
                        "observed_bin": observed,
                        "early_later": "GW1-6" if t.gw <= 6 else "GW7+",
                        "cold_start": cached.cold_start,
                        "price_proxy": cached.price_proxy_dependent,
                        "transfer_status": _transfer_status(t, prior_codes.get(t.code, []), teams),
                        "player_history_cohort": _cohort(prior_codes.get(t.code, [])),
                        "feature_active": expected.features is not None,
                        "feature_evidence": _plain(asdict(expected)),
                        "pmfs": {
                            "current_control": cached.minutes,
                            "candidate": prediction.probabilities,
                            **{arm: values[index] for arm, values in baselines.items()},
                        },
                        "correction_applied": prediction.correction_applied,
                        "fallback_reason": prediction.fallback_reason,
                        "training_rows_sha256": fitted.training_rows_sha256,
                        "minutes_fold_sha256": fold.fold_sha256,
                        "selector_provenance": json.loads(cached.selector_provenance_json),
                        "role_cache_result_sha256": RESULT_SHA256
                        if item.role_batch is not None
                        else None,
                        "same_gw_rows_used": 0,
                    }
                    rows.append(row)
                # Absorb labels only after every target fixture/roster row is predicted.
                history.extend(
                    WorkloadMinutesObservation(item, row["observed_bin"])
                    for item, row in zip(batch, rows, strict=True)
                )
                name = f"{fold.season}-gw{fold.gw:02d}.json"
                publish_json(
                    output / name,
                    _plain(
                        {
                            "rows": rows,
                            "fit": asdict(fitted),
                            "role_cache": str(role_result),
                            "current_minutes_fold_sha256": fold.fold_sha256,
                        }
                    ),
                )
                folds.append(
                    {
                        "season": fold.season,
                        "gw": fold.gw,
                        "file": name,
                        "rows": len(rows),
                        "sha256": file_sha256(output / name),
                    }
                )
                retained.extend(rows)
                logger.info(
                    "workload minutes %s GW%s: %s rows, %s corrected",
                    fold.season,
                    fold.gw,
                    len(rows),
                    sum(r["correction_applied"] for r in rows),
                )
        result = {
            "completed": True,
            "candidate": NAME,
            "evidence_class": EVIDENCE_CLASS,
            "started_at_utc": started,
            "finished_at_utc": datetime.now(UTC).isoformat(),
            "provenance": provenance,
            "claim": str(claim),
            "comparator_reproduction": reproduction,
            "coverage": inputs.coverage,
            "folds": folds,
            "rows": len(retained),
            **summarize(retained, config, fold_count=len(folds)),
        }
        if snapshot(root, paths) != provenance:
            raise ValueError("formal workload source/HEAD/database changed during run")
        publish_json(output / "result.json", result)
        return result
    except BaseException as error:
        publish_json(
            output / "failure.json",
            {
                "candidate": NAME,
                "completed": False,
                "error_class": type(error).__name__,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "completed_folds": folds,
                "claim_preserved": True,
                "retry_permitted": False,
            },
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "db",
        "archive-db",
        "minutes-cache",
        "role-result",
        "stage-report",
        "coverage-report",
        "output",
    ):
        parser.add_argument(f"--{name}", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run(
        root=repo_root(),
        database=args.db,
        archive_database=args.archive_db,
        minutes_directory=args.minutes_cache,
        role_result=args.role_result,
        stage_report=args.stage_report,
        coverage_report=args.coverage_report,
        output=args.output,
    )
    print(json.dumps({"rows": result["rows"], "verdict": result["verdict"]}))


if __name__ == "__main__":
    main()
