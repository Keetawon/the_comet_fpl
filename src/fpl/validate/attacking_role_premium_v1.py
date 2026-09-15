"""Read-only, typed reconstruction of the frozen attacking-usage study population.

Historical observations and future target identities have separate interfaces from
outcome labels. This module computes coverage, never predictions or predictive scores.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from fpl.features.attacking_role_premium_v1 import UsageObservation, UsageTarget
from fpl.jobs.backfill_historical_player_attacking import (
    AUDIT_PATH,
    PATHS,
    canonical,
    instant,
    load_scope,
    pinned_inputs,
    retained_source,
    source_url,
)
from fpl.jobs.competitive_participation_pilot import file_sha256

MANIFEST_SHA256 = "56da2a8c52f96c2d7d4b68586d86d9eeee3fc4011ae17235ddcf940b58dcf03c"
AUDIT_SHA256 = "146a7209c412e20fbebb63c3c8377097d95b1cd711baf5cf465cb78da4edb409"
SCOPE_SHA256 = "2403c87e9de6e284801b97b450f5841606177f03ee30593fbd3de642c444f72a"
OBSERVATIONS_SHA256 = "0d699021537dc7e636f0dfb8e4484f98fc57263663806631c5c8e075b0c5cefc"
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
TargetKey = tuple[str, int, int]


@dataclass(frozen=True)
class UsageOutcome:
    season: str
    gameweek: int
    fixture_id: int
    player_code: int
    xg: float | None
    xa: float | None
    minutes: int | None
    starts: int | None


@dataclass(frozen=True)
class StudyFold:
    season: str
    gameweek: int
    as_of: datetime
    source_snapshot_id: str
    targets: tuple[UsageTarget, ...]


@dataclass(frozen=True)
class StudyPopulation:
    folds: tuple[StudyFold, ...]
    history: tuple[UsageObservation, ...]
    outcomes: Mapping[TargetKey, UsageOutcome]
    receipt: Mapping[str, Any]


@dataclass(frozen=True)
class RegistryPlayer:
    element_id: int
    player_code: int
    fpl_position: str
    team_code: int


@dataclass(frozen=True)
class ScheduledFixture:
    fixture_id: int
    gameweek: int | None
    kickoff_time: datetime | None
    home_team_code: int
    away_team_code: int


@dataclass(frozen=True)
class SourceSnapshot:
    snapshot_id: str
    known_at: datetime
    capture_known_at: datetime
    registry: Mapping[int, RegistryPlayer]
    fixtures: Mapping[int, ScheduledFixture]
    hashes: Mapping[str, str]


@dataclass(frozen=True)
class PopulationRow:
    observation: UsageObservation
    target_identity: UsageTarget
    source_element_id: int


def target_key(target: UsageTarget | UsageOutcome) -> TargetKey:
    return target.season, target.fixture_id, target.player_code


def _integer(value: str | int | float | None, *, optional: bool = False) -> int | None:
    if value is None or value == "":
        if optional:
            return None
        raise ValueError("missing exact integer identity")
    numeric = float(value)
    if isinstance(value, bool) or not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError("invalid exact integer identity")
    return int(numeric)


def _required_integer(value: str | int | float | None) -> int:
    result = _integer(value)
    if result is None or result <= 0:
        raise ValueError("positive exact identity required")
    return result


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError("numeric observation must retain its source type")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("invalid nonnegative opportunity observation")
    return result


def _csv(raw: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("invalid source CSV header")
    rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError("invalid source CSV rows")
    return rows


def _snapshot(
    record: dict[str, Any],
    sources: dict[str, Any],
    seen_elements: dict[int, int],
    seen_codes: dict[int, int],
) -> SourceSnapshot:
    parts: dict[str, bytes] = {}
    hashes: dict[str, str] = {}
    capture_times: list[datetime] = []
    for role in PATHS:
        url = source_url(record, role)
        item = retained_source(url, sources[url])
        if item != sources[url]:
            raise ValueError("manifest source identity differs from its raw receipt")
        parts[role] = Path(item["raw_file"]).read_bytes()
        hashes[role] = item["sha256"]
        capture_times.append(instant(item["captured_at"]))
    team_rows = _csv(parts["teams"])
    teams = {_required_integer(r["id"]): _required_integer(r["code"]) for r in team_rows}
    if len(teams) != len(team_rows) or len(set(teams.values())) != len(teams):
        raise ValueError("duplicate seasonal team identity")
    registry: dict[int, RegistryPlayer] = {}
    for row in _csv(parts["registry"]):
        element, code = _required_integer(row["id"]), _required_integer(row["code"])
        if (
            code in registry
            or seen_elements.get(element, code) != code
            or seen_codes.get(code, element) != element
        ):
            raise ValueError("contradictory deterministic player mapping")
        seen_elements[element], seen_codes[code] = code, element
        kind = _required_integer(row["element_type"])
        if kind not in POSITIONS:
            raise ValueError("unknown historical FPL position")
        registry[code] = RegistryPlayer(
            element, code, POSITIONS[kind], teams[_required_integer(row["team"])]
        )
    fixtures: dict[int, ScheduledFixture] = {}
    for row in _csv(parts["fixtures"]):
        fid = _required_integer(row["id"])
        if fid in fixtures:
            raise ValueError("duplicate source fixture identity")
        fixtures[fid] = ScheduledFixture(
            fid,
            _integer(row["event"], optional=True),
            instant(row["kickoff_time"]) if row["kickoff_time"] else None,
            teams[_required_integer(row["team_h"])],
            teams[_required_integer(row["team_a"])],
        )
    return SourceSnapshot(
        record["snapshot_id"],
        instant(record["source_known_at"]),
        max(capture_times),
        MappingProxyType(registry),
        MappingProxyType(fixtures),
        MappingProxyType(hashes),
    )


def _observation(raw: dict[str, Any], snapshots: Mapping[str, SourceSnapshot]) -> PopulationRow:
    snapshot = snapshots[raw["source_snapshot_id"]]
    known, available, kickoff = (
        instant(raw[k]) for k in ("source_known_at", "available_at", "kickoff_time")
    )
    if (
        raw["season"] != "2023-24"
        or raw["evidence_class"] != "ARCHIVED_AS_OF"
        or known != snapshot.known_at
        or available != known
        or kickoff >= known
        or instant(raw["capture_known_at"]) != snapshot.capture_known_at
        or raw["source_sha256"] != snapshot.hashes["stats"]
        or any(raw["provenance"][role] != sha for role, sha in snapshot.hashes.items())
    ):
        raise ValueError("observation availability/provenance differs from its frozen snapshot")
    code, fixture_id = _required_integer(raw["player_code"]), _required_integer(raw["fixture_id"])
    registered, fixture = snapshot.registry[code], snapshot.fixtures[fixture_id]
    element, gameweek = (
        _required_integer(raw["source_element_id"]),
        _required_integer(raw["gameweek"]),
    )
    if (
        registered.element_id != element
        or registered.fpl_position != raw["fpl_position"]
        or raw["fpl_position"] not in {"DEF", "MID", "FWD"}
        or fixture.gameweek != gameweek
        or fixture.kickoff_time != kickoff
        or raw["venue"] not in {"HOME", "AWAY"}
    ):
        raise ValueError("historical player/position/fixture identity contradiction")
    own, opponent = (
        (fixture.home_team_code, fixture.away_team_code)
        if raw["venue"] == "HOME"
        else (fixture.away_team_code, fixture.home_team_code)
    )
    if own != raw["team_code"] or opponent != raw["opponent_team_code"]:
        raise ValueError("historical fixture-time club identity contradiction")
    if any(
        raw[field] is not None
        for field in ("shots", "shots_on_target", "key_passes", "box_touches")
    ):
        raise ValueError("unexpected source field outside the frozen xG/xA evidence")
    minutes, starts = (
        _integer(raw["minutes"], optional=True),
        _integer(raw["starts"], optional=True),
    )
    if (minutes is not None and not 0 <= minutes <= 120) or starts not in {None, 0, 1}:
        raise ValueError("invalid observed minutes or starts")
    observation = UsageObservation(
        season=raw["season"],
        gameweek=gameweek,
        fixture_id=fixture_id,
        kickoff_time=kickoff,
        player_code=code,
        fpl_position=raw["fpl_position"],
        minutes=minutes,
        starts=starts,
        xg=_number(raw["expected_goals"]),
        xa=_number(raw["expected_assists"]),
        source_known_at=known,
        available_at=available,
        evidence_class=raw["evidence_class"],
        source_snapshot_id=raw["source_snapshot_id"],
        source_sha256=raw["source_sha256"],
    )
    return PopulationRow(
        observation,
        UsageTarget(
            season=raw["season"],
            gameweek=gameweek,
            fixture_id=fixture_id,
            kickoff_time=kickoff,
            player_code=code,
            fpl_position=raw["fpl_position"],
            team_code=own,
            opponent_team_code=opponent,
            venue=raw["venue"],
        ),
        element,
    )


def build_population(
    rows: tuple[PopulationRow, ...],
    snapshots: tuple[SourceSnapshot, ...],
    target_gameweeks: tuple[int, ...],
) -> StudyPopulation:
    """Reconstruct eligibility independently; labels never enter target descriptors."""
    latest: dict[TargetKey, PopulationRow] = {}
    earliest: dict[TargetKey, PopulationRow] = {}
    versions: set[tuple[TargetKey, str]] = set()
    for row in sorted(
        rows, key=lambda r: (r.observation.available_at, r.observation.source_snapshot_id)
    ):
        key = target_key(row.target_identity)
        version = key, row.observation.source_snapshot_id
        if version in versions:
            raise ValueError("duplicate normalized observation version")
        versions.add(version)
        earliest.setdefault(key, row)
        latest[key] = row
    by_gw: dict[int, list[PopulationRow]] = defaultdict(list)
    for key in sorted(latest):
        row = latest[key]
        by_gw[row.target_identity.gameweek].append(row)
    folds: list[StudyFold] = []
    reports: list[dict[str, Any]] = []
    outcomes: dict[TargetKey, UsageOutcome] = {}
    exclusions: Counter[str] = Counter()
    start_players: dict[int, set[int]] = {n: set() for n in (3, 5, 10)}
    for gw in target_gameweeks:
        targets = by_gw[gw]
        if not targets:
            reports.append({"gw": gw, "status": "NO_TARGET_LABELS"})
            continue
        fixture_ids = {r.target_identity.fixture_id for r in targets}
        first_kickoff = min(r.target_identity.kickoff_time for r in targets)
        selected = None
        for snapshot in sorted(snapshots, key=lambda s: (s.known_at, s.snapshot_id), reverse=True):
            scheduled = {f.fixture_id: f for f in snapshot.fixtures.values() if f.gameweek == gw}
            if (
                snapshot.known_at < first_kickoff
                and set(scheduled) == fixture_ids
                and all(
                    f.kickoff_time is not None and f.kickoff_time > snapshot.known_at
                    for f in scheduled.values()
                )
            ):
                selected = snapshot
                break
        if selected is None:
            reports.append(
                {"gw": gw, "status": "NO_WHOLE_FUTURE_GW_SNAPSHOT", "target_rows": len(targets)}
            )
            exclusions["NO_WHOLE_FUTURE_GW_SNAPSHOT"] += len(targets)
            continue
        qualified: list[UsageTarget] = []
        rejected: Counter[str] = Counter()
        positions: Counter[str] = Counter()
        qualifying_minutes: Counter[str] = Counter()
        prior: dict[int, list[UsageObservation]] = defaultdict(list)
        for original in earliest.values():
            observation = original.observation
            if (
                observation.available_at <= selected.known_at
                and observation.kickoff_time < selected.known_at
                and observation.gameweek != gw
                and observation.fixture_id not in fixture_ids
            ):
                prior[observation.player_code].append(observation)
        counts: Counter[str] = Counter()
        coverage = {position: Counter[str]() for position in ("DEF", "MID", "FWD")}
        for row in targets:
            target, observed = row.target_identity, row.observation
            registered = selected.registry.get(target.player_code)
            if registered is None:
                rejected["NO_CUTOFF_REGISTRY"] += 1
                continue
            if registered.fpl_position != target.fpl_position:
                rejected["CUTOFF_POSITION_MISMATCH"] += 1
                continue
            fixture = selected.fixtures[target.fixture_id]
            own, opponent = (
                (fixture.home_team_code, fixture.away_team_code)
                if target.venue == "HOME"
                else (fixture.away_team_code, fixture.home_team_code)
            )
            if registered.team_code != own or own != target.team_code:
                rejected["CUTOFF_CLUB_MISMATCH"] += 1
                continue
            if opponent != target.opponent_team_code or fixture.kickoff_time is None:
                raise ValueError("cutoff opponent/schedule identity contradiction")
            # Target kickoff is the pre-cutoff schedule, not a later corrected kickoff.
            qualified.append(replace(target, kickoff_time=fixture.kickoff_time))
            positions[target.fpl_position] += 1
            previous = prior[target.player_code]
            starts = sum(previous_row.starts == 1 for previous_row in previous)
            measured = {
                "target_rows": 1,
                "paired_xg_xa_measured": int(observed.xg is not None and observed.xa is not None),
                "prior_history_present": int(bool(previous)),
                "prior_history_absent": int(not previous),
                "expected_goals_measured": int(observed.xg is not None),
                "expected_assists_measured": int(observed.xa is not None),
                "shots_measured": 0,
                "shots_on_target_measured": 0,
                "key_passes_measured": 0,
                "box_touches_measured": 0,
            }
            for minimum in start_players:
                measured[f"prior_starts_ge_{minimum}"] = int(starts >= minimum)
                if starts >= minimum:
                    start_players[minimum].add(target.player_code)
            counts.update(measured)
            coverage[target.fpl_position].update(measured)
            if (
                observed.minutes is not None
                and observed.minutes >= 45
                and observed.xg is not None
                and observed.xa is not None
            ):
                qualifying_minutes[target.fpl_position] += 1
            outcomes[target_key(target)] = UsageOutcome(
                target.season,
                gw,
                target.fixture_id,
                target.player_code,
                observed.xg,
                observed.xa,
                observed.minutes,
                observed.starts,
            )
        qualified.sort(key=lambda t: (t.fixture_id, t.player_code))
        exclusions.update(rejected)
        folds.append(
            StudyFold("2023-24", gw, selected.known_at, selected.snapshot_id, tuple(qualified))
        )
        reports.append(
            {
                "gw": gw,
                "status": "AVAILABLE_ARCHIVE_SNAPSHOT_CUTOFF",
                "cutoff": selected.known_at.isoformat(),
                "source_snapshot_id": selected.snapshot_id,
                "target_fixture_ids": sorted(fixture_ids),
                "target_rows": len(qualified),
                "counts": dict(counts),
                "coverage_by_position": {p: dict(c) for p, c in coverage.items()},
                "first_actual_target_kickoff": first_kickoff.isoformat(),
                "official_fpl_deadline": None,
                "distinct_eligible_players": len({t.player_code for t in qualified}),
                "by_position": dict(sorted(positions.items())),
                "exclusions": dict(sorted(rejected.items())),
                "paired_minutes_ge_45_by_position": dict(sorted(qualifying_minutes.items())),
                "paired_minutes_ge_45": sum(qualifying_minutes.values()),
            }
        )
    fingerprint = [
        {
            "gameweek": fold.gameweek,
            "as_of": fold.as_of.isoformat(),
            "source_snapshot_id": fold.source_snapshot_id,
            "targets": [
                {**asdict(t), "kickoff_time": t.kickoff_time.isoformat()} for t in fold.targets
            ],
        }
        for fold in folds
    ]
    receipt = {
        "kind": "attacking_usage_population_reproduction_no_predictive_scoring",
        "folds": reports,
        "target_gameweeks": len(folds),
        "target_rows": len(outcomes),
        "unique_players": len({key[2] for key in outcomes}),
        "exclusions": dict(sorted(exclusions.items())),
        "population_sha256": hashlib.sha256(canonical(fingerprint)).hexdigest(),
        "paired_minutes_ge_45": sum(r.get("paired_minutes_ge_45", 0) for r in reports),
        "official_historical_deadlines": None,
        "evidence_class": "ARCHIVED_AS_OF",
        "target_roster_is_retained_observed_population": True,
        "players_with_prior_starts": {str(n): len(codes) for n, codes in start_players.items()},
    }
    return StudyPopulation(
        tuple(folds),
        tuple(
            r.observation
            for r in sorted(
                rows,
                key=lambda r: (
                    r.observation.available_at,
                    r.observation.source_snapshot_id,
                    target_key(r.target_identity),
                ),
            )
        ),
        MappingProxyType(outcomes),
        MappingProxyType(receipt),
    )


def reconcile_audit(population: StudyPopulation, audit: dict[str, Any]) -> None:
    expected = {r["gw"]: r for r in audit["folds"]}
    actual = {r["gw"]: r for r in population.receipt["folds"]}
    if set(expected) != set(actual):
        raise ValueError("population gameweeks differ from the frozen availability audit")
    for gw, got in actual.items():
        wanted = expected[gw]
        if got["status"] != wanted["status"]:
            raise ValueError("population schedule exclusion differs from the frozen audit")
        if got["status"] != "AVAILABLE_ARCHIVE_SNAPSHOT_CUTOFF":
            if got != wanted:
                raise ValueError("excluded gameweek population differs from the frozen audit")
            continue
        for key in (
            "cutoff",
            "source_snapshot_id",
            "target_fixture_ids",
            "distinct_eligible_players",
            "exclusions",
            "first_actual_target_kickoff",
            "official_fpl_deadline",
            "counts",
        ):
            if got[key] != wanted[key]:
                raise ValueError(f"population {key} differs from the frozen audit")
        if got["target_rows"] != wanted["counts"]["target_rows"] or got["by_position"] != {
            position: values["target_rows"] for position, values in wanted["by_position"].items()
        }:
            raise ValueError("population position/target counts differ from the frozen audit")
        if got["coverage_by_position"] != wanted["by_position"]:
            raise ValueError("population prior-history coverage differs from the frozen audit")
    counts = audit["practical_sufficiency_counts"]
    for actual_key, audit_key in (
        ("target_rows", "outfield_target_rows"),
        ("target_gameweeks", "chronological_target_gameweeks"),
        ("unique_players", "unique_players"),
    ):
        if population.receipt[actual_key] != counts[audit_key]:
            raise ValueError("population aggregate differs from the frozen audit")
    for minimum in (3, 5, 10):
        if (
            population.receipt["players_with_prior_starts"][str(minimum)]
            != counts[f"players_with_{minimum}_prior_starts"]
        ):
            raise ValueError("population prior-start players differ from the frozen audit")


def load_population(
    manifest_path: Path,
    audit_path: Path,
    scope_path: Path,
    observations_path: Path,
) -> StudyPopulation:
    paths = {
        "manifest": manifest_path,
        "audit": audit_path,
        "scope": scope_path,
        "observations": observations_path,
    }
    pins = {
        "manifest": MANIFEST_SHA256,
        "audit": AUDIT_SHA256,
        "scope": SCOPE_SHA256,
        "observations": OBSERVATIONS_SHA256,
    }
    if any(file_sha256(paths[name]) != digest for name, digest in pins.items()):
        raise ValueError("frozen population artifact hash changed")
    manifest, audit = json.loads(manifest_path.read_bytes()), json.loads(audit_path.read_bytes())
    scope = load_scope(scope_path)
    checked = pinned_inputs(scope_path.parent.parent, scope_path, scope)
    if (
        manifest["normalized_sha256"] != pins["observations"]
        or audit["observations_sha256"] != pins["observations"]
        or audit["source_manifest_sha256"] != pins["manifest"]
        or audit["scope_sha256"] != pins["scope"]
        or checked["frozen_inputs_sha256"] != manifest["provenance"]["frozen_inputs_sha256"]
        or checked["implementation_sha256"] != manifest["provenance"]["implementation_sha256"]
        or audit["source_audit_sha256"] != checked["frozen_inputs_sha256"][AUDIT_PATH]
    ):
        raise ValueError("source manifest/audit/parser provenance binding changed")
    expected_urls = {source_url(s, role) for s in scope["snapshots"] for role in PATHS}
    if set(manifest["source_versions"]) != expected_urls:
        raise ValueError("raw source population differs from the frozen scope")
    seen_elements: dict[int, int] = {}
    seen_codes: dict[int, int] = {}
    snapshots = tuple(
        _snapshot(s, manifest["source_versions"], seen_elements, seen_codes)
        for s in scope["snapshots"]
    )
    by_snapshot = {s.snapshot_id: s for s in snapshots}
    rows = tuple(
        _observation(json.loads(line), by_snapshot)
        for line in observations_path.read_bytes().splitlines()
    )
    population = build_population(
        rows, snapshots, tuple(scope["practical_sufficiency"]["target_gameweeks_considered"])
    )
    reconcile_audit(population, audit)
    if len(rows) != manifest["normalized_versions"]:
        raise ValueError("normalized row count differs from the frozen manifest")
    if any(file_sha256(paths[name]) != digest for name, digest in pins.items()):
        raise ValueError("frozen source changed during population reconstruction")
    return replace(
        population,
        receipt=MappingProxyType(
            {
                **population.receipt,
                "input_sha256": pins,
                "raw_payload_hashes_checked": len(expected_urls),
                "source_snapshot_count": len(snapshots),
                "normalized_versions": len(rows),
                "frozen_availability_audit_reproduced": True,
            }
        ),
    )
