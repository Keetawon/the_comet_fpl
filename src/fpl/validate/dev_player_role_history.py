"""One write-once retrospective broad-role experiment; never a prospective interface.

``build_inputs`` performs coverage/identity checks only. Formal fitting is reachable
only after pinned coverage, clean provenance and a repository-wide exclusive claim.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import traceback
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from fpl.config import repo_root
from fpl.ingest.pl_sdp import is_completed_scored_match, parse_match_summary
from fpl.jobs.competitive_participation_pilot import file_sha256, git_clean_head, publish_json
from fpl.storage.competitive_workload import identity, semantic_identity
from fpl.storage.db import connect
from fpl.validate.development_program_provenance import reserve_program_claim
from fpl.validate.metrics import PROBABILITY_FLOOR, log_score
from fpl.validate.player_role_history import (
    COMPLETION_MARGIN_HOURS,
    EVIDENCE_CLASS,
    NAME,
    RAW_ROLES,
    ROLES,
    RoleHistoryRow,
    RoleTarget,
    forecast_role_batch,
)

CONFIG = "config/player_role_history_evaluation.yaml"
CONFIG_SHA256 = "UNREGISTERED_PENDING_V3_COVERAGE"
ALGORITHM_CONFIG = "config/player_role_history_v1.yaml"
ALGORITHM_SOURCE = "src/fpl/validate/player_role_history.py"
INTERPRETATION_ID = "competitive_participation_straight_red_v3"
ARMS = ("candidate", "pooled_prior", "smoothed_last_role", "recent_state_persistence")
BASELINES = ARMS[1:3]
ORIGINAL_CACHE_DATABASE_SHA256 = "0db60c08d5d85cda471c9ec65060365169007e036c28fa1dd851567a7d1ecac8"
VERSION_POLICY = "earliest_complete_final_original_capture_then_version_id_then_semantic_sha256"
FIXED_POLICY: dict[str, Any] = {
    "identity": NAME,
    "evidence_class": EVIDENCE_CLASS,
    "branch": "claude/comet-fpl-v2-architecture-mqrj8f",
    "season": "2025-26",
    "formal_evaluation_authorized": True,
    "promotion_permitted": False,
    "fixtures": 380,
    "folds": 38,
    "roster_rows": 29747,
    "all_fpl_starters": 8360,
    "minutes_cache_proxy_rows": 270,
    "minutes_cache_source_database_sha256": ORIGINAL_CACHE_DATABASE_SHA256,
    "minimum_starting_label_coverage": 0.95,
    "interpretation_id": INTERPRETATION_ID,
    "version_policy": VERSION_POLICY,
    "cutoff": "complete_target_gw_first_kickoff_proxy",
    "completion_margin_hours": 6,
    "known_events": "strictly_before_cutoff",
    "same_gw": "entire_target_season_gw_excluded",
    "target": "raw_provider_broad_role_conditional_on_fpl_recorded_start",
    "roster_projection": "immutable_minutes_cache_schedule_and_stable_identity_only",
    "arms": list(ARMS),
    "primary_baselines": list(BASELINES),
    "log_probability_floor": 1e-12,
    "brier_definition": "sum_of_four_squared_probability_errors",
    "accuracy_tie_break": list(ROLES),
    "minimum_relative_log_lift_vs_best_baseline": 0.01,
    "maximum_brier_relative_regression_vs_best_baseline": 0.0,
    "maximum_class_marginal_absolute_bias": 0.05,
    "maximum_temporal_violations": 0,
    "slices": ["class", "venue", "early_gw_1_6", "later_gw_7_plus", "cold_start", "price_proxy"],
    "parameters_selected": "none",
    "randomness": "none",
    "matched_persistence": "diagnostic_required_for_transition_attribution_not_a_posthoc_gate",
    "claim_policy": "repository_candidate_identity_write_once_before_any_fit",
}
PIN_KEYS = {
    "database_sha256",
    "stage_report_sha256",
    "coverage_report_sha256",
    "minutes_manifest_sha256",
    "algorithm_config_sha256",
    "algorithm_source_sha256",
}


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.utcoffset() is None:
        raise ValueError("role source timestamps must be aware")
    return result.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def _key(season: str, fixture: int, code: int) -> str:
    return f"{season}:{fixture}:{code}"


def _regular(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"existing nonsymlink file required: {path}")


def _database_guard(database: Path, expected: str) -> None:
    _regular(database)
    if Path(str(database) + ".wal").exists() or file_sha256(database) != expected:
        raise ValueError("role database WAL or fingerprint drift")


def load_contract(root: Path, config: Path) -> dict[str, Any]:
    _regular(config)
    if config.resolve() != (root / CONFIG).resolve() or file_sha256(config) != CONFIG_SHA256:
        raise ValueError("role preregistration exact bytes not pinned")
    contract: Any = yaml.safe_load(config.read_bytes())
    if not isinstance(contract, dict) or set(contract) != {
        "policy",
        "pins",
        "expected_eligible_starting_labels",
    }:
        raise ValueError("role contract exact keys required")
    if contract["policy"] != FIXED_POLICY or PROBABILITY_FLOOR != 1e-12:
        raise ValueError("role fixed policy differs")
    pins = contract["pins"]
    if not isinstance(pins, dict) or set(pins) != PIN_KEYS:
        raise ValueError("role provenance pins incomplete")
    if any(
        not isinstance(v, str) or len(v) != 64 or any(c not in "0123456789abcdef" for c in v)
        for v in pins.values()
    ):
        raise ValueError("role SHA256 pins malformed")
    count = contract["expected_eligible_starting_labels"]
    if type(count) is not int or not 7942 <= count <= 8360:
        raise ValueError("role eligible count must meet fixed 95% coverage")
    return dict(contract)


def _clean_branch(root: Path) -> str:
    head = git_clean_head(root)
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=root, text=True
    ).strip()
    if branch != FIXED_POLICY["branch"]:
        raise ValueError("role evaluation requires the V2 branch")
    return head


@dataclass(frozen=True)
class RoleInputs:
    history: tuple[RoleHistoryRow, ...]
    targets: tuple[RoleTarget, ...]
    roster_metadata: dict[str, dict[str, Any]]
    labels: dict[str, str]
    coverage: dict[str, Any]
    source_versions: dict[str, dict[str, Any]]
    input_hashes: dict[str, str]


def _cache_roster(
    manifest_path: Path,
) -> tuple[list[RoleTarget], dict[str, dict[str, Any]], dict[str, str]]:
    """Only identity/schedule projection enters RoleTarget; cached fitted values are unused."""
    _regular(manifest_path)
    manifest = json.loads(manifest_path.read_bytes())
    if manifest.get("completed") is not True or manifest["counts"].get("2025-26") != 29747:
        raise ValueError("completed current-minutes roster reference required")
    if (
        manifest.get("provenance", {}).get("database_sha256")
        != FIXED_POLICY["minutes_cache_source_database_sha256"]
    ):
        raise ValueError("minutes cache must retain its ORIGINAL archive database identity")
    files: dict[str, str] = {str(manifest_path.resolve()): file_sha256(manifest_path)}
    targets: list[RoleTarget] = []
    metadata: dict[str, dict[str, Any]] = {}
    folds: set[tuple[str, int]] = set()
    for entry in manifest["folds"]:
        tag = entry["season"], entry["gw"]
        if tag in folds:
            raise ValueError("duplicate cached season/GW")
        folds.add(tag)
        if entry["season"] != "2025-26":
            continue
        path = manifest_path.parent / entry["file"]
        if not path.resolve().is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("cache path escapes manifest directory")
        _regular(path)
        if file_sha256(path) != entry["sha256"]:
            raise ValueError("cached roster fold hash differs")
        files[str(path.resolve())] = entry["sha256"]
        fold = json.loads(path.read_bytes())
        if (fold["season"], fold["gw"]) != tag or len(fold["rows"]) != entry["rows"]:
            raise ValueError("cached fold identity/count differs")
        cutoff = _time(fold["as_of"])
        projected: list[RoleTarget] = []
        for row in fold["rows"]:
            target = row["target"]
            if (target["season"], target["gw"]) != tag:
                raise ValueError("cached target outside fold")
            key = _key(target["season"], target["fixture"], target["code"])
            if key in metadata or type(row["price_proxy_dependent"]) is not bool:
                raise ValueError("cached duplicate target or invalid proxy lineage")
            projected.append(
                RoleTarget(
                    target["season"],
                    target["gw"],
                    target["fixture"],
                    target["code"],
                    row["team_code"],
                    _time(target["kickoff_time"]),
                    cutoff,
                    f"minutes_cache:{entry['sha256']}",
                )
            )
            metadata[key] = {
                "was_home": target["was_home"],
                "team_id": target["team_id"],
                "opponent_team_id": target["opponent_team_id"],
                "price_proxy_dependent": row["price_proxy_dependent"],
                "cache_fold_sha256": entry["sha256"],
                "cache_file": entry["file"],
                "cache_selector_provenance": row["selector_provenance"],
                "price_proxy_not_role_predictor": True,
            }
        if not projected or min(t.kickoff for t in projected) != cutoff:
            raise ValueError("cached complete-GW cutoff differs")
        targets.extend(projected)
    return targets, metadata, files


def select_versions(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select by original capture, never by correctness or retrospective score."""
    selected: dict[tuple[str, int, int], dict[str, Any]] = {}
    ordered = sorted(
        records, key=lambda r: (_time(r["capture_known_at"]), r["version_id"], r["semantic_sha256"])
    )
    for record in ordered:
        if record["interpretation_id"] != INTERPRETATION_ID or record["season"] != "2025-26":
            continue
        if semantic_identity(record) != record["semantic_sha256"]:
            raise ValueError("retained interpretation semantic hash differs")
        if record["capture_complete"] is not True:
            continue
        if not is_completed_scored_match(
            parse_match_summary(record["raw_match"]), now=_time(record["capture_known_at"])
        ):
            continue
        key = record["season"], record["competition_id"], record["match_id"]
        selected.setdefault(key, record)
    return [selected[k] for k in sorted(selected)]


