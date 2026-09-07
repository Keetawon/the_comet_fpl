"""Write-once offline V2 interpretation of the thirteen retained participation bundles.

No network, database writes, forecasts or model evaluation. Original pilot remains failed.
"""

from __future__ import annotations

import argparse
import json
import traceback
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fpl.config import repo_root
from fpl.ingest.pl_sdp import parse_match_summary
from fpl.jobs import capture_competitive_workload as retained_loader
from fpl.jobs import competitive_participation_pilot as parent
from fpl.storage.db import connect
from fpl.transform.competitive_participation import ParticipationError, aware
from fpl.transform.competitive_participation_v2 import parse_participation_v2

NAME = "competitive_participation_arsenal_palace_v2_offline"
CONFIG = "config/competitive_participation_v2.yaml"
CONFIG_SHA256 = "59678e9a1fc547b7417f48282222a593ab937f7f75bbab62ff423cdf2db4128a"
OLD_RESULT_SHA256 = "f34b0c978b6de9454bbd1bb52cb2d2faabee6347b8baa16403bca773b56bf411"
EXPECTED_MATCHES = 13
SOURCE_FILES = tuple(
    sorted(
        {
            *retained_loader.SOURCE_FILES,
            *parent.SOURCE_FILES,
            CONFIG,
            "src/fpl/jobs/audit_competitive_participation_v2.py",
            "src/fpl/transform/competitive_participation_v2.py",
            "docs/competitive-participation-v2.md",
            "docs/competitive-participation-source-resolution.md",
            "tests/test_audit_competitive_participation_v2.py",
            "tests/test_competitive_participation_v2.py",
        }
    )
)


def load_contract(root: Path) -> dict[str, Any]:
    if parent.file_sha256(root / CONFIG) != CONFIG_SHA256:
        raise ParticipationError("V2 interpretation config differs from frozen contract")
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    return contract


def source_evidence(path: Path, contract: dict[str, Any]) -> dict[str, str]:
    """Verify the new source report and every retained success/refusal byte body."""
    path = path.resolve()
    if parent.file_sha256(path) != contract["source_resolution_report_sha256"]:
        raise ParticipationError("source-resolution evidence report fingerprint differs")
    report = json.loads(path.read_bytes())
    hashes = {str(path): parent.file_sha256(path)}
    for source in report["new_source_captures"]["responses"]:
        name = source["raw_file"]
        raw = (path.parent / name).resolve()
        if Path(name).name != name or not raw.is_relative_to(path.parent):
            raise ParticipationError("source-evidence raw path escapes directory")
        if parent.file_sha256(raw) != source["sha256"] or raw.stat().st_size != source["bytes"]:
            raise ParticipationError("official source evidence raw bytes differ")
        hashes[str(raw)] = source["sha256"]
    return hashes


