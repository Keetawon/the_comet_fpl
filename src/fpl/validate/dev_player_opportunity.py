"""One separately claimed goals OR assists opportunity development experiment.

Consumes a completed current-component cache and original OOS role forecast.
No incumbent component refit, minutes refit, role rerun or full-points simulation.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import subprocess
import traceback
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import duckdb
import yaml

from fpl.config import load_phase2_evaluation, repo_root
from fpl.jobs.competitive_participation_pilot import (
    file_sha256,
    git_clean_head,
    publish_json,
)
from fpl.models.attacking_assists_baselines import (
    AssistHistoryRow,
    PositionalAssistRateBaseline,
    TrailingPlayerAssistRateBaseline,
)
from fpl.models.attacking_baselines import (
    PlayerHistoryRow,
    PositionalGoalRateBaseline,
    TargetRowProjection,
    TrailingPlayerGoalRateBaseline,
    poisson_pmf,
)
from fpl.models.points_composition import conditional_rate
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.attacking_metrics import score_attacking_predictions
from fpl.validate.current_component_reference_cache import (
    load_component_reference_cache,
)
from fpl.validate.dev_v2_tactical_matchup import _clustered
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.development_reference_components import (
    DevelopmentReferenceComponents,
    ValidatedMinutesControlCache,
    read_minutes_control_cache,
)
from fpl.validate.metrics import log_score
from fpl.validate.minutes_baselines import MinuteBins
from fpl.validate.player_opportunity import (
    EVIDENCE_CLASS,
    MINIMUM_GATE_FOLDS,
    MINIMUM_PRIOR_GAMEWEEKS,
    NAMES,
    PLAYER_PRIOR_MINUTES,
    ROLE_PRIOR_MINUTES,
    WINDOW,
    Component,
    OpportunityHistoryRow,
    OpportunityInput,
    PrequentialRoleContext,
    _target_key,
    fit_opportunity,
    marginal_pmf,
    predict_opportunity_batch,
    role_contexts,
)
from fpl.validate.player_role_cache import load_role_cache
from fpl.validate.player_role_history import RoleTarget
from fpl.validate.player_workload_minutes import control_from_cache

CONFIG = "config/player_opportunity_evaluation.yaml"
CONFIG_SHA256 = "958df33180b85215db9d2b336d051f5d5d0510d3aebe38cc96e2b48d7ecce16f"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
ARMS = ("current", "position_baseline", "trailing_baseline", "candidate")
logger = logging.getLogger(__name__)


def load_contract(root: Path, component: Component) -> dict[str, Any]:
    if component not in NAMES or file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("opportunity candidate/config fingerprint differs")
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    pins = {
        "evidence_class": EVIDENCE_CLASS,
        "role_prior_minutes": ROLE_PRIOR_MINUTES,
        "player_prior_minutes": PLAYER_PRIOR_MINUTES,
        "window": WINDOW,
        "minimum_prior_gameweeks": MINIMUM_PRIOR_GAMEWEEKS,
        "minimum_gate_folds": MINIMUM_GATE_FOLDS,
        "development_synthesis_eligible": False,
        "promotion_permitted": False,
    }
    if (
        any(contract[k] != value for k, value in pins.items())
        or contract["candidate_identity"] != NAMES
    ):
        raise ValueError("opportunity frozen model identity/parameters/gate differ")
    original = yaml.safe_load((root / contract["source_contract"][component]).read_bytes())
    if (
        original["promotion"]["minimum_fold_count"] != 181
        or original["promotion"]["minimum_prediction_coverage"] != 1.0
        or original["promotion"]["minimum_primary_relative_lift"] != 0.01
    ):
        raise ValueError("original Stage C contract is not the preregistered gate")
    return contract


def snapshot(
    root: Path, db: Path, component: Component, reference: Path, roles: Path
) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    contract = load_contract(root, component)
    if branch != BRANCH:
        raise ValueError("formal opportunity run requires exact V2 branch")
    if (
        contract["registration_status"] != "REGISTERED"
        or len(contract["component_reference_manifest_sha256"]) != 64
    ):
        raise ValueError("opportunity is UNREGISTERED until completed reference cache is pinned")
    if Path(str(db) + ".wal").exists() or file_sha256(db) != contract["database_sha256"]:
        raise ValueError("original source database hash/WAL differs")
    if file_sha256(reference / "manifest.json") != contract["component_reference_manifest_sha256"]:
        raise ValueError("component reference manifest differs")
    if file_sha256(roles) != contract["role_result_sha256"]:
        raise ValueError("original prequential role artifact differs")
    sources = sorted(
        {
            *root.glob("src/**/*.py"),
            *root.glob("tests/**/*.py"),
            *root.glob("config/*.yaml"),
            *root.glob("docs/*.md"),
            *root.glob("results/*.json"),
            root / "AGENTS.md",
            root / "DEV-ROADMAP.md",
            root / "README.md",
        }
    )
    return {
        "git_head": head,
        "branch": branch,
        "clean_worktree": True,
        "candidate": NAMES[component],
        "component": component,
        "evidence_class": EVIDENCE_CLASS,
        "database_path": str(db),
        "database_sha256": contract["database_sha256"],
        "config_sha256": CONFIG_SHA256,
        "component_reference_manifest_sha256": contract["component_reference_manifest_sha256"],
        "role_result_sha256": contract["role_result_sha256"],
        "minutes_manifest_sha256": contract["minutes_manifest_sha256"],
        "source_sha256": {
            str(p.relative_to(root)).replace("\\", "/"): file_sha256(p) for p in sources
        },
        "seed": contract["seed"],
        "historical_deadline_validity": False,
        "promotion_permitted": False,
        "minimum_gate_folds": 181,
        "full_gate_eligibility": "INELIGIBLE",
        "known_at_rewritten": False,
    }


def load_archive(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    # Safe roster projection and observed labels remain separately named. No target row
    # outcome enters cached reference or prequential role predictor objects.
    frame = con.execute("""SELECT f.season,f.gw,f.fixture,f.kickoff_time,f.code,
          f.position,f.team_id,
          f.opponent_team_id,f.was_home,t.team_code,f.minutes,f.goals_scored,f.assists,
          f.expected_goals,f.expected_assists,
          min(f.kickoff_time) OVER(PARTITION BY f.season,f.gw) as_of
        FROM mart_fact_player_fixture f JOIN mart_dim_team t
          ON t.season=f.season AND t.team_id=f.team_id
        WHERE f.minutes IS NOT NULL ORDER BY f.kickoff_time,f.season,f.fixture,f.code""").pl()
    rows = frame.to_dicts()
    if len({(r["season"], r["fixture"], r["code"]) for r in rows}) != len(rows):
        raise ValueError("duplicate archive player-fixture")
    return rows


def prepare_history(
    rows: Sequence[Mapping[str, Any]],
    contexts: Mapping[Any, PrequentialRoleContext],
    *,
    component: Component,
    database_sha256: str,
) -> list[OpportunityHistoryRow]:
    signal = "expected_goals" if component == "goals" else "expected_assists"
    result = []
    for raw in rows:
        target = RoleTarget(
            raw["season"],
            raw["gw"],
            raw["fixture"],
            raw["code"],
            raw["team_code"],
            raw["kickoff_time"],
            raw["as_of"],
            f"archive-roster:{database_sha256}",
        )
        result.append(
            OpportunityHistoryRow(
                target,
                raw["minutes"],
                raw[signal],
                signal,
                f"archive:{database_sha256}:{target.season}:{target.fixture}:{target.code}:{signal}",
                contexts.get(_target_key(target)),
            )
        )
    return result


def validate_controls(
    cache: ValidatedMinutesControlCache,
    references: Sequence[DevelopmentReferenceComponents],
    archive: Sequence[Mapping[str, Any]],
    *,
    component: Component,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    if len(references) != len(cache.folds) or len(cache.folds) != contract["expected_folds"]:
        raise ValueError("exact current comparator fold count differs")
    observed = {(r["season"], r["fixture"], r["code"]): r for r in archive}
    seen = set()
    proxy = 0
    equation_checked = 0
    seasons: dict[str, int] = defaultdict(int)
    signal = contract["signal"][component]
    label = contract["target"][component]
    for fold, reference in zip(cache.folds, references, strict=True):
        if (reference.season, reference.gw, reference.as_of) != (
            fold.season,
            fold.gw,
            fold.as_of,
        ):
            raise ValueError("comparator batch cutoff/identity differs")
        if len(reference.rows) != len(fold.rows):
            raise ValueError("comparator target count differs")
        team_scales = {
            (f, t): sum(k * p for k, p in enumerate(pmf)) for f, t, pmf in reference.team_scored
        }
        conversion = (
            json.loads(reference.diagnostics_json)["assist_conversion"]
            if component == "assists"
            else 1.0
        )
        for cached, ref in zip(fold.rows, reference.rows, strict=True):
            t = cached.target
            key = t.season, t.fixture, t.code
            if key in seen or key not in observed or ref.target != t:
                raise ValueError("duplicate/unmatched/changed comparator fixture identity")
            seen.add(key)
            raw = observed[key]
            if (
                raw["gw"] != t.gw
                or raw["kickoff_time"] != t.kickoff_time
                or raw["team_id"] != t.team_id
                or raw["opponent_team_id"] != t.opponent_team_id
                or raw["was_home"] is not t.was_home
                or Position(raw["position"]) != t.position
                or raw["team_code"] != cached.team_code
            ):
                raise ValueError("archive/current reference fixture identity contradiction")
            if (
                type(raw[label]) is not int
                or not 0 <= raw[label] <= 10
                or raw[signal] is None
                or not math.isfinite(raw[signal])
                or raw[signal] < 0
            ):
                raise ValueError("registered goal/assist target or xG/xA coverage failed")
            proxy += int(cached.price_proxy_dependent)
            seasons[t.season] += 1
            pmf = getattr(ref.player.components, component)
            rate = (
                ref.unconditional_goal_rate
                if component == "goals"
                else ref.unconditional_assist_rate
            )
            if rate is not None:
                equation_checked += 1
                scale = team_scales[(t.fixture, ref.team_code)] * conversion
                expected = poisson_pmf(conditional_rate(rate, 1 - cached.minutes[0], cap=scale))
                if pmf != expected:
                    raise ValueError(
                        "CURRENT conditional PMF exact reproduction failed before candidate fit"
                    )
            if ref.player.components.minutes != cached.minutes:
                raise ValueError("current minutes comparator changed")
    if (
        len(seen) != contract["expected_rows"]
        or proxy != contract["expected_direct_proxy_rows"]
        or dict(seasons) != contract["season_rows"]
    ):
        raise ValueError("complete population/proxy/season counts differ")
    return {
        "rows": len(seen),
        "folds": len(references),
        "direct_price_proxy_rows": proxy,
        "season_rows": dict(seasons),
        "conditional_pmf_maximum_difference": 0.0,
        "conditional_equation_checked_rows": equation_checked,
        "uncoupled_fallback_cache_rows": len(seen) - equation_checked,
        "signal_and_target_coverage": 1.0,
        "historical_label_audit": {
            "archive_rows": len(archive),
            "missing_label_rows": sum(r[label] is None for r in archive),
            "baseline_missing_policy": "unchanged_original_harness_COALESCE_label_0",
            "missing_signal_policy": "NULL_retained_never_imputed",
        },
        "minutes_refitted": False,
        "component_reference_refitted": False,
        "comparison": "exact_current_component_cache",
        "historical_registry_validity": False,
        "full_gate_eligibility": "INELIGIBLE",
    }


def baseline_predictions(
    archive: Sequence[Mapping[str, Any]],
    reference: DevelopmentReferenceComponents,
    component: Component,
) -> dict[tuple[int, int], tuple[tuple[float, ...], tuple[float, ...]]]:
    prior = [
        r
        for r in archive
        if r["kickoff_time"] < reference.as_of
        and (r["season"], r["gw"]) != (reference.season, reference.gw)
    ]
    models: tuple[Any, Any]
    if component == "goals":
        models = PositionalGoalRateBaseline(), TrailingPlayerGoalRateBaseline()
        goal_rows = [
            PlayerHistoryRow(
                r["season"],
                r["gw"],
                r["fixture"],
                r["kickoff_time"].isoformat(),
                r["code"],
                Position(r["position"]),
                0 if r["goals_scored"] is None else r["goals_scored"],
            )
            for r in prior
        ]
        for m in models:
            m.fit(goal_rows)
    else:
        models = PositionalAssistRateBaseline(), TrailingPlayerAssistRateBaseline()
        assist_rows = [
            AssistHistoryRow(
                r["season"],
                r["gw"],
                r["fixture"],
                r["kickoff_time"].isoformat(),
                r["code"],
                Position(r["position"]),
                0 if r["assists"] is None else r["assists"],
                r["minutes"],
            )
            for r in prior
        ]
        for assist_model in models:
            assist_model.fit(assist_rows)
    result = {}
    for row in reference.rows:
        t = row.target
        target = TargetRowProjection(
            t.season,
            t.gw,
            t.fixture,
            t.kickoff_time.isoformat(),
            t.code,
            t.position,
            t.team_id,
            t.opponent_team_id,
            t.was_home,
        )
        result[(t.fixture, t.code)] = (
            models[0].predict(target),
            models[1].predict(target),
        )
    return result


def score_rows(rows: Sequence[Mapping[str, Any]], *, candidate: str, seed: int) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "arms": {}}
    arms = {}
    outcomes = [r["observed"]["count"] for r in rows]
    for arm in ARMS:
        pmfs = [tuple(r[arm]) for r in rows]
        scored = score_attacking_predictions(pmfs, outcomes, seed=seed)
        means = [math.fsum(k * p for k, p in enumerate(pmf)) for pmf in pmfs]
        average = math.fsum(means) / len(rows)
        arms[arm] = {
            "log_score": scored.mean_log_score,
            "rps": scored.mean_ranked_probability_score,
            "brier_any": scored.mean_brier_at_least_one_goal,
            "pit80": scored.pit_interval_80_coverage,
            "pit80_error": scored.pit_interval_80_error,
            "reliability_any": asdict(scored.reliability_at_least_one_goal),
            "mean_prediction": average,
            "mean_error": math.fsum(p - y for p, y in zip(means, outcomes, strict=True))
            / len(rows),
            "mae": math.fsum(abs(p - y) for p, y in zip(means, outcomes, strict=True)) / len(rows),
            "prediction_sd": math.sqrt(math.fsum((p - average) ** 2 for p in means) / len(rows)),
        }
    deltas = [
        log_score(tuple(r["candidate"]), r["observed"]["count"])
        - log_score(tuple(r["current"]), r["observed"]["count"])
        for r in rows
    ]
    measured = [
        r
        for r in rows
        if r["signal_prediction"] is not None and r["signal_persistence_proxy"] is not None
    ]
    diagnostics = {}
    for arm in ("signal_prediction", "signal_persistence_proxy"):
        errors = [r[arm] - r["observed"]["signal"] for r in measured]
        diagnostics[arm] = {
            "rows": len(errors),
            "mae": math.fsum(abs(e) for e in errors) / len(errors) if errors else None,
            "rmse": math.sqrt(math.fsum(e * e for e in errors) / len(errors)) if errors else None,
        }
    return {
        "rows": len(rows),
        "arms": arms,
        "paired_log_score": _clustered(deltas, rows, candidate=candidate),
        "intermediate_signal_diagnostics": diagnostics,
    }


def summarize(
    rows: list[dict[str, Any]], contract: Mapping[str, Any], candidate: str
) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        for tag in (
            "overall",
            f"season:{r['season']}",
            f"position:{r['position']}",
            "home" if r["was_home"] else "away",
            "GW1-6" if r["gw"] <= 6 else "GW7+",
            "cold" if r["cold_start"] else "established",
            "direct_proxy" if r["price_proxy_dependent"] else "non_proxy",
            "team_proxy" if r["team_price_proxy_codes"] else "no_team_proxy",
            "corrected" if r["correction_applied"] else "fallback",
            "role_forecast_present" if r["oos_role_forecast_present"] else "role_forecast_absent",
        ):
            groups[tag].append(r)
    slices = {
        k: score_rows(v, candidate=candidate, seed=contract["seed"]) for k, v in groups.items()
    }
    arms = slices["overall"]["arms"]
    new = arms["candidate"]
    old = arms["current"]
    baselines = [arms[k] for k in ("position_baseline", "trailing_baseline")]

    def lift(a: float, b: float) -> float:
        return (a - b) / abs(a) if a else 0.0

    gates = {
        "primary_vs_current": lift(old["log_score"], new["log_score"])
        >= contract["minimum_primary_lift_vs_current"],
        "primary_vs_best_required_baseline": lift(
            min(b["log_score"] for b in baselines), new["log_score"]
        )
        >= contract["minimum_primary_lift_vs_required_best_baseline"],
        "rps_no_regression": new["rps"] <= min(old["rps"], *(b["rps"] for b in baselines)),
        "brier_no_regression": new["brier_any"]
        <= min(old["brier_any"], *(b["brier_any"] for b in baselines)),
        "pit80": new["pit80_error"] <= contract["maximum_pit80_absolute_error"],
        "season_consistency": all(
            s["arms"]["candidate"]["log_score"] <= s["arms"]["current"]["log_score"]
            for k, s in slices.items()
            if k.startswith("season:")
        ),
        "required_baseline_season_consistency": all(
            s["arms"]["candidate"]["log_score"]
            <= min(s["arms"][k]["log_score"] for k in ("position_baseline", "trailing_baseline"))
            for k, s in slices.items()
            if k.startswith("season:")
        ),
        "same_population": len(rows) == contract["expected_rows"],
        "direct_proxy_count": sum(r["price_proxy_dependent"] for r in rows) == 821,
        "zero_candidate_event_leakage": all(
            r["maximum_prior_kickoff"] is None
            or datetime.fromisoformat(r["maximum_prior_kickoff"]) + timedelta(hours=6)
            < datetime.fromisoformat(r["as_of"])
            for r in rows
        ),
    }
    relative = lift(old["log_score"], new["log_score"])
    scoped = (
        "SUPPORTED"
        if all(gates.values())
        else "REFUTED"
        if relative <= -contract["refutation_relative_regression"]
        else "INCONCLUSIVE"
    )
    return {
        "slices": slices,
        "numeric_diagnostic_gates": gates,
        "relative_log_lift_vs_current": relative,
        "scoped_diagnostic_verdict": scoped,
        "verdict": "INELIGIBLE",
        "eligibility_reason": (
            "114 nominal folds and one role season do not meet the unchanged 181-fold Stage C gate"
        ),
        "full_gate_fold_requirement": 181,
        "development_synthesis_eligible": False,
        "promotion_permitted": False,
        "hypothesis_scope": (
            "bounded soft-role/exposure opportunity allocation only, "
            "not the full tactical/player-role family"
        ),
    }


def run(
    *,
    root: Path,
    db: Path,
    minutes_cache: Path,
    component_cache: Path,
    role_result: Path,
    output: Path,
    component: Component,
) -> dict[str, Any]:
    root, db, output = root.resolve(), db.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("new external write-once result required")
    with connect(db, read_only=True) as con:
        provenance = snapshot(root, db, component, component_cache, role_result)
        contract = load_contract(root, component)
        cache = read_minutes_control_cache(minutes_cache, db=db, root=root)
        references = load_component_reference_cache(
            component_cache,
            root=root,
            db=db,
            minutes_cache=minutes_cache,
            expected_manifest_sha256=contract["component_reference_manifest_sha256"],
        )
        role_batches = load_role_cache(
            role_result,
            root=root,
            expected_result_sha256=contract["role_result_sha256"],
        )
        contexts = {
            k: v for batch in role_batches.values() for k, v in role_contexts(batch).items()
        }
        archive = load_archive(con)
        reproduction = validate_controls(
            cache, references, archive, component=component, contract=contract
        )
        history = prepare_history(
            archive,
            contexts,
            component=component,
            database_sha256=contract["database_sha256"],
        )
        if snapshot(root, db, component, component_cache, role_result) != provenance:
            raise ValueError("preflight source drift")
        claim = reserve_program_claim(root, NAMES[component], provenance)
        output.mkdir(parents=True, exist_ok=False)
        publish_json(output / "provenance.json", provenance)
        publish_json(output / "comparator_reproduction.json", reproduction)
        observations = {(r["season"], r["fixture"], r["code"]): r for r in archive}
        retained: list[dict[str, Any]] = []
        folds: list[dict[str, Any]] = []
        started = datetime.now(UTC).isoformat()
        try:
            for fold, reference in zip(cache.folds, references, strict=True):
                controls = [control_from_cache(fold, row) for row in fold.rows]
                team = {
                    (f, t): sum(k * p for k, p in enumerate(pmf))
                    for f, t, pmf in reference.team_scored
                }
                conversion = (
                    json.loads(reference.diagnostics_json)["assist_conversion"]
                    if component == "assists"
                    else 1.0
                )
                inputs = []
                for control, ref in zip(controls, reference.rows, strict=True):
                    rate = (
                        ref.unconditional_goal_rate
                        if component == "goals"
                        else ref.unconditional_assist_rate
                    )
                    scale = (
                        None
                        if rate is None
                        else team[(control.target.fixture, ref.team_code)] * conversion
                    )
                    inputs.append(
                        OpportunityInput(
                            control,
                            getattr(ref.player.components, component),
                            rate,
                            scale,
                            contexts.get(_target_key(control.target)),
                        )
                    )
                baselines = baseline_predictions(archive, reference, component)
                fitted = fit_opportunity(
                    history,
                    component=component,
                    season=fold.season,
                    gw=fold.gw,
                    as_of=fold.as_of,
                    bins=MinuteBins.from_config(load_phase2_evaluation()),
                    current_club={r.target.code: r.team_code for r in fold.rows},
                )
                predicted = predict_opportunity_batch(fitted, inputs)
                predictions = []
                for p, source, ref in zip(predicted, inputs, reference.rows, strict=True):
                    t = source.control.target
                    context = source.role_context
                    raw = observations[t.season, t.fixture, t.code]
                    target_label = raw[contract["target"][component]]
                    pmf = marginal_pmf(p.conditional_pmf, source.control.probabilities)
                    incumbent = marginal_pmf(
                        source.conditional_incumbent_pmf, source.control.probabilities
                    )
                    baseline = baselines[(t.fixture, t.code)]
                    signal = ref.raw_goal_signal if component == "goals" else ref.raw_assist_signal
                    r = {
                        "season": t.season,
                        "gw": t.gw,
                        "fixture": t.fixture,
                        "code": t.code,
                        "team_code": t.team_code,
                        "position": ref.target.position.value,
                        "was_home": ref.target.was_home,
                        "kickoff": t.kickoff.isoformat(),
                        "as_of": t.as_of.isoformat(),
                        "candidate": pmf,
                        "current": incumbent,
                        "position_baseline": baseline[0],
                        "trailing_baseline": baseline[1],
                        "conditional_candidate": p.conditional_pmf,
                        "conditional_current": source.conditional_incumbent_pmf,
                        "minutes": source.control.probabilities,
                        "minutes_fold_sha256": fold.fold_sha256,
                        "cold_start": source.control.cold_start,
                        "price_proxy_dependent": source.control.price_proxy_dependent,
                        "team_price_proxy_codes": ref.team_price_proxy_codes,
                        "fixture_price_proxy_codes": ref.fixture_price_proxy_codes,
                        "selector_provenance": json.loads(source.control.selector_provenance_json),
                        "role_source_sha256": p.role_source_sha256,
                        "oos_role_forecast_present": context is not None,
                        "oos_role_forecast": None
                        if context is None
                        else {
                            "probabilities": context.prediction.probabilities,
                            "maximum_prior_event": context.prediction.maximum_prior_event,
                            "maximum_retained_event": context.prediction.maximum_retained_event,
                            "measured_starts": context.prediction.recent_measured_starts,
                            "source_rows_sha256": context.batch_source_sha256,
                        },
                        "role_probabilities": p.role_probabilities,
                        "correction_applied": p.correction_applied,
                        "fallback_reason": p.fallback_reason,
                        "opportunity": asdict(p),
                        "unchanged_team_scale": source.team_scale,
                        "maximum_prior_kickoff": fitted.maximum_prior_kickoff.isoformat()
                        if fitted.maximum_prior_kickoff
                        else None,
                        "signal_prediction": None
                        if p.posterior_rate_per_minute is None
                        else p.posterior_rate_per_minute * p.expected_minutes,
                        "signal_persistence_proxy": None
                        if signal is None
                        else signal * (1 - source.control.probabilities[0]),
                        "observed": {
                            "count": target_label,
                            "signal": raw[contract["signal"][component]],
                            "minutes": raw["minutes"],
                        },
                        "paired_log_loss": log_score(pmf, target_label)
                        - log_score(incumbent, target_label),
                    }
                    # Nested opportunity.target datetimes become explicit strings, never labels.
                    r = json.loads(json.dumps(r, default=str, allow_nan=False))
                    predictions.append(r)
                name = f"{fold.season}-gw{fold.gw:02d}.json"
                publish_json(
                    output / name,
                    {
                        "candidate": NAMES[component],
                        "fit": json.loads(json.dumps(asdict(fitted), default=str)),
                        "rows": predictions,
                        "same_gw_training_rows": 0,
                    },
                )
                folds.append(
                    {
                        "season": fold.season,
                        "gw": fold.gw,
                        "file": name,
                        "sha256": file_sha256(output / name),
                        "rows": len(predictions),
                    }
                )
                retained.extend(predictions)
                logger.info(
                    "%s %s GW%s: %s rows (%s/114)",
                    component,
                    fold.season,
                    fold.gw,
                    len(predictions),
                    len(folds),
                )
            keys = {(r["season"], r["fixture"], r["code"]) for r in retained}
            expected = {
                (r.target.season, r.target.fixture, r.target.code)
                for f in cache.folds
                for r in f.rows
            }
            if keys != expected or len(retained) != len(expected):
                raise ValueError("formal output fixture population changed")
            result = {
                "completed": True,
                "candidate": NAMES[component],
                "component": component,
                "evidence_class": EVIDENCE_CLASS,
                "started_at_utc": started,
                "provenance": provenance,
                "comparator_reproduction": reproduction,
                "claim_path": str(claim),
                "folds": folds,
                "row_count": len(retained),
                "fold_count": len(folds),
                **summarize(retained, contract, NAMES[component]),
            }
            if snapshot(root, db, component, component_cache, role_result) != provenance:
                raise ValueError("postflight source/HEAD/input drift")
            if read_minutes_control_cache(minutes_cache, db=db, root=root) != cache:
                raise ValueError("external minutes cache changed during opportunity scoring")
            if load_component_reference_cache(
                component_cache,
                root=root,
                db=db,
                minutes_cache=minutes_cache,
                expected_manifest_sha256=contract["component_reference_manifest_sha256"],
            ) != tuple(references):
                raise ValueError("external component reference changed during opportunity scoring")
            if (
                load_role_cache(
                    role_result,
                    root=root,
                    expected_result_sha256=contract["role_result_sha256"],
                )
                != role_batches
            ):
                raise ValueError("external OOS role evidence changed during opportunity scoring")
            if any(file_sha256(output / f["file"]) != f["sha256"] for f in folds):
                raise ValueError("completed output fold content changed before publication")
            result["finished_at_utc"] = datetime.now(UTC).isoformat()
            publish_json(output / "result.json", result)
            return result
        except BaseException as error:
            publish_json(
                output / "failure.json",
                {
                    "completed": False,
                    "candidate": NAMES[component],
                    "error_class": type(error).__name__,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                    "completed_folds": folds,
                    "provenance": provenance,
                    "claim_preserved": True,
                    "retry_permitted": False,
                },
            )
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=("goals", "assists"), required=True)
    for name in ("db", "minutes-cache", "component-cache", "role-result", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run(
        root=repo_root(),
        db=args.db,
        minutes_cache=args.minutes_cache,
        component_cache=args.component_cache,
        role_result=args.role_result,
        output=args.output,
        component=cast(Component, args.component),
    )
    print(
        json.dumps(
            {
                "rows": result["row_count"],
                "folds": result["fold_count"],
                "verdict": result["verdict"],
                "relative_log_lift": result["relative_log_lift_vs_current"],
            }
        )
    )


if __name__ == "__main__":
    main()
