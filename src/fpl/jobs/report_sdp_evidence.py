"""Read-side report projection for recorded SDP evidence pairs.

Emits the pair binding plus every retained fixture/player row from the two ledger
vintages, each joined to its separately attached outcome from the append-only outcome
tables. Nothing here writes to the database; the connection is opened read-only and
``--db`` is required and explicit.

The report deliberately does NOT compute scores. It retains the exact rows those scores
consume (stored PMFs beside signed finalized actuals) and documents the remaining metric
CLI limitations in ``notes`` -- see ``docs/sdp-prospective-evidence.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fpl.storage.db import connect
from fpl.storage.sdp_evidence import (
    load_pair,
    pair_player_fixture_rows,
    pair_player_gameweek_rows,
    pair_team_fixture_rows,
)

if TYPE_CHECKING:
    import duckdb

_REPORT_SCHEMA = "fpl.sdp-evidence-pair-report/v2"
_GRAIN_CHOICES = ("team", "player-gameweek", "player-fixture", "all")

_STANDING = {
    "adoption": "owner_directed_sdp_v2_architectural_adoption",
    "statement": (
        "SDP-backed V2 is the primary football-environment architecture by owner direction; "
        "this pair is operational prospective evidence under that adoption. Frozen historical "
        "experimental verdicts are unchanged and nothing here is waiting on a scientific "
        "promotion verdict."
    ),
}

_NOTES = (
    "The inherited full-points artifact caveat stands: every row comes from a "
    "development-only prospective vintage, not a validated production forecast.",
    "Scores (team Goal NLL / clean-sheet Brier / CRPS / calibration; player NLL / CRPS / "
    "signed MAE / within-gameweek Spearman / P(points<=2|>=5|>=10) calibration) are NOT "
    "computed by this CLI; rows are retained at the exact grains and joined to separately "
    "attached finalized outcomes so those metrics can be computed downstream.",
    "Only finalized evidence enters ledger_outcome_*; the existing outcome attachment jobs "
    "remain authoritative. outcome.attached=false means not finalized or not yet attached "
    "(including any partial double gameweek), and such rows must never be scored.",
    "Selector/reason is exposed per fixture from the primary run's football-environment "
    "provenance; the shadow side is null because its environment is disabled by role. SDP "
    "source knowledge times are run-grain (source_provenance), not per fixture.",
    "Absent outcomes remain NULL; they are never zero-filled.",
)


def build_report(
    con: duckdb.DuckDBPyConnection, *, prediction_id: str, grain: str = "team"
) -> dict[str, Any]:
    """Assemble the JSON-ready report for one recorded pair."""
    pair = load_pair(con, prediction_id)
    if pair is None:
        raise ValueError(f"evidence pair {prediction_id} is not recorded")
    report: dict[str, Any] = {
        "schema": _REPORT_SCHEMA,
        "status": "development_only_not_a_validated_production_forecast",
        "standing": _STANDING,
        "pair": pair,
        "operations": _operations_summary(pair),
        "notes": list(_NOTES),
    }
    if grain in {"team", "all"}:
        report["team_fixture_rows"] = pair_team_fixture_rows(con, pair)
    if grain in {"player-gameweek", "all"}:
        report["player_gameweek_rows"] = pair_player_gameweek_rows(con, pair)
    if grain in {"player-fixture", "all"}:
        report["player_fixture_rows"] = pair_player_fixture_rows(con, pair)
    report["operations"]["outcome_attachment_counts"] = _outcome_counts(report)
    return report


def _operations_summary(pair: dict[str, Any]) -> dict[str, Any]:
    """Rate/reason counts and consumed-source summary from the verified SDP environment."""
    environment = pair["verification"].get("sdp_provenance") or {}
    return {
        "selector_counts_team_predictions": environment.get("selector_counts_team_predictions"),
        "sdp_primary": environment.get("primary"),
        "sdp_fallback": environment.get("fallback"),
        "model_version": environment.get("model_version"),
        "model_known_at": environment.get("model_known_at"),
        "latest_sdp_known_at": environment.get("latest_sdp_known_at"),
        "consumed_sources": environment.get("consumed_sources"),
    }


def _outcome_counts(report: dict[str, Any]) -> dict[str, Any]:
    """Per-role attached/absent counts over whichever grains the report includes."""
    counts: dict[str, Any] = {}
    for key in ("team_fixture_rows", "player_gameweek_rows", "player_fixture_rows"):
        rows = report.get(key)
        if not isinstance(rows, list):
            continue
        grain_counts: dict[str, dict[str, int]] = {}
        for row in rows:
            role = str(row["role"])
            bucket = grain_counts.setdefault(role, {"rows": 0, "attached": 0})
            bucket["rows"] += 1
            outcome = row.get("outcome")
            if isinstance(outcome, dict) and outcome.get("attached") is True:
                bucket["attached"] += 1
        counts[key] = grain_counts
    return counts


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Atomic temp-file replacement; a claimed-all-or-nothing report write is one."""
    body = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prediction-id", required=True)
    parser.add_argument("--db", required=True, type=Path, help="explicit database path")
    parser.add_argument(
        "--grain",
        choices=_GRAIN_CHOICES,
        default="team",
        help="retained rows to expose (team-fixture grain is the default)",
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="write the JSON report here (default: stdout)"
    )
    args = parser.parse_args(argv)

    con = connect(args.db, read_only=True)
    try:
        report = build_report(con, prediction_id=args.prediction_id, grain=args.grain)
    except ValueError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1
    finally:
        con.close()
    if args.output is not None:
        _write_json_atomic(args.output, report)
        print(f"wrote report for pair {args.prediction_id} to {args.output}")
    else:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
