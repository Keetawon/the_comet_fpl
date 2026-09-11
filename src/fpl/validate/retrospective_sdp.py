"""Validation-only access to later-captured historical Premier League SOT.

This is deliberately separate from :class:`fpl.features.pit.PointInTimeView`.
It relaxes capture-time validity for retrospective development, but never event-time
causality: every returned match kicked off before ``as_of`` and has a recorded final score.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

import duckdb
import polars as pl

from fpl.features.pit import AsOf
from fpl.transform.pl_sdp import ARCHIVE_PROVIDER, SdpIdentityError
from fpl.transform.pl_sdp import PROVIDER as SDP_PROVIDER

EvidenceClass = Literal["retrospective_backfill_development"]

EVIDENCE_CLASS: Final[EvidenceClass] = "retrospective_backfill_development"
SOT_PROVIDER_FIELD: Final[str] = "ontargetScoringAtt"
SOT_LOCAL_FIELD: Final[str] = "shots_on_target"
VERSION_SELECTION_POLICY: Final[str] = (
    "earliest_successful_complete_match_stats_payload_by_fetched_at_then_payload_id"
)


class RetrospectiveBackfillView:
    """Read-only validation capability for REAL historical SDP shots on target.

    The caller supplies a read-only DuckDB connection.  Unlike ``PointInTimeView``, this
    class intentionally permits ``source_known_at > as_of``.  The original timestamp and
    content-addressed payload identity remain on every returned row; they are never rewritten.
    """

    __slots__ = ("_as_of", "_con")

    EVIDENCE_CLASS: Final[EvidenceClass] = EVIDENCE_CLASS
    PROVIDER: Final[str] = SDP_PROVIDER
    PROVIDER_FIELD: Final[str] = SOT_PROVIDER_FIELD
    VERSION_POLICY: Final[str] = VERSION_SELECTION_POLICY

    def __init__(self, con: duckdb.DuckDBPyConnection, as_of: AsOf) -> None:
        if not isinstance(as_of, AsOf):
            raise TypeError("as_of must be an AsOf, not a bare datetime")
        self._con = con
        self._as_of = as_of

    @property
    def as_of(self) -> AsOf:
        return self._as_of

    @property
    def evidence_class(self) -> EvidenceClass:
        return EVIDENCE_CLASS

    def observed_real_sot(self, *, seasons: Sequence[str] | None = None) -> pl.DataFrame:
        """Return completed pre-``as_of`` archive rows with exact REAL SDP SOT evidence.

        Capture selection is made at whole-payload grain before the SOT metric is joined.
        A payload is successful only when its HTTP capture succeeded and exactly one staged
        home and away side exist.  The earliest such payload wins deterministically.  The
        exact corroborated provider field is then left-joined, so an absent or NULL value
        remains NULL and no alias or later revision can fill it.
        """
        season_predicate, params = self._season_predicate(seasons)
        common = self._common_ctes(season_predicate)

        missing_crosswalk = self._con.execute(
            f"""
            {common}
            SELECT a.season, a.fixture
            FROM archive_anchor AS a
            LEFT JOIN stg_pl_sdp_fixture_crosswalk AS x
              ON x.season = a.season AND x.fixture = a.fixture
            WHERE x.sdp_match_id IS NULL
            ORDER BY a.season, a.fixture
            LIMIT 1
            """,
            params,
        ).fetchone()
        if missing_crosswalk is not None:
            season, fixture = missing_crosswalk
            raise SdpIdentityError(
                f"{season} fixture {fixture}: completed archive fixture has no SDP crosswalk"
            )

        uncorroborated = self._con.execute(
            f"""
            {common}
            SELECT a.season, a.fixture, x.sdp_match_id
            FROM archive_anchor AS a
            JOIN stg_pl_sdp_fixture_crosswalk AS x
              ON x.season = a.season AND x.fixture = a.fixture
            WHERE x.corroborated_kickoff IS DISTINCT FROM TRUE
               OR x.corroborated_teams IS DISTINCT FROM TRUE
               OR x.corroborated_score IS DISTINCT FROM TRUE
            ORDER BY a.season, a.fixture
            LIMIT 1
            """,
            params,
        ).fetchone()
        if uncorroborated is not None:
            season, fixture, match_id = uncorroborated
            raise SdpIdentityError(
                f"{season} fixture {fixture}: SDP match {match_id} crosswalk is not fully "
                "corroborated on kickoff, teams, and score"
            )

        invalid_anchor = self._con.execute(
            f"""
            {common}
            SELECT season, fixture, team_code, opponent_team_code
            FROM archive_anchor
            WHERE team_code IS NULL OR opponent_team_code IS NULL
               OR team_code = opponent_team_code
            ORDER BY season, fixture
            LIMIT 1
            """,
            params,
        ).fetchone()
        if invalid_anchor is not None:
            season, fixture, team_code, opponent_team_code = invalid_anchor
            raise SdpIdentityError(
                f"{season} fixture {fixture}: invalid permanent team identity "
                f"{team_code!r} vs {opponent_team_code!r}"
            )

        mismatch = self._con.execute(
            f"""
            {common}
            SELECT a.season, a.fixture, x.sdp_match_id, s.side,
                   s.sdp_team_id, a.team_code
            FROM archive_anchor AS a
            JOIN stg_pl_sdp_fixture_crosswalk AS x
              ON x.season = a.season AND x.fixture = a.fixture
            JOIN selected_payload AS p ON p.sdp_match_id = x.sdp_match_id
            JOIN stg_pl_sdp_team_match_stats AS s
              ON s.sdp_match_id = p.sdp_match_id AND s.payload_id = p.payload_id
             AND s.side = CASE WHEN a.was_home THEN 'home' ELSE 'away' END
            WHERE s.sdp_team_id IS NULL OR s.sdp_team_id <> a.team_code
            ORDER BY a.season, a.fixture, s.side
            LIMIT 1
            """,
            params,
        ).fetchone()
        if mismatch is not None:
            season, fixture, match_id, side, sdp_team_id, team_code = mismatch
            raise SdpIdentityError(
                f"{season} fixture {fixture}: SDP match {match_id} {side} stats teamId "
                f"{sdp_team_id!r} disagrees with FPL permanent team_code {team_code!r}"
            )

        relation = self._con.execute(
            f"""
            {common}
            SELECT a.season, a.gw, a.fixture, a.pulse_id, x.sdp_match_id,
                   a.kickoff_time, a.team_id, a.team_code, a.opponent_team_id,
                   a.opponent_team_code, a.was_home,
                   a.goals, a.goals_allowed, a.expected_goals,
                   a.expected_goals_allowed,
                   m.value_numeric AS shots_on_target,
                   p.payload_id AS capture_id,
                   p.fetched_at AS source_known_at,
                   p.sha256 AS payload_sha256,
                   '{SDP_PROVIDER}' AS source_provider,
                   '{SOT_PROVIDER_FIELD}' AS provider_field,
                   '{EVIDENCE_CLASS}' AS evidence_class,
                   '{VERSION_SELECTION_POLICY}' AS version_selection_policy
            FROM archive_anchor AS a
            JOIN stg_pl_sdp_fixture_crosswalk AS x
              ON x.season = a.season AND x.fixture = a.fixture
            LEFT JOIN selected_payload AS p ON p.sdp_match_id = x.sdp_match_id
            LEFT JOIN stg_pl_sdp_team_match_stats AS s
              ON s.sdp_match_id = p.sdp_match_id AND s.payload_id = p.payload_id
             AND s.side = CASE WHEN a.was_home THEN 'home' ELSE 'away' END
            LEFT JOIN stg_pl_sdp_team_match_metric AS m
              ON m.sdp_match_id = s.sdp_match_id AND m.side = s.side
             AND m.payload_id = s.payload_id
             AND m.provider_field = '{SOT_PROVIDER_FIELD}'
             AND m.local_field = '{SOT_LOCAL_FIELD}'
            ORDER BY a.kickoff_time, a.season, a.fixture, a.was_home DESC, a.team_code
            """,
            params,
        )
        frame: pl.DataFrame = pl.from_arrow(relation.to_arrow_table())  # type: ignore[assignment]
        invalid_sot = frame.filter(
            pl.col("shots_on_target").is_not_null()
            & (
                ~pl.col("shots_on_target").is_finite()
                | (pl.col("shots_on_target") < 0)
                | (pl.col("shots_on_target") != pl.col("shots_on_target").round(0))
            )
        )
        if not invalid_sot.is_empty():
            row = invalid_sot.select("season", "fixture", "team_code", "shots_on_target").row(
                0, named=True
            )
            raise ValueError(f"shots_on_target must be a non-negative count, got {row}")
        return frame.with_columns(pl.col("shots_on_target").cast(pl.Int64))

    def _season_predicate(self, seasons: Sequence[str] | None) -> tuple[str, list[object]]:
        params: list[object] = [self._as_of.ts]
        if seasons is None:
            return "", params
        if not seasons:
            return "AND FALSE", params
        params.extend(seasons)
        return f"AND a.season IN ({', '.join('?' for _ in seasons)})", params

    @staticmethod
    def _common_ctes(season_predicate: str) -> str:
        return f"""
            WITH archive_anchor AS (
                SELECT a.season, a.gw, a.fixture, a.pulse_id, a.kickoff_time,
                       a.team_id, a.team_code, a.opponent_team_id,
                       a.opponent_team_code, a.was_home,
                       a.goals, a.goals_allowed, a.expected_goals,
                       a.expected_goals_allowed
                FROM mart_fact_team_match_stats_v2 AS a
                WHERE a.provider = '{ARCHIVE_PROVIDER}'
                  AND a.kickoff_time < ?
                  AND a.goals IS NOT NULL AND a.goals_allowed IS NOT NULL
                  AND a.gw IS NOT NULL
                  {season_predicate}
            ),
            complete_sides AS (
                SELECT sdp_match_id, payload_id, min(known_at) AS known_at
                FROM stg_pl_sdp_team_match_stats
                GROUP BY sdp_match_id, payload_id
                HAVING count(*) = 2
                   AND count(*) FILTER (WHERE side = 'home') = 1
                   AND count(*) FILTER (WHERE side = 'away') = 1
                   AND count(sdp_team_id) = 2
                   AND count(DISTINCT sdp_team_id) = 2
                   AND min(known_at) = max(known_at)
            ),
            numeric_sides AS (
                SELECT sdp_match_id, payload_id
                FROM stg_pl_sdp_team_match_metric
                WHERE side IN ('home', 'away')
                GROUP BY sdp_match_id, payload_id
                HAVING count(DISTINCT CASE
                    WHEN value_numeric IS NOT NULL AND isfinite(value_numeric) THEN side
                END) = 2
            ),
            complete_payload AS (
                SELECT r.sdp_match_id, r.payload_id, r.fetched_at, r.sha256
                FROM raw_pl_sdp_payload AS r
                JOIN complete_sides AS s
                  ON s.sdp_match_id = r.sdp_match_id AND s.payload_id = r.payload_id
                JOIN numeric_sides AS n
                  ON n.sdp_match_id = r.sdp_match_id AND n.payload_id = r.payload_id
                WHERE r.provider = '{SDP_PROVIDER}' AND r.endpoint = 'match_stats'
                  AND r.status_code BETWEEN 200 AND 299
                  AND s.known_at = r.fetched_at
            ),
            ranked_payload AS (
                SELECT *, row_number() OVER (
                    PARTITION BY sdp_match_id ORDER BY fetched_at, payload_id
                ) AS version_rank
                FROM complete_payload
            ),
            selected_payload AS (
                SELECT sdp_match_id, payload_id, fetched_at, sha256
                FROM ranked_payload WHERE version_rank = 1
            )
        """
