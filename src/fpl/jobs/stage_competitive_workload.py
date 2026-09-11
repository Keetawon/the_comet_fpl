"""Verify retained workload bytes; append interpretations only to a NEW operational DB copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import traceback
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml

from fpl.config import repo_root
from fpl.ingest.pl_sdp import parse_match_summary
from fpl.jobs import capture_competitive_workload as capture
from fpl.jobs.build_db import (
    _prepare_temporary_database,
    _sha256,
    _temporary_database_path,
    _wal_path,
)
from fpl.jobs.competitive_participation_pilot import file_sha256, publish_json, reference_data
from fpl.jobs.daily_pl_sdp import writer_lock
from fpl.storage.competitive_workload import (
    TABLES,
    append_match,
    append_receipt,
    append_report,
    apply_workload_schema,
    identity,
    semantic_identity,
)
from fpl.storage.db import connect, default_db_path
from fpl.transform.competitive_participation import ParticipationError, _event_time, exact_crosswalk
from fpl.transform.competitive_participation_v2 import INTERPRETATION_ID, parse_participation_v2
from fpl.validate.competitive_workload_view import (
    CatalogueCoverage,
    CompetitiveFixture,
    CompetitiveFixtureKey,
    CompetitiveMatchVersion,
    ObservedPlayerIdentity,
    RetrospectiveCompetitiveWorkloadView,
    WorkloadObservation,
)

CONFIG = "config/competitive_workload_staging.yaml"
SOURCE_FILES = tuple(
    sorted(
        {
            *capture.SOURCE_FILES,
            CONFIG,
            "src/fpl/jobs/stage_competitive_workload.py",
            "src/fpl/storage/competitive_workload.py",
            "src/fpl/validate/competitive_workload_view.py",
            "src/fpl/transform/competitive_participation.py",
            "src/fpl/transform/competitive_participation_v2.py",
            "src/fpl/jobs/build_db.py",
            "src/fpl/jobs/daily_pl_sdp.py",
            "docs/competitive-workload-mart.md",
            "tests/test_competitive_workload_staging.py",
            "tests/test_competitive_workload_view.py",
        }
    )
)
logger = logging.getLogger(__name__)


def safe_file(directory: Path, relative: str) -> Path:
    path = directory / relative
    resolved = path.resolve()
    if (
        not relative
        or Path(relative).is_absolute()
        or not resolved.is_relative_to(directory.resolve())
    ):
        raise ValueError("retained source path escapes capture directory")
    if path.is_symlink() or not path.is_file():
        raise ValueError("retained raw source must be an existing nonsymlink file")
    return resolved


def consistent_copy(source: Path, destination: Path, expected_sha256: str) -> str:
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("database paths must not be symlinks")
    source, destination = source.resolve(), destination.resolve()
    if source == destination or destination == default_db_path().resolve():
        raise ValueError("operational destination must differ from source and default database")
    if destination.exists() or _wal_path(destination).exists():
        raise FileExistsError("operational database must be a new path")
    if not source.is_file() or _wal_path(source).exists():
        raise ValueError("source database missing or has unresolved WAL")
    # The read lease excludes external writers; never acquire a write lease on frozen evidence.
    temporary = _temporary_database_path(destination)
    try:
        with connect(source, read_only=True):
            if _sha256(source) != expected_sha256:
                raise ValueError("frozen source database fingerprint differs")
            copied = _prepare_temporary_database(source, temporary)
            if copied != expected_sha256 or _wal_path(source).exists():
                raise ValueError("source changed during consistent copy")
            # Atomic no-clobber publication: a racing creator can never be overwritten.
            os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return expected_sha256


def verified_body(
    directory: Path, source: dict[str, Any], match_id: int, endpoint: str
) -> tuple[Path, bytes, dict[str, Any]]:
    receipt = deepcopy(source["receipt"])
    path = safe_file(directory, source["copied_raw_file"])
    body = path.read_bytes()
    expected_path = (
        f"/api/v3/matches/{match_id}/lineups"
        if endpoint == "lineups"
        else f"/api/v1/matches/{match_id}/events"
    )
    parsed_url = urlparse(receipt["url"])
    if (
        parsed_url.scheme != "https"
        or parsed_url.netloc != "sdp-prem-prod.premier-league-prod.pulselive.com"
        or parsed_url.path != expected_path
        or parse_qs(parsed_url.query) != {"match_id": [str(match_id)]}
        or source["path"] != expected_path
        or source["params"] != {"match_id": str(match_id)}
        or source["endpoint"] != f"match_{endpoint}"
        or source["status"] != receipt["status"]
        or receipt["status"] != 200
        or source["sha256"] != receipt["sha256"]
        or hashlib.sha256(body).hexdigest() != receipt["sha256"]
        or len(body) != receipt["bytes"]
        or len(body) != source["bytes"]
    ):
        raise ValueError("manifest/request/raw payload identity mismatch")
    for value in (receipt["captured_at_utc"], source["known_at"]):
        if datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("raw source knowledge time must be aware")
    if datetime.fromisoformat(source["known_at"]) < datetime.fromisoformat(
        receipt["captured_at_utc"]
    ):
        raise ValueError("client knowledge time cannot precede raw receipt")
    receipt["source_known_at"] = source["known_at"]
    return path, body, receipt


def club_crosswalk(inputs: capture.RetainedInputs, reference: dict[str, Any]) -> dict[int, int]:
    result: dict[int, int] = {}
    for mid, record in inputs.matches.items():
        if int(record["competitionId"]) != 8:
            continue
        summary = parse_match_summary(record)
        bridge = reference["crosswalk"].get(str(mid))
        if bridge is None or (
            summary.kickoff != datetime.fromisoformat(bridge["kickoff_utc"])
            or summary.home_score != bridge["home_score"]
            or summary.away_score != bridge["away_score"]
        ):
            raise ValueError(f"PL fixture identity contradiction: {mid}")
        for provider, code in (
            (summary.home_team_id, bridge["home_team_code"]),
            (summary.away_team_id, bridge["away_team_code"]),
        ):
            if provider is None or (provider in result and result[provider] != code):
                raise ValueError("nonunique provider-to-stable club crosswalk")
            result[provider] = code
    if len(result) != 20 or len(set(result.values())) != 20:
        raise ValueError("all twenty verified PL clubs require a one-to-one crosswalk")
    return result


def maximum_event_time(payload: dict[str, Any]) -> datetime | None:
    instants: list[datetime] = []
    for label in ("homeTeam", "awayTeam"):
        side = payload.get(label, {})
        for category in ("subs", "cards", "goals"):
            for event in side.get(category, []):
                if event.get("timestamp") is not None:
                    stamp, _ = _event_time(event)
                    instants.append(stamp)
    return max(instants) if instants else None


def interpreted_record(
    *,
    record: dict[str, Any],
    sources: dict[str, Any],
    payloads: dict[str, Any],
    receipts: list[str],
    reference: dict[str, Any],
    clubs: dict[int, int],
    interpreted_at: datetime,
    parser_sha256: str,
    errors: list[str],
) -> dict[str, Any]:
    summary = parse_match_summary(record)
    if summary.kickoff is None:
        raise ValueError("catalogued fixture kickoff unavailable")
    captured_at = max(datetime.fromisoformat(s["known_at"]) for s in sources.values())
    if interpreted_at.utcoffset() is None or interpreted_at < max(
        captured_at, datetime.fromisoformat(reference["identity_observed_at_utc"])
    ):
        raise ValueError("interpretation cannot precede capture or identity evidence")
    output: dict[str, Any] = {
        "provider": "pl_sdp",
        "competition_id": int(record["competitionId"]),
        "season": reference["season"],
        "match_id": summary.match_id,
        "fpl_fixture": reference["crosswalk"].get(str(summary.match_id), {}).get("fixture"),
        "fpl_gw": None,
        "kickoff": summary.kickoff.isoformat(),
        "capture_known_at": captured_at.isoformat(),
        "interpretation_known_at": interpreted_at.isoformat(),
        "interpretation_id": INTERPRETATION_ID,
        "capture_complete": all(endpoint in sources for endpoint in ("lineups", "events")),
        "receipt_ids": sorted(receipts),
        "source_versions": sources,
        "identity_source": {
            "database_sha256": reference["database_sha256"],
            "observed_at": reference["identity_observed_at_utc"],
            "method": "exact_season_fpl_opta_not_registration",
        },
        "raw_match": record,
        "rows": [],
        "errors": list(errors),
        "side_summaries": [],
        "maximum_retained_event_timestamp": None,
        "verified_end_at": None,
        "extra_time": None,
    }
    if output["competition_id"] == 8:
        output["fpl_gw"] = reference["fixture_gw"].get(output["fpl_fixture"])
        if output["fpl_fixture"] is None or output["fpl_gw"] is None:
            raise ValueError("PL capture lacks an exact FPL fixture/gameweek bridge")
    if all(endpoint in payloads for endpoint in ("lineups", "events")):
        try:
            parsed = parse_participation_v2(
                record,
                payloads["lineups"],
                payloads["events"],
                known_at=captured_at,
                event_known_at=datetime.fromisoformat(sources["events"]["known_at"]),
                interpretation_known_at=interpreted_at,
            )
            stamp = maximum_event_time(payloads["events"])
            if stamp is not None and not summary.kickoff <= stamp <= captured_at:
                raise ParticipationError("retained event outside kickoff/capture bounds")
            output["maximum_retained_event_timestamp"] = stamp.isoformat() if stamp else None
            nominal: list[int | None] = []
            for side in parsed["sides"]:
                team = side["provider_team_id"]
                mapped, identity_errors = exact_crosswalk(
                    [r["provider_player_id"] for r in side["rows"]],
                    reference["registry"],
                    season=reference["season"],
                )
                nominal.append(side["nominal_match_minutes"])
                output["errors"].extend(f"side={team}:{e}" for e in side["errors"])
                output["side_summaries"].append(
                    {
                        "provider_team_id": team,
                        "team_code": clubs.get(team),
                        "formation": side["formation"],
                        "membership_policy": side["membership_policy"],
                        "nominal_match_minutes": side["nominal_match_minutes"],
                        "errors": side["errors"],
                        "identity_errors": identity_errors,
                    }
                )
                for row in side["rows"]:
                    output["rows"].append(
                        {
                            **deepcopy(row),
                            "code": mapped[row["provider_player_id"]],
                            "provider_team_id": team,
                            "team_code": clubs.get(team),
                        }
                    )
            output["extra_time"] = (
                any(n == 120 for n in nominal) if all(n is not None for n in nominal) else None
            )
        except (ParticipationError, ValueError, KeyError, TypeError) as error:
            output["errors"].append(f"{type(error).__name__}:{error}")
    output["interpretation_valid"] = output["capture_complete"] and not output["errors"]
    output["version_id"] = identity(
        (
            summary.match_id,
            sorted(receipts),
            INTERPRETATION_ID,
            parser_sha256,
            reference["database_sha256"],
        )
    )
    output["semantic_sha256"] = semantic_identity(output)
    return output


def participation_audit(
    records: list[dict[str, Any]], reference: dict[str, Any], clubs: dict[int, int]
) -> dict[str, Any]:
    counters: dict[str, Counter[str]] = {}
    roles: Counter[str] = Counter()
    pairs: list[dict[str, Any]] = []
    facts = {(r["fixture"], r["code"]): r for r in reference["facts"]}
    for record in records:
        c = counters.setdefault(str(record["competition_id"]), Counter())
        c["catalogued_matches"] += 1
        c["capture_complete"] += record["capture_complete"]
        c["interpretation_valid"] += record["interpretation_valid"]
        for row in record["rows"]:
            c["provider_roster_rows"] += 1
            c["pl_club_roster_rows"] += row["provider_team_id"] in clubs
            c["pl_club_unresolved_player_rows"] += (
                row["provider_team_id"] in clubs and row["code"] is None
            )
            c["minutes_null"] += row["nominal_minutes"] is None
            c["appearances_known_positive"] += row["appeared"] is True
            roles[f"{row['provider_position']}:{row['membership']}"] += 1
            if record["competition_id"] != 8 or row["code"] is None:
                continue
            bridge = reference["crosswalk"][str(record["match_id"])]
            target = facts.get((bridge["fixture"], row["code"]))
            pairs.append(
                {
                    "match_id": record["match_id"],
                    "fixture": bridge["fixture"],
                    "code": row["code"],
                    "provider_team_id": row["provider_team_id"],
                    "team_code": row["team_code"],
                    "identity_agrees": target is not None
                    and target["team_code"] == row["team_code"],
                    "started": row["started"],
                    "appeared": row["appeared"],
                    "nominal_minutes": row["nominal_minutes"],
                    "fpl_minutes": target["minutes"] if target else None,
                    "starter_agrees": target is not None
                    and target["starts"] is not None
                    and row["started"] is not None
                    and row["started"] == (target["starts"] > 0),
                    "appearance_agrees": target is not None
                    and target["minutes"] is not None
                    and row["appeared"] is not None
                    and row["appeared"] == (target["minutes"] > 0),
                    "duration_difference": row["nominal_minutes"] - target["minutes"]
                    if target is not None
                    and row["nominal_minutes"] is not None
                    and target["minutes"] is not None
                    else None,
                }
            )
    diffs = [
        p["duration_difference"]
        for p in pairs
        if p["appeared"] is True and p["duration_difference"] is not None
    ]
    paired = {(p["fixture"], p["code"]) for p in pairs}
    pl_fixture_ids = {
        reference["crosswalk"][str(r["match_id"])]["fixture"]
        for r in records
        if r["competition_id"] == 8
    }
    missing_source_appearances = [
        row
        for row in reference["facts"]
        if row["fixture"] in pl_fixture_ids
        and ((row["minutes"] or 0) > 0 or (row["starts"] or 0) > 0)
        and (row["fixture"], row["code"]) not in paired
    ]
    return {
        "by_competition": {k: dict(v) for k, v in sorted(counters.items())},
        "role_labels": dict(sorted(roles.items())),
        "pl_pairs": pairs,
        "pl_starter_agree": sum(p["starter_agrees"] for p in pairs),
        "pl_appearance_agree": sum(p["appearance_agrees"] for p in pairs),
        "pl_pair_count": len(pairs),
        "pl_recorded_appearance_without_source_pair": missing_source_appearances,
        "pl_duration_measured_appeared_rows": len(diffs),
        "pl_nominal_minus_fpl_duration_distribution": dict(sorted(Counter(diffs).items())),
        "pl_duration_mae": sum(abs(x) for x in diffs) / len(diffs) if diffs else None,
        "pl_duration_within_two_minutes_fraction": sum(abs(x) <= 2 for x in diffs) / len(diffs)
        if diffs
        else None,
        "failures": [
            {"match_id": r["match_id"], "errors": r["errors"]} for r in records if r["errors"]
        ],
        "unresolved_or_unknown_players": [
            {"match_id": r["match_id"], **row}
            for r in records
            for row in r["rows"]
            if row["code"] is None or row["appeared"] is None or row["nominal_minutes"] is None
        ],
        "trusted_historical_membership_intervals": 0,
        "exact_player_workload_licensed": False,
        "model_fitting": False,
    }


def workload_view(
    records: list[dict[str, Any]],
    clubs: dict[int, int],
    catalogue_identity: str,
    catalogue_known_at: datetime,
) -> RetrospectiveCompetitiveWorkloadView:
    fixtures: dict[CompetitiveFixtureKey, CompetitiveFixture] = {}
    versions = []
    for record in records:
        summary = parse_match_summary(record["raw_match"])
        provider_ids = frozenset(
            t for t in (summary.home_team_id, summary.away_team_id) if t is not None
        )
        fixture = CompetitiveFixture(
            CompetitiveFixtureKey(
                "pl_sdp", record["competition_id"], record["season"], record["match_id"]
            ),
            datetime.fromisoformat(record["kickoff"]),
            frozenset(clubs[t] for t in provider_ids if t in clubs),
            record["raw_match"].get("period") == "FullTime",
            provider_ids,
            tuple(sorted((t, clubs[t]) for t in provider_ids if t in clubs)),
        )
        if fixture.key in fixtures and fixtures[fixture.key] != fixture:
            raise ValueError("retained revisions contradict fixture identity")
        fixtures[fixture.key] = fixture
        versions.append(
            CompetitiveMatchVersion(
                fixture,
                record["version_id"],
                datetime.fromisoformat(record["capture_known_at"]),
                INTERPRETATION_ID,
                datetime.fromisoformat(record["interpretation_known_at"]),
                identity(record["receipt_ids"]),
                record["capture_complete"],
                tuple(
                    WorkloadObservation(
                        r["provider_player_id"],
                        r["code"],
                        r["team_code"],
                        r["nominal_minutes"],
                        r["started"],
                        r["appeared"],
                        provider_team_id=r["provider_team_id"],
                    )
                    for r in record["rows"]
                ),
                record["extra_time"],
                datetime.fromisoformat(record["maximum_retained_event_timestamp"])
                if record["maximum_retained_event_timestamp"]
                else None,
                None,
                tuple(record["errors"]),
            )
        )
    # These bounds describe the checked catalogue window, never membership or all football.
    start = min(f.kickoff for f in fixtures.values())
    before = max(f.kickoff for f in fixtures.values()) + timedelta(microseconds=1)
    coverage = tuple(
        CatalogueCoverage(
            "pl_sdp", competition, team, start, before, catalogue_known_at, catalogue_identity, True
        )
        for competition in (8, 1, 2, 5, 6, 1125)
        for team in clubs.values()
    )
    return RetrospectiveCompetitiveWorkloadView(
        interpretation_id=INTERPRETATION_ID,
        fixtures=tuple(fixtures.values()),
        versions=tuple(versions),
        catalogue_coverage=coverage,
        memberships=(),
    )


def _run(
    *,
    root: Path,
    source_db: Path,
    database: Path,
    captured: Path,
    pilot_result: Path,
    results: Path,
) -> dict[str, Any]:
    if any(path.is_symlink() for path in (source_db, database, captured, results)):
        raise ValueError("explicit operational paths cannot be symlinks")
    root, source_db, database, captured, results = (
        p.resolve() for p in (root, source_db, database, captured, results)
    )
    contract: dict[str, Any] = yaml.safe_load((root / CONFIG).read_bytes())
    head = capture._head(root, contract)
    fingerprints = {name: file_sha256(root / name) for name in SOURCE_FILES}
    if (
        file_sha256(root / "src/fpl/transform/competitive_participation_v2.py")
        != contract["parser_sha256"]
    ):
        raise ValueError("pinned V2 parser changed")
    if file_sha256(pilot_result) != contract["revised_pilot_sha256"]:
        raise ValueError("revised pilot result fingerprint differs")
    pilot = json.loads(pilot_result.read_bytes())
    if not pilot["completed"] or not pilot["passed"]:
        raise ValueError("revised pilot must have passed before operational staging")
    if results.is_symlink() or results.is_relative_to(root) or results.is_relative_to(captured):
        raise ValueError("new external report directory required")
    if database.is_relative_to(root) or database.is_relative_to(captured) or database == source_db:
        raise ValueError("new external operational database required")
    report_path = safe_file(captured, "result.json")
    if file_sha256(report_path) != contract["completed_capture_report_sha256"]:
        raise ValueError("completed raw capture report differs from pinned evidence")
    raw_report = json.loads(report_path.read_bytes())
    if not raw_report["completed"] or not raw_report["postflight_unchanged"]:
        raise ValueError("raw capture has not finished with verified provenance")
    inputs = capture.load_retained(root, captured / "inputs", capture.load_contract(root))
    if len(inputs.matches) != contract["expected_selected_matches"]:
        raise ValueError("staging inventory differs from frozen scope")
    statuses = {
        (int(r["sdp_match_id"]), r["endpoint"]): r for r in raw_report["endpoint_inventory"]
    }
    if len(statuses) != len(raw_report["endpoint_inventory"]):
        raise ValueError("duplicate endpoint receipt inventory identity")
    if len(statuses) != 2 * len(inputs.matches):
        raise ValueError("raw capture endpoint inventory incomplete or duplicated")
    if set(statuses) != {(mid, e) for mid in inputs.matches for e in ("lineups", "events")}:
        raise ValueError("raw capture endpoint identities differ from frozen scope")
    started = datetime.now(UTC)
    reference = reference_data(source_db, contract["season"])
    with connect(source_db, read_only=True) as con:
        reference["fixture_gw"] = dict(
            con.execute(
                "SELECT fixture,gw FROM mart_fact_team_match WHERE season=? AND was_home",
                [contract["season"]],
            ).fetchall()
        )
    reference["database_sha256"] = contract["source_database_sha256"]
    clubs = club_crosswalk(inputs, reference)
    database.parent.mkdir(parents=True, exist_ok=True)
    consistent_copy(source_db, database, contract["source_database_sha256"])
    source_hashes = {
        **inputs.source_hashes,
        str(report_path): file_sha256(report_path),
        str(pilot_result.resolve()): file_sha256(pilot_result),
    }
    records = []
    with writer_lock(database) as con:
        con.execute("BEGIN TRANSACTION")
        try:
            apply_workload_schema(con)
            for mid, record in sorted(inputs.matches.items()):
                manifest_path = safe_file(captured, f"capture-{mid}.json")
                manifest = json.loads(manifest_path.read_bytes())
                if manifest["sdp_match_id"] != mid or manifest["selected_match_record"] != record:
                    raise ValueError("manifest fixture identity contradicts checked catalogue")
                source_hashes[str(manifest_path)] = file_sha256(manifest_path)
                meta = manifest["metadata_receipt"]
                if meta != inputs.metadata[mid]:
                    raise ValueError("metadata receipt differs from pinned catalogue")
                meta_path = safe_file(captured / "inputs", meta["raw_file"])
                meta_body = meta_path.read_bytes()
                receipt_ids = [
                    append_receipt(con, receipt=meta, body=meta_body, source_path=str(meta_path))
                ]
                source_hashes[str(meta_path)] = meta["sha256"]
                sources = {
                    "metadata": {
                        "known_at": meta["captured_at_utc"],
                        "sha256": meta["sha256"],
                        "path": str(meta_path),
                    }
                }
                payloads = {}
                errors = []
                for endpoint in ("lineups", "events"):
                    state = manifest["endpoints"][endpoint]
                    expected = {
                        k: v
                        for k, v in statuses[(mid, endpoint)].items()
                        if k not in {"sdp_match_id", "endpoint"}
                    }
                    if state != expected:
                        raise ValueError(
                            "per-match endpoint state differs from final capture report"
                        )
                    if state["status"] not in {"received", "reused"}:
                        errors.append(f"{endpoint}:{state['status']}:{state.get('error', '')}")
                        continue
                    path, body, receipt = verified_body(captured, state["source"], mid, endpoint)
                    sources[endpoint] = deepcopy(state["source"])
                    source_hashes[str(path)] = receipt["sha256"]
                    receipt_ids.append(
                        append_receipt(con, receipt=receipt, body=body, source_path=str(path))
                    )
                    try:
                        payloads[endpoint] = json.loads(body)
                    except (ValueError, UnicodeDecodeError) as error:
                        errors.append(f"{endpoint}:invalid_JSON:{error}")
                interpreted = interpreted_record(
                    record=record,
                    sources=sources,
                    payloads=payloads,
                    receipts=receipt_ids,
                    reference=reference,
                    clubs=clubs,
                    interpreted_at=datetime.now(UTC),
                    parser_sha256=contract["parser_sha256"],
                    errors=errors,
                )
                append_match(con, interpreted)
                records.append(interpreted)
            audit = participation_audit(records, reference, clubs)
            run_id = results.name
            provenance = {
                "run_id": run_id,
                "git_head": head,
                "clean_worktree": True,
                "config": contract,
                "source_database": str(source_db),
                "source_database_sha256": contract["source_database_sha256"],
                "operational_database": str(database),
                "capture_directory": str(captured),
                "source_sha256": fingerprints,
                "input_sha256": source_hashes,
                "started_at_utc": started.isoformat(),
                "provider_to_team_code": clubs,
                "model_fitting": False,
                "network_requests": False,
                "defaults_changed": False,
            }
            append_report(con, "dev_competitive_ingestion", run_id, provenance)
            append_report(con, "dev_competitive_coverage_version", run_id, audit)
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
        con.execute("CHECKPOINT")
        counts = {}
        for table in sorted(TABLES):
            count_row = con.execute(f"SELECT count(*) FROM {table}").fetchone()
            assert count_row is not None
            counts[table] = count_row[0]
    if capture._head(root, contract) != head or any(
        file_sha256(root / n) != h for n, h in fingerprints.items()
    ):
        raise ValueError("staging source provenance changed")
    if _sha256(source_db) != contract["source_database_sha256"] or _wal_path(source_db).exists():
        raise ValueError("original database changed; operational data not certified")
    if any(file_sha256(Path(path)) != sha for path, sha in source_hashes.items()):
        raise ValueError("retained inputs changed during staging")
    with connect(database, read_only=True) as con:
        retained_records = [
            json.loads(row[0])
            for row in con.execute(
                "SELECT CAST(record_json AS VARCHAR) FROM dev_competitive_match_version"
            ).fetchall()
        ]
    view = workload_view(retained_records, clubs, identity(inputs.inventory), started)
    # Data-access proof only: one actual witnessed player after all captures; no model is fitted.
    witness = next(
        (
            r
            for record in records
            if record["interpretation_valid"]
            for r in record["rows"]
            if r["code"] is not None and r["appeared"] is True
        ),
        None,
    )
    access = None
    if witness:
        fixture = next(record for record in records if witness in record["rows"])
        cutoff = datetime.fromisoformat(fixture["kickoff"]) + timedelta(days=2)
        access = asdict(
            view.observed_participation_snapshot(
                identity=ObservedPlayerIdentity(
                    witness["code"],
                    witness["provider_player_id"],
                    contract["source_database_sha256"],
                    datetime.fromisoformat(reference["identity_observed_at_utc"]),
                ),
                scope_team_codes=frozenset(clubs.values()),
                as_of=cutoff,
                excluded_target_gw_fixtures=frozenset(),
            )
        )
    report = {
        "completed": True,
        "provenance": provenance,
        "counts": counts,
        "audit": audit,
        "observed_view_access_check": access,
        "source_database_preserved": True,
        "operational_database_sha256": _sha256(database),
        "operational_no_wal": not _wal_path(database).exists(),
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "model_fitting": False,
        "promotion_permitted": False,
    }
    serializable: dict[str, Any] = json.loads(
        json.dumps(report, default=_json_default, allow_nan=False)
    )
    publish_json(results / "result.json", serializable)
    return serializable


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return asdict(value)


def run(
    *,
    root: Path,
    source_db: Path,
    database: Path,
    captured: Path,
    pilot_result: Path,
    results: Path,
) -> dict[str, Any]:
    """Own one new report directory, preserving structured failure evidence without overwrites."""
    if (
        results.is_symlink()
        or results.exists()
        or results.resolve().is_relative_to(root.resolve())
        or results.resolve().is_relative_to(captured.resolve())
        or results.resolve() in {source_db.resolve(), database.resolve()}
    ):
        raise ValueError("new external report directory required")
    results.mkdir(parents=True, exist_ok=False)
    try:
        return _run(
            root=root,
            source_db=source_db,
            database=database,
            captured=captured,
            pilot_result=pilot_result,
            results=results,
        )
    except Exception as error:
        publish_json(
            results / "failure.json",
            {
                "completed": False,
                "failure_class": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
                "source_database": str(source_db.resolve()),
                "operational_database": str(database.resolve()),
                "operational_database_exists": database.exists(),
                "operational_wal_exists": _wal_path(database).exists(),
                "source_database_sha256_at_failure": _sha256(source_db)
                if source_db.is_file()
                else None,
                "source_wal_exists": _wal_path(source_db).exists(),
                "note": "Any operational copy is preserved for diagnosis, not certified complete.",
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "model_fitting": False,
                "network_requests": False,
                "defaults_changed": False,
            },
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-db", "db", "capture", "pilot-result", "results"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    report = run(
        root=repo_root(),
        source_db=args.source_db,
        database=args.db,
        captured=args.capture,
        pilot_result=args.pilot_result,
        results=args.results,
    )
    logger.info("Operational workload staged: %s", report["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
