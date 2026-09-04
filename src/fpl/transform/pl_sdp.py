"""Premier League SDP: raw landing, typed staging, and the measured fixture crosswalk.

Three responsibilities, kept apart because they fail differently:

  * `land_payload` writes provider bytes verbatim and is append-only. A restatement is a new
    row, never an overwrite, which is what makes `known_at` mean anything downstream.
  * `stage_*` interprets those bytes against the metric dictionary. It is rebuildable: drop
    the staging tables and re-derive them from raw without another network call.
  * `resolve_crosswalk` MEASURES whether `pulse_id` equals the SDP `matchId` rather than
    assuming it, and fails closed on any ambiguity.

Nothing here reaches the network; the client is the only module that does.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import duckdb

from fpl.config import SdpMetricType, load_sdp_metrics
from fpl.ingest.pl_sdp import (
    RawPayload,
    SdpSchemaError,
    extract_items,
    parse_match_summary,
    parse_team_stats,
)

PROVIDER: Final[str] = "pl_sdp"
ARCHIVE_PROVIDER: Final[str] = "fpl_archive"

# How a fixture was matched to an SDP match. Recorded per row so a later audit can separate
# "the identifiers are the same thing" from "we reconstructed it".
MATCH_METHOD_PULSE_ID: Final[str] = "pulse_id"
MATCH_METHOD_IDENTITY: Final[str] = "identity_fallback"

# Kickoff agreement tolerance for corroboration, in seconds. Providers disagree by minutes on
# a rescheduled fixture without either being wrong; a whole-day slack would let two different
# matches corroborate each other, which is the failure this guards.
KICKOFF_TOLERANCE_SECONDS: Final[float] = 3 * 60 * 60


class SdpIdentityError(RuntimeError):
    """A fixture could not be mapped to exactly one SDP match.

    Raised rather than resolved: an ambiguous or contradictory identity silently attaches one
    club's football metrics to another club's fixture, and no downstream check would catch it.
    """


def _instant(value: object, *, name: str) -> datetime:
    """Rebuild an aware UTC instant from DuckDB `epoch_us()` microseconds.

    Every query below projects `epoch_us(...)` rather than the TIMESTAMPTZ itself. DuckDB
    converts a fetched TIMESTAMPTZ into a Python datetime through `pytz`, which this project
    deliberately does not depend on -- it pins `tzdata` for `zoneinfo` -- so fetching one
    directly raises ModuleNotFoundError on a clean install. Microseconds carry no timezone
    name, so no IANA lookup happens at all.
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SdpSchemaError(f"{name} is not an epoch-microsecond integer: {value!r}")
    return datetime.fromtimestamp(value / 1_000_000, tz=UTC)


def _optional_instant(value: object, *, name: str) -> datetime | None:
    """As `_instant`, but a genuinely absent timestamp stays absent rather than becoming zero."""
    return None if value is None else _instant(value, name=name)


