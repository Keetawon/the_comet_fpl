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
from fpl.storage.db import table_exists
from fpl.transform.competitive_participation_v2 import RESULT_TYPES

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
                   known_at, capture_id,
                   row_number() OVER (
                       PARTITION BY season, team_id, fixture
                       ORDER BY known_at DESC, capture_id DESC
                   ) AS recency
            FROM mart_team_fixture_live
            WHERE season = ? AND known_at <= ?
        )
        SELECT team_id, fixture, gw, kickoff_time, opponent_team_id, was_home, known_at, capture_id
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
            fixture_id=int(row["fixture"]),
            known_at=row["known_at"],
            capture_id=str(row["capture_id"]),
        )
    return out


def _record_times_valid(record: dict[str, Any], known_at: datetime) -> bool:
    """An interpretation cannot know its identity or raw sources before they exist."""
    stamps = [record.get("identity_known_at"), record.get("fetched_at")]
    stamps.extend(source.get("known_at") for source in record.get("source_versions", {}).values())
    try:
        if (
            record.get("known_at") is not None
            and datetime.fromisoformat(record["known_at"].replace("Z", "+00:00")) != known_at
        ):
            return False
        return all(
            (stamp := datetime.fromisoformat(value.replace("Z", "+00:00"))).utcoffset() is not None
            and stamp <= known_at
            for value in stamps
            if value is not None
        )
    except (ValueError, TypeError, AttributeError):
        return False


def _fpl_comparisons(
    con: duckdb.DuckDBPyConnection, *, season: str, as_of: datetime
) -> dict[tuple[int, int], dict[str, Any]]:
    """Exact captured league fixture/code only; no pulse-id assumption or archive proxy."""
    if not all(
        table_exists(con, table)
        for table in ("mart_fact_player_fixture_live", "stg_pl_sdp_fixture_crosswalk")
    ):
        return {}
    frame = con.execute(
        """
        WITH h AS (
            SELECT * FROM mart_fact_player_fixture_live WHERE season=? AND known_at<=?
            QUALIFY row_number() OVER (
                PARTITION BY season,code,fixture ORDER BY known_at DESC,capture_id DESC
            )=1
        )
        SELECT x.sdp_match_id, h.code, h.fixture, h.minutes, h.known_at, h.capture_id,
               h.kickoff_time, h.team_id, h.opponent_team_id, h.was_home
        FROM h JOIN stg_pl_sdp_fixture_crosswalk x USING (season,fixture)
        WHERE x.resolved_at<=? AND x.corroborated_kickoff AND x.corroborated_teams
          AND h.kickoff_time<? AND h.position IN ('GK','DEF','MID','FWD')
        """,
        [season, as_of, as_of, as_of],
    ).pl()
    return {(r["sdp_match_id"], r["code"]): r for r in frame.iter_rows(named=True)}