def build_inputs(database: Path, minutes_manifest: Path) -> RoleInputs:
    """Coverage-only audit: no role probability/score computation, DB always read-only."""
    digest = file_sha256(database)
    _database_guard(database, digest)
    targets, metadata, hashes = _cache_roster(minutes_manifest)
    with connect(database, read_only=True) as con:
        records = select_versions(
            [
                json.loads(r[0])
                for r in con.execute(
                    "SELECT CAST(record_json AS VARCHAR) FROM dev_competitive_match_version "
                    "WHERE interpretation_id=?",
                    [INTERPRETATION_ID],
                ).fetchall()
            ]
        )
        anchors = dict(
            con.execute(
                "SELECT code,opta_code FROM mart_dim_player WHERE season='2025-26'"
            ).fetchall()
        )
        # Outcome projection is for independent label denominator/reconciliation only.
        columns = (
            "fixture",
            "gw",
            "code",
            "team_code",
            "starts",
            "kickoff",
            "was_home",
            "team_id",
            "opponent_team_id",
        )
        facts = [
            dict(zip(columns, row, strict=True))
            for row in con.execute("""
            SELECT f.fixture,f.gw,f.code,t.team_code,f.starts,CAST(f.kickoff_time AS VARCHAR),
                   f.was_home,f.team_id,f.opponent_team_id
            FROM mart_fact_player_fixture f JOIN mart_dim_team t
              ON f.season=t.season AND f.team_id=t.team_id
            WHERE f.season='2025-26' ORDER BY f.fixture,f.code
        """).fetchall()
        ]
    by_key = {_key("2025-26", r["fixture"], r["code"]): r for r in facts}
    if len(by_key) != len(facts) or set(by_key) != set(metadata):
        raise ValueError("cached and archive all-roster fixture identities differ")
    for target in targets:
        key = _key(target.season, target.fixture, target.code)
        f = by_key[key]
        m = metadata[key]
        if (
            target.gw,
            target.team_code,
            target.kickoff,
            m["was_home"],
            m["team_id"],
            m["opponent_team_id"],
        ) != (
            f["gw"],
            f["team_code"],
            _time(f["kickoff"]),
            f["was_home"],
            f["team_id"],
            f["opponent_team_id"],
        ):
            raise ValueError("cached roster identity/schedule contradiction")
    pl_records = {r["fpl_fixture"]: r for r in records if r["competition_id"] == 8}
    if len(pl_records) != sum(r["competition_id"] == 8 for r in records) or set(pl_records) != {
        t.fixture for t in targets
    }:
        raise ValueError("complete PL staged fixture population differs")
    history = []
    versions = {}
    measured: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    ignored: Counter[str] = Counter()
    for record in records:
        version_id = record["version_id"]
        summary = parse_match_summary(record["raw_match"])
        if summary.match_id != record["match_id"] or summary.kickoff != _time(record["kickoff"]):
            raise ValueError("staged match metadata identity contradiction")
        if record["competition_id"] == 8:
            fixture_facts = [f for f in facts if f["fixture"] == record["fpl_fixture"]]
            if {f["gw"] for f in fixture_facts} != {record["fpl_gw"]} or {
                _time(f["kickoff"]) for f in fixture_facts
            } != {summary.kickoff}:
                raise ValueError("PL source GW/kickoff contradiction")
        versions[version_id] = {
            k: record[k]
            for k in (
                "version_id",
                "semantic_sha256",
                "season",
                "competition_id",
                "match_id",
                "kickoff",
                "capture_known_at",
                "interpretation_known_at",
                "interpretation_id",
                "source_versions",
                "maximum_retained_event_timestamp",
                "verified_end_at",
                "interpretation_valid",
                "errors",
            )
        }
        for row in record["rows"]:
            if row["code"] is None or row["team_code"] is None:
                ignored["unresolved_stable_player_or_club"] += 1
                continue
            if anchors.get(row["code"]) != f"p{row['provider_player_id']}":
                raise ValueError("role provider-to-player identity contradiction")
            if record["competition_id"] == 8:
                key = _key(record["season"], record["fpl_fixture"], row["code"])
                if key in measured:
                    raise ValueError("duplicate staged player-fixture role")
                measured[key] = record, row
                if key in by_key and by_key[key]["team_code"] != row["team_code"]:
                    raise ValueError("role fixture club contradiction")
            if not record["interpretation_valid"] or not is_completed_scored_match(
                summary, now=_time(record["capture_known_at"])
            ):
                ignored["invalid_or_unfinished_membership_row"] += 1
                continue
            history.append(
                RoleHistoryRow(
                    record["season"],
                    record["competition_id"],
                    record["match_id"],
                    record["fpl_gw"],
                    row["code"],
                    row["team_code"],
                    _time(record["kickoff"]),
                    True,
                    row["started"],
                    row["provider_position"],
                    row["provider_player_id"],
                    anchors[row["code"]],
                    identity(record["identity_source"]),
                    version_id,
                    record["source_versions"]["lineups"]["sha256"],
                    _time(record["capture_known_at"]),
                    _time(record["interpretation_known_at"]),
                    _time(record["maximum_retained_event_timestamp"])
                    if record["maximum_retained_event_timestamp"]
                    else None,
                    _time(record["verified_end_at"]) if record["verified_end_at"] else None,
                )
            )
    labels: dict[str, str] = {}
    exclusions = []
    coverage_by_gw: defaultdict[int, Counter[str]] = defaultdict(Counter)
    for key, fact in by_key.items():
        if fact["starts"] is None:
            raise ValueError("FPL starting-target denominator is incomplete")
        if fact["starts"] == 0:
            continue
        if fact["starts"] != 1:
            raise ValueError("FPL fixture start label must be binary")
        source = measured.get(key)
        reason = "missing_provider_row"
        if source:
            record, row = source
            if not record["interpretation_valid"]:
                reason = "invalid_whole_fixture_interpretation"
            elif row["started"] is not True or row["membership"] != "starting_xi":
                reason = "unverified_starting_membership"
            elif row["provider_position"] not in RAW_ROLES:
                reason = "unlicensed_or_missing_raw_role"
            else:
                reason = "eligible"
                labels[key] = RAW_ROLES[row["provider_position"]]
        coverage_by_gw[fact["gw"]][reason] += 1
        if reason != "eligible":
            exclusions.append(
                {
                    "key": key,
                    "gw": fact["gw"],
                    "reason": reason,
                    "fixture_errors": pl_records[fact["fixture"]]["errors"],
                }
            )
    n_starters = len(labels) + len(exclusions)
    coverage = {
        "database_sha256": digest,
        "minutes_cache_source_database_sha256": FIXED_POLICY[
            "minutes_cache_source_database_sha256"
        ],
        "minutes_manifest_sha256": file_sha256(minutes_manifest),
        "interpretation_id": INTERPRETATION_ID,
        "version_policy": FIXED_POLICY["version_policy"],
        "roster_rows": len(targets),
        "fixtures": len(pl_records),
        "folds": len({t.gw for t in targets}),
        "all_fpl_starters": n_starters,
        "eligible_starting_labels": len(labels),
        "starting_label_coverage": len(labels) / n_starters if n_starters else 0.0,
        "minimum_starting_label_coverage": 0.95,
        "coverage_gate_passed": bool(n_starters and len(labels) / n_starters >= 0.95),
        "minutes_cache_proxy_rows": sum(m["price_proxy_dependent"] for m in metadata.values()),
        "role_counts": dict(sorted(Counter(labels.values()).items())),
        "by_gw": {str(gw): dict(sorted(c.items())) for gw, c in sorted(coverage_by_gw.items())},
        "excluded_starting_rows": exclusions,
        "ignored_history_rows": dict(sorted(ignored.items())),
        "history_rows": len(history),
        "selected_versions": len(versions),
        "source_version_identity": identity(versions),
        "roster_identity": identity(_jsonable([asdict(t) for t in targets])),
        "label_identity": identity(labels),
        "model_fitting": False,
        "model_scoring": False,
    }
    _database_guard(database, digest)
    return RoleInputs(tuple(history), tuple(targets), metadata, labels, coverage, versions, hashes)