def payload_id(raw: RawPayload) -> str:
    """Content-addressed identity: same request AND same body -> same id.

    Deliberately includes the body hash, so re-fetching unchanged data is idempotent while a
    provider restatement lands as a distinct row alongside the original.
    """
    material = "|".join([PROVIDER, raw.endpoint, raw.path, raw.params_json(), raw.sha256])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def land_payload(
    con: duckdb.DuckDBPyConnection,
    raw: RawPayload,
    *,
    season: str | None = None,
    sdp_match_id: int | None = None,
) -> tuple[str, bool]:
    """Append one provider response. Returns `(payload_id, is_new)`.

    Idempotent by construction: an identical body for an identical request re-derives the same
    `payload_id` and is not written twice.
    """
    identifier = payload_id(raw)
    existing = con.execute(
        "SELECT 1 FROM raw_pl_sdp_payload WHERE payload_id = ?", [identifier]
    ).fetchone()
    if existing:
        return identifier, False
    con.execute(
        """
        INSERT INTO raw_pl_sdp_payload (
            payload_id, provider, endpoint, request_path, params_json, season, sdp_match_id,
            fetched_at, status_code, payload, sha256, byte_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            identifier,
            PROVIDER,
            raw.endpoint,
            raw.path,
            raw.params_json(),
            season,
            sdp_match_id,
            raw.fetched_at,
            raw.status_code,
            raw.text,
            raw.sha256,
            raw.byte_count,
        ],
    )
    return identifier, True


# --------------------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StagingReport:
    """What a staging pass did, and what it could not interpret."""

    payloads_read: int = 0
    matches_staged: int = 0
    team_sides_staged: int = 0
    metric_rows_staged: int = 0
    unmapped_provider_fields: tuple[str, ...] = ()
    schema_failures: tuple[str, ...] = ()


def _coerce(value: Any, metric_type: SdpMetricType) -> tuple[float | None, str | None]:
    """Split a provider value into its numeric and textual renderings.

    Both are kept. The numeric one is what models read; the text one preserves an unparseable
    value so `NULL` never has to stand for "the provider sent something we could not read",
    which is a different fact from "the provider sent nothing".
    """
    if value is None:
        return None, None
    if isinstance(value, bool):
        return float(value), str(value)
    if isinstance(value, int | float):
        return float(value), None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None, None
        try:
            return float(text), None
        except ValueError:
            return None, text
    if isinstance(value, dict | list):
        return None, json.dumps(value, sort_keys=True, separators=(",", ":"))
    return None, str(value)


def _typed(value: float | None, metric_type: SdpMetricType) -> float | int | None:
    if value is None:
        return None
    if metric_type is SdpMetricType.INT:
        return round(value)
    return float(value)


def stage_matches(
    con: duckdb.DuckDBPyConnection, *, season_labels: Mapping[int, str]
) -> StagingReport:
    """Re-derive `stg_pl_sdp_match` from every landed match/matches payload.

    `season_labels` maps the provider's season id to a season label. A match whose season can
    be resolved neither from the payload nor from the landing parameters is SKIPPED and
    counted, never stored under a guessed label -- a wrongly-labelled season would join to the
    wrong set of season-scoped team ids.
    """
    rows = con.execute(
        """
        SELECT payload_id, endpoint, params_json, season, epoch_us(fetched_at), payload
        FROM raw_pl_sdp_payload
        WHERE endpoint IN ('matches', 'match')
        ORDER BY fetched_at, payload_id
        """
    ).fetchall()

    con.execute("DELETE FROM stg_pl_sdp_match")
    staged = 0
    failures: list[str] = []
    for identifier, endpoint, params_json, landed_season, fetched_us, payload_text in rows:
        fetched_at = _instant(fetched_us, name=f"{identifier} fetched_at")
        try:
            payload = json.loads(payload_text)
            single = endpoint == "match" and isinstance(payload, dict)
            records = [payload] if single else extract_items(payload)
            summaries = [parse_match_summary(record) for record in records]
        except (SdpSchemaError, json.JSONDecodeError) as error:
            failures.append(f"{identifier}: {error}")
            continue

        params = json.loads(params_json) if params_json else {}
        param_season_id = params.get("season")
        for summary in summaries:
            season_id = summary.season_id
            if season_id is None and isinstance(param_season_id, int):
                season_id = param_season_id
            mapped = season_labels.get(season_id) if season_id is not None else None
            if landed_season is not None and mapped is not None and landed_season != mapped:
                failures.append(
                    f"{identifier}: match {summary.match_id} landed as season "
                    f"{landed_season!r}, but provider season id {season_id} is configured as "
                    f"{mapped!r}; skipped rather than choosing either label"
                )
                continue
            label = landed_season or mapped
            if label is None:
                failures.append(
                    f"{identifier}: match {summary.match_id} has no resolvable season label "
                    f"(provider season id {season_id!r}); skipped rather than guessed"
                )
                continue
            con.execute(
                """
                INSERT OR REPLACE INTO stg_pl_sdp_match (
                    sdp_match_id, payload_id, known_at, season, sdp_season_id, matchweek,
                    kickoff_time, home_team_name, away_team_name, home_sdp_team_id,
                    away_sdp_team_id, home_score, away_score, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    summary.match_id,
                    identifier,
                    fetched_at,
                    label,
                    season_id,
                    summary.matchweek,
                    summary.kickoff,
                    summary.home_team_name,
                    summary.away_team_name,
                    summary.home_team_id,
                    summary.away_team_id,
                    summary.home_score,
                    summary.away_score,
                    summary.status,
                ],
            )
            staged += 1
    return StagingReport(
        payloads_read=len(rows), matches_staged=staged, schema_failures=tuple(failures)
    )


