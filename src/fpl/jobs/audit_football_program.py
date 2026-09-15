"""Read-only prerequisite inventory; never a model evaluation or readiness verdict.

    python -m fpl.jobs.audit_football_program --db PATH --output NEW_REPORT.json

The caller must name an existing quiescent database and a new report. No database is
created, staged, checkpointed, or repaired. Missing tables/evidence are reported as missing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from fpl.config import repo_root
from fpl.storage.db import table_columns, table_exists

EVIDENCE_PATTERNS = (
    "docs/evidence/phase2-stage-b-*.json",
    "docs/evidence/phase3-stage-c-*.json",
    "results/stage_c_*_development.json",
    "docs/results/phase4-*-development.json",
)
# GK evidence is nested inside the frozen team-environment result, not a separate file.
REQUIRED_EVIDENCE = (
    "docs/evidence/phase2-stage-b-baseline-2026-07-29.json",
    "docs/evidence/phase2-stage-b-candidate-v1-2026-07-30.json",
    "docs/evidence/phase2-stage-b-candidate-v2-2026-07-30.json",
    "docs/evidence/phase2-stage-b-candidate-v3-2026-07-30.json",
    "docs/evidence/phase3-stage-c-attacking-baseline-2026-07-31.json",
    "docs/evidence/phase3-stage-c-attacking-candidate-v1-2026-07-31.json",
    "docs/evidence/phase3-stage-c-attacking-candidate-v2-2026-08-01.json",
    "docs/evidence/phase3-stage-c-attacking-candidate-v3-2026-08-01.json",
    "docs/evidence/phase3-stage-c-assists-baseline-2026-08-01.json",
    "docs/evidence/phase3-stage-c-assists-candidate-v1-2026-08-01.json",
    "results/stage_c_goals_candidate_v4_development.json",
    "results/stage_c_assists_candidate_v2_development.json",
    "results/v2_team_environment_development.json",
    "results/v2_dc_development.json",
    "results/ev_backtest_2025_26_gw29_38.json",
)
SOURCE_PATTERNS = (
    "src/fpl/models/minutes_*.py",
    "src/fpl/models/attacking*.py",
)
REQUIRED_SOURCES = (
    "src/fpl/jobs/audit_football_program.py",
    "src/fpl/jobs/prospective_points_v1.py",
    "src/fpl/models/minutes_v1.py",
    "src/fpl/models/minutes_v2.py",
    "src/fpl/models/minutes_v3.py",
    "src/fpl/models/minutes_shrinkage.py",
    "src/fpl/models/attacking_v2.py",
    "src/fpl/models/attacking_v3.py",
    "src/fpl/models/price_starter_prior.py",
    "src/fpl/models/points_composition.py",
    "src/fpl/models/component_engine_v2.py",
    "src/fpl/models/scoring.py",
    "src/fpl/models/bps_bonus.py",
    "src/fpl/models/gk_saves_v1.py",
    "src/fpl/models/defensive_contribution_v1.py",
    "src/fpl/validate/baselines.py",
    "src/fpl/validate/points_harness.py",
    "src/fpl/validate/points_harness_v3.py",
    "src/fpl/validate/ev_backtest_adapter.py",
    "src/fpl/validate/ev_backtest_harness.py",
    "src/fpl/validate/metrics.py",
    "src/fpl/config.py",
    "config/phase2_evaluation.yaml",
    "config/phase3_evaluation.yaml",
    "config/phase3_stage_c_assists_evaluation.yaml",
    "config/phase4_ev_backtest_evaluation.yaml",
    "config/v2_gk_saves_evaluation.yaml",
    "config/v2_dc_evaluation.yaml",
    "config/scoring_2026_27.yaml",
)
SUMMARY_FIELDS = frozenset(
    {
        "schema",
        "schema_version",
        "status",
        "model",
        "contract",
        "contract_version",
        "provenance",
        "run",
        "environment_before",
        "environment_after",
        "git",
        "allow_dirty",
        "generated_at",
        "created_at",
        "completed_at",
        "git_commit_sha",
        "database_sha256",
        "contract_sha256",
        "scoring_sha256",
        "source_hashes",
        "historical_proxy_caveats",
        "limitations",
        "not_a_promotion",
        "baseline",
        "best_baseline",
        "population",
        "overall",
        "by_season",
        "by_position",
        "by_slice",
        "by_home_away",
        "folds_by_season",
        "folds_evaluated",
        "eligible_predictions",
        "total_predictions",
        "leakage_failures",
        "development_diagnostics",
        "covered_season_judging",
        "gk_saves",
        "target_completeness",
        "primary_architecture",
        "diagnostic_comparator",
        "contract_policy_applied",
        "components",
        "scored_label",
        "lift_against_baseline",
    }
)


def file_sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _paths(repo: Path, required: tuple[str, ...], patterns: tuple[str, ...]) -> list[str]:
    found = set(required)
    for pattern in patterns:
        found.update(path.relative_to(repo).as_posix() for path in repo.glob(pattern))
    return sorted(found)


def _summary(payload: dict[str, Any]) -> dict[str, Any]:
    result = {key: value for key, value in payload.items() if key in SUMMARY_FIELDS}
    harness = payload.get("harness")
    if isinstance(harness, dict):
        result["harness"] = _summary(harness)
    # Counts in a harness are scalar; never retain a large fixture prediction array here.
    if isinstance(payload.get("predictions"), int):
        result["predictions"] = payload["predictions"]
    return result


def repository_inventory(repo: Path) -> dict[str, Any]:
    """Fully parse frozen JSON but retain scores/provenance, not duplicate PMF arrays."""
    evidence: dict[str, Any] = {}
    for relative in _paths(repo, REQUIRED_EVIDENCE, EVIDENCE_PATTERNS):
        path = repo / relative
        if not path.is_file():
            evidence[relative] = {"status": "missing"}
            continue
        body = path.read_bytes()
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError(f"frozen evidence is not a JSON object: {relative}")
        evidence[relative] = {
            "status": "retained_not_reevaluated",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "top_level_keys": sorted(payload),
            "retained_summary": _summary(payload),
        }
    sources = {
        relative: (
            {"status": "present", "sha256": file_sha256(repo / relative)}
            if (repo / relative).is_file()
            else {"status": "missing"}
        )
        for relative in _paths(repo, REQUIRED_SOURCES, SOURCE_PATTERNS)
    }
    return {"frozen_evidence": evidence, "incumbent_source_fingerprints": sources}


def _rows(con: duckdb.DuckDBPyConnection, query: str) -> list[dict[str, Any]]:
    cursor = con.execute(query)
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _available(con: duckdb.DuckDBPyConnection, table: str, columns: set[str]) -> bool:
    return table_exists(con, table) and columns <= set(table_columns(con, table))


def database_inventory(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Validation-layer observations only: no output is a model-facing feature."""
    snapshots = None
    if _available(con, "snapshot_capture", {"season", "captured_at"}):
        snapshots = _rows(
            con,
            """
            SELECT season, count(*) AS captures,
                   strftime(min(captured_at), '%Y-%m-%dT%H:%M:%SZ') AS first_capture_utc,
                   strftime(max(captured_at), '%Y-%m-%dT%H:%M:%SZ') AS last_capture_utc
            FROM snapshot_capture GROUP BY season ORDER BY season
        """,
        )
    cards: dict[str, Any] = {}
    for table in ("raw_merged_gw", "stg_player_fixture", "mart_fact_player_fixture"):
        if not _available(con, table, {"season", "yellow_cards", "red_cards", "minutes"}):
            cards[table] = {"status": "missing_table_or_columns"}
            continue
        # Raw VARCHAR tokens (including blanks) remain verbatim in the joint-state inventory.
        cards[table] = {
            "status": "observed_only_not_semantic_verification",
            "joint_states": _rows(
                con,
                f"""
                SELECT season, yellow_cards, red_cards, count(*) AS rows,
                       count(*) FILTER (WHERE TRY_CAST(minutes AS DOUBLE) = 0) AS zero_minutes,
                       count(*) FILTER (WHERE TRY_CAST(minutes AS DOUBLE) > 0) AS appeared,
                       count(*) FILTER (WHERE TRY_CAST(minutes AS DOUBLE) IS NULL)
                           AS unmeasured_minutes
                FROM {table} GROUP BY season, yellow_cards, red_cards
                ORDER BY season, yellow_cards NULLS FIRST, red_cards NULLS FIRST
            """,
            ),
        }
    bench_columns = {
        "season",
        "gw",
        "fixture",
        "code",
        "position",
        "minutes",
        "yellow_cards",
        "red_cards",
    }
    benches = None
    if _available(con, "mart_fact_player_fixture", bench_columns):
        benches = _rows(
            con,
            """
            SELECT season, gw, fixture, code, position, minutes, yellow_cards, red_cards
            FROM mart_fact_player_fixture
            WHERE minutes = 0 AND (yellow_cards > 0 OR red_cards > 0)
            ORDER BY season, gw, fixture, code
        """,
        )
    completeness = None
    if _available(
        con,
        "mart_target_completeness",
        {"season", "ruleset_id", "is_complete", "missing_components", "row_count"},
    ):
        completeness = _rows(
            con,
            """
            SELECT season, ruleset_id, is_complete, missing_components, row_count
            FROM mart_target_completeness ORDER BY season, ruleset_id
        """,
        )
    raw_participation = None
    if _available(
        con, "raw_pl_sdp_payload", {"provider", "endpoint", "season", "status_code", "sdp_match_id"}
    ):
        raw_participation = _rows(
            con,
            """
            SELECT provider, endpoint, season, status_code, count(*) AS payload_versions,
                   count(DISTINCT sdp_match_id) AS distinct_matches
            FROM raw_pl_sdp_payload WHERE endpoint IN ('match_lineups', 'match_events')
            GROUP BY provider, endpoint, season, status_code
            ORDER BY provider, endpoint, season, status_code
        """,
        )
    staging = []
    for (table,) in con.execute("SHOW TABLES").fetchall():
        if str(table).startswith("stg_") and any(
            token in str(table).lower() for token in ("lineup", "event", "participation")
        ):
            # Table names are database metadata, not trusted SQL identifiers.
            quoted = '"' + str(table).replace('"', '""') + '"'
            count = con.execute(f"SELECT count(*) FROM {quoted}").fetchone()
            staging.append({"table": table, "rows": count[0] if count else None})
    return {
        "versioned_registry_snapshot_coverage": snapshots,
        "cards": cards,
        "zero_minute_card_exceptions": benches,
        "target_completeness": completeness,
        "raw_lineup_event_captures": raw_participation,
        "staging_participation_tables": sorted(staging, key=lambda row: row["table"]),
        "participation_caveat": (
            "Capture/table counts do not establish identity, minutes, or PIT coverage."
        ),
    }


