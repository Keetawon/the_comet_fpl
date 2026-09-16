"""Development-only archived player observations; no production feature capability.

An audited archive witness is a separate fact from this project's current capture.
The runner owns the frozen source investigation and exact snapshot/hash allowlist.
This parser cannot turn a retrospective CSV or a dated filename into PIT evidence.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from fpl.config import load_data_quality

EvidenceClass = Literal[
    "STRICT_HISTORICAL_PIT", "ARCHIVED_AS_OF", "RETROSPECTIVE_DEVELOPMENT", "CURRENT_PROSPECTIVE"
]
SOURCE_PARTS = ("stats", "registry", "fixtures", "teams")
POSITION = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def _instant(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if parsed.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return parsed.astimezone(UTC)


@dataclass(frozen=True)
class BackfillScope:
    seasons: tuple[str, ...]
    gameweeks: tuple[int, ...]
    allowed_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotEvidence:
    season: str
    snapshot_id: str
    evidence_class: EvidenceClass
    author_at: datetime
    committer_at: datetime
    capture_known_at: datetime
    expected_hashes: tuple[tuple[str, str], ...]
    audited_source_witness: str | None = None
    source_name: str = "vaastav/Fantasy-Premier-League"

    def availability(self, scope: BackfillScope) -> tuple[datetime | None, datetime]:
        if self.season not in scope.seasons or self.snapshot_id not in scope.allowed_snapshot_ids:
            raise ValueError("snapshot outside frozen scope")
        if not re.fullmatch(r"[0-9a-f]{40}", self.snapshot_id):
            raise ValueError("full immutable commit identity required")
        captured = _instant(self.capture_known_at)
        source = max(_instant(self.author_at), _instant(self.committer_at))
        if source > captured:
            raise ValueError("source evidence cannot postdate actual capture")
        if self.evidence_class in {"STRICT_HISTORICAL_PIT", "ARCHIVED_AS_OF"}:
            if not self.audited_source_witness or not self.audited_source_witness.strip():
                raise ValueError("historical class requires an audited source witness")
            return source, source
        if self.evidence_class not in {"RETROSPECTIVE_DEVELOPMENT", "CURRENT_PROSPECTIVE"}:
            raise ValueError("unsupported evidence class")
        return None, captured


@dataclass(frozen=True)
class HistoricalPlayerAttackingObservation:
    season: str
    gameweek: int
    fixture_id: int
    kickoff_time: datetime
    player_code: int
    source_element_id: int
    fpl_position: str
    team_code: int
    opponent_team_code: int
    venue: Literal["HOME", "AWAY"]
    minutes: int | None
    starts: int | None
    started: bool | None
    expected_goals: float | None
    expected_assists: float | None
    expected_goal_involvements: float | None
    goals: int | None
    assists: int | None
    total_points: int | None
    influence: float | None
    creativity: float | None
    threat: float | None
    ict_index: float | None
    shots: int | None
    shots_on_target: int | None
    key_passes: int | None
    box_touches: int | None
    source_name: str
    source_record_id: str
    source_snapshot_id: str
    observed_match_time: datetime
    source_known_at: datetime | None
    capture_known_at: datetime
    available_at: datetime
    evidence_class: EvidenceClass
    source_sha256: str
    provenance: tuple[tuple[str, str], ...]


def _csv(body: bytes, *, label: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig"), newline=""))
    if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValueError(f"missing or duplicate {label} CSV headers")
    result: list[dict[str, str]] = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f"malformed {label} CSV row")
        result.append(row)
    if not result:
        raise ValueError(f"empty {label} source")
    return result


def _number(row: dict[str, str], key: str, *, signed: bool = False) -> float | None:
    text = row.get(key)
    if text is None or text.strip().lower() in {"", "null", "none", "na"}:
        return None
    try:
        value = float(text)
    except ValueError as error:
        raise ValueError(f"invalid numeric {key}") from error
    if not math.isfinite(value) or (not signed and value < 0):
        raise ValueError(f"invalid numeric {key}")
    return value


def _integer(row: dict[str, str], key: str, *, signed: bool = False) -> int | None:
    value = _number(row, key, signed=signed)
    if value is None:
        return None
    if not value.is_integer():
        raise ValueError(f"non-integer {key}")
    return int(value)


def _identity(row: dict[str, str], key: str) -> int:
    value = _integer(row, key)
    if value is None or value <= 0:
        raise ValueError(f"missing or invalid identity {key}")
    return value


def _index(rows: list[dict[str, str]], *, label: str) -> dict[int, dict[str, str]]:
    result: dict[int, dict[str, str]] = {}
    for row in rows:
        key = _identity(row, "id")
        if key in result:
            raise ValueError(f"duplicate {label} identity")
        result[key] = row
    return result


def _boolean(row: dict[str, str], key: str) -> bool:
    value = row.get(key, "").lower()
    if value not in {"true", "false", "1", "0"}:
        raise ValueError(f"missing or invalid boolean {key}")
    return value in {"true", "1"}


def parse_snapshot(
    *,
    stats_bytes: bytes,
    registry_bytes: bytes,
    fixtures_bytes: bytes,
    teams_bytes: bytes,
    evidence: SnapshotEvidence,
    scope: BackfillScope,
) -> tuple[HistoricalPlayerAttackingObservation, ...]:
    """Validate one whole, hash-pinned source snapshot; never infer missing statistics."""
    source_known, available = evidence.availability(scope)
    null_rules = load_data_quality().nullify_for(evidence.season)
    parts = dict(
        zip(SOURCE_PARTS, (stats_bytes, registry_bytes, fixtures_bytes, teams_bytes), strict=True)
    )
    hashes = dict(evidence.expected_hashes)
    if len(hashes) != len(evidence.expected_hashes) or set(hashes) != set(SOURCE_PARTS):
        raise ValueError("exact four source hashes required")
    for label, body in parts.items():
        if hashlib.sha256(body).hexdigest() != hashes[label]:
            raise ValueError(f"content hash mismatch: {label}")
    registry = _index(_csv(registry_bytes, label="registry"), label="player")
    fixtures = _index(_csv(fixtures_bytes, label="fixtures"), label="fixture")
    teams = _index(_csv(teams_bytes, label="teams"), label="team")
    codes = [_identity(row, "code") for row in registry.values()]
    if len(codes) != len(set(codes)):
        raise ValueError("duplicate stable player mapping")
    team_codes = [_identity(row, "code") for row in teams.values()]
    if len(team_codes) != len(set(team_codes)):
        raise ValueError("duplicate stable team mapping")
    result: list[HistoricalPlayerAttackingObservation] = []
    seen: set[tuple[int, int]] = set()
    for row in _csv(stats_bytes, label="stats"):
        if row.get("season", evidence.season) != evidence.season:
            raise ValueError("source season contradiction")
        if (
            not {"GW", "element", "fixture", "kickoff_time", "opponent_team", "was_home"}
            <= row.keys()
        ):
            raise ValueError("required observation fields missing")
        gw = _identity(row, "GW")
        if gw not in scope.gameweeks:
            raise ValueError("gameweek outside frozen scope")
        if "round" in row and _integer(row, "round") not in {None, gw}:
            raise ValueError("source round/gameweek contradiction")
        element = _identity(row, "element")
        fixture_id = _identity(row, "fixture")
        if element not in registry or fixture_id not in fixtures:
            raise ValueError("unmapped exact player or fixture identity")
        player, fixture = registry[element], fixtures[fixture_id]
        code = _identity(player, "code")
        if (fixture_id, code) in seen:
            raise ValueError("duplicate fixture/player row")
        seen.add((fixture_id, code))
        player_type = _identity(player, "element_type")
        if player_type not in {*POSITION, 5}:
            raise ValueError("unsupported registered position")
        if player_type == 5:
            continue
        position = POSITION[player_type]
        observed_position = row.get("position")
        if observed_position:
            observed_position = {"GKP": "GK"}.get(observed_position, observed_position)
            if observed_position != position:
                raise ValueError("historical position contradiction")
        if "code" in row and _identity(row, "code") != code:
            raise ValueError("stable player identity contradiction")
        if _identity(fixture, "event") != gw:
            raise ValueError("fixture/gameweek contradiction")
        if not _boolean(fixture, "finished"):
            raise ValueError("observation fixture is not completed")
        kickoff = _instant(row["kickoff_time"])
        if kickoff != _instant(fixture["kickoff_time"]):
            raise ValueError("fixture kickoff contradiction")
        if kickoff >= available or kickoff >= _instant(evidence.capture_known_at):
            raise ValueError("observation must precede source availability and capture")
        home, away = _identity(fixture, "team_h"), _identity(fixture, "team_a")
        if home == away or home not in teams or away not in teams:
            raise ValueError("fixture team identity contradiction")
        was_home = _boolean(row, "was_home")
        own, opponent = (home, away) if was_home else (away, home)
        if _identity(row, "opponent_team") != opponent:
            raise ValueError("opponent/venue identity contradiction")
        if row.get("team") and row["team"] != teams[own].get("name"):
            raise ValueError("source team identity contradiction")
        minutes, starts = _integer(row, "minutes"), _integer(row, "starts")
        if (minutes is not None and minutes > 120) or starts not in {None, 0, 1}:
            raise ValueError("impossible minutes or starts")
        if position == "GK":
            continue
        expected = {
            key: _number(row, key)
            for key in ("expected_goals", "expected_assists", "expected_goal_involvements")
        }
        # Reuse declared archive repairs; literal placeholder zeros are not measurements.
        for rule in null_rules:
            if (rule.gw_min is None or gw >= rule.gw_min) and (
                rule.gw_max is None or gw <= rule.gw_max
            ):
                for key in rule.columns:
                    if key in expected:
                        expected[key] = None
        result.append(
            HistoricalPlayerAttackingObservation(
                season=evidence.season,
                gameweek=gw,
                fixture_id=fixture_id,
                kickoff_time=kickoff,
                player_code=code,
                source_element_id=element,
                fpl_position=position,
                team_code=_identity(teams[own], "code"),
                opponent_team_code=_identity(teams[opponent], "code"),
                venue="HOME" if was_home else "AWAY",
                minutes=minutes,
                starts=starts,
                started=None if starts is None else bool(starts),
                expected_goals=expected["expected_goals"],
                expected_assists=expected["expected_assists"],
                expected_goal_involvements=expected["expected_goal_involvements"],
                goals=_integer(row, "goals_scored"),
                assists=_integer(row, "assists"),
                total_points=_integer(row, "total_points", signed=True),
                influence=_number(row, "influence", signed=True),
                creativity=_number(row, "creativity"),
                threat=_number(row, "threat"),
                ict_index=_number(row, "ict_index"),
                shots=_integer(row, "shots"),
                shots_on_target=_integer(row, "shots_on_target"),
                key_passes=_integer(row, "key_passes"),
                box_touches=_integer(row, "box_touches"),
                source_name=evidence.source_name,
                source_record_id=f"{evidence.season}:{fixture_id}:{element}",
                source_snapshot_id=evidence.snapshot_id,
                observed_match_time=kickoff,
                source_known_at=source_known,
                capture_known_at=_instant(evidence.capture_known_at),
                available_at=available,
                evidence_class=evidence.evidence_class,
                source_sha256=hashes["stats"],
                provenance=(
                    *sorted(hashes.items()),
                    ("audited_source_witness", evidence.audited_source_witness or ""),
                    ("author_at", _instant(evidence.author_at).isoformat()),
                    ("committer_at", _instant(evidence.committer_at).isoformat()),
                    ("normalization_version", "historical_player_attacking_v1"),
                ),
            )
        )
    return tuple(sorted(result, key=lambda r: (r.season, r.gameweek, r.fixture_id, r.player_code)))


def historical_eligible(
    row: HistoricalPlayerAttackingObservation,
    *,
    as_of: datetime,
    target_season: str,
    target_gameweek: int,
    target_fixture: int | None = None,
) -> bool:
    """Historical research gate only; class D has its existing prospective capability."""
    cutoff = _instant(as_of)
    return (
        row.evidence_class in {"STRICT_HISTORICAL_PIT", "ARCHIVED_AS_OF"}
        and row.source_known_at is not None
        and bool(dict(row.provenance).get("audited_source_witness"))
        and _instant(row.source_known_at) <= cutoff
        and _instant(row.available_at) <= cutoff
        and _instant(row.kickoff_time) < cutoff
        and (row.season, row.gameweek) != (target_season, target_gameweek)
        and (
            target_fixture is None
            or (row.season, row.fixture_id) != (target_season, target_fixture)
        )
    )


def earliest_eligible_observations(
    rows: Iterable[HistoricalPlayerAttackingObservation],
    *,
    as_of: datetime,
    target_season: str,
    target_gameweek: int,
    target_fixture: int | None = None,
) -> tuple[HistoricalPlayerAttackingObservation, ...]:
    """Keep the earliest eligible whole source version, including its original NULLs."""
    _instant(as_of)
    versions: dict[tuple[str, int, int, str], HistoricalPlayerAttackingObservation] = {}
    for row in rows:
        if not historical_eligible(
            row,
            as_of=as_of,
            target_season=target_season,
            target_gameweek=target_gameweek,
            target_fixture=target_fixture,
        ):
            continue
        version = (row.season, row.fixture_id, row.player_code, row.source_snapshot_id)
        if version in versions and row != versions[version]:
            raise ValueError("contradictory values for the same source version")
        versions[version] = row
    selected: dict[tuple[str, int, int], HistoricalPlayerAttackingObservation] = {}
    for row in sorted(
        versions.values(),
        key=lambda r: (_instant(cast(datetime, r.source_known_at)), r.source_snapshot_id),
    ):
        selected.setdefault((row.season, row.fixture_id, row.player_code), row)
    return tuple(
        selected[key]
        for key in sorted(selected, key=lambda key: (selected[key].kickoff_time, *key))
    )