def interpret(
    inputs: retained_loader.RetainedInputs,
    reference: dict[str, Any],
    old_contract: dict[str, Any],
    *,
    interpretation_known_at: datetime,
) -> dict[str, Any]:
    """The retained-loader catalogue is broad, but this operation is exactly 13 bundles."""
    selected_ids = sorted({mid for mid, _ in inputs.reused})
    if len(selected_ids) != EXPECTED_MATCHES:
        raise ParticipationError("retained pilot bundle count differs")
    expected_pl = set(old_contract["expected_pl_match_ids"])
    actual_pl = {mid for mid in selected_ids if int(inputs.matches[mid]["competitionId"]) == 8}
    if actual_pl != expected_pl:
        raise ParticipationError("retained pilot PL fixture population differs")
    parsed_matches = []
    failures = []
    for mid in selected_ids:
        manifest = json.loads(inputs.files[f"capture-{mid}.json"])
        match = manifest["selected_match_record"]
        if mid in actual_pl:
            summary = parse_match_summary(match)
            bridge = reference["crosswalk"].get(str(mid))
            if bridge is None or (
                summary.kickoff != datetime.fromisoformat(bridge["kickoff_utc"])
                or summary.home_team_id != bridge["home_team_code"]
                or summary.away_team_id != bridge["away_team_code"]
                or summary.home_score != bridge["home_score"]
                or summary.away_score != bridge["away_score"]
            ):
                raise ParticipationError(f"PL fixture crosswalk contradiction: {mid}")
        versions = manifest["source_versions"]
        old_known_at = max(
            *(aware(datetime.fromisoformat(version["known_at"])) for version in versions.values()),
            aware(datetime.fromisoformat(manifest["identity_evidence_observed_at_utc"])),
        )
        payloads = {
            endpoint: json.loads(
                inputs.files[inputs.reused[(mid, endpoint)]["receipt"]["raw_file"]]
            )
            for endpoint in ("lineups", "events")
        }
        try:
            parsed = parse_participation_v2(
                match,
                payloads["lineups"],
                payloads["events"],
                known_at=old_known_at,
                event_known_at=datetime.fromisoformat(versions["events"]["known_at"]),
                interpretation_known_at=interpretation_known_at,
            )
            parsed["source_versions"] = deepcopy(versions)
            parsed["original_identity_evidence_observed_at_utc"] = manifest[
                "identity_evidence_observed_at_utc"
            ]
            parsed["reference_identity_rechecked_at_utc"] = reference["identity_observed_at_utc"]
            parsed_matches.append(parsed)
        except (ParticipationError, KeyError, TypeError, ValueError) as error:
            failures.append(
                {
                    "sdp_match_id": mid,
                    "class": type(error).__name__,
                    "message": str(error),
                    "source_versions": deepcopy(versions),
                }
            )
    # V1 validator attaches identity annotations only to these freshly parsed output rows.
    validation = parent.validate_results(parsed_matches, reference, old_contract)
    summaries = []
    unknown = []
    clubs = {club["team_code"] for club in old_contract["clubs"]}
    selected_unassigned = []
    for parsed in parsed_matches:
        for side in parsed["sides"]:
            rows = side["rows"]
            summaries.append(
                {
                    "sdp_match_id": parsed["sdp_match_id"],
                    "side": side["side"],
                    "provider_team_id": side["provider_team_id"],
                    "roster_rows": len(rows),
                    "started_true": sum(row["started"] is True for row in rows),
                    "bench_true": sum(row["on_bench"] is True for row in rows),
                    "appeared_true": sum(row["appeared"] is True for row in rows),
                    "minutes_nonnull": sum(row["nominal_minutes"] is not None for row in rows),
                    "minutes_unknown": sum(row["nominal_minutes"] is None for row in rows),
                    "membership_policy": side["membership_policy"],
                    "errors": side["errors"],
                }
            )
            for row in rows:
                if row["appeared"] is None or row["nominal_minutes"] is None:
                    unavailable = {
                        "sdp_match_id": parsed["sdp_match_id"],
                        "provider_team_id": side["provider_team_id"],
                        **deepcopy(row),
                    }
                    unknown.append(unavailable)
                    if side["provider_team_id"] in clubs:
                        selected_unassigned.append(unavailable)
    complete = len(parsed_matches) == len(selected_ids) and not failures
    checks = {
        "all_thirteen_matches_interpreted": complete,
        "all_twenty_six_sides_reported": len(summaries) == 2 * EXPECTED_MATCHES,
        "all_selected_xi_exactly_eleven": all(row["started_true"] == 11 for row in summaries),
        "selected_club_exposure_known": not selected_unassigned,
        "original_pl_tolerances_pass": validation["passed"],
    }
    return {
        "selected_matches": len(selected_ids),
        "selected_match_ids": selected_ids,
        "parsed_matches": len(parsed_matches),
        "pl_matches": len(actual_pl),
        "team_side_summaries": summaries,
        "unknown_roster_or_duration_rows": unknown,
        "selected_club_unknown_rows": selected_unassigned,
        "all_fixture_roster_exposure_known": not unknown,
        "scope": (
            "same thirteen Arsenal/Palace fixtures; "
            "acceptance is not global all-player completeness"
        ),
        "checks": checks,
        "passed": all(checks.values()),
        "failures": failures,
        "validation": validation,
        "matches": parsed_matches,
    }