def prerequisite_status(inventory: dict[str, Any]) -> list[dict[str, str]]:
    complete = inventory["target_completeness"]
    has_target = complete is not None and any(
        row["ruleset_id"] == "2026_27" and row["is_complete"] for row in complete
    )
    return [
        {
            "phase": "D",
            "status": "not_assessed",
            "requires": (
                "Exact seasonal/price incumbent adapter and OOS role/workload coverage; "
                "new contract."
            ),
        },
        {
            "phase": "E",
            "status": "not_assessed",
            "requires": (
                "Separate goal/assist contracts; OOS role/minutes marginalization and conservation."
            ),
        },
        {
            "phase": "F",
            "status": "not_assessed",
            "requires": (
                "Recorded joint-state semantics and new gate; draw-only appearance restriction."
            ),
        },
        {
            "phase": "I",
            "status": "not_assessed",
            "requires": (
                "Mechanically selected upstream evidence; cards-off exact PMF/RNG reproduction."
            ),
        },
        {
            "phase": "J",
            "status": "prerequisites_unverified" if has_target else "blocked_no_complete_target",
            "requires": (
                "Exact current incumbent, complete targets, same population, OOS stacking; "
                "new contract."
            ),
        },
    ]


def _git(repo: Path) -> dict[str, str | bool]:
    def call(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    return {"head": call("rev-parse", "HEAD"), "clean_worktree": not call("status", "--porcelain")}


def run_audit(database: Path, output: Path, *, repo: Path) -> dict[str, Any]:
    database = database.resolve(strict=True)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"write-once report already exists: {output}")
    output = output.resolve()
    wal = Path(f"{database}.wal")
    if output == wal:
        raise ValueError("report cannot be the database WAL sidecar")
    if wal.exists():
        raise RuntimeError(f"unresolved WAL; close writers and inspect recovery: {wal}")
    git = _git(repo)
    repository = repository_inventory(repo)
    # The read lease excludes an external DuckDB writer; hash while that lease is held.
    with duckdb.connect(str(database), read_only=True) as con:
        con.execute("SET TimeZone = 'UTC'")
        if wal.exists():
            raise RuntimeError("WAL appeared before the read lease")
        before = file_sha256(database)
        observations = database_inventory(con)
        after = file_sha256(database)
        if before != after or wal.exists():
            raise RuntimeError("database changed during read-only audit; no report published")
        if repository != repository_inventory(repo) or git != _git(repo):
            raise RuntimeError("repository evidence changed during audit; no report published")
        report: dict[str, Any] = {
            "schema_version": 1,
            "status": "prerequisite_inventory_only",
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "git": git,
            "database": {
                "path": str(database),
                "sha256_before": before,
                "sha256_after": after,
                "read_only": True,
                "wal_absent": True,
            },
            "repository": repository,
            "observations": observations,
            "prerequisites": prerequisite_status(observations),
            "model_fitting_performed": False,
            "evaluation_performed": False,
            "readiness_claim": False,
            "defaults_changed": False,
            "interpretation": {
                "incumbent": (
                    "prospective_points_v1: attacking=v3, appearance=seasonal, "
                    "share_signal=auto, assists=coupled"
                ),
                "historical_adapter": (
                    "Existing EV adapter is not exact current prospective behaviour; "
                    "reproduce current primitives first."
                ),
                "learned_constants": (
                    "Inherited alpha/price/cap/exposure constants used later historical evidence; "
                    "not untouched historical OOS estimates."
                ),
                "cards": (
                    "Nonappearance means zero SIMULATED card points only; "
                    "retain actual bench cards and marginalize predicted appearance."
                ),
                "points": (
                    "Keep actual replay totals; incumbent proper scores fold negative totals "
                    "to zero and upper tail to 34; raw error metrics do not."
                ),
            },
        }
        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation is shared with daily_pl_sdp; never overwrite an earlier audit.
        with output.open("x", encoding="utf-8") as handle:
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    run_audit(args.db, args.output, repo=repo_root())
    print(f"Read-only prerequisite inventory written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