def completed_fixtures(
    con: duckdb.DuckDBPyConnection,
    *,
    season: str,
    as_of: datetime,
    window_hours: int,
    teams: dict[int, int] | None = None,
    source_issues: list[str] | None = None,
) -> list[CompletedFixture]:
    """Latest cutoff-known whole interpretations; never hide an invalid revision.

    Retained normalized rows already carry the capture job's exact club bridge. Reuse
    those cutoff-known bridges for failed/empty later interpretations as well. A
    missing/contradictory bridge stays unresolved; names never resolve an identity.
    """
    if not table_exists(con, "sdp_competitive_match_version"):
        if source_issues is not None:
            source_issues.append("competitive_participation_not_captured")
        return []
    all_versions = (
        con.execute(
            """SELECT version_id, competition, provider_match_id, kickoff_time, known_at,
                  CAST(record_json AS VARCHAR) AS body
           FROM sdp_competitive_match_version
           WHERE provider='pl_sdp' AND season=? AND known_at<=?
           ORDER BY known_at, version_id""",
            [season, as_of],
        )
        .pl()
        .to_dicts()
    )
    versions: dict[tuple[int, int], dict[str, Any]] = {}
    club_candidates: dict[int, set[int]] = {}
    for row in all_versions:
        record = json.loads(row["body"])
        row["record"] = record
        versions[row["competition"], row["provider_match_id"]] = row
        if row["kickoff_time"] >= as_of or not _record_times_valid(record, row["known_at"]):
            continue
        for entry in record.get("rows", ()):
            provider = entry.get("provider_team_id")
            code = entry.get("team_code")
            if isinstance(provider, int) and isinstance(code, int):
                club_candidates.setdefault(provider, set()).add(code)
    mapping = {p: next(iter(c)) for p, c in club_candidates.items() if len(c) == 1}
    # Many provider ids mapping to one club is equally ambiguous.
    mapping = {p: c for p, c in mapping.items() if list(mapping.values()).count(c) == 1}
    official = _fpl_comparisons(con, season=season, as_of=as_of)
    fixtures: list[CompletedFixture] = []
    start = as_of - timedelta(hours=window_hours)
    for row in sorted(
        versions.values(),
        key=lambda r: (r["kickoff_time"], r["competition"], r["provider_match_id"]),
    ):
        if not start <= row["kickoff_time"] < as_of:
            continue
        record = row["record"]
        competition = int(row["competition"])
        if competition not in COMPETITION_NAMES:
            continue
        match_id = int(row["provider_match_id"])
        try:
            summary = parse_match_summary(record["raw_metadata"])
        except (ValueError, KeyError, TypeError):
            if source_issues is not None:
                source_issues.append(f"match_metadata_unresolved:{match_id}")
            continue
        opponents = {
            summary.home_team_id: summary.away_team_name,
            summary.away_team_id: summary.home_team_name,
        }
        whole_errors: list[str] = []
        if not _record_times_valid(record, row["known_at"]):
            whole_errors.append("source_time_contradiction")
        if summary.match_id != match_id or (
            summary.kickoff is not None and summary.kickoff != row["kickoff_time"]
        ):
            whole_errors.append("match_identity_contradiction")
        metadata = record["raw_metadata"]
        if metadata.get("period") != "FullTime" or metadata.get("resultType") not in RESULT_TYPES:
            whole_errors.append("match_completion_unproven")
        for provider_id, opponent in opponents.items():
            team_code = mapping.get(provider_id) if provider_id is not None else None
            if team_code is None:
                if source_issues is not None:
                    source_issues.append(f"provider_club_unresolved:{match_id}:{provider_id}")
                continue
            side_rows = [
                e for e in record.get("rows", ()) if e.get("provider_team_id") == provider_id
            ]
            errors = list(whole_errors)
            if not side_rows:
                errors.append("empty_side_interpretation")
            if any(
                e.get("team_code") != team_code or e.get("code") is None or e.get("identity_errors")
                for e in side_rows
            ):
                errors.append("side_identity_unresolved")
            opponent_provider = (
                summary.away_team_id
                if provider_id == summary.home_team_id
                else summary.home_team_id
            )
            opponent_code = None if opponent_provider is None else mapping.get(opponent_provider)
            observations: list[PlayerObservation] = []
            for entry in side_rows:
                if entry.get("team_code") != team_code or entry.get("code") is None:
                    continue
                code = int(entry["code"])
                fpl = official.get((match_id, code)) if competition == 8 else None
                if fpl is not None and (
                    fpl["kickoff_time"] != row["kickoff_time"]
                    or (teams or {}).get(fpl["team_id"]) != team_code
                    or fpl["was_home"] != (provider_id == summary.home_team_id)
                    or (teams or {}).get(fpl["opponent_team_id"]) != opponent_code
                ):
                    fpl = None
                observations.append(
                    PlayerObservation(
                        code=code,
                        appeared=entry.get("appeared"),
                        started=entry.get("started"),
                        nominal_minutes=entry.get("nominal_minutes"),
                        errors=tuple(entry.get("identity_errors") or ()),
                        fpl_minutes=None if fpl is None else fpl["minutes"],
                        fpl_fixture_id=None if fpl is None else fpl["fixture"],
                        fpl_known_at=None if fpl is None else fpl["known_at"],
                        fpl_capture_id=None if fpl is None else fpl["capture_id"],
                    )
                )
            fixtures.append(
                CompletedFixture(
                    competition_id=competition,
                    provider_match_id=match_id,
                    kickoff=row["kickoff_time"],
                    team_code=team_code,
                    opponent_name=opponent,
                    roster_proven=record.get("valid") is True
                    and not record.get("errors")
                    and not errors,
                    observations=tuple(sorted(observations, key=lambda o: o.code)),
                    source_known_at=row["known_at"],
                    version_id=row["version_id"],
                    errors=tuple(errors),
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
        source_issues: list[str] = []
        fixtures = completed_fixtures(
            con,
            season=season,
            as_of=as_of,
            window_hours=window_hours,
            teams=teams,
            source_issues=source_issues,
        )
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
        # The retained workload store contains attempted recent FullTime legs, not a
        # complete all-competition census. A traversable schedule catalogue alone also
        # does not establish that every played leg was captured. Never infer full rest.
        source_issues=source_issues,
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
