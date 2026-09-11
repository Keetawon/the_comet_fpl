"""Read-only source gates for the frozen GW1-3 diagnostic, never forecast inputs.

The runner must freeze every prediction before calling ``load_official_outcomes``.
``inspect_cutoff`` projects only identities, chronology and raw-source checksums.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Any

import duckdb

from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.ingest.fpl_api import ApiFixture, BootstrapStatic, ElementSummary, detect_season_skew
from fpl.ingest.live_snapshot import POSITION_BY_TYPE, capture_payload
from fpl.jobs.prospective_points_v1 import live_bootstrap_snapshot
from fpl.validate.freshness import assess_prospective_freshness

_COMPONENTS = (
    "minutes",
    "starts",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "defensive_contribution",
    "bonus",
    "bps",
)


def _stamp(epoch: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=epoch)


def _capture_provenance(con: duckdb.DuckDBPyConnection, capture_id: str) -> dict[str, Any]:
    """Verify raw bytes in SQL; expose metadata, never player outcome values."""
    headers = con.execute(
        """SELECT season, mode, epoch_us(captured_at), payload_count,
                  CAST(manifest AS VARCHAR), manifest_sha256
           FROM snapshot_capture WHERE capture_id = ?""",
        [capture_id],
    ).fetchall()
    if len(headers) != 1:
        raise ValueError("capture identity is missing or ambiguous")
    season, mode, epoch, count, manifest_text, manifest_sha = headers[0]
    manifest = json.loads(str(manifest_text))
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canonical).hexdigest() != manifest_sha:
        raise ValueError("capture manifest checksum mismatch")
    if manifest.get("schema_version") != "1" or not isinstance(manifest.get("payloads"), list):
        raise ValueError("capture manifest schema mismatch")
    entries = []
    for endpoint, parameter, sha, size, rows, actual_sha, actual_size in con.execute(
        """SELECT endpoint, parameter, sha256, byte_count, row_count,
                  sha256(CAST(payload AS VARCHAR)),
                  octet_length(encode(CAST(payload AS VARCHAR)))
           FROM snapshot_payload WHERE capture_id = ? ORDER BY endpoint, parameter""",
        [capture_id],
    ).fetchall():
        if sha != actual_sha or size != actual_size:
            raise ValueError("raw payload checksum/length mismatch")
        entries.append(
            {
                "endpoint": endpoint,
                "parameter": parameter,
                "sha256": sha,
                "byte_count": size,
                "row_count": rows,
            }
        )

    def key(item: dict[str, Any]) -> tuple[str, str]:
        return str(item["endpoint"]), str(item["parameter"])

    if (
        len(entries) != count
        or len({key(item) for item in entries}) != count
        or sorted(manifest["payloads"], key=key) != entries
    ):
        raise ValueError("raw capture does not reconcile with immutable manifest")
    return {
        "capture_id": capture_id,
        "season": season,
        "mode": mode,
        "known_at": _stamp(int(epoch)).isoformat(),
        "payload_count": count,
        "manifest_sha256": manifest_sha,
        "raw_sources": entries,
    }


def _promoted_teams(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    cutoff: datetime,
    current_team_codes: set[int],
) -> tuple[list[int] | None, dict[str, Any] | None]:
    """Reporting-only club membership; missing prior league evidence is unknown."""
    year = int(season[:4])
    previous = f"{year - 1}-{str(year)[2:]}"
    previous_codes = con.execute(
        "SELECT team_code FROM mart_dim_team WHERE season = ? ORDER BY team_code", [previous]
    ).fetchall()
    codes = [row[0] for row in previous_codes]
    # A partial club dimension cannot prove that an absent club was promoted.
    if (
        len(codes) != 20
        or len(set(codes)) != 20
        or any(type(code) is not int or code <= 0 for code in codes)
    ):
        return None, None
    logs = con.execute(
        """SELECT sha256, min(epoch_us(ingested_at)), max(epoch_us(ingested_at)),
                  min(row_count), max(row_count)
           FROM raw_ingest_log WHERE season = ? AND source_table = 'raw_teams'
           GROUP BY sha256""",
        [previous],
    ).fetchall()
    if len(logs) != 1:
        return None, None
    sha, first, last, minimum, maximum = logs[0]
    if minimum != 20 or maximum != 20 or _stamp(int(last)) > cutoff:
        return None, None
    return sorted(current_team_codes - set(codes)), {
        "season": previous,
        "source_table": "raw_teams",
        "source_sha256": sha,
        "first_ingested_at": _stamp(int(first)).isoformat(),
        "last_ingested_at": _stamp(int(last)).isoformat(),
        "club_count": len(codes),
        "identity": "stable team_code membership in the complete prior PL season",
    }


def inspect_cutoff(
    con: duckdb.DuckDBPyConnection, *, season: str, gw: int, cutoff: datetime
) -> dict[str, Any]:
    """Inspect the actual production PIT population without outcomes or inference."""
    cutoff = AsOf(cutoff).ts.astimezone(UTC)
    view = PointInTimeView(FeatureSource(con), AsOf(cutoff))
    registry = view.player_registry(columns=["code", "season", "capture_id", "position"])
    if registry.is_empty() or set(registry["season"]) != {season}:
        raise ValueError("missing or incompatible cutoff registry")
    snapshot = live_bootstrap_snapshot(con, season, cutoff)
    bootstrap = BootstrapStatic.model_validate(snapshot.data)
    events = bootstrap.events
    deadlines = [event.deadline_time for event in events if event.id == gw]
    if deadlines != [cutoff]:
        raise ValueError("cutoff is not the uniquely witnessed official gameweek deadline")
    schedule = view.schedule(seasons=[season])
    fixture_gameweeks: dict[int, int] = {}
    targets: set[int] = set()
    for row in schedule.iter_rows(named=True):
        fixture, gameweek = int(row["fixture"]), row["gw"]
        if gameweek is None:
            continue
        if fixture in fixture_gameweeks and fixture_gameweeks[fixture] != gameweek:
            raise ValueError("contradictory fixture gameweek identity")
        fixture_gameweeks[fixture] = int(gameweek)
        if gameweek == gw:
            if row["kickoff_time"] is None or row["kickoff_time"] <= cutoff:
                raise ValueError("every target fixture must be strictly future")
            targets.add(fixture)
    if not targets:
        raise ValueError("target gameweek has no fixtures")
    history = view.observed_player_fixtures(
        seasons=[season], columns=["season", "code", "fixture", "gw", "kickoff_time"]
    )
    if any(
        row["gw"] is None or row["gw"] >= gw or row["fixture"] in targets
        for row in history.iter_rows(named=True)
    ):
        raise ValueError("same/later gameweek history cannot enter the target batch")
    history_versions = con.execute(
        """SELECT DISTINCT capture_id FROM (
               SELECT capture_id, kickoff_time,
                      row_number() OVER (PARTITION BY season, code, fixture
                         ORDER BY known_at DESC, capture_id DESC) n
               FROM stg_live_player_fixture_version WHERE season = ? AND known_at <= ?
           ) WHERE n = 1 AND kickoff_time < ? ORDER BY capture_id""",
        [season, cutoff, cutoff],
    ).fetchall()
    schedule_versions = con.execute(
        """SELECT DISTINCT capture_id FROM (
               SELECT capture_id, row_number() OVER (PARTITION BY season, fixture
                   ORDER BY known_at DESC, capture_id DESC) n
               FROM stg_live_fixture_version WHERE season = ? AND known_at <= ?
           ) WHERE n = 1 ORDER BY capture_id""",
        [season, cutoff],
    ).fetchall()
    capture_ids = sorted(
        set(registry["capture_id"])
        | {snapshot.capture_id}
        | {row[0] for row in history_versions + schedule_versions}
    )
    sources = [_capture_provenance(con, identity) for identity in capture_ids]
    if any(
        source["season"] != season or datetime.fromisoformat(source["known_at"]) > cutoff
        for source in sources
    ):
        raise ValueError("selected raw source is not cutoff eligible")
    freshness = assess_prospective_freshness(con, as_of=cutoff)
    if not freshness.covered:
        raise ValueError("incumbent prerequisite history is unavailable")
    current_codes = {team.code for team in bootstrap.teams if team.code is not None}
    if len(current_codes) != len(bootstrap.teams) or any(code <= 0 for code in current_codes):
        raise ValueError("ambiguous current stable team identity")
    promoted, promoted_provenance = _promoted_teams(
        con, season=season, cutoff=cutoff, current_team_codes=current_codes
    )
    return {
        "season": season,
        "gw": gw,
        "cutoff": cutoff.isoformat(),
        "registry_count": registry.height,
        "registry_capture_ids": sorted(set(registry["capture_id"])),
        "bootstrap_capture_id": snapshot.capture_id,
        "bootstrap_known_at": snapshot.known_at.astimezone(UTC).isoformat(),
        "bootstrap_sha256": snapshot.payload_sha256,
        "fixture_gameweeks": dict(sorted(fixture_gameweeks.items())),
        "target_fixture_ids": sorted(targets),
        "target_fixture_count": len(targets),
        "history_rows": history.height,
        "history_capture_ids": [row[0] for row in history_versions],
        "history_eligible": True,
        "promoted_team_codes": promoted,
        "promoted_team_provenance": promoted_provenance,
        "freshness": asdict(freshness),
        "sources": sources,
    }


def _integer(value: Any, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid official numeric field: {name}")
    if name not in {"total_points", "bps"} and value < 0:
        raise ValueError(f"negative official count: {name}")
    bounds = {"minutes": 120, "starts": 1, "clean_sheets": 1, "bonus": 3}
    if name in bounds and value > bounds[name]:
        raise ValueError(f"impossible official count: {name}")
    return value


def load_official_outcomes(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    capture_id: str,
    gameweeks: Sequence[int],
) -> list[dict[str, Any]]:
    """Load finalized fixture-grain labels ONLY after the runner freezes forecasts.

    A complete summary capture does not imply a row for every registered player in
    every fixture. Missing labels remain absent; callers must never invent DNPs.
    """
    if not gameweeks or len(set(gameweeks)) != len(gameweeks) or any(gw < 1 for gw in gameweeks):
        raise ValueError("outcome gameweek scope must be nonempty, positive and unique")
    provenance = _capture_provenance(con, capture_id)
    if provenance["season"] != season or provenance["mode"] != "player-history":
        raise ValueError("outcome capture season/mode mismatch")
    known_at = datetime.fromisoformat(provenance["known_at"])
    payloads: dict[tuple[str, str], Any] = {}
    hashes = {
        (item["endpoint"], item["parameter"]): item["sha256"] for item in provenance["raw_sources"]
    }
    for endpoint, parameter, body in con.execute(
        "SELECT endpoint, parameter, CAST(payload AS VARCHAR) FROM snapshot_payload "
        "WHERE capture_id = ? ORDER BY endpoint, parameter",
        [capture_id],
    ).fetchall():
        value = json.loads(str(body))
        if (
            capture_payload(endpoint, value, parameter=parameter).sha256
            != hashes[(endpoint, parameter)]
        ):
            raise ValueError("raw canonical checksum mismatch")
        payloads[(endpoint, parameter)] = value
    raw_bootstrap = payloads.get(("bootstrap-static", ""))
    if not isinstance(raw_bootstrap, dict) or any(
        not raw_bootstrap.get(key) for key in ("elements", "teams", "events")
    ):
        raise ValueError("missing bootstrap identity evidence")
    bootstrap = BootstrapStatic.model_validate(raw_bootstrap)
    elements = {item.id: item for item in bootstrap.elements}
    teams = {item.id: item for item in bootstrap.teams}
    if (
        len(elements) != len(bootstrap.elements)
        or len({p.code for p in elements.values()}) != len(elements)
        or any(p.id <= 0 or p.code <= 0 for p in elements.values())
        or len(teams) != len(bootstrap.teams)
        or any(t.id <= 0 or t.code is None or t.code <= 0 for t in teams.values())
        or len({t.code for t in teams.values()}) != len(teams)
    ):
        raise ValueError("ambiguous stable player/team identity")
    supported = {p.id for p in elements.values() if p.element_type in POSITION_BY_TYPE}
    if {parameter for endpoint, parameter in payloads if endpoint == "element-summary"} != {
        str(element) for element in supported
    }:
        raise ValueError("incomplete or unexpected element-summary population")
    events = {event.id: event for event in bootstrap.events}
    if len(events) != len(bootstrap.events) or any(
        gw not in events or not events[gw].finished for gw in gameweeks
    ):
        raise ValueError("official gameweek is not finalized")
    raw_fixtures = payloads.get(("fixtures", ""))
    if not isinstance(raw_fixtures, list):
        raise ValueError("missing fixtures source")
    for raw_fixture in raw_fixtures:
        if not isinstance(raw_fixture, dict):
            raise ValueError("malformed official fixture")
        for field in ("team_h_score", "team_a_score"):
            _integer(raw_fixture.get(field), field)
    fixtures = [ApiFixture.model_validate(raw) for raw in raw_fixtures]
    skew = detect_season_skew(bootstrap, fixtures)
    if (
        not skew.is_consistent
        or skew.bootstrap_first_deadline is None
        or skew.bootstrap_first_deadline.year != int(season[:4])
    ):
        raise ValueError("incompatible source season timelines")
    by_fixture = {fixture.id: fixture for fixture in fixtures}
    if len(by_fixture) != len(fixtures):
        raise ValueError("duplicate fixture identity")
    for scheduled in fixtures:
        if (
            scheduled.team_h not in teams
            or scheduled.team_a not in teams
            or scheduled.team_h == scheduled.team_a
        ):
            raise ValueError("invalid fixture club identity")
        if scheduled.event in gameweeks and (
            not scheduled.finished
            or scheduled.kickoff_time is None
            or AsOf(scheduled.kickoff_time).ts >= known_at
        ):
            raise ValueError("official fixture is not finalized before capture")
    if any(not any(f.event == gw for f in fixtures) for gw in gameweeks):
        raise ValueError("gameweek fixture population unavailable")
    contradictions = con.execute(
        """SELECT count(*) FROM (
               SELECT code FROM stg_live_player_version WHERE season = ? AND known_at <= ?
               GROUP BY code HAVING count(DISTINCT position) > 1 OR count(DISTINCT element) > 1
               UNION ALL SELECT element FROM stg_live_player_version
               WHERE season = ? AND known_at <= ?
               GROUP BY element HAVING count(DISTINCT code) > 1
           )""",
        [season, known_at, season, known_at],
    ).fetchone()
    if contradictions and contradictions[0]:
        raise ValueError("contradictory season-local player identity/position")
    result: list[dict[str, Any]] = []
    for element in sorted(supported):
        player = elements[element]
        raw_summary = payloads[("element-summary", str(element))]
        if not isinstance(raw_summary, dict) or not isinstance(raw_summary.get("history"), list):
            raise ValueError("missing player history is not an empty history")
        summary = ElementSummary.model_validate(raw_summary)
        seen: set[int] = set()
        for raw, row in zip(raw_summary["history"], summary.history, strict=True):
            fixture = by_fixture.get(row.fixture)
            if fixture is None or row.fixture in seen or row.element != element:
                raise ValueError("duplicate or unresolved player-fixture identity")
            seen.add(row.fixture)
            opponent = fixture.team_a if row.was_home else fixture.team_h
            team = fixture.team_h if row.was_home else fixture.team_a
            if (
                row.round != fixture.event
                or row.opponent_team != opponent
                or row.kickoff_time != fixture.kickoff_time
                or not isinstance(raw.get("was_home"), bool)
            ):
                raise ValueError("contradictory fixture-time player identity")
            if row.round not in gameweeks:
                continue
            data = {name: _integer(raw.get(name), name) for name in _COMPONENTS}
            result.append(
                {
                    "season": season,
                    "gw": row.round,
                    "fixture": row.fixture,
                    "code": player.code,
                    "position": POSITION_BY_TYPE[player.element_type],
                    "team_code": teams[team].code,
                    "opponent_team_code": teams[opponent].code,
                    "was_home": row.was_home,
                    "kickoff_time": row.kickoff_time.astimezone(UTC).isoformat(),
                    "total_points_as_recorded": _integer(raw.get("total_points"), "total_points"),
                    **data,
                    "team_goals_scored": _integer(
                        fixture.team_h_score if row.was_home else fixture.team_a_score,
                        "team_goals_scored",
                    ),
                    "team_goals_conceded": _integer(
                        fixture.team_a_score if row.was_home else fixture.team_h_score,
                        "team_goals_conceded",
                    ),
                    "source_provenance": {
                        "capture_id": capture_id,
                        "known_at": provenance["known_at"],
                        "manifest_sha256": provenance["manifest_sha256"],
                        "summary_sha256": hashes[("element-summary", str(element))],
                        "bootstrap_sha256": hashes[("bootstrap-static", "")],
                        "fixtures_sha256": hashes[("fixtures", "")],
                    },
                }
            )
    return sorted(result, key=lambda row: (row["gw"], row["fixture"], row["code"]))
