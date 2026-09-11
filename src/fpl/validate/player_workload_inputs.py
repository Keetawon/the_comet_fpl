"""Read-only V3 workload / frozen-role adapter and coverage-only audit for Phase D.

No target outcomes, model fits, role refits, database writes or fabricated rest.
Keep shared whole-match versions in memory once; row evidence references their IDs.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fpl.ingest.pl_sdp import parse_match_summary
from fpl.jobs.competitive_participation_pilot import file_sha256
from fpl.storage.competitive_workload import identity
from fpl.storage.db import connect
from fpl.validate.competitive_workload_view import (
    COMPETITIONS,
    CatalogueCoverage,
    CompetitiveFixture,
    CompetitiveFixtureKey,
    CompetitiveMatchVersion,
    ObservedPlayerIdentity,
    RetrospectiveCompetitiveWorkloadView,
    WorkloadObservation,
)
from fpl.validate.dev_player_role_history import INTERPRETATION_ID, _completed, select_versions
from fpl.validate.development_reference_components import (
    ValidatedMinutesControlCache,
    read_minutes_control_cache,
)
from fpl.validate.player_role_cache import RESULT_SHA256, load_role_cache
from fpl.validate.player_workload_cache import observe_workload_batch
from fpl.validate.player_workload_minutes import (
    WorkloadFeatureEvidence,
    WorkloadMinutesInput,
    control_from_cache,
    workload_role_features,
)

DATABASE_SHA256 = "a8584ce79f421e0bd43057f3a8f63bac03e30b59cc1c2407b8a7c28387a35021"
STAGE_SHA256 = "2df5d126c466edb2cf3e6f78e4bf3df9a24c350a44f47d2fc890d31ec3bf46c9"


def _time(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("workload-source timestamps must be timezone aware")
    return result


def _guard(database: Path) -> None:
    if (
        database.is_symlink()
        or Path(str(database) + ".wal").exists()
        or file_sha256(database) != DATABASE_SHA256
    ):
        raise ValueError("explicit frozen V3 workload database hash/WAL differs")


def version_view(
    records: list[dict[str, Any]],
    clubs: dict[int, int],
    *,
    catalogue_identity: str,
    catalogue_known_at: datetime,
) -> RetrospectiveCompetitiveWorkloadView:
    """Correct V3 whole-version DTOs; finality/earliest policy is selected upstream."""
    fixtures, versions = [], []
    for record in records:
        if record["interpretation_id"] != INTERPRETATION_ID:
            raise ValueError("V3 workload adapter rejects other interpretations")
        if not _completed(record) or record["capture_complete"] is not True:
            raise ValueError("workload adapter requires complete competitive-final source")
        summary = parse_match_summary(record["raw_match"])
        if summary.kickoff != _time(record["kickoff"]) or summary.match_id != record["match_id"]:
            raise ValueError("workload match identity/kickoff contradiction")
        provider_ids = frozenset(
            t for t in (summary.home_team_id, summary.away_team_id) if t is not None
        )
        fixture = CompetitiveFixture(
            CompetitiveFixtureKey(
                "pl_sdp", record["competition_id"], record["season"], record["match_id"]
            ),
            _time(record["kickoff"]),
            frozenset(clubs[t] for t in provider_ids if t in clubs),
            True,
            provider_ids,
            tuple(sorted((t, clubs[t]) for t in provider_ids if t in clubs)),
        )
        fixtures.append(fixture)
        versions.append(
            CompetitiveMatchVersion(
                fixture,
                record["version_id"],
                _time(record["capture_known_at"]),
                INTERPRETATION_ID,
                _time(record["interpretation_known_at"]),
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
                None
                if record["maximum_retained_event_timestamp"] is None
                else _time(record["maximum_retained_event_timestamp"]),
                None if record["verified_end_at"] is None else _time(record["verified_end_at"]),
                tuple(record["errors"]),
            )
        )
    if not fixtures:
        raise ValueError("nonempty verified competitive catalogue required")
    start = min(f.kickoff for f in fixtures)
    before = max(f.kickoff for f in fixtures) + timedelta(microseconds=1)
    coverage = tuple(
        CatalogueCoverage(
            "pl_sdp",
            competition,
            team,
            start,
            before,
            catalogue_known_at,
            catalogue_identity,
            True,
        )
        for competition in sorted(COMPETITIONS)
        for team in sorted(clubs.values())
    )
    return RetrospectiveCompetitiveWorkloadView(
        interpretation_id=INTERPRETATION_ID,
        fixtures=tuple(fixtures),
        versions=tuple(versions),
        catalogue_coverage=coverage,
        memberships=(),
    )


@dataclass(frozen=True, slots=True)
class WorkloadProgramInputs:
    reference: ValidatedMinutesControlCache
    batches: dict[tuple[str, int], tuple[WorkloadMinutesInput, ...]]
    evidence: dict[tuple[str, int, int], WorkloadFeatureEvidence]
    source_versions: dict[str, dict[str, Any]]
    coverage: dict[str, Any]


def build_workload_inputs(
    *,
    root: Path,
    database: Path,
    archive_database: Path,
    minutes_directory: Path,
    role_result: Path,
    stage_report: Path,
) -> WorkloadProgramInputs:
    """Full fixed roster; inspect measured features only, never minutes/role targets."""
    _guard(database)
    if file_sha256(stage_report) != STAGE_SHA256:
        raise ValueError("V3 stage report hash differs")
    stage = json.loads(stage_report.read_bytes())
    if stage["completed"] is not True or stage["operational_database_sha256"] != DATABASE_SHA256:
        raise ValueError("V3 stage was not completed on this database")
    reference = read_minutes_control_cache(minutes_directory, db=archive_database, root=root)
    roles = load_role_cache(role_result, root=root)
    with connect(database, read_only=True) as con:
        records = select_versions(
            [
                json.loads(r[0])
                for r in con.execute(
                    "SELECT record_json FROM dev_competitive_match_version "
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
        team_codes = dict(
            con.execute(
                "SELECT team_id,team_code FROM mart_dim_team WHERE season='2025-26'"
            ).fetchall()
        )
    if len(records) != 574:
        raise ValueError("fixed six-competition catalogue must retain all574 matches")
    clubs: dict[int, int] = {}
    identities: dict[int, ObservedPlayerIdentity] = {}
    pl_records = {}
    for record in records:
        if record["competition_id"] == 8:
            if record["fpl_fixture"] in pl_records:
                raise ValueError("ambiguous PL fixture crosswalk")
            pl_records[record["fpl_fixture"]] = record
        for row in record["rows"]:
            provider, code, team = row["provider_player_id"], row["code"], row["team_code"]
            if team is not None:
                if team not in team_codes.values():
                    raise ValueError("source club not in season-qualified PL scope")
                previous = clubs.setdefault(row["provider_team_id"], team)
                if previous != team:
                    raise ValueError("contradictory exact provider club identity")
            if code is None:
                continue
            if anchors.get(code) != f"p{provider}":
                raise ValueError("source player does not match exact season-qualified Opta anchor")
            witness = ObservedPlayerIdentity(
                code,
                provider,
                identity(record["identity_source"]),
                _time(record["identity_source"]["observed_at"]),
            )
            if code in identities and identities[code].provider_player_id != provider:
                raise ValueError("ambiguous player crosswalk")
            if code not in identities or witness.known_at < identities[code].known_at:
                identities[code] = witness
    if len(clubs) != 20 or len(set(clubs.values())) != 20 or len(pl_records) != 380:
        raise ValueError("full20-club380-PL-fixture scope required")
    view = version_view(
        records,
        clubs,
        catalogue_identity=f"completed-stage:{STAGE_SHA256}",
        catalogue_known_at=max(
            _time(r["source_versions"]["metadata"]["known_at"]) for r in records
        ),
    )
    source_versions = {
        r["version_id"]: {
            k: r[k]
            for k in (
                "version_id",
                "semantic_sha256",
                "receipt_ids",
                "competition_id",
                "season",
                "match_id",
                "fpl_fixture",
                "fpl_gw",
                "capture_known_at",
                "interpretation_known_at",
                "interpretation_id",
                "maximum_retained_event_timestamp",
                "verified_end_at",
                "errors",
                "source_versions",
                "identity_source",
            )
        }
        for r in records
    }
    batches = {}
    evidence = {}
    counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    by_gw = []
    for fold in reference.folds:
        key = fold.season, fold.gw
        excluded: frozenset[CompetitiveFixtureKey] = frozenset()
        observed = {}
        if fold.season == "2025-26":
            fixture_ids = {r.target.fixture for r in fold.rows}
            expected = {
                r["fpl_fixture"]
                for r in records
                if r["competition_id"] == 8 and r["fpl_gw"] == fold.gw
            }
            if fixture_ids != expected:
                raise ValueError("entire target-GW fixture crosswalk differs from reference")
            excluded = frozenset(
                CompetitiveFixtureKey("pl_sdp", 8, fold.season, pl_records[f]["match_id"])
                for f in fixture_ids
            )
            for row in fold.rows:
                record = pl_records[row.target.fixture]
                if _time(record["kickoff"]) != row.target.kickoff_time:
                    raise ValueError("target fixture kickoff does not match provider crosswalk")
                summary = parse_match_summary(record["raw_match"])
                provider_team = (
                    summary.home_team_id if row.target.was_home else summary.away_team_id
                )
                if provider_team not in clubs or clubs[provider_team] != row.team_code:
                    raise ValueError("target provider/venue/stable club contradiction")
            active_codes = sorted({r.target.code for r in fold.rows} & identities.keys())
            snapshots = observe_workload_batch(
                view,
                [identities[c] for c in active_codes],
                scope_team_codes=frozenset(clubs.values()),
                as_of=fold.as_of,
                excluded_target_gw_fixtures=excluded,
            )
            observed = {s.code: s for s in snapshots}
        inputs = []
        local: Counter[str] = Counter()
        for row in fold.rows:
            fixture = (
                None
                if fold.season != "2025-26"
                else CompetitiveFixtureKey(
                    "pl_sdp", 8, fold.season, pl_records[row.target.fixture]["match_id"]
                )
            )
            item = WorkloadMinutesInput(
                control_from_cache(fold, row),
                observed.get(row.target.code),
                roles.get(key),
                fixture,
                excluded,
            )
            feature = workload_role_features(item)
            inputs.append(item)
            evidence[(fold.season, row.target.fixture, row.target.code)] = feature
            local["rows"] += 1
            local["price_proxy_rows"] += row.price_proxy_dependent
            local["feature_active_rows"] += feature.features is not None
            local[feature.fallback_reason or "measured_positive_workload_and_role"] += 1
        batches[key] = tuple(inputs)
        counts[fold.season].update(local)
        by_gw.append(
            {"season": fold.season, "gw": fold.gw, "as_of": fold.as_of.isoformat(), **dict(local)}
        )
    _guard(database)
    coverage = {
        "database_sha256": DATABASE_SHA256,
        "role_result_sha256": RESULT_SHA256,
        "stage_report_sha256": STAGE_SHA256,
        "rows": sum(len(v) for v in batches.values()),
        "folds": len(batches),
        "price_proxy_rows": sum(v["price_proxy_rows"] for v in counts.values()),
        "by_season": {k: dict(v) for k, v in counts.items()},
        "by_gw": by_gw,
        "selected_versions": len(records),
        "source_version_identity": identity(source_versions),
        "feature_identity": identity(
            [
                {"key": list(k), "evidence": json.loads(json.dumps(asdict(v), default=str))}
                for k, v in sorted(evidence.items())
            ]
        ),
        "model_fitting": False,
        "model_scoring": False,
        "exact_rest_hours_available": False,
        "role_arm": "frozen_transition_candidate_not_matched_persistence",
        "minimum_stage_b_folds": 181,
        "full_stage_b_gate_eligible": False,
    }
    return WorkloadProgramInputs(reference, batches, evidence, source_versions, coverage)
