"""Emit the descriptive pre-deadline rest summary from already-captured sources.

Thin orchestration only: it reads the operational database read-only, hands typed rows to
:mod:`fpl.publish.rest_summary`, and writes an immutable JSON document beside a reviewable
text block. It captures nothing, fits nothing, and writes no table.

    python -m fpl.jobs.rest_summary --db D:/FPL/operational.duckdb --out D:/FPL/rest \
        --code-file my-squad.txt

Both inputs are produced by jobs that already run daily: `capture_sdp_workload` retains the
competitive lineups/events, and the FPL snapshot loader supplies the registry and schedule.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from fpl.config import load_sources
from fpl.ingest.pl_sdp import parse_match_summary
from fpl.jobs.prospective_points_v1 import live_bootstrap_snapshot, team_code_map_live
from fpl.publish.rest_summary import (
    COMPETITION_NAMES,
    DEFAULT_WINDOW_HOURS,
    CompletedFixture,
    NextFixture,
    PlayerObservation,
    RestSummary,
    RosterPlayer,
    build_rest_summary,
    load_international_breaks,
    render_rest_summary_text,
    validate_rest_summary,
)

# Assistant managers (element type 5) are not players and stay out of every population.
PLAYER_ELEMENT_TYPES = (1, 2, 3, 4)


def _roster(snapshot: Any, teams: dict[int, int]) -> tuple[list[RosterPlayer], dict[int, str]]:
    names = {int(t["id"]): str(t["name"]) for t in snapshot.data["teams"]}
    club_names = {teams[i]: name for i, name in names.items() if i in teams}
    roster = [
        RosterPlayer(
            code=int(element["code"]),
            web_name=str(element["web_name"]),
            team_code=teams[int(element["team"])],
            team_name=club_names[teams[int(element["team"])]],
        )
        for element in snapshot.data["elements"]
        if int(element["element_type"]) in PLAYER_ELEMENT_TYPES and int(element["team"]) in teams
    ]
    return roster, club_names


def next_fixtures(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    as_of: datetime,
    teams: dict[int, int],
    club_names: dict[int, str],
) -> dict[int, NextFixture]:
    """The club's earliest listed fixture at or after the cutoff, from the latest capture."""
    frame = con.execute(
        """
        WITH latest AS (
            SELECT season, team_id, fixture, gw, kickoff_time, opponent_team_id, was_home,
                   row_number() OVER (
                       PARTITION BY season, team_id, fixture
                       ORDER BY known_at DESC, capture_id DESC
                   ) AS recency
            FROM mart_team_fixture_live
            WHERE season = ? AND known_at <= ?
        )
        SELECT team_id, gw, kickoff_time, opponent_team_id, was_home
        FROM latest
        WHERE recency = 1 AND kickoff_time IS NOT NULL AND kickoff_time >= ? AND gw IS NOT NULL
        ORDER BY team_id, kickoff_time, fixture
        """,
        [season, as_of, as_of],
    ).pl()
    out: dict[int, NextFixture] = {}
    for row in frame.iter_rows(named=True):
        team_id = int(row["team_id"])
        if team_id not in teams or teams[team_id] in out:
            continue  # Rows arrive in kickoff order, so the first one is the next fixture.
        opponent = teams.get(int(row["opponent_team_id"]))
        out[teams[team_id]] = NextFixture(
            team_code=teams[team_id],
            gw=int(row["gw"]),
            kickoff=row["kickoff_time"],
            opponent_name=None if opponent is None else club_names.get(opponent),
            was_home=bool(row["was_home"]),
        )
    return out