def stage_team_stats(con: duckdb.DuckDBPyConnection) -> StagingReport:
    """Re-derive the team-side stats tables from every landed `match_stats` payload.

    Every provider field lands in the tall store whether the dictionary claims it or not. A
    field the dictionary DOES claim is additionally written to its typed column -- and two
    aliases of one metric carrying different values in the same payload fails closed rather
    than letting declaration order decide which number becomes the record.
    """
    dictionary = load_sdp_metrics()
    aliases = dictionary.alias_index()
    types = {metric.local_field: metric.type for metric in dictionary.all_fields()}
    typed_columns = sorted(set(aliases.values()))

    rows = con.execute(
        """
        SELECT payload_id, params_json, sdp_match_id, epoch_us(fetched_at), payload
        FROM raw_pl_sdp_payload
        WHERE endpoint = 'match_stats'
        ORDER BY fetched_at, payload_id
        """
    ).fetchall()

    con.execute("DELETE FROM stg_pl_sdp_team_match_stats")
    con.execute("DELETE FROM stg_pl_sdp_team_match_metric")

    sides_staged = 0
    metric_rows = 0
    unmapped: set[str] = set()
    failures: list[str] = []
    for identifier, params_json, landed_match_id, fetched_us, payload_text in rows:
        fetched_at = _instant(fetched_us, name=f"{identifier} fetched_at")
        params = json.loads(params_json) if params_json else {}
        match_id = landed_match_id if landed_match_id is not None else params.get("match_id")
        if not isinstance(match_id, int):
            failures.append(f"{identifier}: stats payload carries no match id")
            continue
        try:
            sides = parse_team_stats(json.loads(payload_text), match_id=match_id)
        except (SdpSchemaError, json.JSONDecodeError) as error:
            failures.append(f"{identifier}: {error}")
            continue

        for side in sides:
            resolved: dict[str, float | None] = {}
            for provider_field, value in side.stats.items():
                local = aliases.get(provider_field)
                numeric, text = _coerce(value, types.get(local or "", SdpMetricType.FLOAT))
                if local is None:
                    unmapped.add(provider_field)
                elif local in resolved and resolved[local] != numeric:
                    raise SdpSchemaError(
                        f"match {match_id} side {side.side}: metric {local!r} is claimed by two "
                        f"provider fields with different values ({resolved[local]!r} then "
                        f"{numeric!r}); refusing to choose one"
                    )
                else:
                    resolved[local] = numeric
                con.execute(
                    """
                    INSERT OR REPLACE INTO stg_pl_sdp_team_match_metric (
                        sdp_match_id, side, payload_id, provider_field, local_field,
                        value_numeric, value_text
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [match_id, side.side, identifier, provider_field, local, numeric, text],
                )
                metric_rows += 1

            fixed = (
                "sdp_match_id",
                "side",
                "payload_id",
                "known_at",
                "sdp_team_id",
                "team_name",
                "stats_json",
                "metric_count",
                "mapped_count",
            )
            columns = [*fixed, *typed_columns]
            parameters: list[object] = [
                match_id,
                side.side,
                identifier,
                fetched_at,
                side.team_id,
                side.team_name,
                json.dumps(dict(side.stats), sort_keys=True, separators=(",", ":")),
                len(side.stats),
                len(resolved),
                *(
                    _typed(resolved.get(column), types.get(column, SdpMetricType.FLOAT))
                    for column in typed_columns
                ),
            ]
            con.execute(
                f"""
                INSERT OR REPLACE INTO stg_pl_sdp_team_match_stats
                    ({", ".join(f'"{column}"' for column in columns)})
                VALUES ({", ".join("?" for _ in columns)})
                """,
                parameters,
            )
            sides_staged += 1

    return StagingReport(
        payloads_read=len(rows),
        team_sides_staged=sides_staged,
        metric_rows_staged=metric_rows,
        unmapped_provider_fields=tuple(sorted(unmapped)),
        schema_failures=tuple(failures),
    )


# --------------------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FixtureIdentity:
    """One FPL fixture, reduced to the dimensions identity may be corroborated on."""

    season: str
    fixture: int
    pulse_id: int | None
    kickoff_time: datetime | None
    home_team_code: int | None
    away_team_code: int | None
    home_score: int | None
    away_score: int | None


@dataclass
class IdentityAudit:
    """The measured answer to `pulse_id == sdp_match_id`, and what it cost to get it."""

    fpl_fixtures: int = 0
    sdp_matches: int = 0
    matched_by_pulse_id: int = 0
    matched_by_identity_fallback: int = 0
    unmatched_fpl_fixtures: int = 0
    unmatched_sdp_matches: int = 0
    pulse_id_present: int = 0
    pulse_id_exact_matches: int = 0
    kickoff_corroborated: int = 0
    teams_corroborated: int = 0
    score_corroborated: int = 0
    ambiguities: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)
    by_season: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def pulse_id_match_rate(self) -> float | None:
        """Share of pulse-id-bearing fixtures whose pulse_id IS an SDP match id.

        `None` rather than 0.0 when nothing carried a pulse_id: "the question could not be
        asked" and "the answer is no" are different findings.
        """
        if self.pulse_id_present == 0:
            return None
        return self.pulse_id_exact_matches / self.pulse_id_present


def _fixture_identities(
    con: duckdb.DuckDBPyConnection, seasons: Sequence[str] | None
) -> list[FixtureIdentity]:
    predicate = ""
    params: list[object] = []
    if seasons:
        predicate = f"WHERE f.season IN ({', '.join('?' for _ in seasons)})"
        params = list(seasons)
    rows = con.execute(
        f"""
        WITH archive_fixture AS (
            SELECT f.season, f.fixture, f.pulse_id, f.kickoff_time,
                   th.team_code AS home_team_code, ta.team_code AS away_team_code,
                   f.team_h_score, f.team_a_score
            FROM stg_fixture AS f
            LEFT JOIN mart_dim_team AS th
              ON th.season = f.season AND th.team_id = f.team_h
            LEFT JOIN mart_dim_team AS ta
              ON ta.season = f.season AND ta.team_id = f.team_a
        ), live_ranked AS (
            SELECT l.season, l.fixture, l.pulse_id, l.kickoff_time,
                   th.team_code AS home_team_code, ta.team_code AS away_team_code,
                   f.team_h_score, f.team_a_score,
                   row_number() OVER (
                       PARTITION BY l.season, l.fixture
                       ORDER BY l.known_at DESC, l.capture_id DESC
                   ) AS version_rank
            FROM mart_team_fixture_live AS l
            JOIN stg_live_fixture_version AS f
              ON f.season = l.season AND f.fixture = l.fixture
             AND f.capture_id = l.capture_id
             AND f.team_h = l.team_id
             AND f.team_a = l.opponent_team_id
            LEFT JOIN stg_live_team_version AS th
              ON th.season = l.season AND th.team_id = l.team_id
             AND th.capture_id = l.capture_id
            LEFT JOIN stg_live_team_version AS ta
              ON ta.season = l.season AND ta.team_id = l.opponent_team_id
             AND ta.capture_id = l.capture_id
            WHERE l.was_home
        ), combined AS (
            SELECT * FROM archive_fixture
            UNION ALL
            SELECT l.* EXCLUDE (version_rank)
            FROM live_ranked AS l
            WHERE l.version_rank = 1
              AND NOT EXISTS (
                  SELECT 1 FROM stg_fixture AS a
                  WHERE a.season = l.season AND a.fixture = l.fixture
              )
        )
        SELECT f.season, f.fixture, f.pulse_id, epoch_us(f.kickoff_time),
               f.home_team_code, f.away_team_code,
               f.team_h_score, f.team_a_score
        FROM combined AS f
        {predicate}
        ORDER BY f.season, f.fixture
        """,
        params,
    ).fetchall()
    return [
        FixtureIdentity(
            season=str(season),
            fixture=int(fixture),
            pulse_id=None if pulse_id is None or int(pulse_id) <= 0 else int(pulse_id),
            kickoff_time=_optional_instant(kickoff, name=f"{season} fixture {fixture} kickoff"),
            home_team_code=None if home is None else int(home),
            away_team_code=None if away is None else int(away),
            home_score=None if hs is None else int(hs),
            away_score=None if as_ is None else int(as_),
        )
        for season, fixture, pulse_id, kickoff, home, away, hs, as_ in rows
    ]


def _latest_sdp_matches(con: duckdb.DuckDBPyConnection) -> dict[int, dict[str, Any]]:
    """Newest staged version per SDP match id."""
    rows = con.execute(
        """
        WITH ranked AS (
            SELECT *, row_number() OVER (
                PARTITION BY sdp_match_id ORDER BY known_at DESC, payload_id DESC
            ) AS version_rank
            FROM stg_pl_sdp_match
        )
        SELECT sdp_match_id, season, matchweek, epoch_us(kickoff_time), home_team_name,
               away_team_name, home_sdp_team_id, away_sdp_team_id,
               home_score, away_score
        FROM ranked WHERE version_rank = 1
        """
    ).fetchall()
    return {
        int(row[0]): {
            "season": row[1],
            "matchweek": row[2],
            "kickoff_time": _optional_instant(row[3], name=f"sdp match {row[0]} kickoff"),
            "home_team_name": row[4],
            "away_team_name": row[5],
            "home_sdp_team_id": row[6],
            "away_sdp_team_id": row[7],
            "home_score": row[8],
            "away_score": row[9],
        }
        for row in rows
    }


def _kickoffs_agree(left: datetime | None, right: datetime | None) -> bool | None:
    if left is None or right is None:
        return None
    return abs((left - right).total_seconds()) <= KICKOFF_TOLERANCE_SECONDS


def _scores_agree(fixture: FixtureIdentity, match: Mapping[str, Any]) -> bool | None:
    if fixture.home_score is None or fixture.away_score is None:
        return None
    if match["home_score"] is None or match["away_score"] is None:
        return None
    return bool(
        fixture.home_score == match["home_score"] and fixture.away_score == match["away_score"]
    )


def resolve_crosswalk(
    con: duckdb.DuckDBPyConnection,
    *,
    seasons: Sequence[str] | None = None,
    team_name_codes: Mapping[str, int] | None = None,
    strict: bool = True,
) -> IdentityAudit:
    """Populate `stg_pl_sdp_fixture_crosswalk` and report what the mapping actually is.

    Resolution order, per fixture:

      1. `pulse_id == sdp_match_id`, corroborated on season, kickoff and score;
      2. a deterministic fallback on `(season, kickoff within tolerance)` narrowed by score,
         used only when it lands on EXACTLY ONE candidate.

    Both paths refuse a contradiction. Under `strict` a contradiction raises; otherwise it is
    recorded and the fixture is left unmapped. There is no name-similarity matching anywhere:
    club names are used only to corroborate a match already made by other means, because a
    fuzzy name match that is wrong is indistinguishable from one that is right.
    """
    fixtures = _fixture_identities(con, seasons)
    matches = _latest_sdp_matches(con)
    audit = IdentityAudit(fpl_fixtures=len(fixtures), sdp_matches=len(matches))

    if seasons:
        con.execute(
            f"DELETE FROM stg_pl_sdp_fixture_crosswalk "
            f"WHERE season IN ({', '.join('?' for _ in seasons)})",
            list(seasons),
        )
    else:
        con.execute("DELETE FROM stg_pl_sdp_fixture_crosswalk")
    resolved_at = datetime.now(UTC)
    claimed = {
        int(match_id): (str(season), int(fixture))
        for season, fixture, match_id in con.execute(
            "SELECT season, fixture, sdp_match_id FROM stg_pl_sdp_fixture_crosswalk"
        ).fetchall()
    }

    by_season_kickoff: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for match_id, match in matches.items():
        by_season_kickoff.setdefault(str(match["season"]), []).append((match_id, match))

    for fixture in fixtures:
        season_stats = audit.by_season.setdefault(
            fixture.season, {"fixtures": 0, "pulse_id": 0, "fallback": 0, "unmatched": 0}
        )
        season_stats["fixtures"] += 1
        if fixture.pulse_id is not None:
            audit.pulse_id_present += 1

        chosen: int | None = None
        method = ""

        pulse_contradiction: str | None = None
        candidate = matches.get(fixture.pulse_id) if fixture.pulse_id is not None else None
        if candidate is not None:
            audit.pulse_id_exact_matches += 1
            if str(candidate["season"]) != fixture.season:
                pulse_contradiction = (
                    f"{fixture.season} fixture {fixture.fixture}: pulse_id {fixture.pulse_id} "
                    f"is an SDP match in season {candidate['season']!r}"
                )
            elif _kickoffs_agree(fixture.kickoff_time, candidate["kickoff_time"]) is False:
                pulse_contradiction = (
                    f"{fixture.season} fixture {fixture.fixture}: pulse_id {fixture.pulse_id} "
                    f"kickoff {candidate['kickoff_time']} disagrees with {fixture.kickoff_time}"
                )
            elif _scores_agree(fixture, candidate) is False:
                pulse_contradiction = (
                    f"{fixture.season} fixture {fixture.fixture}: pulse_id {fixture.pulse_id} "
                    f"score {candidate['home_score']}-{candidate['away_score']} disagrees with "
                    f"{fixture.home_score}-{fixture.away_score}"
                )
            else:
                chosen, method = fixture.pulse_id, MATCH_METHOD_PULSE_ID
            if pulse_contradiction is not None:
                audit.contradictions.append(pulse_contradiction)

        if chosen is None and pulse_contradiction is None and fixture.kickoff_time is not None:
            pool = [
                (match_id, match)
                for match_id, match in by_season_kickoff.get(fixture.season, [])
                if _kickoffs_agree(fixture.kickoff_time, match["kickoff_time"])
            ]
            if len(pool) > 1:
                narrowed = [
                    (match_id, match)
                    for match_id, match in pool
                    if _teams_corroborated(fixture, match, team_name_codes) is True
                ]
                if narrowed:
                    pool = narrowed
            if len(pool) > 1 and fixture.home_score is not None:
                narrowed = [
                    (match_id, match) for match_id, match in pool if _scores_agree(fixture, match)
                ]
                if narrowed:
                    pool = narrowed
            if len(pool) == 1:
                chosen, method = pool[0][0], MATCH_METHOD_IDENTITY
            elif len(pool) > 1:
                audit.ambiguities.append(
                    f"{fixture.season} fixture {fixture.fixture}: {len(pool)} SDP matches share "
                    f"its kickoff and score; refusing to guess between "
                    f"{sorted(match_id for match_id, _ in pool)}"
                )

        if chosen is None:
            audit.unmatched_fpl_fixtures += 1
            season_stats["unmatched"] += 1
            continue
        if chosen in claimed:
            other_season, other_fixture = claimed[chosen]
            audit.ambiguities.append(
                f"SDP match {chosen} is claimed by both {other_season} fixture {other_fixture} "
                f"and {fixture.season} fixture {fixture.fixture}"
            )
            audit.unmatched_fpl_fixtures += 1
            season_stats["unmatched"] += 1
            continue

        match = matches[chosen]
        kickoff_ok = _kickoffs_agree(fixture.kickoff_time, match["kickoff_time"])
        score_ok = _scores_agree(fixture, match)
        teams_ok = _teams_corroborated(fixture, match, team_name_codes)
        audit.kickoff_corroborated += int(kickoff_ok is True)
        audit.score_corroborated += int(score_ok is True)
        audit.teams_corroborated += int(teams_ok is True)
        if teams_ok is False:
            audit.contradictions.append(
                f"{fixture.season} fixture {fixture.fixture}: SDP match {chosen} home/away "
                f"team identities disagree (SDP teamId {match['home_sdp_team_id']!r}/"
                f"{match['away_sdp_team_id']!r}, FPL permanent team_code "
                f"{fixture.home_team_code!r}/{fixture.away_team_code!r})"
            )
            audit.unmatched_fpl_fixtures += 1
            season_stats["unmatched"] += 1
            continue
        if method == MATCH_METHOD_PULSE_ID:
            audit.matched_by_pulse_id += 1
            season_stats["pulse_id"] += 1
        else:
            audit.matched_by_identity_fallback += 1
            season_stats["fallback"] += 1
        claimed[chosen] = (fixture.season, fixture.fixture)
        con.execute(
            """
            INSERT INTO stg_pl_sdp_fixture_crosswalk (
                season, fixture, sdp_match_id, match_method, pulse_id,
                corroborated_kickoff, corroborated_teams, corroborated_score, resolved_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                fixture.season,
                fixture.fixture,
                chosen,
                method,
                fixture.pulse_id,
                kickoff_ok,
                teams_ok,
                score_ok,
                resolved_at,
            ],
        )

    audit.unmatched_sdp_matches = len(set(matches) - set(claimed))
    if strict and (audit.ambiguities or audit.contradictions):
        raise SdpIdentityError(
            "fixture identity did not resolve cleanly: "
            f"{len(audit.contradictions)} contradiction(s), {len(audit.ambiguities)} "
            f"ambiguity/ambiguities. First: "
            f"{(audit.contradictions + audit.ambiguities)[0]}"
        )
    return audit


