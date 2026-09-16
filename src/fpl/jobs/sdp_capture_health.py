"""Read-only health report over ``daily_pl_sdp`` capture receipts.

Scans the run-receipt tree written by :mod:`fpl.jobs.daily_pl_sdp` and answers, without
writing anything: when a capture last completed, when it last succeeded, how old that
success is, what the newest receipt says about production health, and which receipts are
still running, failed, malformed, or undated. Unknown evidence is reported as ``null``,
never guessed.

Evidence rules this module enforces deliberately:

- Receipts may sit directly under the runs root (scheduled cycles) or nested below
  grouping directories (pre-deadline receipts); ordering uses each receipt's validated
  ``finished_at`` instant, never the directory name. Descendants of an identified
  receipt directory (its ``staging/`` outputs, logs, and backups) are never receipts
  themselves, the runs root itself is never a receipt, and only a true run directory -
  a daily-job timestamp run id or a directory holding a ``run.log``/``before.json``
  witness - can be a pending run; arbitrary empty grouping or staging folders are
  ignored.
- A timestamp that is missing, unparseable, naive, or in the future is UNKNOWN: such a
  receipt is undated and can never prove freshness. A healthy verdict is never claimed
  from an older receipt while a newer -- or positionally unknown -- malformed or undated
  receipt for this database (or an unattributable one) exists, and an unattributed
  (``database``-less) receipt never proves success for a requested database; only an
  exactly attributed success proves freshness.
- Staleness is judged only against an explicitly supplied ``--max-success-age-hours``
  bound (finite and positive); this module invents no threshold of its own. With no
  dated success, or while a suspect receipt blocks the evidence, staleness stays null.

Exit status is nonzero for an actually unhealthy newest receipt, proven staleness under
the explicit bound, (opt-in) reported production failure, or an explicit bound whose
required freshness cannot be proven because suspects block the evidence - a monitor must
not exit success when freshness is unproven; the verdict then stays ``unknown`` with all
unknown fields null. This CLI never deletes, prunes, or rewrites a receipt, including
failed ones, and never reads or writes any database.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "fpl.sdp-capture-health"
SCHEMA_VERSION = 2

#: Malformed-receipt run ids shown in full; the count is always complete.
MAX_MALFORMED_RUN_IDS = 10

#: Files whose presence marks a directory as a true run in progress (a witness that the
#: daily job created work before its final ``report.json``), alongside the timestamp
#: run-id shape itself.
RUN_WITNESS_FILES = ("run.log", "before.json", "before.duckdb")

_EPOCH = datetime(1, 1, 1, tzinfo=UTC)

_PRODUCTION_KEYS = (
    "season",
    "matches_valid",
    "latest_completed_match",
    "latest_valid_sdp_known_at",
    "global_failure",
    "schema_validation_failures",
    "identity_failures",
)


@dataclass(frozen=True)
class Receipt:
    """One parsed receipt directory under the ``--runs`` root.

    ``report_present`` false means the run may still be executing (``daily_pl_sdp``
    writes ``report.json`` last). ``problem`` non-null means the receipt exists but
    cannot be trusted and its health is unknown. ``finished_at`` is the validated
    instant or None when it is missing, unparseable, naive, or in the future.
    """

    run_id: str
    path: Path
    report_path: Path
    report_present: bool
    healthy: bool | None = None
    consumer_ready: bool | None = None
    exit_code: int | None = None
    mode: str | None = None
    database: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    production_health: dict[str, Any] | None = None
    problem: str | None = None

    @property
    def completed(self) -> bool:
        """A trustworthy final report was read."""
        return self.report_present and self.problem is None

    @property
    def undated_completed(self) -> bool:
        """Completed but its timestamp proves nothing about recency."""
        return self.completed and self.finished_at is None


def _parse_offset_instant(value: object) -> datetime | None:
    """Parse an operator-supplied ISO-8601 instant; a naive value is taken as UTC."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def parse_receipt_instant(value: object, now: datetime) -> datetime | None:
    """Parse a receipt timestamp; anything unprovable stays ``None``.

    ``daily_pl_sdp`` serializes aware UTC datetimes through ``str()``, which
    ``datetime.fromisoformat`` accepts. Naive values are rejected (an unqualified wall
    clock proves nothing), as are future instants relative to ``now``.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    if parsed > now:
        return None
    return parsed


def load_receipt(run_dir: Path, run_id: str, now: datetime) -> Receipt:
    """Classify one receipt directory without ever raising on its content."""
    report_path = run_dir / "report.json"
    if not report_path.is_file():
        return Receipt(run_id=run_id, path=run_dir, report_path=report_path, report_present=False)
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return Receipt(
            run_id=run_id,
            path=run_dir,
            report_path=report_path,
            report_present=True,
            problem=f"unreadable report.json: {type(error).__name__}",
        )
    if not isinstance(payload, dict) or not isinstance(payload.get("healthy"), bool):
        # Best-effort attribution even for untrustworthy reports: an unattributable
        # suspect must stay visible instead of silently dropping out of a --db filter.
        database = payload.get("database") if isinstance(payload, dict) else None
        finished = (
            parse_receipt_instant(payload.get("finished_at"), now)
            if isinstance(payload, dict)
            else None
        )
        return Receipt(
            run_id=run_id,
            path=run_dir,
            report_path=report_path,
            report_present=True,
            database=database if isinstance(database, str) else None,
            finished_at=finished,
            problem="report.json is not an object with a boolean 'healthy' field",
        )
    exit_code = payload.get("exit_code")
    production = payload.get("production_health")
    return Receipt(
        run_id=run_id,
        path=run_dir,
        report_path=report_path,
        report_present=True,
        healthy=payload["healthy"],
        consumer_ready=(
            payload["consumer_ready"] if isinstance(payload.get("consumer_ready"), bool) else None
        ),
        exit_code=int(exit_code) if isinstance(exit_code, int) else None,
        mode=payload.get("mode") if isinstance(payload.get("mode"), str) else None,
        database=payload.get("database") if isinstance(payload.get("database"), str) else None,
        started_at=parse_receipt_instant(payload.get("started_at"), now),
        finished_at=parse_receipt_instant(payload.get("finished_at"), now),
        production_health=production if isinstance(production, dict) else None,
    )


#: The daily job's fixed-width run-id directory-name shape (``<utcstamp>-<8 hex>``),
#: which marks a true run directory even before any file is written into it.
_RUN_ID_PATTERN = re.compile(r"^\d{8}T\d{6}\.\d{6}Z-[0-9a-f]{8}$")


def _is_run_directory(directory: Path) -> bool:
    """A true run directory: timestamp run id, or an in-progress witness file."""
    return _RUN_ID_PATTERN.match(directory.name) is not None or any(
        (directory / witness).exists() for witness in RUN_WITNESS_FILES
    )


def scan_receipts(runs_root: Path, now: datetime) -> list[Receipt]:
    """Every receipt under ``runs_root``, nested pre-deadline runs included.

    A receipt directory carries a ``report.json``; once one is identified, its
    descendants are pruned (its ``staging/`` outputs, logs, and backups are not
    receipts). A directory without a ``report.json`` counts as a pending run only when
    it is a true run directory - a daily-job timestamp run id, or a directory holding a
    ``run.log``/``before.json`` witness - never for arbitrary empty grouping or staging
    folders, and the runs root itself is never a receipt. Order is newest validated
    ``finished_at`` first, run id breaking ties; undated receipts sort last because
    their recency is unknown.
    """
    if not runs_root.is_dir():
        return []
    receipts: list[Receipt] = []

    def _visit(directory: Path, inside_receipt: bool) -> None:
        for entry in sorted(directory.iterdir()):
            if inside_receipt or not entry.is_dir():
                continue
            run_id = entry.relative_to(runs_root).as_posix()
            if (entry / "report.json").is_file():
                receipts.append(load_receipt(entry, run_id, now))
                continue  # identified capture: staging/logs/backups below are pruned
            if _is_run_directory(entry):
                receipts.append(load_receipt(entry, run_id, now))
                continue  # a true run directory without its final report: pending
            _visit(entry, False)  # grouping directory: keep looking below it

    _visit(runs_root, inside_receipt=False)
    receipts.sort(
        key=lambda receipt: (
            (1, receipt.finished_at, receipt.run_id)
            if receipt.finished_at is not None
            else (0, _EPOCH, receipt.run_id)
        ),
        reverse=True,
    )
    return receipts


def build_report(
    *,
    runs_root: Path,
    database: Path | None,
    max_success_age_hours: float | None,
    fail_on_production_failure: bool,
    now: datetime,
) -> dict[str, Any]:
    """The complete health record; every unknown field stays ``null``."""
    receipts = scan_receipts(runs_root, now)
    candidates: set[Path] | None = None
    if database is not None:
        # Receipts store the operational database path exactly as the daily job recorded
        # it; compare through Path so the given and resolved spellings both match.
        candidates = {Path(database), database.resolve()}

    def _attributed(receipt: Receipt) -> bool | None:
        """True/false when the receipt's database matches/mismatches, None if unknown."""
        if candidates is None:
            return True
        if receipt.database is None:
            return None
        try:
            return Path(receipt.database) in candidates
        except (OSError, ValueError):
            return None

    applicable = [r for r in receipts if _attributed(r) is not False]
    # Only exactly attributed successes can prove freshness for the requested database;
    # an unattributed (``database``-less) receipt stays evidence without proving it.
    attributed = [r for r in applicable if _attributed(r) is True]
    completed = [r for r in applicable if r.completed]
    running = [r for r in receipts if not r.report_present]
    malformed = [r for r in receipts if r.report_present and r.problem is not None]
    failed = [r for r in completed if r.healthy is False]
    undated = [
        r for r in applicable if r.undated_completed
    ]  # completed receipts that cannot prove recency
    unattributed = sum(1 for r in receipts if _attributed(r) is None)

    latest_completed = completed[0] if completed else None
    # Only a dated, exactly attributed success proves freshness; unknown timestamps and
    # unattributed successes are never healthy evidence for a requested database.
    latest_success = next((r for r in attributed if r.healthy and r.finished_at is not None), None)
    success_age_hours: float | None = None
    if latest_success is not None and latest_success.finished_at is not None:
        success_age_hours = round((now - latest_success.finished_at).total_seconds() / 3600, 6)

    # A malformed or undated receipt newer than the proven success - or of unknown
    # recency - could be the real latest state, so no healthy claim survives it. With a
    # --db filter, an unattributed receipt is suspect for the same reason: it could be
    # this database's latest state.
    def _success_key(receipt: Receipt) -> tuple[datetime, str]:
        return (receipt.finished_at or _EPOCH, receipt.run_id)

    def _is_suspect(receipt: Receipt) -> bool:
        if (receipt.report_present and receipt.problem is not None) or receipt.undated_completed:
            return True
        return candidates is not None and receipt.completed and receipt.database is None

    def _blocks(receipt: Receipt) -> bool:
        if not _is_suspect(receipt):
            return False
        if _attributed(receipt) is False:
            return False  # provably another database's receipt
        if latest_success is None:
            return True
        if receipt.finished_at is None:
            return True  # unknown position: could be newer
        return _success_key(receipt) > _success_key(latest_success)

    blocking = [r for r in receipts if _blocks(r)]

    stale: bool | None = None
    if max_success_age_hours is not None:
        if latest_success is None:
            stale = True
        elif blocking or success_age_hours is None:
            stale = None  # recency is disputed (or, impossibly, unmeasurable)
        else:
            stale = success_age_hours > max_success_age_hours

    unhealthy = latest_completed is not None and latest_completed.healthy is False
    production_source = next((r for r in completed if r.production_health is not None), None)
    production: dict[str, Any] | None = None
    if production_source is not None and production_source.production_health is not None:
        raw = production_source.production_health
        production = {
            "source_run_id": production_source.run_id,
            "source_finished_at": _iso(production_source.finished_at),
            **{key: raw.get(key) for key in _PRODUCTION_KEYS},
            "failure_count": (
                len(raw["failures"]) if isinstance(raw.get("failures"), dict) else None
            ),
            "failure_count_scope": "all_retained_seasons",
            "current_failure_count": (
                len(raw["current_match_failures"])
                if isinstance(raw.get("current_match_failures"), dict)
                else None
            ),
        }

    production_failure = bool(
        fail_on_production_failure and production is not None and production["global_failure"]
    )
    healthy = (
        True
        if latest_success is not None
        and not blocking
        and (latest_completed is None or latest_completed.healthy is not False)
        else False
        if unhealthy
        else None
    )
    # A monitor with an explicit freshness bound must not exit success while suspects
    # block the evidence: unproven freshness fails closed, with all unknowns still null.
    freshness_unproven = max_success_age_hours is not None and bool(blocking)
    exit_code = 1 if unhealthy or stale or production_failure or freshness_unproven else 0
    verdict = (
        "unhealthy"
        if unhealthy
        else "stale"
        if stale
        else "production_failure"
        if production_failure
        else "healthy"
        if healthy
        else "unknown"
    )
    return {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "checked_at": _iso(now),
        "runs_root": str(runs_root),
        "database": str(database) if database is not None else None,
        "receipts_scanned": len(receipts),
        "other_database_receipts": {"count": len(receipts) - len(applicable)},
        "unattributed_receipts": {"count": unattributed},
        "completed_receipts": {"count": len(completed)},
        "running_receipts": {
            "count": len(running),
            "latest_run_id": running[0].run_id if running else None,
        },
        "malformed_receipts": {
            "count": len(malformed),
            "run_ids": [r.run_id for r in malformed[:MAX_MALFORMED_RUN_IDS]],
        },
        "undated_receipts": {
            "count": len(undated),
            "latest_run_id": undated[0].run_id if undated else None,
        },
        "newer_suspects": {
            "count": len(blocking),
            "latest_run_id": blocking[0].run_id if blocking else None,
        },
        "failed_receipts": {
            "count": len(failed),
            "latest_run_id": failed[0].run_id if failed else None,
            "latest_finished_at": _iso(failed[0].finished_at) if failed else None,
        },
        "latest_completed": _summary(latest_completed),
        "latest_success": _summary(latest_success),
        "success_age_hours": success_age_hours,
        "max_success_age_hours": max_success_age_hours,
        "stale": stale,
        "freshness_unproven": freshness_unproven,
        "production_health": production,
        "healthy": healthy,
        "verdict": verdict,
        "exit_code": exit_code,
    }


