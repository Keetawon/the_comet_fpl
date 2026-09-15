"""One clean, write-once disciplinary experiment over the shared minutes proxy.

No production entry point or optional dirty mode. Predictions and conditional
PMFs are retained per fixture before read-only scoring; the claim survives failure.
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
from typing import Any

import duckdb
import yaml

from fpl.config import repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256, git_clean_head, publish_json
from fpl.models.disciplinary_development import (
    EVIDENCE_CLASS,
    NAME,
    NONE,
    ConditionalDisciplinary,
    DisciplinaryObservation,
    DisciplinaryParameters,
    ExposurePooledDisciplinary,
    scored_card_state,
)
from fpl.models.points_composition import ComponentDistributions
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.dev_v2_tactical_matchup import _clustered
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.development_reference_components import (
    ValidatedMinutesControlCache,
    read_minutes_control_cache,
)
from fpl.validate.minutes_metrics import _reliability_curve

CONFIG = "config/player_disciplinary_evaluation.yaml"
CONFIG_SHA256 = "698572ded8ca4477482baca215717a88e229add0f319d285080df29b6ce32b6f"
AUDIT = "results/player_disciplinary_target_audit.json"
AUDIT_SHA256 = "89acf83a4c664a77d5b30591f823f8ef5ef7397d3c15f2ea4d50dd2806e3fea6"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
ARMS = ("incumbent_zero", "position_control", "candidate")
FLOOR = 1e-12
logger = logging.getLogger(__name__)


def load_contract(root: Path) -> dict[str, Any]:
    if file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ValueError("disciplinary preregistration bytes changed")
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    for key, value in asdict(DisciplinaryParameters()).items():
        config_key = "global_pseudocount_per_cause" if key == "global_pseudocount" else key
        if contract[config_key] != value:
            raise ValueError("disciplinary model parameter differs from frozen contract")
    if contract["candidate"] != NAME or contract["evidence_class"] != EVIDENCE_CLASS:
        raise ValueError("disciplinary candidate/evidence mismatch")
    return contract


def snapshot(root: Path, db: Path) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    if branch != BRANCH:
        raise ValueError("formal disciplinary run requires exact V2 branch")
    contract = load_contract(root)
    if not db.is_file() or Path(str(db) + ".wal").exists():
        raise ValueError("missing database or unresolved WAL")
    if file_sha256(db) != contract["database_sha256"]:
        raise ValueError("disciplinary database differs from shared proxy reference")
    if file_sha256(root / AUDIT) != AUDIT_SHA256:
        raise ValueError("disciplinary source audit changed")
    files = sorted(
        {
            *root.glob("src/**/*.py"),
            *root.glob("tests/**/*.py"),
            *root.glob("config/*.yaml"),
            *root.glob("results/*.json"),
            *root.glob("docs/*.md"),
            root / "AGENTS.md",
            root / "DEV-ROADMAP.md",
            root / "README.md",
        }
    )
    return {
        "git_head": head,
        "clean_worktree": True,
        "branch": branch,
        "candidate": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "production_promotion": False,
        "database_path": str(db),
        "database_sha256": contract["database_sha256"],
        "config_sha256": CONFIG_SHA256,
        "source_audit_sha256": AUDIT_SHA256,
        "source_sha256": {
            str(p.relative_to(root)).replace("\\", "/"): file_sha256(p) for p in files
        },
        "seed": contract["seed"],
        "historical_deadline_validity": False,
        "minutes_comparator": contract["minutes_comparator"],
        "registry_proxy_scope": "821_price_sensitive_cold_rows_only",
        "known_at_rewritten": False,
    }


def reserve_claim(root: Path, provenance: Mapping[str, Any]) -> Path:
    return reserve_program_claim(root, NAME, provenance)


def load_targets(con: duckdb.DuckDBPyConnection) -> list[DisciplinaryObservation]:
    frame = con.execute(
        """SELECT season,gw,fixture,code,position,kickoff_time,minutes,
                  yellow_cards,red_cards FROM mart_fact_player_fixture
           ORDER BY kickoff_time,season,fixture,code"""
    ).pl()
    rows = []
    seen = set()
    for raw in frame.iter_rows(named=True):
        identity = raw["season"], raw["fixture"], raw["code"]
        if identity in seen:
            raise ValueError("duplicate archive card target")
        seen.add(identity)
        scored_card_state(raw["yellow_cards"], raw["red_cards"])
        rows.append(
            DisciplinaryObservation(
                raw["season"],
                raw["gw"],
                raw["fixture"],
                raw["code"],
                Position(raw["position"]),
                raw["kickoff_time"],
                raw["minutes"],
                raw["yellow_cards"],
                raw["red_cards"],
            )
        )
    return rows


def validate_population(
    cache: ValidatedMinutesControlCache, history: Sequence[DisciplinaryObservation]
) -> dict[str, Any]:
    targets = {(r.season, r.fixture, r.code): r for r in history}
    identities = set()
    proxy = 0
    seasons: dict[str, int] = defaultdict(int)
    for fold in cache.folds:
        for cached in fold.rows:
            target = cached.target
            key = target.season, target.fixture, target.code
            if key in identities or key not in targets:
                raise ValueError("shared card target population differs")
            identities.add(key)
            row = targets[key]
            if (
                row.gw != fold.gw
                or row.position != target.position
                or row.kickoff != target.kickoff_time
                or row.minutes is None
                or scored_card_state(row.yellow, row.red) is None
            ):
                raise ValueError("card target identity/coverage differs")
            proxy += int(cached.price_proxy_dependent)
            seasons[fold.season] += 1
    if len(identities) != 86755 or len(cache.folds) != 114 or proxy != 821:
        raise ValueError("card population/fold/proxy counts differ from preregistration")
    if seasons != {"2023-24": 29725, "2024-25": 27283, "2025-26": 29747}:
        raise ValueError("card season population differs")
    if ComponentDistributions.__dataclass_fields__["disciplinary"].default is not None:
        raise ValueError("current incumbent no longer defaults to zero card outcomes")
    return {
        "rows": len(identities),
        "folds": len(cache.folds),
        "direct_price_proxy_rows": proxy,
        "non_proxy_rows": len(identities) - proxy,
        "by_season": dict(seasons),
        "zero_card_incumbent_confirmed": True,
        "minutes_control_full_pmf_hashes_validated": True,
    }


def independent_position_control(
    history: Sequence[DisciplinaryObservation], cutoff: datetime, excluded: tuple[str, int]
) -> dict[Position, ConditionalDisciplinary]:
    """Independent count aggregation/algebra, no candidate predict call."""
    counts = {p: [0.0, 0.0, 0.0] for p in Position}
    exposure: dict[int, list[int]] = defaultdict(list)
    for row in history:
        if row.kickoff + timedelta(hours=6) >= cutoff or (row.season, row.gw) == excluded:
            continue
        state = scored_card_state(row.yellow, row.red)
        if row.minutes is None or row.minutes <= 0 or state is None:
            continue
        c = counts[row.position]
        c[0] += row.minutes
        c[1] += int(state == 1)
        c[2] += int(state == 2)
        exposure[1 if row.minutes < 60 else 2 if row.minutes < 90 else 3].append(row.minutes)
    total = [sum(v[k] for v in counts.values()) for k in range(3)]
    league = [(total[k] + 0.5) / (total[0] + 90) for k in (1, 2)]
    result = {}
    for position in Position:
        c = counts[position]
        rates = [(c[k] + 4500 * league[k - 1]) / (c[0] + 4500) for k in (1, 2)]
        summed = sum(rates)
        pmfs = [NONE]
        for b, fallback in enumerate((0, 59, 89, 90)):
            if not b:
                continue
            minutes = sum(exposure[b]) / len(exposure[b]) if exposure[b] else fallback
            probability = -math.expm1(-summed * minutes)
            pmfs.append(
                (1 - probability, probability * rates[0] / summed, probability * rates[1] / summed)
            )
        result[position] = ConditionalDisciplinary((pmfs[0], pmfs[1], pmfs[2], pmfs[3]))
    return result


def _binary_log(p: float, y: int) -> float:
    return -math.log(max(FLOOR, p if y else 1 - p))


def losses(pmf: Sequence[float], outcome: int) -> dict[str, float]:
    if len(pmf) != 3 or any(not math.isfinite(p) or p < 0 for p in pmf):
        raise ValueError("invalid scored card PMF")
    if not math.isclose(sum(pmf), 1, rel_tol=0, abs_tol=1e-12) or outcome not in (0, 1, 2):
        raise ValueError("invalid card support or mass")
    return {
        "joint_log": -math.log(max(FLOOR, pmf[outcome])),
        "yellow_log": _binary_log(pmf[1], int(outcome == 1)),
        "yellow_brier": (pmf[1] - int(outcome == 1)) ** 2,
        "red_log": _binary_log(pmf[2], int(outcome == 2)),
        "red_brier": (pmf[2] - int(outcome == 2)) ** 2,
    }


def average_precision(probabilities: Sequence[float], labels: Sequence[int]) -> float | None:
    """Threshold-grouped AP: equal probabilities never gain arbitrary row-order resolution."""
    positives = sum(labels)
    if not positives:
        return None
    groups: dict[float, list[int]] = defaultdict(list)
    for p, y in zip(probabilities, labels, strict=True):
        groups[p].append(y)
    seen = true = 0
    total = 0.0
    for p in sorted(groups, reverse=True):
        ys = groups[p]
        gained = sum(ys)
        seen += len(ys)
        true += gained
        total += gained / positives * true / seen
    return total


def score_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "arms": {}}
    arms = {}
    for arm in ARMS:
        scores = [losses(row[arm], row["outcome"]) for row in rows]
        summary = {k: math.fsum(s[k] for s in scores) / len(rows) for k in scores[0]}
        calibration = {}
        for state, name in ((1, "yellow"), (2, "red")):
            ps, ys = (
                [row[arm][state] for row in rows],
                [int(row["outcome"] == state) for row in rows],
            )
            calibration[name] = {
                "bias": math.fsum(p - y for p, y in zip(ps, ys, strict=True)) / len(rows),
                "mean_probability": math.fsum(ps) / len(rows),
                "observed_rate": sum(ys) / len(rows),
                "reliability": asdict(_reliability_curve(ps, ys, [i / 10 for i in range(11)])),
            }
        arms[arm] = {
            **summary,
            "calibration": calibration,
            "red_average_precision": average_precision(
                [row[arm][2] for row in rows], [int(row["outcome"] == 2) for row in rows]
            ),
        }
    uncertainty = {}
    for control in ARMS[:2]:
        deltas = [
            losses(r["candidate"], r["outcome"])["joint_log"]
            - losses(r[control], r["outcome"])["joint_log"]
            for r in rows
        ]
        uncertainty[control] = _clustered(deltas, rows, candidate=NAME)
    return {"rows": len(rows), "arms": arms, "paired_joint_loss": uncertainty}


def summarise(rows: list[dict[str, Any]], contract: Mapping[str, Any]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tags = (
            "overall",
            f"season:{row['season']}",
            f"position:{row['position']}",
            "home" if row["was_home"] else "away",
            "GW1-6" if row["gw"] <= 6 else "GW7+",
            "direct_price_proxy" if row["price_proxy_dependent"] else "non_proxy",
            "cold_start" if row["cold_start"] else "established",
            "actual_zero_minutes" if row["minutes_observed"] == 0 else "appeared",
            f"actual_minutes_bin:{row['observed_bin']}",
        )
        for tag in tags:
            groups[tag].append(row)
    slices = {tag: score_rows(group) for tag, group in groups.items()}
    overall = slices["overall"]["arms"]
    candidate, control = overall["candidate"], overall["position_control"]

    def lift(old: float, new: float) -> float:
        return (old - new) / old if old else 0.0

    gates = {
        "joint_lift_vs_incumbent": lift(
            overall["incumbent_zero"]["joint_log"], candidate["joint_log"]
        )
        >= contract["minimum_joint_lift_vs_incumbent"],
        "joint_lift_vs_position": lift(control["joint_log"], candidate["joint_log"])
        >= contract["minimum_joint_lift_vs_informative_control"],
        "yellow_log_lift": lift(control["yellow_log"], candidate["yellow_log"])
        >= contract["minimum_yellow_log_lift_vs_informative_control"],
        "yellow_brier": candidate["yellow_brier"] <= control["yellow_brier"],
        "red_log": candidate["red_log"] <= control["red_log"],
        "red_brier": candidate["red_brier"] <= control["red_brier"],
        "season_joint": all(
            s["arms"]["candidate"]["joint_log"] <= s["arms"]["position_control"]["joint_log"]
            for tag, s in slices.items()
            if tag.startswith("season:")
        ),
        "calibration": all(
            abs(candidate["calibration"][s]["bias"]) <= 0.02 for s in ("yellow", "red")
        ),
        "same_population": len(rows) == contract["expected_rows"],
        "proxy_population": len(groups["direct_price_proxy"]) == 821,
        "zero_leakage": all(
            r["maximum_source_kickoff"] is None
            or datetime.fromisoformat(r["maximum_source_kickoff"]) + timedelta(hours=6)
            < datetime.fromisoformat(r["as_of"])
            for r in rows
        ),
    }
    relative = lift(control["joint_log"], candidate["joint_log"])
    verdict = (
        "SUPPORTED"
        if all(gates.values())
        else (
            "REFUTED"
            if relative <= -contract["refutation_relative_joint_regression"]
            else "INCONCLUSIVE"
        )
    )
    diagnostic = slices["non_proxy"]["arms"]
    return {
        "slices": slices,
        "gates": gates,
        "verdict": verdict,
        "relative_joint_lift_vs_position": relative,
        "proxy_exclusion_diagnostic_relative_joint_lift": lift(
            diagnostic["position_control"]["joint_log"], diagnostic["candidate"]["joint_log"]
        ),
        "proxy_exclusion_changes_primary_population": False,
        "development_synthesis_eligible": all(gates.values()),
        "promotion_permitted": False,
    }


def run(*, root: Path, db: Path, minutes_cache: Path, output: Path) -> dict[str, Any]:
    root, db, output = root.resolve(), db.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("require new external output; no overwrite or tracked formal outputs")
    provenance = snapshot(root, db)
    contract = load_contract(root)
    cache = read_minutes_control_cache(minutes_cache, db=db, root=root)
    with connect(db, read_only=True) as con:
        history = load_targets(con)
        reproduction = validate_population(cache, history)
        if snapshot(root, db) != provenance:
            raise ValueError("formal preflight provenance changed")
        claim = reserve_claim(root, provenance)
        output.mkdir(parents=True, exist_ok=False)
        publish_json(output / "provenance.json", provenance)
        publish_json(output / "comparator_reproduction.json", reproduction)
        target_map = {(r.season, r.fixture, r.code): r for r in history}
        retained: list[dict[str, Any]] = []
        folds = []
        started = datetime.now(UTC).isoformat()
        try:
            for fold in cache.folds:
                fitted = ExposurePooledDisciplinary().fit(
                    history, as_of=fold.as_of, excluded_target_gw=(fold.season, fold.gw)
                )
                independent = independent_position_control(
                    history, fold.as_of, (fold.season, fold.gw)
                )
                # Comparator verified independently BEFORE candidate predictions for this fold.
                for position in Position:
                    if fitted.predict(-1, position, position_only=True) != independent[position]:
                        raise ValueError(
                            "independent position comparator PMF failed exact reproduction"
                        )
                predictions = []
                for cached in fold.rows:
                    target = cached.target
                    observed = target_map[target.season, target.fixture, target.code]
                    outcome = scored_card_state(observed.yellow, observed.red)
                    assert outcome is not None
                    assert observed.minutes is not None
                    conditional = fitted.predict(target.code, target.position)
                    control = independent[target.position]
                    candidate_pmf, control_pmf = (
                        conditional.marginal(cached.minutes),
                        control.marginal(cached.minutes),
                    )
                    row = {
                        "season": fold.season,
                        "gw": fold.gw,
                        "fixture": target.fixture,
                        "code": target.code,
                        "team_code": cached.team_code,
                        "position": target.position.value,
                        "was_home": target.was_home,
                        "kickoff": target.kickoff_time.isoformat(),
                        "as_of": fold.as_of.isoformat(),
                        "outcome": outcome,
                        "yellow_observed": observed.yellow,
                        "red_observed": observed.red,
                        "minutes_observed": observed.minutes,
                        "observed_bin": 0
                        if observed.minutes == 0
                        else 1
                        if observed.minutes < 60
                        else 2
                        if observed.minutes < 90
                        else 3,
                        "cold_start": cached.cold_start,
                        "price_proxy_dependent": cached.price_proxy_dependent,
                        "minutes": cached.minutes,
                        "minutes_fold_sha256": fold.fold_sha256,
                        "selector_provenance": json.loads(cached.selector_provenance_json),
                        "incumbent_zero": NONE,
                        "position_control": control_pmf,
                        "candidate": candidate_pmf,
                        "conditional_candidate": asdict(conditional),
                        "conditional_position_control": asdict(control),
                        "maximum_source_kickoff": fitted.maximum_source_kickoff.isoformat()
                        if fitted.maximum_source_kickoff
                        else None,
                        "source_completion_margin_hours": 6,
                        "same_gw_rows_used": 0,
                        "paired_joint_loss_vs_position": losses(candidate_pmf, outcome)["joint_log"]
                        - losses(control_pmf, outcome)["joint_log"],
                    }
                    predictions.append(row)
                name = f"{fold.season}-gw{fold.gw:02d}.json"
                publish_json(
                    output / name,
                    {
                        "rows": predictions,
                        "bin_exposure": fitted.bin_exposure,
                        "position_rates": {p.value: v for p, v in fitted.position_rates.items()},
                        "excluded_zero_minute_history_cards": fitted.excluded_zero_minute_cards,
                        "independent_position_pmf_maximum_difference": 0.0,
                        "parameters": asdict(fitted.parameters),
                    },
                )
                folds.append(
                    {"file": name, "sha256": file_sha256(output / name), "rows": len(predictions)}
                )
                retained.extend(predictions)
                logger.info("cards fold %s GW%s: %s rows", fold.season, fold.gw, len(predictions))
            result = {
                "completed": True,
                "candidate": NAME,
                "evidence_class": EVIDENCE_CLASS,
                "started_at_utc": started,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "provenance": provenance,
                "comparator_reproduction": reproduction,
                "fold_count": len(folds),
                "row_count": len(retained),
                "folds": folds,
                "claim_path": str(claim),
                "seed": contract["seed"],
                **summarise(retained, contract),
                "role_tactical_workload_effects": "not_fitted_in_this_bounded_candidate",
                "zero_minute_cards": [
                    r for r in retained if r["minutes_observed"] == 0 and r["outcome"] != 0
                ],
            }
            if snapshot(root, db) != provenance:
                raise ValueError("formal postflight source/HEAD/database changed")
            publish_json(output / "result.json", result)
            return result
        except BaseException as error:
            publish_json(
                output / "failure.json",
                {
                    "candidate": NAME,
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
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--minutes-cache", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run(root=repo_root(), db=args.db, minutes_cache=args.minutes_cache, output=args.output)
    print(
        json.dumps(
            {
                "rows": result["row_count"],
                "folds": result["fold_count"],
                "verdict": result["verdict"],
            }
        )
    )


if __name__ == "__main__":
    main()