def _teams_corroborated(
    fixture: FixtureIdentity,
    match: Mapping[str, Any],
    team_name_codes: Mapping[str, int] | None,
) -> bool | None:
    """Whether both clubs agree, resolved through an explicit name -> team_code map.

    SDP ``teamId`` equals FPL's permanent ``team_code``. Exact ids take precedence; names are
    the fallback.
    Returns `None` when the question cannot be asked. That is deliberately not `False`: missing
    identity evidence must not be reported as disagreement.
    """
    home_provider_id = match.get("home_sdp_team_id")
    away_provider_id = match.get("away_sdp_team_id")
    if (
        fixture.home_team_code is not None
        and fixture.away_team_code is not None
        and home_provider_id is not None
        and away_provider_id is not None
    ):
        return bool(
            fixture.home_team_code == int(home_provider_id)
            and fixture.away_team_code == int(away_provider_id)
        )
    if team_name_codes is None:
        return None
    home_name, away_name = match.get("home_team_name"), match.get("away_team_name")
    if not isinstance(home_name, str) or not isinstance(away_name, str):
        return None
    home_code = team_name_codes.get(home_name.strip().casefold())
    away_code = team_name_codes.get(away_name.strip().casefold())
    if home_code is None or away_code is None:
        return None
    if fixture.home_team_code is None or fixture.away_team_code is None:
        return None
    return bool(home_code == fixture.home_team_code and away_code == fixture.away_team_code)


def team_name_code_map(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Club name / short name -> permanent `team_code`, from the season-scoped dimension.

    Built for corroboration only. A name that resolves to two different clubs across seasons
    is DROPPED rather than resolved to either -- corroboration that can be wrong is worse than
    corroboration that is absent.
    """
    rows = con.execute(
        """
        SELECT team_name, short_name, team_code
        FROM mart_dim_team WHERE team_code IS NOT NULL
        UNION ALL
        SELECT team_name, short_name, team_code
        FROM stg_live_team_version WHERE team_code IS NOT NULL
        """
    ).fetchall()
    seen: dict[str, set[int]] = {}
    for team_name, short_name, team_code in rows:
        for label in (team_name, short_name):
            if isinstance(label, str) and label.strip():
                seen.setdefault(label.strip().casefold(), set()).add(int(team_code))
    return {label: next(iter(codes)) for label, codes in seen.items() if len(codes) == 1}