def run(*, root: Path, db: Path, retained: Path, evidence: Path, results: Path) -> dict[str, Any]:
    contract = load_contract(root)
    workload_contract = retained_loader.load_contract(root)
    head = retained_loader._head(root, workload_contract)
    old_contract = parent.load_contract(root)
    db, retained, evidence, results = (path.resolve() for path in (db, retained, evidence, results))
    if results.exists() or any(
        results.is_relative_to(base) for base in (root.resolve(), retained, evidence.parent)
    ):
        raise ParticipationError("new external result directory required; no overwrite/resume")
    if not db.is_file() or Path(str(db) + ".wal").exists():
        raise ParticipationError("read-only reference DB required without WAL")
    inputs = retained_loader.load_retained(root, retained, workload_contract)
    old = json.loads(inputs.files["pilot-result.json"])
    if workload_contract["retained_report_sha256"] != OLD_RESULT_SHA256:
        raise ParticipationError("wrong original pilot result identity")
    original_result = retained / "result.json"
    if parent.file_sha256(original_result) != OLD_RESULT_SHA256:
        raise ParticipationError("original external pilot result fingerprint changed")
    input_hashes = {**inputs.source_hashes, **source_evidence(evidence, contract)}
    input_hashes[str(original_result)] = OLD_RESULT_SHA256
    source_hashes = {name: parent.file_sha256(root / name) for name in SOURCE_FILES}
    lease = connect(db, read_only=True)
    try:
        database_hash = parent.file_sha256(db)
        if database_hash != old["provenance"]["database_sha256"]:
            raise ParticipationError("reference DB differs from original pilot")
        reference = parent.reference_data(db, old_contract["season"])
        interpreted_at = datetime.now(UTC)
        provenance = {
            "name": NAME,
            "git_head": head,
            "clean_worktree": True,
            "config": contract,
            "source_sha256": source_hashes,
            "source_inputs_sha256": input_hashes,
            "database": str(db),
            "database_sha256": database_hash,
            "database_read_only": True,
            "original_pilot_result_sha256": OLD_RESULT_SHA256,
            "original_pilot_remains_passed": False,
            "retained_directory": str(retained),
            "source_resolution": str(evidence),
            "interpretation_known_at": interpreted_at.isoformat(),
            "reference_identity_rechecked_at_utc": reference["identity_observed_at_utc"],
            "network_requests": 0,
            "model_fitting": False,
        }
        results.mkdir(parents=True, exist_ok=False)
        parent.publish_json(results / "provenance.json", provenance)
        report: dict[str, Any] = {"completed": False, "passed": False, "provenance": provenance}
        try:
            report.update(
                interpret(inputs, reference, old_contract, interpretation_known_at=interpreted_at)
            )
            report["completed"] = True
        except Exception as error:
            report["execution_failure"] = {
                "class": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        try:
            postflight = {
                "git_clean_unchanged": parent.git_clean_head(root) == head,
                "database_sha256": parent.file_sha256(db),
                "no_wal": not Path(str(db) + ".wal").exists(),
                "source_sha256": {name: parent.file_sha256(root / name) for name in SOURCE_FILES},
                "source_inputs_sha256": {
                    name: parent.file_sha256(Path(name)) for name in input_hashes
                },
            }
            report["postflight"] = postflight
            if (
                not postflight["git_clean_unchanged"]
                or not postflight["no_wal"]
                or postflight["database_sha256"] != database_hash
                or postflight["source_sha256"] != source_hashes
                or postflight["source_inputs_sha256"] != input_hashes
            ):
                raise ParticipationError("postflight source/input/database provenance changed")
        except Exception as error:
            report["completed"] = report["passed"] = False
            report["postflight_failure"] = {"class": type(error).__name__, "message": str(error)}
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        parent.publish_json(results / "result.json", report)
        return report
    finally:
        lease.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--retained", required=True, type=Path)
    parser.add_argument("--source-resolution", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    args = parser.parse_args(argv)
    report = run(
        root=repo_root(),
        db=args.db,
        retained=args.retained,
        evidence=args.source_resolution,
        results=args.results,
    )
    print(json.dumps({"completed": report["completed"], "passed": report["passed"]}))
    return 0 if report["completed"] and report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
