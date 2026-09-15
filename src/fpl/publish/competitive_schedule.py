"""Public, descriptive cup/European schedules from already-retained SDP catalogues.

This does not capture data, estimate fatigue, or supply prediction features. EPL
dates/FDR remain owned by the existing official FPL schedule in the dashboard.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import duckdb
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from fpl.config import load_sources
from fpl.ingest.pl_sdp import extract_items, parse_match_summary
from fpl.jobs.capture_sdp_workload import COMPETITIONS
from fpl.storage.sdp_runtime import load_sdp_state, raw_at
from fpl.transform.competitive_participation import uint


class PublicRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(PublicRecord):
    payload_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    known_at: AwareDatetime


class Match(PublicRecord):
    provider_match_id: int = Field(gt=0)
    home_team_code: int | None
    away_team_code: int | None
    home_name: str
    away_name: str
    home_short: str
    away_short: str
    kickoff_time: AwareDatetime | None
    status: str
    source_payload_id: str


class Competition(PublicRecord):
    competition_id: int
    name: str
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE", "NOT_PUBLISHED"]
    issues: list[str]
    sources: list[Source]
    matches: list[Match]


class CompetitiveSchedule(PublicRecord):
    schema_version: Literal[1] = 1
    semantics: Literal["current_schedule_not_prediction"] = "current_schedule_not_prediction"
    season: str
    as_of: AwareDatetime
    verified_team_codes: list[int]
    identity_sources: list[Source]
    competitions: list[Competition]


def _source(row: dict[str, Any]) -> Source:
    return Source(payload_id=row["payload_id"], sha256=row["sha256"], known_at=row["fetched_at"])


def _body(row: dict[str, Any]) -> dict[str, Any]:
    body = row["body"].encode("utf-8")
    if (
        row["status_code"] != 200
        or len(body) != row["byte_count"]
        or hashlib.sha256(body).hexdigest() != row["sha256"]
    ):
        raise ValueError("raw_hash_or_http_failure")
    result = json.loads(body)
    if not isinstance(result, dict):
        raise ValueError("invalid_catalogue_envelope")
    return result


def build_catalogues(
    raw: list[dict[str, Any]], *, season: str, as_of: datetime, team_map: dict[int, int]
) -> list[Competition]:
    """Follow the latest root's exact cursor chain, never union obsolete pages.

    Unchanged pages keep their original capture times in the raw store. A
    terminated chain means the retained catalogue is traversable, not that every
    future draw has been announced or that no fixture can subsequently change.
    """
    pages: dict[tuple[int, str | None], dict[str, Any]] = {}
    for row in sorted(raw, key=lambda r: (r["fetched_at"], r["payload_id"])):
        if (
            row["endpoint"] != "competitive_matches"
            or row["season"] != season
            or row["fetched_at"] > as_of
        ):
            continue
        params = json.loads(row["params_json"])
        if set(params) - {"competition", "season", "_limit", "_next"}:
            continue  # Do not mistake a filtered/legacy page for a full catalogue.
        if str(params.get("season")) != season[:4]:
            continue
        comp = uint(params.get("competition"), "competition")
        pages[comp, params.get("_next")] = row
    results: list[Competition] = []
    for comp, name in COMPETITIONS.items():
        if comp == 8:
            continue  # FPL owns EPL fixture identity/date/GW/FDR.
        result = Competition(
            competition_id=comp, name=name, status="UNAVAILABLE", issues=[], sources=[], matches=[]
        )
        cursor: str | None = None
        visited: set[str | None] = set()
        seen: set[int] = set()
        try:
            while True:
                if cursor in visited:
                    raise ValueError("repeated_catalogue_cursor")
                visited.add(cursor)
                page = pages.get((comp, cursor))
                if page is None:
                    result.issues.append("missing_catalogue_page")
                    result.status = "PARTIAL" if result.sources else "UNAVAILABLE"
                    break
                body = _body(page)
                result.sources.append(_source(page))
                for record in extract_items(body):
                    summary = parse_match_summary(record)
                    if (
                        uint(record.get("competitionId"), "competition") != comp
                        or summary.season_id != int(season[:4])
                        or summary.home_team_id is None
                        or summary.away_team_id is None
                        or summary.home_team_id == summary.away_team_id
                        or summary.match_id in seen
                    ):
                        raise ValueError("duplicate_or_contradictory_match_identity")
                    seen.add(summary.match_id)
                    home = team_map.get(summary.home_team_id)
                    away = team_map.get(summary.away_team_id)
                    if home is None and away is None:
                        continue
                    if not summary.home_team_name or not summary.away_team_name:
                        raise ValueError("missing_opponent_identity")
                    result.matches.append(
                        Match(
                            provider_match_id=summary.match_id,
                            home_team_code=home,
                            away_team_code=away,
                            home_name=summary.home_team_name,
                            away_name=summary.away_team_name,
                            home_short=str(
                                record["homeTeam"].get("abbr") or summary.home_team_name
                            ),
                            away_short=str(
                                record["awayTeam"].get("abbr") or summary.away_team_name
                            ),
                            kickoff_time=summary.kickoff,
                            status=str(record.get("period") or summary.status or "Unknown"),
                            source_payload_id=page["payload_id"],
                        )
                    )
                pagination = body.get("pagination")
                if not isinstance(pagination, dict) or "_next" not in pagination:
                    raise ValueError("pagination_completeness_unavailable")
                next_cursor = pagination["_next"]
                if next_cursor is None or next_cursor == "":
                    result.status = "AVAILABLE" if seen else "NOT_PUBLISHED"
                    break
                if not isinstance(next_cursor, (str, int)) or isinstance(next_cursor, bool):
                    raise ValueError("invalid_catalogue_cursor")
                cursor = str(next_cursor)
        except (ValueError, KeyError, TypeError):
            # An invalid revision never falls back silently to an older schedule.
            result.status = "UNAVAILABLE"
            result.issues.append("catalogue_schema_hash_or_identity_failure")
            result.matches = []
        result.matches.sort(key=lambda m: (str(m.kickoff_time or ""), m.provider_match_id))
        results.append(result)
    return results


def build_competitive_schedule(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime
) -> CompetitiveSchedule:
    season = load_sources().current_season.season
    raw = raw_at(con, as_of)
    by_id = {row["payload_id"]: row for row in raw}
    state = load_sdp_state(con, cutoff=as_of, season=season)
    # The existing EPL crosswalk proves provider-team -> permanent FPL code.
    # Do not assume numerical equality or join by names, including promoted clubs.
    mapping: dict[int, int] = {}
    witnesses: dict[str, Source] = {}
    for team in state.rows:
        if team.season != season:
            continue
        pid = team.provenance["match_metadata_payload_id"]
        row = by_id[pid]
        matches = extract_items(_body(row)) if row["endpoint"] == "matches" else [_body(row)]
        match = next(
            parse_match_summary(m)
            for m in matches
            if parse_match_summary(m).match_id == team.provenance["provider_match_id"]
        )
        provider_id = match.home_team_id if team.was_home else match.away_team_id
        if provider_id is None or mapping.get(provider_id, team.team_code) != team.team_code:
            raise ValueError("ambiguous provider club crosswalk")
        mapping[provider_id] = team.team_code
        witnesses[pid] = _source(row)
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("nonunique provider club crosswalk")
    return CompetitiveSchedule(
        season=season,
        as_of=as_of,
        verified_team_codes=sorted(mapping.values()),
        identity_sources=[witnesses[k] for k in sorted(witnesses)],
        competitions=build_catalogues(raw, season=season, as_of=as_of, team_map=mapping),
    )


def validate_competitive_schedule(value: Any) -> CompetitiveSchedule:
    document = CompetitiveSchedule.model_validate(value)
    if document.as_of > datetime.now(UTC):
        raise ValueError("future schedule export time")
    codes = set(document.verified_team_codes)
    if len(codes) != len(document.verified_team_codes) or any(code <= 0 for code in codes):
        raise ValueError("duplicate or invalid club identity")
    if {c.competition_id for c in document.competitions} != set(COMPETITIONS) - {8} or len(
        document.competitions
    ) != len(COMPETITIONS) - 1:
        raise ValueError("missing or duplicate competition coverage")
    for competition in document.competitions:
        ids = {source.payload_id for source in competition.sources}
        seen: set[int] = set()
        if competition.status in {"UNAVAILABLE", "NOT_PUBLISHED"} and competition.matches:
            raise ValueError("unavailable catalogue contains fixtures")
        for source in [*competition.sources, *document.identity_sources]:
            if source.known_at > document.as_of:
                raise ValueError("future source")
        for match in competition.matches:
            if (
                match.provider_match_id in seen
                or match.source_payload_id not in ids
                or not {match.home_team_code, match.away_team_code} & codes
                or any(
                    c is not None and c not in codes
                    for c in (match.home_team_code, match.away_team_code)
                )
            ):
                raise ValueError("invalid schedule identity/provenance")
            seen.add(match.provider_match_id)
    return document


def export_competitive_schedule(db: Path, target: Path, *, as_of: datetime) -> dict[str, Any]:
    with duckdb.connect(str(db), read_only=True) as con:
        document = build_competitive_schedule(con, as_of=as_of)
    value = document.model_dump(mode="json")
    validate_competitive_schedule(value)
    body = (
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("xb") as handle:
        handle.write(body)
    return {
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "as_of": as_of.isoformat(),
    }
