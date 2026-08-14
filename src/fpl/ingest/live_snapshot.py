"""Versioned live-snapshot contract and current-season loader.

Raw capture and derived live rows share one transaction. Every promoted row carries
`known_at`, while player outcomes additionally require a completed fixture grain from
element-summary. The gameweek live feed is retained as a fast safety net but is never
misrepresented as player-fixture data because it aggregates double gameweeks.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import uuid4

import duckdb

from fpl.ingest.fpl_api import (
    ApiFixture,
    BootstrapStatic,
    ElementSummary,
    detect_season_skew,
)

POSITION_BY_TYPE: Final[dict[int, str]] = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


@dataclass(frozen=True, slots=True)
class CapturedPayload:
    endpoint: str
    parameter: str
    payload: Any
    sha256: str

    @property
    def payload_json(self) -> str:
        return json.dumps(self.payload, separators=(",", ":"), sort_keys=True)

    @property
    def byte_count(self) -> int:
        return len(self.payload_json.encode("utf-8"))

    @property
    def row_count(self) -> int | None:
        if isinstance(self.payload, list):
            return len(self.payload)
        if isinstance(self.payload, dict):
            for key in ("history", "elements"):
                rows = self.payload.get(key)
                if isinstance(rows, list):
                    return len(rows)
        return None

    @property
    def resource(self) -> str:
        return f"{self.endpoint}/{self.parameter}" if self.parameter else self.endpoint


@dataclass(frozen=True, slots=True)
class LoadResult:
    player_versions: int = 0
    team_versions: int = 0
    fixture_versions: int = 0
    player_fixture_versions: int = 0
    skipped_rows: int = 0


@dataclass(frozen=True, slots=True)
class CaptureResult:
    capture_id: str
    captured_at: datetime
    payload_count: int
    loaded: LoadResult


def capture_payload(endpoint: str, payload: Any, *, parameter: str = "") -> CapturedPayload:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return CapturedPayload(
        endpoint=endpoint,
        parameter=parameter,
        payload=payload,
        sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def _manifest(captured: list[CapturedPayload]) -> tuple[str, str]:
    entries = [
        {
            "endpoint": item.endpoint,
            "parameter": item.parameter,
            "sha256": item.sha256,
            "byte_count": item.byte_count,
            "row_count": item.row_count,
        }
        for item in captured
    ]
    body = json.dumps(
        {"schema_version": "1", "payloads": entries},
        separators=(",", ":"),
        sort_keys=True,
    )
    return body, hashlib.sha256(body.encode("utf-8")).hexdigest()


def write_capture(
    con: duckdb.DuckDBPyConnection,
    captured: list[CapturedPayload],
    *,
    season: str,
    gw: int | None,
    mode: str,
    captured_at: datetime | None = None,
    capture_id: str | None = None,
) -> CaptureResult:
    """Atomically persist a capture, its manifest, and derived live versions."""
    if not captured:
        raise ValueError("refusing to write an empty capture")
    stamp = captured_at or datetime.now(UTC)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("captured_at must be timezone-aware")
    identity = capture_id or str(uuid4())
    manifest, manifest_sha = _manifest(captured)

    con.execute("BEGIN TRANSACTION")
    try:
        con.execute(
            """
            INSERT INTO snapshot_capture
                (capture_id, captured_at, season, gw, mode, payload_count, manifest,
                 manifest_sha256)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [identity, stamp, season, gw, mode, len(captured), manifest, manifest_sha],
        )
        for item in captured:
            con.execute(
                """
                INSERT INTO snapshot_payload
                    (capture_id, endpoint, parameter, payload, sha256, byte_count, row_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    identity,
                    item.endpoint,
                    item.parameter,
                    item.payload_json,
                    item.sha256,
                    item.byte_count,
                    item.row_count,
                ],
            )
            # Compatibility for existing databases and operational queries.
            con.execute(
                """
                INSERT INTO snapshot_bootstrap (captured_at, gw, endpoint, payload, sha256)
                VALUES (?, ?, ?, ?, ?)
                """,
                [stamp, gw, item.resource, item.payload_json, item.sha256],
            )
        loaded = load_capture(con, identity)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    return CaptureResult(identity, stamp, len(captured), loaded)


def _payloads_for_capture(
    con: duckdb.DuckDBPyConnection, capture_id: str
) -> dict[tuple[str, str], Any]:
    payloads: dict[tuple[str, str], Any] = {}
    rows = con.execute(
        """
        SELECT endpoint, parameter, CAST(payload AS VARCHAR), sha256
        FROM snapshot_payload WHERE capture_id = ?
        """,
        [capture_id],
    ).fetchall()
    for endpoint, parameter, payload_json, expected_sha in rows:
        payload = json.loads(str(payload_json))
        actual = capture_payload(str(endpoint), payload, parameter=str(parameter)).sha256
        if actual != expected_sha:
            raise ValueError(f"payload checksum mismatch for {endpoint}/{parameter}")
        payloads[(str(endpoint), str(parameter))] = payload
    return payloads


def _insert_many(
    con: duckdb.DuckDBPyConnection,
    table: str,
    columns: tuple[str, ...],
    rows: list[tuple[object, ...]],
) -> None:
    if not rows:
        return
    allowed = {
        "stg_live_player_version",
        "stg_live_team_version",
        "stg_live_fixture_version",
        "stg_live_player_fixture_version",
        "mart_fact_player_fixture_live",
        "mart_team_fixture_live",
    }
    if table not in allowed:
        raise ValueError(f"unapproved live table: {table}")
    projection = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    con.executemany(f"INSERT OR IGNORE INTO {table} ({projection}) VALUES ({placeholders})", rows)


def _record_skew(
    con: duckdb.DuckDBPyConnection, *, season: str, detail: str, captured_at: datetime
) -> None:
    con.execute(
        """
        INSERT INTO ingest_anomaly
            (detected_at, check_id, season, detail)
        VALUES (?, 'live_season_skew', ?, ?)
        """,
        [captured_at, season, detail],
    )


def load_capture(con: duckdb.DuckDBPyConnection, capture_id: str) -> LoadResult:
    """Verify and promote one raw capture without inventing unavailable knowledge time."""
    header = con.execute(
        """
        SELECT CAST(captured_at AS VARCHAR), season, payload_count
        FROM snapshot_capture WHERE capture_id = ?
        """,
        [capture_id],
    ).fetchone()
    if header is None:
        raise ValueError(f"unknown capture_id: {capture_id}")
    captured_at_raw, season, expected_count = header
    captured_at = datetime.fromisoformat(str(captured_at_raw))
    payloads = _payloads_for_capture(con, capture_id)
    if len(payloads) != expected_count:
        raise ValueError(
            f"capture {capture_id} expected {expected_count} payloads, found {len(payloads)}"
        )

    raw_bootstrap = payloads.get(("bootstrap-static", ""))
    if raw_bootstrap is None:
        raise ValueError("capture has no bootstrap-static payload")
    bootstrap = BootstrapStatic.model_validate(raw_bootstrap)
    all_players = {player.id: player for player in bootstrap.elements}
    players = {
        element: player
        for element, player in all_players.items()
        if player.element_type in POSITION_BY_TYPE
    }
    unsupported = len(all_players) - len(players)

    player_rows: list[tuple[object, ...]] = []
    for player in players.values():
        position = POSITION_BY_TYPE.get(player.element_type)
        if position is None:
            raise ValueError(f"unknown element_type {player.element_type} for {player.id}")
        player_rows.append(
            (
                season,
                player.id,
                player.code,
                captured_at,
                capture_id,
                player.web_name,
                player.element_type,
                position,
                player.team,
                player.now_cost,
                player.status,
            )
        )
    _insert_many(
        con,
        "stg_live_player_version",
        (
            "season",
            "element",
            "code",
            "known_at",
            "capture_id",
            "web_name",
            "element_type",
            "position",
            "team_id",
            "now_cost",
            "status",
        ),
        player_rows,
    )

    team_rows: list[tuple[object, ...]] = [
        (
            season,
            team.id,
            team.code,
            captured_at,
            capture_id,
            team.name,
            team.short_name,
            team.pulse_id,
        )
        for team in bootstrap.teams
    ]
    _insert_many(
        con,
        "stg_live_team_version",
        (
            "season",
            "team_id",
            "team_code",
            "known_at",
            "capture_id",
            "team_name",
            "short_name",
            "pulse_id",
        ),
        team_rows,
    )

    raw_fixtures = payloads.get(("fixtures", ""), [])
    fixtures = [ApiFixture.model_validate(item) for item in raw_fixtures]
    skew = detect_season_skew(bootstrap, fixtures)
    if fixtures and not skew.is_consistent:
        _record_skew(con, season=season, detail=skew.detail, captured_at=captured_at)
        return LoadResult(
            player_versions=len(player_rows),
            team_versions=len(team_rows),
            skipped_rows=len(fixtures) + unsupported,
        )

    fixture_by_id = {fixture.id: fixture for fixture in fixtures}
    fixture_rows: list[tuple[object, ...]] = []
    team_fixture_rows: list[tuple[object, ...]] = []
    for fixture in fixtures:
        fixture_rows.append(
            (
                season,
                fixture.id,
                captured_at,
                capture_id,
                fixture.event,
                fixture.kickoff_time,
                fixture.team_h,
                fixture.team_a,
                fixture.team_h_difficulty,
                fixture.team_a_difficulty,
                fixture.finished,
            )
        )
        for team_id, opponent_id, was_home, fdr in (
            (fixture.team_h, fixture.team_a, True, fixture.team_h_difficulty),
            (fixture.team_a, fixture.team_h, False, fixture.team_a_difficulty),
        ):
            team_fixture_rows.append(
                (
                    season,
                    fixture.event,
                    fixture.id,
                    fixture.pulse_id,
                    fixture.kickoff_time,
                    team_id,
                    opponent_id,
                    was_home,
                    fdr,
                    None,
                    captured_at,
                    capture_id,
                )
            )
    _insert_many(
        con,
        "stg_live_fixture_version",
        (
            "season",
            "fixture",
            "known_at",
            "capture_id",
            "gw",
            "kickoff_time",
            "team_h",
            "team_a",
            "team_h_difficulty",
            "team_a_difficulty",
            "finished",
        ),
        fixture_rows,
    )
    _insert_many(
        con,
        "mart_team_fixture_live",
        (
            "season",
            "gw",
            "fixture",
            "pulse_id",
            "kickoff_time",
            "team_id",
            "opponent_team_id",
            "was_home",
            "fdr",
            "rest_days",
            "known_at",
            "capture_id",
        ),
        team_fixture_rows,
    )

    history_rows: list[tuple[object, ...]] = []
    skipped = unsupported
    first_deadline = min(
        (event.deadline_time for event in bootstrap.events if event.deadline_time), default=None
    )
    earliest_safe = first_deadline - timedelta(days=1) if first_deadline else None
    for (endpoint, parameter), raw_summary in payloads.items():
        if endpoint != "element-summary":
            continue
        summary_player = all_players.get(int(parameter))
        if summary_player is None:
            raise ValueError(f"element-summary references unknown element {parameter}")
        if summary_player.element_type not in POSITION_BY_TYPE:
            raw_history = raw_summary.get("history", []) if isinstance(raw_summary, dict) else []
            skipped += len(raw_history) if isinstance(raw_history, list) else 1
            continue
        position = POSITION_BY_TYPE[summary_player.element_type]
        summary = ElementSummary.model_validate(raw_summary)
        for history in summary.history:
            if history.element != summary_player.id:
                raise ValueError(
                    f"element-summary {summary_player.id} contains element {history.element}"
                )
            history_fixture = fixture_by_id.get(history.fixture)
            if (
                history_fixture is None
                or history_fixture.kickoff_time is None
                or (earliest_safe is not None and history.kickoff_time < earliest_safe)
            ):
                skipped += 1
                continue
            team_id = history_fixture.team_h if history.was_home else history_fixture.team_a
            expected_opponent = (
                history_fixture.team_a if history.was_home else history_fixture.team_h
            )
            if expected_opponent != history.opponent_team:
                raise ValueError(
                    f"fixture {history.fixture} opponent mismatch for element {summary_player.id}"
                )
            history_rows.append(
                (
                    season,
                    summary_player.id,
                    summary_player.code,
                    history.fixture,
                    history_fixture.pulse_id,
                    captured_at,
                    capture_id,
                    history.round,
                    history.kickoff_time,
                    position,
                    team_id,
                    history.opponent_team,
                    history.was_home,
                    history.minutes,
                    history.starts,
                    history.goals_scored,
                    history.assists,
                    history.clean_sheets,
                    history.goals_conceded,
                    history.saves,
                    history.penalties_saved,
                    history.penalties_missed,
                    history.own_goals,
                    history.yellow_cards,
                    history.red_cards,
                    history.bonus,
                    history.bps,
                    history.expected_goals,
                    history.expected_assists,
                    history.threat,
                    history.creativity,
                    history.influence,
                    history.expected_goals_conceded,
                    history.defensive_contribution,
                    history.tackles,
                    history.recoveries,
                    history.clearances_blocks_interceptions,
                    history.value,
                    history.selected,
                    history.transfers_in,
                    history.transfers_out,
                    history.total_points,
                )
            )

    history_columns = (
        "season",
        "element",
        "code",
        "fixture",
        "pulse_id",
        "known_at",
        "capture_id",
        "gw",
        "kickoff_time",
        "position",
        "team_id",
        "opponent_team_id",
        "was_home",
        "minutes",
        "starts",
        "goals_scored",
        "assists",
        "clean_sheets",
        "goals_conceded",
        "saves",
        "penalties_saved",
        "penalties_missed",
        "own_goals",
        "yellow_cards",
        "red_cards",
        "bonus",
        "bps",
        "expected_goals",
        "expected_assists",
        "threat",
        "creativity",
        "influence",
        "expected_goals_conceded",
        "defensive_contribution",
        "tackles",
        "recoveries",
        "clearances_blocks_interceptions",
        "value",
        "selected",
        "transfers_in",
        "transfers_out",
        "total_points",
    )
    _insert_many(con, "stg_live_player_fixture_version", history_columns, history_rows)
    mart_columns = tuple(
        column for column in history_columns if column not in {"element", "total_points"}
    )
    mart_indexes = [history_columns.index(column) for column in mart_columns]
    mart_rows = [tuple(row[index] for index in mart_indexes) for row in history_rows]
    _insert_many(con, "mart_fact_player_fixture_live", mart_columns, mart_rows)
    return LoadResult(
        player_versions=len(player_rows),
        team_versions=len(team_rows),
        fixture_versions=len(fixture_rows),
        player_fixture_versions=len(history_rows),
        skipped_rows=skipped,
    )