def _score(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    if not rows:
        return {"rows": 0}
    losses, briers, hits = [], [], []
    predicted = [0.0] * 4
    actual = [0] * 4
    reliability: list[list[list[float]]] = [[[] for _ in range(10)] for _ in ROLES]
    for row in rows:
        p = tuple(row["probabilities"][arm])
        if (
            len(p) != 4
            or any(not math.isfinite(v) or v < 0 for v in p)
            or not math.isclose(sum(p), 1, abs_tol=1e-12)
        ):
            raise ValueError("invalid categorical role PMF")
        y = ROLES.index(row["actual_role"])
        losses.append(log_score(p, y))
        briers.append(math.fsum((v - float(i == y)) ** 2 for i, v in enumerate(p)))
        hits.append(max(range(4), key=lambda i: p[i]) == y)
        for i in range(4):
            predicted[i] += p[i]
            actual[i] += i == y
            reliability[i][min(9, int(p[i] * 10))].extend((p[i], float(i == y)))
    n = len(rows)
    bias = [(predicted[i] - actual[i]) / n for i in range(4)]
    return {
        "rows": n,
        "mean_log_score": math.fsum(losses) / n,
        "multinomial_brier": math.fsum(briers) / n,
        "accuracy": sum(hits) / n,
        "class_marginal_bias": dict(zip(ROLES, bias, strict=True)),
        "maximum_class_marginal_absolute_bias": max(map(abs, bias)),
        "mean_probabilities": dict(zip(ROLES, [v / n for v in predicted], strict=True)),
        "observed_frequencies": dict(zip(ROLES, [v / n for v in actual], strict=True)),
        "reliability": {
            role: [
                {
                    "bucket": j,
                    "rows": len(v) // 2,
                    "mean_probability": math.fsum(v[::2]) / (len(v) // 2) if v else None,
                    "observed_frequency": math.fsum(v[1::2]) / (len(v) // 2) if v else None,
                }
                for j, v in enumerate(reliability[i])
            ]
            for i, role in enumerate(ROLES)
        },
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Score retained common-label rows only; diagnostics cannot change the fitted candidate."""
    slices: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tags = [
            "overall",
            f"role:{row['actual_role']}",
            "home" if row["was_home"] else "away",
            "early_gw_1_6" if row["gw"] <= 6 else "later_gw_7_plus",
            "cold" if row["recent_measured_starts"] == 0 else "measured_history",
            "price_proxy" if row["price_proxy_dependent"] else "non_price_proxy",
        ]
        for tag in tags:
            slices[tag].append(row)
    scores = {tag: {arm: _score(part, arm) for arm in ARMS} for tag, part in sorted(slices.items())}
    overall = scores["overall"]
    best_log = min(overall[a]["mean_log_score"] for a in BASELINES)
    best_brier = min(overall[a]["multinomial_brier"] for a in BASELINES)
    candidate = overall["candidate"]
    lift = (best_log - candidate["mean_log_score"]) / best_log if best_log > 0 else 0.0
    gate = {
        "log_lift": lift >= 0.01,
        "brier_no_regression": candidate["multinomial_brier"] <= best_brier,
        "class_calibration": candidate["maximum_class_marginal_absolute_bias"] <= 0.05,
        "temporal_violations": 0,
    }
    paired = {}
    for arm in ARMS[1:]:
        groups: defaultdict[int, list[float]] = defaultdict(list)
        for row in rows:
            y = ROLES.index(row["actual_role"])
            groups[row["gw"]].append(
                log_score(tuple(row["probabilities"]["candidate"]), y)
                - log_score(tuple(row["probabilities"][arm]), y)
            )
        n = len(rows)
        mean = math.fsum(v for values in groups.values() for v in values) / n
        g = len(groups)
        se = (
            math.sqrt(
                g
                / (g - 1)
                * math.fsum((math.fsum(v) - len(v) * mean) ** 2 for v in groups.values())
            )
            / n
            if g > 1
            else None
        )
        paired[arm] = {
            "candidate_minus_control_log": mean,
            "gw_clusters": g,
            "gw_clustered_standard_error": se,
            "normal_95_interval": [mean - 1.96 * se, mean + 1.96 * se] if se is not None else None,
        }
    supported = gate["log_lift"] and gate["brier_no_regression"] and gate["class_calibration"]
    return {
        "scores": scores,
        "relative_log_lift_vs_best_baseline": lift,
        "gate": gate,
        "verdict": "SUPPORTED_FOR_DEVELOPMENT"
        if supported
        else "REFUTED"
        if lift < -0.01
        else "INCONCLUSIVE",
        "paired": paired,
        "transition_attribution_supported": candidate["mean_log_score"]
        < overall["recent_state_persistence"]["mean_log_score"],
        "promotion_permitted": False,
    }


def _fingerprints(root: Path) -> dict[str, str]:
    paths = {*root.glob("src/**/*.py"), *root.glob("config/**/*.yaml"), *root.glob("results/**/*")}
    return {
        str(p.relative_to(root)).replace("\\", "/"): file_sha256(p)
        for p in sorted(paths)
        if p.is_file()
    }


def _claim(root: Path, provenance: dict[str, Any]) -> Path:
    return reserve_program_claim(root, NAME, provenance)


def run(
    *,
    root: Path,
    database: Path,
    minutes_manifest: Path,
    stage_report: Path,
    coverage_report: Path,
    config: Path,
    output: Path,
) -> dict[str, Any]:
    """Refuse unregistered, changed, dirty or previously claimed runs before any fit."""
    if output.exists() or output.is_symlink() or output.resolve().is_relative_to(root.resolve()):
        raise ValueError("new external role output directory required")
    contract = load_contract(root, config)
    head = _clean_branch(root)
    pins = contract["pins"]
    checked_files = {
        database: pins["database_sha256"],
        minutes_manifest: pins["minutes_manifest_sha256"],
        stage_report: pins["stage_report_sha256"],
        coverage_report: pins["coverage_report_sha256"],
        root / ALGORITHM_CONFIG: pins["algorithm_config_sha256"],
        root / ALGORITHM_SOURCE: pins["algorithm_source_sha256"],
    }
    for path, digest in checked_files.items():
        _regular(path)
        if file_sha256(path) != digest:
            raise ValueError(f"role pinned input drift: {path}")
    _database_guard(database, pins["database_sha256"])
    stage = json.loads(stage_report.read_bytes())
    if (
        stage.get("completed") is not True
        or stage["operational_database_sha256"] != pins["database_sha256"]
        or stage.get("regressed_match_ids")
    ):
        raise ValueError("V3 staged source not certified")
    inputs = build_inputs(database, minutes_manifest)
    frozen_coverage = json.loads(coverage_report.read_bytes())
    if inputs.coverage != frozen_coverage:
        raise ValueError("coverage-only audit does not reproduce exactly")
    for key in ("roster_rows", "fixtures", "folds", "all_fpl_starters", "minutes_cache_proxy_rows"):
        if inputs.coverage[key] != FIXED_POLICY[key]:
            raise ValueError(f"role exact population differs: {key}")
    if (
        not inputs.coverage["coverage_gate_passed"]
        or len(inputs.labels) != contract["expected_eligible_starting_labels"]
    ):
        raise ValueError("role coverage gate failed before any fit")
    fingerprints = _fingerprints(root)
    provenance = {
        "identity": NAME,
        "evidence_class": EVIDENCE_CLASS,
        "git_head": head,
        "clean_worktree": True,
        "config_sha256": file_sha256(config),
        "contract": contract,
        "database": str(database.resolve()),
        "database_sha256": pins["database_sha256"],
        "source_sha256": fingerprints,
        "input_sha256": {str(p.resolve()): s for p, s in checked_files.items()}
        | inputs.input_hashes,
        "started_at_utc": datetime.now(UTC).isoformat(),
        "cutoff": FIXED_POLICY["cutoff"],
        "original_capture_times_preserved": True,
        "historical_deadline_knowledge_validity": False,
        "promotion_permitted": False,
    }
    if _clean_branch(root) != head:
        raise ValueError("role provenance changed before claim")
    claim = _claim(root, provenance)
    folds: list[dict[str, Any]] = []
    output.mkdir(parents=True, exist_ok=False)
    try:
        publish_json(output / "provenance.json", provenance)
        publish_json(output / "source_versions.json", inputs.source_versions)
        grouped: defaultdict[tuple[str, int], list[RoleTarget]] = defaultdict(list)
        for target in inputs.targets:
            grouped[(target.season, target.gw)].append(target)
        scored = []
        for tag in sorted(grouped, key=lambda t: grouped[t][0].as_of):
            batch = forecast_role_batch(inputs.history, grouped[tag])
            predictions = []
            for prediction in batch.predictions:
                t = prediction.target
                key = _key(t.season, t.fixture, t.code)
                if (
                    prediction.maximum_prior_event is not None
                    and prediction.maximum_prior_event >= t.as_of
                ):
                    raise ValueError("role future training event")
                if (
                    prediction.maximum_retained_event is not None
                    and prediction.maximum_retained_event >= t.as_of
                ):
                    raise ValueError("role future retained event")
                for source in prediction.recent_sources:
                    if (source.competition_id == 8 and (source.season, source.gw) == tag) or (
                        source.verified_end_at
                        or source.kickoff + timedelta(hours=COMPLETION_MARGIN_HOURS)
                    ) >= t.as_of:
                        raise ValueError("role target-GW or completion-bound leakage")
                probabilities = dict(
                    zip(
                        ARMS,
                        (
                            prediction.probabilities,
                            prediction.pooled_prior_baseline,
                            prediction.smoothed_last_role_baseline,
                            prediction.recent_state_persistence_baseline,
                        ),
                        strict=True,
                    )
                )
                row = _jsonable(asdict(prediction))
                row["key"] = key
                row["arm_probabilities"] = probabilities
                row["recent_sources"] = [_jsonable(asdict(s)) for s in prediction.recent_sources]
                row["cache_reference"] = inputs.roster_metadata[key]
                predictions.append(row)
                if key in inputs.labels:
                    scored.append(
                        {
                            "key": key,
                            "gw": t.gw,
                            "actual_role": inputs.labels[key],
                            "was_home": inputs.roster_metadata[key]["was_home"],
                            "price_proxy_dependent": inputs.roster_metadata[key][
                                "price_proxy_dependent"
                            ],
                            "recent_measured_starts": prediction.recent_measured_starts,
                            "probabilities": probabilities,
                        }
                    )
            fold = _jsonable(asdict(batch))
            fold["predictions"] = predictions
            name = f"{batch.season}-gw{batch.gw:02d}.json"
            publish_json(output / name, fold)
            folds.append(
                {
                    "file": name,
                    "sha256": file_sha256(output / name),
                    "gw": batch.gw,
                    "rows": len(predictions),
                }
            )
        if (
            sum(f["rows"] for f in folds) != 29747
            or len(folds) != 38
            or len(scored) != len(inputs.labels)
        ):
            raise ValueError("formal role population accounting failed")
        summary = summarize(scored)
        if _clean_branch(root) != head or _fingerprints(root) != fingerprints:
            raise ValueError("role source/HEAD changed during formal run")
        for path, digest in provenance["input_sha256"].items():
            if file_sha256(Path(path)) != digest:
                raise ValueError("role input changed during formal run")
        _database_guard(database, pins["database_sha256"])
        result = {
            "completed": True,
            "provenance": provenance,
            "claim": str(claim),
            "coverage": inputs.coverage,
            "folds": folds,
            "scored_rows": scored,
            **summary,
            "finished_at_utc": datetime.now(UTC).isoformat(),
        }
        publish_json(output / "result.json", result)
        return result
    except Exception as error:
        publish_json(
            output / "failure.json",
            {
                "completed": False,
                "claim_consumed": True,
                "claim": str(claim),
                "failure_class": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "retained_folds": folds,
                "provenance": provenance,
                "finished_at_utc": datetime.now(UTC).isoformat(),
            },
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("db", "minutes-cache", "stage-report", "coverage-report", "config", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    run(
        root=repo_root(),
        database=args.db,
        minutes_manifest=args.minutes_cache,
        stage_report=args.stage_report,
        coverage_report=args.coverage_report,
        config=args.config,
        output=args.output,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
