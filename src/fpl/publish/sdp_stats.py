"""Observed SDP dashboard sidecar; no predictions, source writes or inferred player stats."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from fpl.config import SdpMetric, load_sdp_metrics, load_sources
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.ingest.fpl_api import ApiFixture, BootstrapStatic, ElementSummary, detect_season_skew
from fpl.ingest.live_snapshot import POSITION_BY_TYPE
from fpl.ingest.pl_sdp import parse_team_stats
from fpl.jobs.competitive_participation_pilot import publish_bytes
from fpl.publish.player_attacking_usage import _raw_capture
from fpl.storage.sdp_runtime import load_sdp_state, raw_at, workload_at

SCHEMA = "fpl.sdp-stats"
FPL_FIELDS = (
    "minutes",
    "starts",
    "total_points_as_recorded",
    "expected_goals",
    "expected_assists",
    "goals_scored",
    "assists",
    "saves",
    "defensive_contribution",
    "bonus",
    "bps",
    "yellow_cards",
    "red_cards",
    "clean_sheets",
    "goals_conceded",
    "expected_goals_conceded",
)
TEAM_FPL_FIELDS = ("goals_scored", "goals_conceded")
OPPONENT_METRICS = {"shots_allowed": "shots", "expected_goals_allowed": "expected_goals"}
COMMON = {
    "season",
    "gw",
    "fixture",
    "kickoff_time",
    "team_code",
    "team_name",
    "team_short_name",
    "opponent_team_code",
    "opponent_name",
    "opponent_short_name",
    "was_home",
    "status",
    "known_at",
    "provider_match_id",
    "source_version",
}
PLAYER_FIELDS = {
    "code",
    "provider_player_id",
    "web_name",
    "position",
    "provider_position",
    "provider_sub_position",
    "started",
    "bench",
    "appeared",
    "minutes_sdp",
    "nominal_minutes_sdp",
    "minutes_fpl",
    "sdp",
    "fpl",
}
STATUS_FIELDS = {
    "team_stats",
    "player_stats",
    "player_lineups",
    "fpl_enrichment",
    "latest_sdp_known_at",
    "latest_fpl_known_at",
    "latest_completed_kickoff",
    "notes",
}
COVERAGE_FIELDS = {
    "team_matches",
    "player_matches",
    "sdp_lineup_player_matches",
    "fpl_player_matches",
    "team_failures",
    "unmapped_players",
    "seasons",
}


def _iso(value: datetime) -> str:
    return AsOf(value).ts.astimezone(UTC).isoformat()


def _version(*values: str | None) -> str:
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _number(value: Any, *, integer: bool = False, signed: bool = False) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or (not signed and result < 0):
        return None
    if integer and not result.is_integer():
        return None
    return int(result) if integer else result


def metric_value(stats: dict[str, Any], metric: SdpMetric) -> float | int | None:
    """Ambiguous aliases and invalid optional values stay unavailable."""
    raw = [stats[field] for field in metric.provider_fields if field in stats]
    if not raw:
        return None
    values = [_number(value, integer=metric.type == "int") for value in raw]
    if any(value is None for value in values) or len(set(values)) != 1:
        return None
    result = values[0]
    if metric.type == "percent" and result is not None and result > 100:
        return None
    return result


def metric_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for metric in load_sdp_metrics().metrics:
        catalog.append(
            {
                "key": metric.local_field,
                "label": metric.local_field.replace("_", " ").capitalize(),
                "group": metric.group,
                "source": "sdp",
                "scope": "team",
                "unit": "percent"
                if metric.type == "percent"
                else ("xg" if metric.local_field.startswith("expected_") else "count"),
                "aggregation": "mean" if metric.type == "percent" else "sum",
                "per90_denominator": None,
                "verified_semantics": metric.verified_semantics,
                "description": metric.description
                if metric.verified_semantics
                else ("Provider observation; not independently reconciled. " + metric.description),
                "provider_field": " | ".join(metric.provider_fields),
            }
        )
    for key, original in OPPONENT_METRICS.items():
        source = next(m for m in catalog if m["key"] == original)
        catalog.append(
            {
                **source,
                "key": key,
                "label": key.replace("_", " ").capitalize(),
                "group": "defence",
                "description": "Exact opponent observed value in the same fixture.",
                "provider_field": "opponent: " + source["provider_field"],
            }
        )
    for field in TEAM_FPL_FIELDS:
        catalog.append(
            {
                "key": field,
                "label": field.replace("_", " ").capitalize(),
                "group": "score",
                "source": "fpl",
                "scope": "team",
                "unit": "count",
                "aggregation": "sum",
                "per90_denominator": None,
                "verified_semantics": True,
                "description": "Official FPL fixture score for this exact home/away side.",
                "provider_field": "team_h_score / team_a_score",
            }
        )
    groups = {
        "minutes": "exposure",
        "starts": "exposure",
        "total_points_as_recorded": "FPL points",
        "expected_goals": "attack",
        "goals_scored": "attack",
        "expected_assists": "creation",
        "assists": "creation",
        "saves": "GK",
        "defensive_contribution": "defence",
        "clean_sheets": "defence",
        "goals_conceded": "defence",
        "expected_goals_conceded": "defence",
        "yellow_cards": "discipline",
        "red_cards": "discipline",
        "bonus": "FPL points",
        "bps": "FPL points",
    }
    for field in FPL_FIELDS:
        catalog.append(
            {
                "key": field,
                "label": field.replace("_", " ").capitalize(),
                "group": groups[field],
                "source": "fpl",
                "scope": "player",
                "unit": "xg" if field.startswith("expected_") else "count",
                "aggregation": "sum",
                "per90_denominator": None if field in {"minutes", "starts"} else "minutes_fpl",
                "verified_semantics": True,
                "description": "Observed FPL element-summary value, separate from SDP.",
                "provider_field": "total_points" if field == "total_points_as_recorded" else field,
            }
        )
    return catalog


def _base(
    *,
    season: str,
    gw: int,
    fixture: int,
    kickoff: datetime,
    team_code: int,
    opponent_code: int,
    was_home: bool,
    known_at: datetime,
    names: dict[tuple[str, int], tuple[str, str]],
    status: str = "FINAL",
) -> dict[str, Any]:
    team_name, short = names.get((season, team_code), (str(team_code), str(team_code)))
    opponent_name, opponent_short = names.get(
        (season, opponent_code), (str(opponent_code), str(opponent_code))
    )
    return {
        "season": season,
        "gw": gw,
        "fixture": fixture,
        "kickoff_time": _iso(kickoff),
        "team_code": team_code,
        "team_name": team_name,
        "team_short_name": short,
        "opponent_team_code": opponent_code,
        "opponent_name": opponent_name,
        "opponent_short_name": opponent_short,
        "was_home": was_home,
        "status": status,
        "known_at": _iso(known_at),
        "provider_match_id": None,
        "source_version": None,
    }


def _empty_player(base: dict[str, Any]) -> dict[str, Any]:
    return {
        **base,
        "code": None,
        "provider_player_id": None,
        "web_name": "Unknown",
        "position": None,
        "provider_position": None,
        "provider_sub_position": None,
        "started": None,
        "bench": None,
        "appeared": None,
        "minutes_sdp": None,
        "nominal_minutes_sdp": None,
        "minutes_fpl": None,
        "sdp": {},
        "fpl": dict.fromkeys(FPL_FIELDS),
    }


def _fpl_rows(
    con: duckdb.DuckDBPyConnection,
    season: str,
    cutoff: datetime,
    names: dict[tuple[str, int], tuple[str, str]],
    *,
    metadata_out: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], datetime, list[dict[str, Any]]]:
    _, stamp, manifest_sha, payloads, sources = _raw_capture(con, season, cutoff)
    raw_bootstrap = payloads.get(("bootstrap-static", ""))
    if not isinstance(raw_bootstrap, dict) or any(
        not isinstance(raw_bootstrap.get(key), list) or not raw_bootstrap[key]
        for key in ("teams", "events", "elements")
    ):
        raise ValueError("incomplete FPL bootstrap")
    bootstrap = BootstrapStatic.model_validate(raw_bootstrap)
    teams = {team.id: team for team in bootstrap.teams}
    players = {player.id: player for player in bootstrap.elements}
    if (
        len(teams) != len(bootstrap.teams)
        or len(players) != len(bootstrap.elements)
        or len({p.code for p in players.values()}) != len(players)
        or len({t.code for t in teams.values()}) != len(teams)
        or any(t.code is None or t.code <= 0 for t in teams.values())
    ):
        raise ValueError("ambiguous FPL identity")
    supported = {p.id for p in players.values() if p.element_type in POSITION_BY_TYPE}
    raw_fixtures = payloads.get(("fixtures", ""))
    if not isinstance(raw_fixtures, list):
        raise ValueError("missing FPL fixture evidence")
    fixtures = [ApiFixture.model_validate(raw) for raw in raw_fixtures]
    skew = detect_season_skew(bootstrap, fixtures)
    if (
        not skew.is_consistent
        or skew.bootstrap_first_deadline is None
        or (skew.bootstrap_first_deadline.year != int(season[:4]))
    ):
        raise ValueError("FPL season mismatch")
    by_fixture = {fixture.id: fixture for fixture in fixtures}
    if len(by_fixture) != len(fixtures):
        raise ValueError("duplicate FPL fixture")
    for team in teams.values():
        assert team.code is not None
        names[season, team.code] = team.name, team.short_name
    fixture_rows: dict[int, dict[str, Any]] = {}
    raw_by_fixture = {raw["id"]: raw for raw in raw_fixtures}
    for scheduled in fixtures:
        if (
            scheduled.team_h == scheduled.team_a
            or scheduled.team_h not in teams
            or scheduled.team_a not in teams
        ):
            raise ValueError("invalid FPL scheduled sides")
        if (
            scheduled.kickoff_time is None
            or scheduled.kickoff_time >= min(stamp, cutoff)
            or not (scheduled.finished or scheduled.finished_provisional)
        ):
            continue
        if scheduled.event is None:
            raise ValueError("completed scheduled lacks GW")
        fixture_rows[scheduled.id] = {
            "gw": scheduled.event,
            "kickoff": scheduled.kickoff_time,
            "home": teams[scheduled.team_h].code,
            "away": teams[scheduled.team_a].code,
            "status": "FINAL" if scheduled.finished else "PROVISIONAL",
            "home_score": _number(raw_by_fixture[scheduled.id].get("team_h_score"), integer=True),
            "away_score": _number(raw_by_fixture[scheduled.id].get("team_a_score"), integer=True),
            "source_version": manifest_sha,
            "known_at": stamp,
        }
    gameweeks = [
        {
            "season": season,
            "gw": event.id,
            "finished": event.finished,
            "fixtures_total": sum(f.event == event.id for f in fixtures),
            "fixtures_completed": sum(
                f.event == event.id and f.id in fixture_rows for f in fixtures
            ),
            "source_known_at": _iso(stamp),
        }
        for event in sorted(bootstrap.events, key=lambda e: e.id)
    ]
    if metadata_out is not None:
        # Verified fixture evidence survives an optional player-summary failure.
        metadata_out.update(fixtures=fixture_rows, known_at=stamp, gameweeks=gameweeks)
    if {p for e, p in payloads if e == "element-summary"} != {str(p) for p in supported}:
        raise ValueError("incomplete FPL history population")
    conflicts = con.execute(
        """SELECT count(*) FROM (
        SELECT code FROM stg_live_player_version WHERE season=? AND known_at<=?
        GROUP BY code HAVING count(DISTINCT position)>1 OR count(DISTINCT element)>1
        UNION ALL SELECT element FROM stg_live_player_version WHERE season=? AND known_at<=?
        GROUP BY element HAVING count(DISTINCT code)>1)""",
        [season, stamp, season, stamp],
    ).fetchone()
    if conflicts is not None and conflicts[0]:
        raise ValueError("contradictory season-local player mapping")
    hashes = {(s["endpoint"], s["parameter"]): s["sha256"] for s in sources}
    result: list[dict[str, Any]] = []
    for element in sorted(supported):
        player = players[element]
        raw_summary = payloads["element-summary", str(element)]
        if not isinstance(raw_summary, dict) or not isinstance(raw_summary.get("history"), list):
            raise ValueError("missing history is not zero appearances")
        summary = ElementSummary.model_validate(raw_summary)
        seen: set[int] = set()
        for raw, observation in zip(raw_summary["history"], summary.history, strict=True):
            fixture = by_fixture.get(observation.fixture)
            if fixture is None or observation.fixture in seen or observation.element != element:
                raise ValueError("duplicate or unresolved player-fixture")
            seen.add(observation.fixture)
            if (
                observation.round != fixture.event
                or observation.kickoff_time != fixture.kickoff_time
                or observation.opponent_team
                != (fixture.team_a if observation.was_home else fixture.team_h)
                or not isinstance(raw.get("was_home"), bool)
            ):
                raise ValueError("contradictory fixture-time player identity")
            if fixture.id not in fixture_rows:
                continue
            side = fixture_rows[fixture.id]
            row = _empty_player(
                _base(
                    season=season,
                    gw=side["gw"],
                    fixture=fixture.id,
                    kickoff=side["kickoff"],
                    team_code=side["home"] if observation.was_home else side["away"],
                    opponent_code=side["away"] if observation.was_home else side["home"],
                    was_home=observation.was_home,
                    known_at=stamp,
                    names=names,
                    status=side["status"],
                )
            )
            metrics = {
                field: _number(
                    raw.get("total_points" if field == "total_points_as_recorded" else field),
                    integer=not field.startswith("expected_"),
                    signed=field in {"total_points_as_recorded", "bps"},
                )
                for field in FPL_FIELDS
            }
            if metrics["minutes"] is not None and metrics["minutes"] > 120:
                metrics["minutes"] = None
            if metrics["starts"] not in (0, 1, None):
                metrics["starts"] = None
            row.update(
                code=player.code,
                web_name=player.web_name,
                position=POSITION_BY_TYPE[player.element_type],
                minutes_fpl=metrics["minutes"],
                fpl=metrics,
                source_version=_version(manifest_sha, hashes["element-summary", str(element)]),
            )
            result.append(row)
    return result, fixture_rows, stamp, gameweeks


def _add_lineups(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict[str, Any]],
    fixtures: dict[int, dict[str, Any]],
    *,
    season: str,
    cutoff: datetime,
    names: dict[tuple[str, int], tuple[str, str]],
) -> tuple[int, int]:
    crosswalk = {
        int(match): (int(fixture), datetime.fromisoformat(known))
        for match, fixture, known in con.execute(
            """SELECT sdp_match_id,fixture,CAST(resolved_at AS VARCHAR)
            FROM stg_pl_sdp_fixture_crosswalk
            WHERE season=? AND resolved_at<=? AND corroborated_kickoff AND corroborated_teams""",
            [season, cutoff],
        ).fetchall()
    }
    by_code = {(row["fixture"], row["code"]): row for row in rows}
    count = failures = 0
    for record in workload_at(con, cutoff):
        if record["season"] != season or record["competition"] != 8:
            continue
        mapped = crosswalk.get(record["provider_match_id"])
        if not record["valid"] or mapped is None or mapped[0] not in fixtures:
            failures += 1
            continue
        fixture, identity_known = mapped
        source = fixtures[fixture]
        stamp = max(datetime.fromisoformat(record["known_at"]), identity_known, source["known_at"])
        if stamp > cutoff or datetime.fromisoformat(record["kickoff_time"]) != source["kickoff"]:
            failures += 1
            continue
        pending: list[dict[str, Any]] = []
        seen: set[int] = set()
        seen_codes: set[int] = set()
        invalid = False
        for observed in record["rows"]:
            provider_id = observed["provider_player_id"]
            club = observed.get("team_code")
            code = observed.get("code")
            if provider_id in seen or club not in {source["home"], source["away"]}:
                invalid = True
                break
            seen.add(provider_id)
            if observed.get("identity_errors"):
                code = None
            if code is not None:
                if code in seen_codes:
                    invalid = True
                    break
                seen_codes.add(code)
            existing = by_code.get((fixture, code)) if code is not None else None
            if existing is not None and existing["team_code"] != club:
                invalid = True
                break
            row = (
                dict(existing)
                if existing
                else _empty_player(
                    _base(
                        season=season,
                        gw=source["gw"],
                        fixture=fixture,
                        kickoff=source["kickoff"],
                        team_code=club,
                        opponent_code=source["away"] if club == source["home"] else source["home"],
                        was_home=club == source["home"],
                        known_at=stamp,
                        names=names,
                        status=source["status"],
                    )
                )
            )
            raw_player = observed.get("raw_player", {})
            row.update(
                code=code,
                provider_player_id=provider_id,
                provider_match_id=record["provider_match_id"],
                provider_position=observed.get("provider_position"),
                provider_sub_position=raw_player.get("subPosition"),
                started=observed.get("started"),
                bench=observed.get("on_bench"),
                appeared=observed.get("appeared"),
                nominal_minutes_sdp=_number(observed.get("nominal_minutes")),
                known_at=_iso(max(stamp, datetime.fromisoformat(row["known_at"]))),
            )
            # Bind both public source versions without exposing internal payload/capture identities.
            row["source_version"] = _version(
                row["source_version"], record["version_id"], source["source_version"]
            )
            if existing is None:
                row["web_name"] = (
                    raw_player.get("knownName")
                    or " ".join(
                        str(raw_player.get(k, "")) for k in ("firstName", "lastName")
                    ).strip()
                    or "Unknown"
                )
            pending.append(row)
        if invalid:
            failures += 1
            continue
        for row in pending:
            key = (fixture, row["code"])
            existing = by_code.get(key) if row["code"] is not None else None
            if existing is None:
                rows.append(row)
            else:
                existing.update(row)
            count += 1
    return count, failures


def build_sdp_stats(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: datetime,
    season: str | None = None,
) -> dict[str, Any]:
    """Read cutoff-eligible observed sources; an invalid source remains visibly unavailable."""
    cutoff = AsOf(as_of).ts.astimezone(UTC)
    if cutoff > datetime.now(UTC):
        raise ValueError("descriptive export cutoff cannot be in the future")
    current = season or load_sources().current_season.season
    names = {
        (str(s), int(code)): (str(name), str(short))
        for s, code, name, short in con.execute(
            "SELECT season,team_code,team_name,short_name FROM mart_dim_team "
            "WHERE team_code IS NOT NULL"
        ).fetchall()
    }
    notes = [
        "Observed match statistics only. No predictions or player-role inference.",
        "Detailed SDP player statistics are not present in retained captures; "
        "FPL enrichment is labelled separately.",
        "SDP nominal participation intervals are not elapsed or FPL minutes "
        "and cannot be used for per90 rates.",
        "FINAL denotes an ended fixture; provider statistics and recorded FPL points "
        "may still be revised.",
    ]
    players: list[dict[str, Any]] = []
    fixtures: dict[int, dict[str, Any]] = {}
    gameweeks: list[dict[str, Any]] = []
    fpl_stamp: datetime | None = None
    frame: dict[str, Any] = {}
    try:
        players, fixtures, fpl_stamp, gameweeks = _fpl_rows(
            con, current, cutoff, names, metadata_out=frame
        )
    except (ValueError, KeyError, TypeError, duckdb.Error):
        notes.append(
            "Latest eligible FPL history failed completeness/identity validation; "
            "FPL enrichment is unavailable."
        )
    if frame:
        fixtures = frame["fixtures"]
        gameweeks = frame["gameweeks"]
    fixture_stamp = frame.get("known_at")
    state = load_sdp_state(con, cutoff=cutoff, season=current)
    raw = raw_at(con, cutoff)
    raw_by_id = {r["payload_id"]: r for r in raw}
    metrics = load_sdp_metrics().metrics
    team_keys = [m.local_field for m in metrics] + list(OPPONENT_METRICS)
    teams: dict[tuple[str, int, int], dict[str, Any]] = {}
    view = PointInTimeView(FeatureSource(con), AsOf(cutoff))
    metadata = view.observed_team_football(
        providers=["pl_sdp", "fpl_archive"],
        columns=[
            "season",
            "gw",
            "fixture",
            "kickoff_time",
            "team_code",
            "opponent_team_code",
            "was_home",
            "known_at",
        ],
    ).to_dicts()
    for row in metadata:
        if row["team_code"] is None or row["opponent_team_code"] is None or row["gw"] is None:
            continue
        key = (row["season"], row["fixture"], row["team_code"])
        teams[key] = {
            **_base(
                season=row["season"],
                gw=row["gw"],
                fixture=row["fixture"],
                kickoff=row["kickoff_time"],
                team_code=row["team_code"],
                opponent_code=row["opponent_team_code"],
                was_home=row["was_home"],
                known_at=row["known_at"],
                names=names,
                status="UNAVAILABLE",
            ),
            "sdp": dict.fromkeys(team_keys),
            "fpl": dict.fromkeys(TEAM_FPL_FIELDS),
        }
    for fixture, row in fixtures.items():
        for home in (True, False):
            code = row["home"] if home else row["away"]
            teams[current, fixture, code] = {
                **_base(
                    season=current,
                    gw=row["gw"],
                    fixture=fixture,
                    kickoff=row["kickoff"],
                    team_code=code,
                    opponent_code=row["away"] if home else row["home"],
                    was_home=home,
                    known_at=fixture_stamp or cutoff,
                    names=names,
                    status="UNAVAILABLE",
                ),
                "sdp": dict.fromkeys(team_keys),
                "fpl": dict.fromkeys(TEAM_FPL_FIELDS),
            }
    for fixture, source in fixtures.items():
        for home in (True, False):
            code = source["home"] if home else source["away"]
            teams[current, fixture, code]["fpl"] = {
                "goals_scored": source["home_score"] if home else source["away_score"],
                "goals_conceded": source["away_score"] if home else source["home_score"],
            }
            teams[current, fixture, code]["source_version"] = source["source_version"]
    if state.global_failure is None:
        for observed in state.rows:
            source = raw_by_id[observed.provenance["payload_id"]]
            parsed = parse_team_stats(
                json.loads(source["body"]), match_id=observed.provenance["provider_match_id"]
            )
            side = next(p for p in parsed if p.side == ("home" if observed.was_home else "away"))
            opponent = next(p for p in parsed if p.side != side.side)
            measured = {m.local_field: metric_value(dict(side.stats), m) for m in metrics}
            for metric_key, original in OPPONENT_METRICS.items():
                metric = next(m for m in metrics if m.local_field == original)
                measured[metric_key] = metric_value(dict(opponent.stats), metric)
            previous = teams.get(observed.key)
            known = datetime.fromisoformat(observed.provenance["known_at"])
            if previous is not None:
                known = max(known, datetime.fromisoformat(previous["known_at"]))
            teams[observed.key] = {
                **_base(
                    season=observed.season,
                    gw=observed.gw,
                    fixture=observed.fixture,
                    kickoff=observed.kickoff,
                    team_code=observed.team_code,
                    opponent_code=observed.opponent_team_code,
                    was_home=observed.was_home,
                    known_at=known,
                    names=names,
                ),
                "sdp": measured,
                "fpl": previous["fpl"] if previous is not None else dict.fromkeys(TEAM_FPL_FIELDS),
                "provider_match_id": observed.provenance["provider_match_id"],
                "source_version": _version(
                    source["sha256"],
                    observed.provenance["match_metadata_sha256"],
                    previous["source_version"] if previous is not None else None,
                ),
            }
    fpl_count = len(players)
    lineup_count, lineup_failures = _add_lineups(
        con,
        players,
        fixtures,
        season=current,
        cutoff=cutoff,
        names=names,
    )
    team_rows = [teams[k] for k in sorted(teams)]
    players.sort(
        key=lambda r: (r["season"], r["fixture"], r["code"] or 0, r["provider_player_id"] or 0)
    )
    failures = len({(r["season"], r["fixture"]) for r in team_rows if r["status"] == "UNAVAILABLE"})
    valid = sum(r["status"] != "UNAVAILABLE" for r in team_rows)
    latest_sdp = max((r["fetched_at"] for r in raw), default=None)
    if failures:
        notes.append(
            f"{failures} fixture(s) lack valid complete SDP core evidence; "
            "metric rows remain unavailable."
        )
    if lineup_failures:
        notes.append(
            f"{lineup_failures} retained lineup bundle(s) failed identity/source validation."
        )
    document = {
        "schema": SCHEMA,
        "json_schema_version": 1,
        "as_of": _iso(cutoff),
        "source_status": {
            "team_stats": "UNAVAILABLE" if not valid else "PARTIAL" if failures else "AVAILABLE",
            "player_stats": "UNAVAILABLE",
            "player_lineups": "UNAVAILABLE" if not lineup_count else "PARTIAL",
            "fpl_enrichment": "AVAILABLE" if fpl_stamp is not None else "UNAVAILABLE",
            "latest_sdp_known_at": _iso(latest_sdp) if latest_sdp else None,
            "latest_fpl_known_at": _iso(fixture_stamp) if fixture_stamp else None,
            "latest_completed_kickoff": max((r["kickoff_time"] for r in team_rows), default=None),
            "notes": notes,
        },
        "coverage": {
            "team_matches": len(team_rows),
            "player_matches": len(players),
            "sdp_lineup_player_matches": lineup_count,
            "fpl_player_matches": fpl_count,
            "team_failures": failures,
            "unmapped_players": sum(r["code"] is None for r in players),
            "seasons": sorted({r["season"] for r in team_rows + players}),
        },
        "metrics": metric_catalog(),
        "gameweeks": gameweeks,
        "team_matches": team_rows,
        "player_matches": players,
    }
    validate_sdp_stats(document)
    return document


def validate_sdp_stats(document: dict[str, Any]) -> None:
    """Strict public allowlist: no PMFs, private capture identities, paths or source bodies."""
    if (
        set(document)
        != {
            "schema",
            "json_schema_version",
            "as_of",
            "source_status",
            "coverage",
            "metrics",
            "team_matches",
            "player_matches",
            "gameweeks",
        }
        or document["schema"] != SCHEMA
        or document["json_schema_version"] != 1
    ):
        raise ValueError("invalid SDP sidecar envelope")
    cutoff = AsOf(datetime.fromisoformat(document["as_of"])).ts
    if (
        set(document["source_status"]) != STATUS_FIELDS
        or set(document["coverage"]) != COVERAGE_FIELDS
    ):
        raise ValueError("invalid SDP sidecar status/coverage")
    if document["metrics"] != metric_catalog():
        raise ValueError("metric catalog differs from the observed-source contract")
    for field in ("team_stats", "player_stats", "player_lineups", "fpl_enrichment"):
        if document["source_status"][field] not in {"AVAILABLE", "PARTIAL", "UNAVAILABLE"}:
            raise ValueError("invalid source availability")
    for field in ("latest_sdp_known_at", "latest_fpl_known_at", "latest_completed_kickoff"):
        stamp = document["source_status"][field]
        if stamp is not None and AsOf(datetime.fromisoformat(stamp)).ts > cutoff:
            raise ValueError("future-known source status")
    for field in COVERAGE_FIELDS - {"seasons"}:
        count = document["coverage"][field]
        if type(count) is not int or count < 0:
            raise ValueError("invalid coverage count")
    team_fields = {m.local_field for m in load_sdp_metrics().metrics} | set(OPPONENT_METRICS)
    for gw in document["gameweeks"]:
        if set(gw) != {
            "season",
            "gw",
            "finished",
            "fixtures_total",
            "fixtures_completed",
            "source_known_at",
        }:
            raise ValueError("invalid gameweek completeness witness")
        if (
            not isinstance(gw["finished"], bool)
            or not 0 <= gw["fixtures_completed"] <= gw["fixtures_total"]
        ):
            raise ValueError("invalid gameweek completeness")
        if datetime.fromisoformat(gw["source_known_at"]) > cutoff:
            raise ValueError("future-known gameweek completeness")
    for scope in ("team", "player"):
        seen: set[tuple[Any, ...]] = set()
        for row in document[f"{scope}_matches"]:
            if set(row) != COMMON | ({"sdp", "fpl"} if scope == "team" else PLAYER_FIELDS):
                raise ValueError("unexpected public observed-row field")
            if row["status"] not in {"FINAL", "PROVISIONAL", "UNAVAILABLE"}:
                raise ValueError("unknown observed-row status")
            for field in ("gw", "fixture", "team_code", "opponent_team_code"):
                if type(row[field]) is not int or row[field] <= 0:
                    raise ValueError("invalid observed numeric identity")
            for field in ("provider_match_id",) + (
                ("code", "provider_player_id") if scope == "player" else ()
            ):
                if row[field] is not None and (type(row[field]) is not int or row[field] <= 0):
                    raise ValueError("invalid provider/player identity")
            if row["source_version"] is not None and not re.fullmatch(
                "[0-9a-f]{64}", row["source_version"]
            ):
                raise ValueError("invalid opaque source version")
            if (
                datetime.fromisoformat(row["known_at"]) > cutoff
                or datetime.fromisoformat(row["kickoff_time"]) >= cutoff
            ):
                raise ValueError("future-known observed row")
            if (
                not isinstance(row["was_home"], bool)
                or row["team_code"] == row["opponent_team_code"]
            ):
                raise ValueError("invalid observed fixture identity")
            key = (
                row["season"],
                row["fixture"],
                row["team_code"]
                if scope == "team"
                else (
                    ("fpl", row["code"])
                    if row["code"] is not None
                    else ("sdp", row["provider_player_id"])
                ),
            )
            if key in seen:
                raise ValueError("duplicate observed identity")
            seen.add(key)
            if set(row["sdp"]) != (team_fields if scope == "team" else set()):
                raise ValueError("unexpected SDP metric/player allocation")
            if scope == "player" and (
                set(row["fpl"]) != set(FPL_FIELDS)
                or row["minutes_sdp"] is not None
                or row["minutes_fpl"] != row["fpl"]["minutes"]
            ):
                raise ValueError("invalid player metric source or denominator")
            if scope == "player":
                if row["position"] not in {None, "GK", "DEF", "MID", "FWD"}:
                    raise ValueError("invalid FPL registered position")
                for field in ("started", "bench", "appeared"):
                    if row[field] is not None and type(row[field]) is not bool:
                        raise ValueError("invalid observed membership marker")
            if scope == "team" and set(row["fpl"]) != set(TEAM_FPL_FIELDS):
                raise ValueError("invalid team FPL score source")
            for source in ("sdp", "fpl"):
                for value in row[source].values():
                    if value is not None and (
                        isinstance(value, bool)
                        or not isinstance(value, (float, int))
                        or not math.isfinite(value)
                    ):
                        raise ValueError("non-finite/non-numeric observed metric")

    def check_strings(value: Any) -> None:
        if isinstance(value, dict):
            for child in value.values():
                check_strings(child)
        elif isinstance(value, list):
            for child in value:
                check_strings(child)
        elif isinstance(value, str) and re.search(
            r"(?i)([a-z]:[/\\]|https?://|file://|\\\\)", value
        ):
            raise ValueError("public observed data contains a path or URL")

    check_strings(document)
    json.dumps(document, allow_nan=False)


def sdp_stats_bytes(document: dict[str, Any]) -> bytes:
    validate_sdp_stats(document)
    return (
        json.dumps(
            document, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def export_sdp_stats(db: Path, output_file: Path, *, as_of: datetime) -> dict[str, Any]:
    if output_file.exists():
        raise ValueError("SDP export already exists; use a new immutable output path")
    con = duckdb.connect(str(db), read_only=True)
    try:
        document = build_sdp_stats(con, as_of=as_of)
    finally:
        con.close()
    body = sdp_stats_bytes(document)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    publish_bytes(output_file, body)
    return {
        "schema": SCHEMA,
        "sha256": hashlib.sha256(body).hexdigest(),
        "byte_count": len(body),
        "as_of": document["as_of"],
        "coverage": document["coverage"],
        "source_status": document["source_status"],
    }
