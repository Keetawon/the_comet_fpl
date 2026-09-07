"""Bounded prospective competitive lineups/events, using the existing SDP client/raw store.

No cup statistics are requested. Whole interpretation versions have actual knowledge
times and retain unresolved participants. They do not change the minutes component.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fpl.config import load_sources, repo_root
from fpl.football_configuration import load_football_environment
from fpl.ingest.pl_sdp import PlSdpClient, RawPayload, extract_items, parse_match_summary
from fpl.jobs.prospective_points_v1 import live_bootstrap_snapshot, team_code_map_live
from fpl.models.sdp_environment import canonical
from fpl.storage.db import initialise
from fpl.storage.sdp_runtime import load_sdp_state
from fpl.transform.competitive_participation import exact_crosswalk, uint
from fpl.transform.competitive_participation_v2 import RESULT_TYPES
from fpl.transform.competitive_participation_v3 import INTERPRETATION_ID, parse_participation_v3
from fpl.transform.pl_sdp import land_payload

COMPETITIONS = {
    8: "Premier League",
    1: "FA Cup",
    2: "League Cup",
    5: "Champions League",
    6: "Europa League",
    1125: "Conference League",
}
DDL = """CREATE TABLE IF NOT EXISTS sdp_competitive_match_version (
    version_id VARCHAR PRIMARY KEY, provider VARCHAR NOT NULL, competition INTEGER NOT NULL,
    season VARCHAR NOT NULL, provider_match_id BIGINT NOT NULL, known_at TIMESTAMPTZ NOT NULL,
    kickoff_time TIMESTAMPTZ NOT NULL, record_json JSON NOT NULL
)"""


def normalize_bundle(
    *,
    metadata: dict[str, Any],
    sources: dict[str, tuple[str, RawPayload]],
    season: str,
    registry: list[dict[str, Any]],
    team_codes: set[int],
    identity_known_at: datetime,
    interpreted_at: datetime,
) -> dict[str, Any]:
    competition = uint(metadata.get("competitionId"), "competition")
    if competition not in COMPETITIONS:
        raise ValueError("unverified competitive identity")
    summary = parse_match_summary(metadata)
    config = load_sources().pl_sdp
    assert config is not None
    if summary.season_id != config.season_id(season):
        raise ValueError("competitive season identity mismatch")
    if summary.kickoff is None:
        raise ValueError("competitive kickoff unavailable")
    source_known = max(raw.fetched_at for _, raw in sources.values())
    if interpreted_at < max(source_known, identity_known_at):
        raise ValueError("interpretation precedes source/identity availability")
    provenance = {
        endpoint: {
            "payload_id": pid,
            "sha256": raw.sha256,
            "known_at": raw.fetched_at.isoformat(),
            "fetched_at": raw.fetched_at.isoformat(),
            "path": raw.path,
            "schema_version": raw.payload.get("schemaVersion")
            if isinstance(raw.payload, dict)
            else None,
        }
        for endpoint, (pid, raw) in sorted(sources.items())
    }
    parser_files = [
        f"src/fpl/transform/competitive_participation{suffix}.py" for suffix in ("", "_v2", "_v3")
    ]
    parser_hashes = {
        name: hashlib.sha256((repo_root() / name).read_bytes()).hexdigest() for name in parser_files
    }
    record: dict[str, Any] = {
        "provider": "pl_sdp",
        "competition": competition,
        "season": season,
        "provider_match_id": summary.match_id,
        "kickoff_time": summary.kickoff.isoformat(),
        "fetched_at": source_known.isoformat(),
        "known_at": interpreted_at.isoformat(),
        "identity_known_at": identity_known_at.isoformat(),
        "normalization_version": INTERPRETATION_ID,
        "parser_sha256": parser_hashes,
        "source_versions": provenance,
        "provider_team_ids": [summary.home_team_id, summary.away_team_id],
        "raw_metadata": metadata,
        "rows": [],
        "errors": [],
        "valid": False,
        "exact_rest_hours": None,
        "duration_definition": "nominal_period_clock_intervals_v1_not_fpl_minutes",
    }
    try:
        if set(sources) != {"metadata", "lineups", "events"}:
            raise ValueError("complete metadata/lineup/event bundle required")
        for _, raw in sources.values():
            if (
                raw.status_code != 200
                or hashlib.sha256(raw.text.encode()).hexdigest() != raw.sha256
            ):
                raise ValueError("raw source status/hash contradiction")
            if isinstance(raw.payload, dict) and "matchId" in raw.payload:
                if uint(raw.payload["matchId"], "source match") != summary.match_id:
                    raise ValueError("competitive source match identity mismatch")
        parsed = parse_participation_v3(
            metadata,
            sources["lineups"][1].payload,
            sources["events"][1].payload,
            known_at=source_known,
            event_known_at=sources["events"][1].fetched_at,
            interpretation_known_at=interpreted_at,
        )
        for side in parsed["sides"]:
            team = side["provider_team_id"]
            mapping, identity_errors = exact_crosswalk(
                [r["provider_player_id"] for r in side["rows"]], registry, season=season
            )
            record["errors"].extend(side["errors"])
            for row in side["rows"]:
                record["rows"].append(
                    {
                        **row,
                        "code": mapping[row["provider_player_id"]],
                        "team_code": team if team in team_codes else None,
                        "provider_team_id": team,
                        "nominal_match_minutes": side["nominal_match_minutes"],
                        "identity_errors": [
                            e
                            for e in identity_errors
                            if e.startswith(f"player {row['provider_player_id']}:")
                        ],
                    }
                )
        record["valid"] = not record["errors"]
    except (ValueError, KeyError, TypeError, RuntimeError) as error:
        record["errors"].append(f"{type(error).__name__}: {error}")
    material = (
        season,
        competition,
        summary.match_id,
        provenance,
        parser_hashes,
        hashlib.sha256(canonical(registry).encode()).hexdigest(),
        identity_known_at.isoformat(),
    )
    record["version_id"] = hashlib.sha256(canonical(material).encode()).hexdigest()
    return record


def capture(*, database: Path, lookback_days: int = 5) -> dict[str, Any]:
    if lookback_days <= 0:
        raise ValueError("positive lookback required")
    config = load_sources()
    assert config.pl_sdp is not None
    competitions = load_football_environment().workload_competitions
    if not set(competitions) <= COMPETITIONS.keys() or len(set(competitions)) != len(competitions):
        raise ValueError("unique supported competitions required")
    now = datetime.now(UTC)
    report: dict[str, Any] = {"started_at": now.isoformat(), "competitions": {}, "errors": []}
    with initialise(database) as con:
        con.execute(DDL)
        bootstrap = live_bootstrap_snapshot(con, config.current_season.season, now)
        # Club numeric equality is accepted only after the established exact EPL fixture
        # crosswalk/raw boundary has corroborated it in this season at this cutoff.
        state = load_sdp_state(con, cutoff=now, season=config.current_season.season)
        teams = set(team_code_map_live(bootstrap).values()) & {
            row.team_code for row in state.rows if row.season == config.current_season.season
        }
        report["club_identity_witnesses"] = [
            row.provenance for row in state.rows if row.season == config.current_season.season
        ]
        report["unresolved_fpl_team_codes"] = sorted(
            set(team_code_map_live(bootstrap).values()) - teams
        )

        def retained(raw: RawPayload, match_id: int | None = None) -> tuple[str, RawPayload]:
            pid, _ = land_payload(
                con, raw, season=config.current_season.season, sdp_match_id=match_id
            )
            stamp = (
                con.execute("SELECT fetched_at FROM raw_pl_sdp_payload WHERE payload_id=?", [pid])
                .pl()
                .item()
            )
            # An unchanged response points to its original immutable receipt, not today's
            # request time. Today's successful request is recorded in this cycle's report.
            return pid, replace(raw, fetched_at=stamp)

        registry = [
            {**row, "season": config.current_season.season}
            for row in bootstrap.data["elements"]
            if row.get("element_type") in {1, 2, 3, 4}
        ]
        for competition in competitions:
            counts: dict[str, Any] = {"expected": 0, "captured": 0, "valid": 0, "failures": []}
            report["competitions"][str(competition)] = counts
            try:
                provider_config = config.pl_sdp.model_copy(update={"competition": competition})
                with PlSdpClient(config=provider_config) as client:
                    seen: set[int] = set()
                    for raw, _ in client.iter_matches(
                        season_id=provider_config.season_id(config.current_season.season)
                    ):
                        # Distinct endpoint label keeps competitive catalogues OUT of EPL staging.
                        raw = replace(raw, endpoint="competitive_matches")
                        metadata_id, metadata_raw = retained(raw)
                        for metadata in extract_items(raw.payload):
                            summary = parse_match_summary(metadata)
                            if (
                                summary.match_id in seen
                                or uint(metadata.get("competitionId"), "competition") != competition
                                or summary.season_id
                                != provider_config.season_id(config.current_season.season)
                            ):
                                raise ValueError(
                                    "duplicate or contradictory competition/match identity"
                                )
                            seen.add(summary.match_id)
                            if (
                                summary.kickoff is None
                                or not now - timedelta(days=lookback_days) <= summary.kickoff < now
                                or not teams.intersection(
                                    {summary.home_team_id, summary.away_team_id}
                                )
                                or metadata.get("period") != "FullTime"
                                or metadata.get("resultType") not in RESULT_TYPES
                            ):
                                continue
                            counts["expected"] += 1
                            sources = {"metadata": (metadata_id, metadata_raw)}
                            for endpoint, fetch in (
                                ("lineups", client.fetch_match_lineups),
                                ("events", client.fetch_match_events),
                            ):
                                try:
                                    body = fetch(summary.match_id)
                                    sources[endpoint] = retained(body, summary.match_id)
                                except Exception as error:
                                    counts["failures"].append(
                                        f"{summary.match_id}/{endpoint}: "
                                        f"{type(error).__name__}: {error}"
                                    )
                            record = normalize_bundle(
                                metadata=metadata,
                                sources=sources,
                                season=config.current_season.season,
                                registry=registry,
                                team_codes=teams,
                                identity_known_at=bootstrap.known_at,
                                interpreted_at=datetime.now(UTC),
                            )
                            counts["captured"] += int(len(sources) == 3)
                            counts["valid"] += int(record["valid"])
                            prior = con.execute(
                                "SELECT version_id FROM sdp_competitive_match_version "
                                "WHERE version_id=?",
                                [record["version_id"]],
                            ).fetchone()
                            if prior is None:
                                con.execute(
                                    "INSERT INTO sdp_competitive_match_version "
                                    "VALUES (?,?,?,?,?,?,?,?)",
                                    [
                                        record["version_id"],
                                        "pl_sdp",
                                        competition,
                                        config.current_season.season,
                                        summary.match_id,
                                        record["known_at"],
                                        summary.kickoff,
                                        canonical(record),
                                    ],
                                )
            except Exception as error:
                counts["failures"].append(f"{type(error).__name__}: {error}")
            report["errors"].extend(counts["failures"])
    report["finished_at"] = datetime.now(UTC).isoformat()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--lookback-days", type=int, default=5)
    args = parser.parse_args(argv)
    from fpl.jobs.daily_pl_sdp import writer_lock

    with writer_lock(args.db):
        report = capture(database=args.db, lookback_days=args.lookback_days)
    print(canonical(report))
    return int(bool(report["errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
