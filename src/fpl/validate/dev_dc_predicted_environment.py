"""One write-once retrospective DC successor, never a prospective default.

Reproduce CURRENT V1 first. Then one claimed sequential pass supplies genuinely
out-of-sample mean forecasts and fold-local dispersion; no target exposure input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import traceback
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from fpl.config import load_scoring_rules, repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256, git_clean_head, publish_json
from fpl.models.defensive_contribution_v1 import NAME as INCUMBENT
from fpl.models.defensive_contribution_v1 import DcHistoryRow, DefensiveContributionV1
from fpl.models.defensive_environment_v3 import (
    COMPLETION_MARGIN,
    DISPERSION_MINIMUM_ROWS,
    DISPERSION_PRIOR_ROWS,
    EVIDENCE_CLASS,
    MAXIMUM_COUNT,
    NAME,
    PRIOR_MATCHES,
    WINDOW,
    DcOosObservation,
    DcPlayerObservation,
    DcTarget,
    DcTeamObservation,
    PredictedDefensiveEnvironment,
    fit_dispersion,
    predict_threshold,
)
from fpl.storage.db import connect
from fpl.types import Position
from fpl.validate.dev_v2_tactical_matchup import _clustered
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.development_reference_components import (
    MANIFEST_SHA256,
    ValidatedMinutesControlCache,
    ValidatedMinutesControlFold,
    read_minutes_control_cache,
)
from fpl.validate.points_harness import default_component_suite

CONFIG = "config/dc_predicted_environment_evaluation.yaml"
CONFIG_SHA256 = "dd62d5db901d10e1004d7750763c7caaa97adf7e8b9820eaeba2220c209b02e4"
AUDIT = "results/dc_predicted_environment_coverage.json"
AUDIT_SHA256 = "a5e6ffb4e523bb887f5822964a901550d83be58eb86800cbee61836053af3c85"
BRANCH = "claude/comet-fpl-v2-architecture-mqrj8f"
ARMS = ("incumbent", "poisson", "candidate")


def document(value: Any) -> Any:
    return json.loads(
        json.dumps(value, sort_keys=True, allow_nan=False, default=lambda v: v.isoformat())
    )


def load_contract(root: Path) -> dict[str, Any]:
    if file_sha256(root / CONFIG) != CONFIG_SHA256 or file_sha256(root / AUDIT) != AUDIT_SHA256:
        raise ValueError("DC preregistration/source-audit bytes changed")
    config: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    pins = {
        "candidate": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "incumbent": INCUMBENT,
        "minutes_manifest_sha256": MANIFEST_SHA256,
        "team_window": WINDOW,
        "player_window": WINDOW,
        "prior_matches": PRIOR_MATCHES,
        "dispersion_minimum_rows": DISPERSION_MINIMUM_ROWS,
        "dispersion_prior_rows": DISPERSION_PRIOR_ROWS,
        "maximum_count": MAXIMUM_COUNT,
        "source_completion_margin_hours": COMPLETION_MARGIN.total_seconds() / 3600,
    }
    if any(config[k] != v for k, v in pins.items()):
        raise ValueError("DC implemented policy differs from preregistration")
    return config


def snapshot(root: Path, db: Path) -> dict[str, Any]:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    if branch != BRANCH:
        raise ValueError("DC formal run requires exact V2 branch")
    config = load_contract(root)
    if (
        not db.is_file()
        or Path(str(db) + ".wal").exists()
        or file_sha256(db) != config["database_sha256"]
    ):
        raise ValueError("DC database hash/WAL differs")
    files = sorted(
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
        "clean_worktree": True,
        "branch": branch,
        "candidate": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "historical_deadline_validity": False,
        "known_at_rewritten": False,
        "promotion_permitted": False,
        "database_path": str(db),
        "database_sha256": config["database_sha256"],
        "config_sha256": CONFIG_SHA256,
        "coverage_audit_sha256": AUDIT_SHA256,
        "minutes_manifest_sha256": MANIFEST_SHA256,
        "seed": config["seed"],
        "source_sha256": {p.relative_to(root).as_posix(): file_sha256(p) for p in files},
    }


def load_history(
    con: duckdb.DuckDBPyConnection,
) -> tuple[list[DcPlayerObservation], list[DcTeamObservation]]:
    p = con.execute("""SELECT p.season,p.gw,p.fixture,p.kickoff_time,p.code,t.team_code,
                 p.position,p.minutes,p.defensive_contribution
          FROM mart_fact_player_fixture p LEFT JOIN mart_dim_team t
            ON p.season=t.season AND p.team_id=t.team_id
          ORDER BY p.kickoff_time,p.season,p.fixture,p.code""").pl()
    players = [
        DcPlayerObservation(
            r["season"],
            r["gw"],
            r["fixture"],
            r["kickoff_time"],
            r["code"],
            r["team_code"],
            Position(r["position"]),
            r["minutes"],
            r["defensive_contribution"],
        )
        for r in p.iter_rows(named=True)
    ]
    t = con.execute("""SELECT season,gw,fixture,kickoff_time,team_code,defensive_actions
          FROM mart_fact_team_match_stats_v2 WHERE provider='fpl_archive'
          ORDER BY kickoff_time,season,fixture,team_code""").pl()
    teams = [
        DcTeamObservation(
            r["season"],
            r["gw"],
            r["fixture"],
            r["kickoff_time"],
            r["team_code"],
            r["defensive_actions"],
        )
        for r in t.iter_rows(named=True)
    ]
    if len({(r.season, r.fixture, r.code) for r in players}) != len(players) or len(
        {(r.season, r.fixture, r.team_code) for r in teams}
    ) != len(teams):
        raise ValueError("duplicate retained DC history identities")
    return players, teams


def primary(row: DcPlayerObservation) -> bool:
    return (
        row.position is not Position.GK
        and row.minutes is not None
        and row.minutes > 0
        and row.defensive_contribution is not None
    )


def eligible_folds(
    cache: ValidatedMinutesControlCache,
    players: Sequence[DcPlayerObservation],
    config: Mapping[str, Any],
) -> list[ValidatedMinutesControlFold]:
    return [
        fold
        for fold in cache.folds
        if fold.season in config["eligible_seasons"]
        and len(
            {
                (r.season, r.gw)
                for r in players
                if primary(r)
                and r.kickoff + COMPLETION_MARGIN < fold.as_of
                and (r.season, r.gw) != (fold.season, fold.gw)
            }
        )
        >= config["minimum_prior_measured_gameweeks"]
    ]


def verify_population(
    cache: ValidatedMinutesControlCache,
    players: Sequence[DcPlayerObservation],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    targets = {(r.season, r.fixture, r.code): r for r in players}
    keys = []
    full_rows = proxy = full_proxy = transferred = 0
    folds = eligible_folds(cache, players, config)
    for fold in folds:
        prior = [
            r
            for r in players
            if r.kickoff + COMPLETION_MARGIN < fold.as_of
            and (r.season, r.gw) != (fold.season, fold.gw)
        ]
        clubs: dict[tuple[str, int], set[int]] = defaultdict(set)
        for r in prior:
            clubs[r.season, r.code].add(r.team_code)
        for cached in fold.rows:
            target = cached.target
            if target.position is Position.GK:
                continue
            row = targets[target.season, target.fixture, target.code]
            if (
                row.position != target.position
                or row.gw != target.gw
                or row.kickoff != target.kickoff_time
                or row.team_code != cached.team_code
            ):
                raise ValueError("shared DC target identity mismatch")
            if row.minutes is None or row.defensive_contribution is None:
                raise ValueError("missing DC target must not be zero-filled or silently excluded")
            full_rows += 1
            full_proxy += cached.price_proxy_dependent
            if primary(row):
                keys.append((row.season, row.gw, row.fixture, row.code))
                proxy += cached.price_proxy_dependent
                transferred += any(code != row.team_code for code in clubs[row.season, row.code])
    identity = hashlib.sha256(json.dumps(sorted(keys), separators=(",", ":")).encode()).hexdigest()
    actual = {
        "primary_rows": len(keys),
        "outer_folds": len(folds),
        "all_outfield_roster_diagnostic_rows": full_rows,
        "primary_price_proxy_rows": proxy,
        "all_outfield_price_proxy_rows": full_proxy,
        "transferred_rows": transferred,
        "target_identity_sha256": identity,
    }
    if any(actual[k] != config[k] for k in actual) or len(keys) != len(set(keys)):
        raise ValueError("DC population differs from frozen coverage-only preregistration")
    if (
        sum(len(f.rows) for f in cache.folds) != 86755
        or len(cache.folds) != 114
        or sum(r.price_proxy_dependent for f in cache.folds for r in f.rows) != 821
    ):
        raise ValueError("shared complete minutes/proxy population differs")
    return actual


def reproduce_incumbent(
    folds: Sequence[ValidatedMinutesControlFold],
    players: Sequence[DcPlayerObservation],
    thresholds: Mapping[Position, int],
) -> tuple[dict[tuple[str, int, int], float], dict[str, Any]]:
    predictions = {}
    suite = default_component_suite()
    if suite.dc_name != INCUMBENT:
        raise ValueError("current prospective DC incumbent changed")
    for fold in folds:
        prior = [r for r in players if r.kickoff < fold.as_of]
        if any(
            r.kickoff + COMPLETION_MARGIN >= fold.as_of
            or (r.season, r.gw) == (fold.season, fold.gw)
            for r in prior
            if r.defensive_contribution is not None
        ):
            raise ValueError(
                "exact current DC history cannot reproduce stronger completion/GW boundary"
            )
        history = [
            DcHistoryRow(r.code, r.position, r.minutes, r.defensive_contribution)
            for r in prior
            if r.minutes is not None and r.defensive_contribution is not None
        ]
        original = DefensiveContributionV1(thresholds)
        original.fit(history)
        factory = suite.fit_dc(history, thresholds)
        if original.parameters() != {"alpha": 5.0, "window": 5}:
            raise ValueError("current DC incumbent parameters changed")
        for cached in fold.rows:
            target = cached.target
            if target.position is Position.GK:
                continue
            p = original.predict(target.code, target.position)
            if p != factory.predict(target.code, target.position):
                raise ValueError("current factory/DC class failed exact comparator reproduction")
            predictions[target.season, target.fixture, target.code] = p
    digest = hashlib.sha256(
        json.dumps(
            sorted((list(k), v) for k, v in predictions.items()), separators=(",", ":")
        ).encode()
    ).hexdigest()
    return predictions, {
        "incumbent": INCUMBENT,
        "parameters": {"alpha": 5.0, "window": 5},
        "folds": len(folds),
        "all_outfield_rows": len(predictions),
        "maximum_probability_difference": 0.0,
        "full_predictions_sha256": digest,
    }


def binary_scores(p: float, y: int) -> tuple[float, float]:
    if not math.isfinite(p) or not 0 <= p <= 1 or type(y) is not int or y not in (0, 1):
        raise ValueError("invalid binary DC probability/label")
    return -math.log(max(1e-12, p if y else 1 - p)), (p - y) ** 2


def auc(ps: Sequence[float], ys: Sequence[int]) -> float | None:
    grouped: dict[float, list[int]] = defaultdict(list)
    for p, y in zip(ps, ys, strict=True):
        grouped[p].append(y)
    positive = sum(ys)
    negative = len(ys) - positive
    if not positive or not negative:
        return None
    wins = 0.0
    seen_negative = 0
    for p in sorted(grouped):
        pos = sum(grouped[p])
        neg = len(grouped[p]) - pos
        wins += pos * (seen_negative + 0.5 * neg)
        seen_negative += neg
    return wins / (positive * negative)


def score(rows: Sequence[Mapping[str, Any]], *, unconditional: bool = False) -> dict[str, Any]:
    if not rows:
        return {"rows": 0, "arms": {}}
    slot = "unconditional" if unconditional else "conditional"
    arms = {}
    for arm in ARMS:
        ps = [r[slot][arm] for r in rows]
        ys = [r["observed_hit"] for r in rows]
        scores = [binary_scores(p, y) for p, y in zip(ps, ys, strict=True)]
        bins = []
        for b in range(10):
            selected = [(p, y) for p, y in zip(ps, ys, strict=True) if min(int(p * 10), 9) == b]
            bins.append(
                {
                    "lower": b / 10,
                    "upper": (b + 1) / 10,
                    "rows": len(selected),
                    "predicted": math.fsum(p for p, y in selected) / len(selected)
                    if selected
                    else None,
                    "observed": sum(y for p, y in selected) / len(selected) if selected else None,
                }
            )
        arms[arm] = {
            "mean_log_score": math.fsum(s[0] for s in scores) / len(rows),
            "brier_score": math.fsum(s[1] for s in scores) / len(rows),
            "auc": auc(ps, ys),
            "mean_predicted": math.fsum(ps) / len(rows),
            "observed_rate": sum(ys) / len(rows),
            "reliability": bins,
        }
    paired = {
        control: _clustered(
            [
                binary_scores(r[slot]["candidate"], r["observed_hit"])[0]
                - binary_scores(r[slot][control], r["observed_hit"])[0]
                for r in rows
            ],
            rows,
            candidate=NAME,
        )
        for control in ARMS[:2]
    }
    return {"rows": len(rows), "arms": arms, "paired_loss": paired}


def summarise(rows: list[dict[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if not r["primary"]:
            continue
        tags = (
            "overall",
            f"season:{r['season']}",
            f"position:{r['position']}",
            "home" if r["was_home"] else "away",
            "GW11-19" if r["gw"] < 20 else "GW20-29" if r["gw"] < 30 else "GW30+",
            "past_witnessed_transfer"
            if r["past_witnessed_transfer"]
            else "no_past_witnessed_transfer",
            "direct_price_proxy" if r["price_proxy_dependent"] else "non_proxy",
            "cold_start" if r["cold_start"] else "established",
            "predicted_appearance_zero"
            if sum(r["minutes_pmf"][1:]) == 0
            else "predicted_appearance_positive",
        )
        for tag in tags:
            groups[tag].append(r)
    slices = {tag: score(group) for tag, group in groups.items()}
    overall = slices["overall"]["arms"]
    control = overall["incumbent"]
    candidate = overall["candidate"]
    relative = (control["mean_log_score"] - candidate["mean_log_score"]) / control["mean_log_score"]
    transferred = slices.get("past_witnessed_transfer", {}).get("arms", {})
    gates = {
        "minimum_log_lift": relative >= config["minimum_relative_log_lift"],
        "no_brier_regression": candidate["brier_score"] <= control["brier_score"],
        "transferred_improves": bool(transferred)
        and transferred["candidate"]["mean_log_score"] < transferred["incumbent"]["mean_log_score"],
        "season_passes": all(
            (s["arms"]["incumbent"]["mean_log_score"] - s["arms"]["candidate"]["mean_log_score"])
            / s["arms"]["incumbent"]["mean_log_score"]
            >= config["minimum_relative_log_lift"]
            and s["arms"]["candidate"]["brier_score"] <= s["arms"]["incumbent"]["brier_score"]
            for tag, s in slices.items()
            if tag.startswith("season:")
        ),
        "same_population": len(groups["overall"]) == config["primary_rows"],
        "zero_leakage": all(
            r["maximum_source_kickoff"] is None
            or datetime.fromisoformat(r["maximum_source_kickoff"]) + COMPLETION_MARGIN
            < datetime.fromisoformat(r["as_of"])
            for r in rows
        ),
    }
    verdict = (
        "SUPPORTED" if all(gates.values()) else "REFUTED" if relative <= -0.01 else "INCONCLUSIVE"
    )
    return {
        "slices": slices,
        "all_outfield_unconditional_diagnostic": score(rows, unconditional=True),
        "gates": gates,
        "relative_log_lift_vs_current": relative,
        "verdict": verdict,
        "development_synthesis_eligible": all(gates.values()),
        "promotion_permitted": False,
        "proxy_exclusion_changes_primary_population": False,
    }


def run(*, root: Path, db: Path, minutes_cache: Path, output: Path) -> dict[str, Any]:
    root, db, output = root.resolve(), db.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(root):
        raise ValueError("new external output required; no result overwrite")
    provenance = snapshot(root, db)
    config = load_contract(root)
    cache = read_minutes_control_cache(minutes_cache, db=db, root=root)
    with connect(db, read_only=True) as con:
        players, teams = load_history(con)
        population = verify_population(cache, players, config)
        folds = eligible_folds(cache, players, config)
        thresholds = load_scoring_rules("2026_27").defensive_contribution.thresholds
        incumbent, reproduction = reproduce_incumbent(folds, players, thresholds)
        if snapshot(root, db) != provenance:
            raise ValueError("DC preflight provenance changed")
        claim = reserve_program_claim(root, NAME, provenance)
        output.mkdir(parents=True, exist_ok=False)
        (output / "oos_means").mkdir()
        publish_json(output / "provenance.json", provenance)
        publish_json(output / "comparator_reproduction.json", reproduction)
        retained = []
        oos: list[DcOosObservation] = []
        manifest = []
        upstream = []
        lookup = {(r.season, r.fixture, r.code): r for r in players}
        outer = {(f.season, f.gw) for f in folds}
        started = datetime.now(UTC).isoformat()
        try:
            for fold in sorted(
                (f for f in cache.folds if f.season in config["eligible_seasons"]),
                key=lambda f: (f.as_of, f.season, f.gw),
            ):
                key = (fold.season, fold.gw)
                model = PredictedDefensiveEnvironment().fit(
                    players, teams, as_of=fold.as_of, excluded_target_gw=key
                )
                dispersion = fit_dispersion(oos, as_of=fold.as_of, excluded_target_gw=key)
                batch = []
                predictions = []
                for cached in fold.rows:
                    t = cached.target
                    if t.position is Position.GK:
                        continue
                    target = DcTarget(
                        t.season,
                        t.gw,
                        t.fixture,
                        t.kickoff_time,
                        t.code,
                        cached.team_code,
                        t.position,
                        cached.minutes,
                    )
                    mean = model.predict_mean(target)
                    observed = lookup[t.season, t.fixture, t.code]
                    batch.append(
                        DcOosObservation(mean, observed.defensive_contribution, observed.minutes)
                    )
                    if key not in outer:
                        continue
                    old = incumbent[t.season, t.fixture, t.code]
                    cand = predict_threshold(mean, dispersion, thresholds[t.position], old)
                    poisson = predict_threshold(
                        mean, replace(dispersion, alpha=0.0), thresholds[t.position], old
                    )
                    assert observed.defensive_contribution is not None
                    p_play = math.fsum(cached.minutes[1:])
                    predictions.append(
                        {
                            "season": t.season,
                            "gw": t.gw,
                            "fixture": t.fixture,
                            "code": t.code,
                            "team_code": cached.team_code,
                            "position": t.position.value,
                            "was_home": t.was_home,
                            "kickoff": t.kickoff_time.isoformat(),
                            "as_of": fold.as_of.isoformat(),
                            "minutes_pmf": cached.minutes,
                            "minutes_fold_sha256": fold.fold_sha256,
                            "selector_provenance": json.loads(cached.selector_provenance_json),
                            "price_proxy_dependent": cached.price_proxy_dependent,
                            "cold_start": cached.cold_start,
                            "observed_count": observed.defensive_contribution,
                            "observed_minutes": observed.minutes,
                            "observed_hit": int(
                                observed.defensive_contribution >= thresholds[t.position]
                            ),
                            "threshold": thresholds[t.position],
                            "primary": primary(observed),
                            "past_witnessed_transfer": mean.past_witnessed_transfer,
                            "conditional": {
                                "incumbent": old,
                                "poisson": poisson.conditional_hit_probability,
                                "candidate": cand.conditional_hit_probability,
                            },
                            "unconditional": {
                                "incumbent": p_play * old,
                                "poisson": poisson.marginal_hit_probability,
                                "candidate": cand.marginal_hit_probability,
                            },
                            "candidate_count": document(asdict(cand)),
                            "poisson_count": document(asdict(poisson)),
                            "mean": document(asdict(mean)),
                            "maximum_source_kickoff": mean.maximum_source_kickoff.isoformat()
                            if mean.maximum_source_kickoff
                            else None,
                            "same_gw_source_rows": 0,
                        }
                    )
                # Attach this batch only after every target was predicted from the same state.
                name = f"{fold.season}-gw{fold.gw:02d}.json"
                publish_json(
                    output / "oos_means" / name,
                    {
                        "rows": document([asdict(r) for r in batch]),
                        "as_of": fold.as_of.isoformat(),
                        "same_gw_source_rows": 0,
                    },
                )
                upstream.append(
                    {
                        "file": "oos_means/" + name,
                        "sha256": file_sha256(output / "oos_means" / name),
                        "rows": len(batch),
                    }
                )
                oos.extend(batch)
                if key in outer:
                    publish_json(
                        output / name,
                        {
                            "rows": predictions,
                            "dispersion": document(asdict(dispersion)),
                            "league_environment": model.league_environment,
                            "position_ratios": {
                                p.value: v for p, v in model.position_ratios.items()
                            },
                            "history_sha256": model.history_sha256,
                        },
                    )
                    manifest.append(
                        {
                            "file": name,
                            "sha256": file_sha256(output / name),
                            "rows": len(predictions),
                            "primary_rows": sum(r["primary"] for r in predictions),
                        }
                    )
                    retained.extend(predictions)
                print(
                    f"DC {fold.season} GW{fold.gw}: upstream={len(batch)} outer={len(predictions)}",
                    flush=True,
                )
            result = {
                "completed": True,
                "candidate": NAME,
                "evidence_class": EVIDENCE_CLASS,
                "started_at_utc": started,
                "provenance": provenance,
                "population": population,
                "comparator_reproduction": reproduction,
                "upstream_folds": upstream,
                "folds": manifest,
                "claim_path": str(claim),
                **summarise(retained, config),
            }
            if (
                len(upstream) > config["maximum_environment_fits"]
                or len(manifest) != config["outer_folds"]
            ):
                raise ValueError("DC bounded fold count differs")
            if snapshot(root, db) != provenance:
                raise ValueError("DC postflight provenance changed")
            read_minutes_control_cache(minutes_cache, db=db, root=root)
            result["finished_at_utc"] = datetime.now(UTC).isoformat()
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
                    "claim_preserved": True,
                    "retry_permitted": False,
                    "completed_folds": manifest,
                },
            )
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--minutes-cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(root=repo_root(), db=args.db, minutes_cache=args.minutes_cache, output=args.output)
    print(
        json.dumps(
            {"candidate": NAME, "verdict": result["verdict"], "population": result["population"]}
        )
    )


if __name__ == "__main__":
    main()