def _summary(receipt: Receipt | None) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {
        "run_id": receipt.run_id,
        "started_at": _iso(receipt.started_at),
        "finished_at": _iso(receipt.finished_at),
        "healthy": receipt.healthy,
        "consumer_ready": receipt.consumer_ready,
        "exit_code": receipt.exit_code,
        "mode": receipt.mode,
        "database": receipt.database,
        "problem": receipt.problem,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs",
        required=True,
        type=Path,
        help="daily_pl_sdp --runs root (read-only)",
    )
    parser.add_argument("--db", type=Path, default=None, help="only receipts for this database")
    parser.add_argument(
        "--max-success-age-hours",
        type=float,
        default=None,
        help="explicit staleness bound; without it staleness is never judged",
    )
    parser.add_argument(
        "--fail-on-production-failure",
        action="store_true",
        help="also exit nonzero when the newest production health reports a global failure",
    )
    parser.add_argument(
        "--now",
        type=str,
        default=None,
        help="ISO-8601 instant override for deterministic checks; defaults to the clock",
    )
    args = parser.parse_args(argv)
    if args.max_success_age_hours is not None and (
        not math.isfinite(args.max_success_age_hours) or args.max_success_age_hours <= 0
    ):
        parser.error("--max-success-age-hours must be finite and positive")
    now = datetime.now(UTC)
    if args.now is not None:
        override = _parse_offset_instant(args.now)
        if override is None:
            parser.error("--now must be an ISO-8601 instant")
        now = override
    report = build_report(
        runs_root=args.runs,
        database=args.db,
        max_success_age_hours=args.max_success_age_hours,
        fail_on_production_failure=args.fail_on_production_failure,
        now=now,
    )
    json.dump(report, sys.stdout, indent=2, sort_keys=True, allow_nan=False)
    sys.stdout.write("\n")
    return int(report["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