def completed_fixtures(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    as_of: datetime,
    window_hours: int,
) -> list[CompletedFixture]:
    """One row per scoped club side of every retained competitive fixture in the window."""
    frame = con.execute(
        """
        WITH latest AS (
            SELECT competition, provider_match_id, kickoff_time, record_json,
                   row_number() OVER (
                       PARTITION BY competition, provider_match_id
                       ORDER BY known_at ASC, version_id ASC
                   ) AS retained
            FROM sdp_competitive_match_version
            WHERE season = ? AND known_at <= ?
              AND kickoff_time >= ? AND kickoff_time < ?
        )
        SELECT competition, provider_match_id, kickoff_time, CAST(record_json AS VARCHAR) AS body
        FROM latest
        WHERE retained = 1
        ORDER BY kickoff_time, competition, provider_match_id
        """,
        [season, as_of, as_of - timedelta(hours=window_hours), as_of],
    ).pl()

    fixtures: list[CompletedFixture] = []
    for row in frame.iter_rows(named=True):
        record = json.loads(row["body"])
        competition = int(row["competition"])
        if competition not in COMPETITION_NAMES:
            continue
        summary = parse_match_summary(record["raw_metadata"])
        opponents = {
            summary.home_team_id: summary.away_team_name,
            summary.away_team_id: summary.home_team_name,
        }
        proven = record.get("valid") is True
        sides: dict[int, list[PlayerObservation]] = {}
        provider_of: dict[int, int | None] = {}
        for entry in record.get("rows", ()):
            team_code = entry.get("team_code")
            if team_code is None or entry.get("code") is None:
                # An unresolved club or player identity is never attached to a scoped side.
                continue
            sides.setdefault(int(team_code), []).append(
                PlayerObservation(
                    code=int(entry["code"]),
                    appeared=entry.get("appeared"),
                    started=entry.get("started"),
                    nominal_minutes=entry.get("nominal_minutes"),
                    errors=tuple(entry.get("identity_errors") or ()),
                )
            )
            provider_of[int(team_code)] = entry.get("provider_team_id")
        for team_code, observations in sides.items():
            opponent = opponents.get(provider_of.get(team_code))
            fixtures.append(
                CompletedFixture(
                    competition_id=competition,
                    provider_match_id=int(row["provider_match_id"]),
                    kickoff=row["kickoff_time"],
                    team_code=team_code,
                    opponent_name=opponent,
                    roster_proven=proven,
                    observations=tuple(sorted(observations, key=lambda o: o.code)),
                )
            )
    return fixtures


def build(
    database: Path,
    *,
    as_of: datetime,
    window_hours: int = DEFAULT_WINDOW_HOURS,
    codes: frozenset[int] | None = None,
) -> RestSummary:
    season = load_sources().current_season.season
    with duckdb.connect(str(database), read_only=True) as con:
        snapshot = live_bootstrap_snapshot(con, season, as_of)
        teams = team_code_map_live(snapshot)
        roster, club_names = _roster(snapshot, teams)
        if codes is not None:
            missing = codes - {p.code for p in roster}
            if missing:
                raise ValueError(
                    "requested player codes are absent from the selectable registry: "
                    + ", ".join(str(c) for c in sorted(missing))
                )
            roster = [p for p in roster if p.code in codes]
        upcoming = next_fixtures(
            con, season=season, as_of=as_of, teams=teams, club_names=club_names
        )
        fixtures = completed_fixtures(con, season=season, as_of=as_of, window_hours=window_hours)
    source, windows = load_international_breaks()
    return build_rest_summary(
        season=season,
        as_of=as_of,
        roster=roster,
        fixtures=fixtures,
        next_fixtures=upcoming,
        international_windows=windows,
        break_source=source,
        window_hours=window_hours,
    )


def write(document: RestSummary, directory: Path) -> dict[str, Any]:
    """Write the document and its text block without overwriting an earlier one."""
    value = document.model_dump(mode="json")
    validate_rest_summary(value)
    stamp = document.as_of.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory.mkdir(parents=True, exist_ok=True)
    body = (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()
    target = directory / f"rest-summary-{stamp}.json"
    with target.open("xb") as handle:
        handle.write(body)
    text = render_rest_summary_text(document) + "\n"
    text_target = directory / f"rest-summary-{stamp}.txt"
    with text_target.open("x", encoding="utf-8") as handle:
        handle.write(text)
    return {
        "json": str(target),
        "text": str(text_target),
        "sha256": hashlib.sha256(body).hexdigest(),
        "counts": document.counts,
    }


def _codes(args: argparse.Namespace) -> frozenset[int] | None:
    selected: set[int] = set()
    if args.codes:
        selected.update(int(value) for value in args.codes.split(",") if value.strip())
    if args.code_file:
        for line in Path(args.code_file).read_text(encoding="utf-8").splitlines():
            entry = line.split("#", 1)[0].strip()
            if entry:
                selected.add(int(entry))
    return frozenset(selected) or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--window-hours", type=int, default=DEFAULT_WINDOW_HOURS)
    parser.add_argument("--codes", help="comma-separated stable player codes")
    parser.add_argument("--code-file", type=Path, help="one stable player code per line")
    parser.add_argument("--as-of", help="ISO cutoff; defaults to now")
    args = parser.parse_args(argv)
    as_of = (
        datetime.now(UTC)
        if args.as_of is None
        else datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    )
    if as_of.utcoffset() is None:
        raise ValueError("--as-of must carry an explicit offset")
    document = build(args.db, as_of=as_of, window_hours=args.window_hours, codes=_codes(args))
    result = write(document, args.out)
    print(json.dumps(result, indent=2))
    print()
    print(render_rest_summary_text(document))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
