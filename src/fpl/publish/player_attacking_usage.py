"""Immutable descriptive scouting export over one retained current FPL capture.

This reporting boundary reads raw evidence. It never writes the operational database
or supplies inputs to forecasts, fixture environments, or decision engines.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from fpl.config import load_sources
from fpl.features.attacking_role_premium_v1 import UsageObservation
from fpl.features.pit import AsOf
from fpl.features.player_attacking_usage import (
    PlayerAttackingUsageSnapshot,
    RegisteredUsagePlayer,
    build_player_attacking_usage,
)
from fpl.ingest.fpl_api import ApiFixture, BootstrapStatic, ElementSummary, detect_season_skew
from fpl.ingest.live_snapshot import POSITION_BY_TYPE, capture_payload

METHOD_NOTE = (
    "Attacking Usage Percentile describes observed xG/xA relative to the same FPL position. "
    "Recent attacking usage is descriptive. In the frozen historical study, recent spikes "
    "did not improve next-match xG/xA forecasts over longer-term player history. "
    "V1 was REFUTED. This is not a future boost, tactical OOP prediction or recommendation."
)
SORT_FIELDS = (
    "recent_usage_percentile",
    "recent_xg_percentile",
    "recent_xa_percentile",
    "long_xgi90",
    "recent_xgi90",
    "delta_xgi90",
    "historical_minutes",
)
CSV_FIELDS = (
    "player_code",
    "web_name",
    "fpl_position",
    "team_code",
    "historical_minutes",
    "measured_minutes",
    "historical_starts",
    "exposure_bucket",
    "long_xg90",
    "long_xa90",
    "long_xgi90",
    "recent_window_minutes",
    "recent_xg90",
    "recent_xa90",
    "recent_xgi90",
    "long_usage_percentile",
    "recent_usage_percentile",
    "recent_xg_percentile",
    "recent_xa_percentile",
    "delta_xgi90",
    "recent_usage_bucket",
    "long_profile_status",
    "recent_profile_status",
    "as_of",
    "source_known_at",
    "available_at",
)


@dataclass(frozen=True, slots=True)
class UsageCapture:
    season: str
    capture_id: str
    known_at: datetime
    manifest_sha256: str
    raw_sources: tuple[dict[str, str], ...]
    players: tuple[RegisteredUsagePlayer, ...]
    history: tuple[UsageObservation, ...]
    fixture_provenance: tuple[dict[str, object], ...]
    completed_gameweeks: tuple[int, ...]


def _json_bytes(value: object) -> bytes:
    def default(item: object) -> str:
        if isinstance(item, datetime):
            return item.astimezone(UTC).isoformat()
        raise TypeError(f"unsupported serialization: {type(item)}")

    return (
        json.dumps(
            value,
            default=default,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _raw_capture(
    con: duckdb.DuckDBPyConnection,
    season: str,
    as_of: datetime,
) -> tuple[str, datetime, str, dict[tuple[str, str], Any], tuple[dict[str, str], ...]]:
    header = con.execute(
        """SELECT capture_id, epoch_us(captured_at), payload_count,
                  CAST(manifest AS VARCHAR), manifest_sha256
           FROM snapshot_capture
           WHERE season = ? AND mode = 'player-history' AND captured_at <= ?
           ORDER BY captured_at DESC, capture_id DESC LIMIT 1""",
        [season, as_of],
    ).fetchone()
    if header is None:
        raise ValueError("no cutoff-eligible current player-history capture")
    capture_id, epoch, count, manifest_text, manifest_sha = header
    manifest = json.loads(str(manifest_text))
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if _sha(canonical) != manifest_sha or manifest.get("schema_version") != "1":
        raise ValueError("capture manifest checksum/schema mismatch")
    entries = manifest.get("payloads")
    if not isinstance(entries, list) or len(entries) != count:
        raise ValueError("capture manifest count mismatch")
    payloads: dict[tuple[str, str], Any] = {}
    actual_entries: list[dict[str, object]] = []
    sources: list[dict[str, str]] = []
    for endpoint, parameter, body, expected_sha in con.execute(
        """SELECT endpoint, parameter, CAST(payload AS VARCHAR), sha256
           FROM snapshot_payload WHERE capture_id = ? ORDER BY endpoint, parameter""",
        [capture_id],
    ).fetchall():
        key = (str(endpoint), str(parameter))
        if key in payloads:
            raise ValueError("duplicate raw source identity")
        payload = json.loads(str(body))
        item = capture_payload(key[0], payload, parameter=key[1])
        if item.sha256 != expected_sha:
            raise ValueError("raw payload checksum mismatch")
        payloads[key] = payload
        actual_entries.append(
            {
                "endpoint": key[0],
                "parameter": key[1],
                "sha256": item.sha256,
                "byte_count": item.byte_count,
                "row_count": item.row_count,
            }
        )
        sources.append({"endpoint": key[0], "parameter": key[1], "sha256": item.sha256})

    def sort_key(entry: dict[str, Any]) -> tuple[str, str]:
        return str(entry["endpoint"]), str(entry["parameter"])

    if len(payloads) != count or sorted(entries, key=sort_key) != sorted(
        actual_entries, key=sort_key
    ):
        raise ValueError("raw capture does not reconcile with immutable manifest")
    return (
        str(capture_id),
        datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(epoch)),
        str(manifest_sha),
        payloads,
        tuple(sources),
    )


def load_usage_capture(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str,
) -> UsageCapture:
    """Read one complete capture, keeping fixture-time club and actual knowledge time."""
    cutoff = AsOf(as_of).ts.astimezone(UTC)
    if season != load_sources().current_season.season:
        raise ValueError("live scouting accepts the configured current season only")
    if cutoff > datetime.now(UTC):
        raise ValueError("a live scouting cutoff cannot be in the future")
    identity, stamp, manifest_sha, payloads, sources = _raw_capture(con, season, cutoff)
    raw_bootstrap = payloads.get(("bootstrap-static", ""))
    if not isinstance(raw_bootstrap, dict) or any(
        not isinstance(raw_bootstrap.get(field), list) or not raw_bootstrap[field]
        for field in ("elements", "teams", "events")
    ):
        raise ValueError("incomplete bootstrap identity evidence")
    bootstrap = BootstrapStatic.model_validate(raw_bootstrap)
    elements = {player.id: player for player in bootstrap.elements}
    teams = {team.id: team for team in bootstrap.teams}
    if (
        len(elements) != len(bootstrap.elements)
        or len({p.code for p in bootstrap.elements}) != len(elements)
        or len(teams) != len(bootstrap.teams)
        or any(t.code is None or t.code <= 0 for t in bootstrap.teams)
        or len({t.code for t in bootstrap.teams}) != len(teams)
    ):
        raise ValueError("ambiguous stable player/team identity")
    supported = {p.id for p in bootstrap.elements if p.element_type in POSITION_BY_TYPE}
    summaries = {parameter for endpoint, parameter in payloads if endpoint == "element-summary"}
    if summaries != {str(element) for element in supported}:
        raise ValueError("incomplete or unexpected element-summary population")
    raw_fixtures = payloads.get(("fixtures", ""))
    if not isinstance(raw_fixtures, list):
        raise ValueError("missing fixtures source")
    fixtures = [ApiFixture.model_validate(raw) for raw in raw_fixtures]
    skew = detect_season_skew(bootstrap, fixtures)
    if not skew.is_consistent:
        raise ValueError(f"incompatible season timelines: {skew.detail}")
    if skew.bootstrap_first_deadline is None or skew.bootstrap_first_deadline.year != int(
        season[:4]
    ):
        raise ValueError("bootstrap timeline does not establish the configured current season")
    by_fixture = {fixture.id: fixture for fixture in fixtures}
    if len(by_fixture) != len(fixtures):
        raise ValueError("duplicate fixture identity")
    for scheduled in fixtures:
        if (
            scheduled.team_h not in teams
            or scheduled.team_a not in teams
            or scheduled.team_h == scheduled.team_a
        ):
            raise ValueError("invalid fixture team identity")
    conflicting = {
        int(code)
        for (code,) in con.execute(
            """SELECT code FROM stg_live_player_version
               WHERE season = ? AND known_at <= ? GROUP BY code
               HAVING count(DISTINCT position) > 1 OR count(DISTINCT element) > 1""",
            [season, cutoff],
        ).fetchall()
    }
    if conflicting.intersection(p.code for p in bootstrap.elements):
        raise ValueError("contradictory season-local player identity/position history")
    conflicting_elements = {
        int(element)
        for (element,) in con.execute(
            """SELECT element FROM stg_live_player_version
               WHERE season = ? AND known_at <= ? GROUP BY element
               HAVING count(DISTINCT code) > 1""",
            [season, cutoff],
        ).fetchall()
    }
    if conflicting_elements.intersection(elements):
        raise ValueError("contradictory season-local element to stable code history")
    players: list[RegisteredUsagePlayer] = []
    history: list[UsageObservation] = []
    provenance: list[dict[str, object]] = []
    source_hashes = {(s["endpoint"], s["parameter"]): s["sha256"] for s in sources}
    for player in sorted(bootstrap.elements, key=lambda p: p.code):
        position = POSITION_BY_TYPE.get(player.element_type)
        if position is None:
            continue
        raw_summary = payloads[("element-summary", str(player.id))]
        if not isinstance(raw_summary, dict) or not isinstance(raw_summary.get("history"), list):
            raise ValueError("absent player history is not evidence of zero workload")
        for raw_history in raw_summary["history"]:
            if not isinstance(raw_history, dict) or any(
                isinstance(raw_history.get(field), bool)
                for field in ("minutes", "starts", "expected_goals", "expected_assists")
            ):
                raise ValueError("invalid raw player history numeric type")
        summary = ElementSummary.model_validate(raw_summary)
        team = teams.get(player.team)
        if team is None or team.code is None:
            raise ValueError("unresolved current player club")
        if position == "GK":
            continue
        players.append(
            RegisteredUsagePlayer(
                season, player.code, player.web_name, position, team.code, stamp, stamp, identity
            )
        )
        seen: set[int] = set()
        for row in summary.history:
            fixture = by_fixture.get(row.fixture)
            if fixture is None or fixture.kickoff_time is None:
                raise ValueError("unresolved player fixture")
            opponent = fixture.team_a if row.was_home else fixture.team_h
            club = fixture.team_h if row.was_home else fixture.team_a
            if (
                row.fixture in seen
                or row.element != player.id
                or row.opponent_team != opponent
                or row.round != fixture.event
                or row.kickoff_time != fixture.kickoff_time
            ):
                raise ValueError("duplicate or contradictory player-fixture identity")
            seen.add(row.fixture)
            kickoff = AsOf(fixture.kickoff_time).ts.astimezone(UTC)
            if (
                kickoff >= cutoff
                or kickoff >= stamp
                or not (fixture.finished or fixture.finished_provisional)
            ):
                continue
            raw_sha = source_hashes[("element-summary", str(player.id))]
            history.append(
                UsageObservation(
                    season,
                    row.round,
                    row.fixture,
                    kickoff,
                    player.code,
                    position,
                    row.minutes,
                    row.starts,
                    row.expected_goals,
                    row.expected_assists,
                    stamp,
                    stamp,
                    "CURRENT_PROSPECTIVE",
                    identity,
                    raw_sha,
                )
            )
            provenance.append(
                {
                    "player_code": player.code,
                    "fixture_id": row.fixture,
                    "gameweek": row.round,
                    "kickoff_time": kickoff,
                    "team_code": teams[club].code,
                    "opponent_team_code": teams[opponent].code,
                    "was_home": row.was_home,
                    "outcome_status": "FINAL" if fixture.finished else "PROVISIONAL",
                    "source_snapshot_id": identity,
                    "source_sha256": raw_sha,
                }
            )
    complete_gws = tuple(sorted(event.id for event in bootstrap.events if event.finished))
    return UsageCapture(
        season,
        identity,
        stamp,
        manifest_sha,
        sources,
        tuple(players),
        tuple(history),
        tuple(provenance),
        complete_gws,
    )


def coverage(
    capture: UsageCapture, snapshots: tuple[PlayerAttackingUsageSnapshot, ...]
) -> dict[str, object]:
    return {
        "completed_gameweeks": capture.completed_gameweeks,
        "observed_gameweeks": sorted({r.gameweek for r in capture.history}),
        "outfield_players": len(snapshots),
        "player_fixture_rows": len(capture.history),
        "positive_minute_rows": sum(
            r.minutes is not None and r.minutes > 0 for r in capture.history
        ),
        "measured_xg_xa_rows": sum(r.xg is not None and r.xa is not None for r in capture.history),
        "position_players": dict(Counter(r.fpl_position for r in snapshots)),
        "position_rows": dict(Counter(r.fpl_position for r in capture.history)),
        "exposure_buckets": dict(Counter(r.exposure_bucket for r in snapshots)),
        "players_by_minimum_minutes": {
            str(minimum): sum(
                r.historical_minutes is not None and r.historical_minutes >= minimum
                for r in snapshots
            )
            for minimum in (90, 180, 360, 450, 900)
        },
        "zero_history_players": sum(r.historical_minutes == 0 for r in snapshots),
        "missing_minute_players": sum(r.historical_minutes is None for r in snapshots),
    }


def build_usage_export(
    db: Path,
    output_dir: Path,
    *,
    as_of: datetime,
    position: str | None = None,
    sort: str = "recent_usage_percentile",
    minimum_minutes: int = 180,
) -> dict[str, Any]:
    """Publish an immutable directory; filters affect CSV/lists, never percentiles."""
    if (
        sort not in SORT_FIELDS
        or position not in (None, "DEF", "MID", "FWD")
        or minimum_minutes < 0
    ):
        raise ValueError("invalid descriptive export selection")
    if output_dir.exists():
        raise ValueError("export already exists; use a new immutable output directory")
    season = load_sources().current_season.season
    con = duckdb.connect(str(db), read_only=True)
    try:
        capture = load_usage_capture(con, as_of=as_of, season=season)
    finally:
        con.close()
    snapshots = build_player_attacking_usage(capture.history, capture.players, as_of)
    records = [asdict(row) for row in snapshots]
    eligible = [
        row
        for row in records
        if row["historical_minutes"] is not None
        and row["historical_minutes"] >= minimum_minutes
        and row["recent_usage_percentile"] is not None
    ]
    eligible.sort(key=lambda row: (row[sort] is None, -(row[sort] or 0), row["player_code"]))
    # The canonical watchlist uses its fixed 180-minute rule independently of CSV filters.
    watchlist = sorted(
        row["player_code"]
        for row in records
        if row["fpl_position"] == "DEF"
        and row["historical_minutes"] is not None
        and row["historical_minutes"] >= 180
        and row["recent_usage_percentile"] is not None
        and row["recent_usage_percentile"] >= 0.90
    )
    audit = coverage(capture, snapshots)
    document = {
        "schema_version": 1,
        "contract": "PlayerAttackingUsageSnapshot",
        "purpose": "DESCRIPTIVE_SCOUTING_ONLY",
        "methodology": METHOD_NOTE,
        "frozen_scientific_verdict": "C_REFUTED",
        "season": season,
        "as_of": as_of,
        "recent_window_minutes": 360,
        "shrinkage_minutes": 450,
        "percentile_method": (
            "same-position current-roster eligible observed-profile midrank; equal xG/xA composite"
        ),
        "exposure_note": (
            "Observation depth only; not predictive confidence. Zero-history players are unranked."
        ),
        "capture_id": capture.capture_id,
        "source_known_at": capture.known_at,
        "available_at": capture.known_at,
        "evidence_class": "CURRENT_PROSPECTIVE",
        "capture_manifest_sha256": capture.manifest_sha256,
        "raw_sources": capture.raw_sources,
        "fixture_provenance": capture.fixture_provenance,
        "coverage": audit,
        "players": records,
        "leaderboard_minimum_minutes": minimum_minutes,
        "leaderboards": {
            pos: [r["player_code"] for r in eligible if r["fpl_position"] == pos]
            for pos in ("DEF", "MID", "FWD")
        },
        "defender_watchlist_label": "High attacking-usage DEF",
        "defender_watchlist": watchlist,
    }
    csv_rows = [
        r
        for r in records
        if (position is None or r["fpl_position"] == position)
        and (
            minimum_minutes == 0
            or (r["historical_minutes"] is not None and r["historical_minutes"] >= minimum_minutes)
        )
    ]
    csv_rows.sort(key=lambda row: (row[sort] is None, -(row[sort] or 0), row["player_code"]))
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream, fieldnames=CSV_FIELDS, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for record in csv_rows:
        writer.writerow(
            {
                key: value.isoformat() if isinstance(value, datetime) else value
                for key, value in record.items()
            }
        )
    files = {
        "player_attacking_usage.json": _json_bytes(document),
        "player_attacking_usage.csv": stream.getvalue().encode("utf-8"),
        "README.txt": (
            METHOD_NOTE + "\n\nNULL JSON fields / empty CSV cells mean unavailable. "
            "CSV filters do not change positional percentiles. See JSON for long and recent "
            "profiles, source versions, and the complete current roster.\n"
        ).encode(),
    }
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC),
        "as_of": as_of,
        "source_capture_id": capture.capture_id,
        "source_manifest_sha256": capture.manifest_sha256,
        "files": {name: _sha(data) for name, data in files.items()},
        "implementation_sha256": {
            str(path.relative_to(Path(__file__).parents[2])): _sha(path.read_bytes())
            for path in (
                Path(__file__),
                Path(__file__).parents[1] / "features" / "player_attacking_usage.py",
                Path(__file__).parents[1] / "features" / "attacking_role_premium_v1.py",
            )
        },
        "csv_selection": {"position": position, "sort": sort, "minimum_minutes": minimum_minutes},
    }
    files["manifest.json"] = _json_bytes(manifest)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".attacking-usage-", dir=output_dir.parent))
    try:
        for name, data in files.items():
            (temporary / name).write_bytes(data)
        temporary.rename(output_dir)
    except BaseException:
        for name in files:
            (temporary / name).unlink(missing_ok=True)
        temporary.rmdir()
        raise
    return {
        "output_dir": str(output_dir),
        "coverage": audit,
        "defender_watchlist_count": len(watchlist),
        "csv_rows": len(csv_rows),
        "files": manifest["files"],
        "source_capture_id": capture.capture_id,
    }
