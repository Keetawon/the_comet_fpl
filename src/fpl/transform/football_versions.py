"""Retained SDP revisions for strict point-in-time football readers.

The reporting fact is latest-only. This additive read model keeps each complete stats
payload paired with each retained fixture-metadata capture instead. Availability is the
later of those two knowledge times; neither timestamp is rewritten to kickoff. Readers
must filter that availability before selecting one revision per team-fixture.
"""

from __future__ import annotations

import duckdb

from fpl.config import load_sdp_metrics
from fpl.storage.db import table_columns, table_exists
from fpl.transform.pl_sdp import PROVIDER, SdpIdentityError

_TABLE = "mart_fact_team_match_stats_v2_version"

# A fixture's retained metadata versions must not be collapsed to the latest snapshot:
# even a corrected kickoff/gameweek received tomorrow cannot change yesterday's features.
_SOURCE_CTES = """
    WITH complete_payload AS (
        SELECT st.sdp_match_id, st.payload_id
        FROM stg_pl_sdp_team_match_stats AS st
        GROUP BY st.sdp_match_id, st.payload_id
        HAVING count(*) = 2 AND count(DISTINCT st.side) = 2
           AND bool_and(st.side IN ('home', 'away'))
           AND bool_and(EXISTS (
               SELECT 1 FROM json_each(st.stats_json) AS metric
               WHERE metric.type IN ('BIGINT', 'UBIGINT', 'DOUBLE', 'VARCHAR')
                 AND isfinite(try_cast(json_extract_string(metric.value, '$') AS DOUBLE))
           ))
    ),
    sided AS (
        SELECT st.* FROM stg_pl_sdp_team_match_stats AS st
        JOIN complete_payload AS c USING (sdp_match_id, payload_id)
    ),
    archive_anchor AS (
        SELECT t.season, t.gw, t.fixture, t.pulse_id, t.kickoff_time,
               t.team_id, dt.team_code, t.opponent_team_id,
               dopp.team_code AS opponent_team_code, t.was_home,
               'archive' AS metadata_capture_id, t.kickoff_time AS metadata_known_at
        FROM mart_fact_team_match AS t
        LEFT JOIN mart_dim_team AS dt
          ON dt.season = t.season AND dt.team_id = t.team_id
        LEFT JOIN mart_dim_team AS dopp
          ON dopp.season = t.season AND dopp.team_id = t.opponent_team_id
    ),
    live_anchor AS (
        SELECT l.season, l.gw, l.fixture, l.pulse_id, l.kickoff_time,
               l.team_id, dt.team_code, l.opponent_team_id,
               dopp.team_code AS opponent_team_code, l.was_home,
               l.capture_id AS metadata_capture_id,
               greatest(l.known_at, dt.known_at, dopp.known_at) AS metadata_known_at
        FROM mart_team_fixture_live AS l
        JOIN stg_live_team_version AS dt
          ON dt.season = l.season AND dt.team_id = l.team_id
         AND dt.capture_id = l.capture_id
        JOIN stg_live_team_version AS dopp
          ON dopp.season = l.season AND dopp.team_id = l.opponent_team_id
         AND dopp.capture_id = l.capture_id
        WHERE l.kickoff_time IS NOT NULL
          AND dt.team_code IS NOT NULL AND dopp.team_code IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM mart_fact_team_match AS a
              WHERE a.season = l.season AND a.fixture = l.fixture
          )
    ),
    anchor AS (
        SELECT * FROM archive_anchor
        UNION ALL
        SELECT * FROM live_anchor
    ),
    joined AS (
        SELECT t.*, x.sdp_match_id, st.payload_id, st.known_at AS source_known_at,
               st.sdp_team_id, st.side
        FROM anchor AS t
        JOIN stg_pl_sdp_fixture_crosswalk AS x
          ON x.season = t.season AND x.fixture = t.fixture
        JOIN sided AS st
          ON st.sdp_match_id = x.sdp_match_id
         AND st.side = CASE WHEN t.was_home THEN 'home' ELSE 'away' END
    )
"""


def build_team_match_versions(con: duckdb.DuckDBPyConnection) -> int:
    """Append complete, identity-verified SDP payload/metadata pairs, idempotently.

    Incomplete responses remain in raw/staging but cannot displace the last complete
    version. Opponent metrics always come from the other side of the SAME payload.
    Legacy live metadata without both exact-capture stable identities is ineligible;
    it cannot displace an older complete metadata capture or borrow today's registry.
    Archive metadata retains the existing unversioned kickoff-time proxy; it does not
    acquire historical real-deadline provenance through this addition.
    """
    if not table_exists(con, _TABLE) or not table_exists(con, "stg_pl_sdp_fixture_crosswalk"):
        return 0

    missing_anchor = con.execute(
        f"""
        {_SOURCE_CTES}
        SELECT x.season, x.fixture, x.sdp_match_id
        FROM stg_pl_sdp_fixture_crosswalk AS x
        JOIN complete_payload AS c ON c.sdp_match_id = x.sdp_match_id
        WHERE NOT EXISTS (
            SELECT 1 FROM anchor AS a WHERE a.season = x.season AND a.fixture = x.fixture
        )
        ORDER BY x.season, x.fixture LIMIT 1
        """
    ).fetchone()
    if missing_anchor is not None:
        raise SdpIdentityError(f"complete SDP payload has no fixture metadata: {missing_anchor!r}")

    invalid = con.execute(
        f"""
        {_SOURCE_CTES}
        SELECT season, fixture, sdp_match_id, payload_id, metadata_capture_id
        FROM joined
        GROUP BY season, fixture, sdp_match_id, payload_id, metadata_capture_id
        HAVING count(*) <> 2 OR count(DISTINCT side) <> 2
           OR count(DISTINCT team_id) <> 2 OR count(DISTINCT source_known_at) <> 1
           OR count(DISTINCT metadata_known_at) <> 1 OR count(DISTINCT kickoff_time) <> 1
           OR count(DISTINCT gw) > 1 OR count(gw) NOT IN (0, 2)
        ORDER BY season, fixture, payload_id, metadata_capture_id LIMIT 1
        """
    ).fetchone()
    if invalid is not None:
        raise SdpIdentityError(f"invalid reciprocal SDP payload/metadata pair: {invalid!r}")

    mismatch = con.execute(
        f"""
        {_SOURCE_CTES}
        SELECT j.season, j.fixture, j.sdp_match_id, j.side, j.sdp_team_id, j.team_code
        FROM joined AS j
        LEFT JOIN joined AS opp
          ON opp.season = j.season AND opp.fixture = j.fixture
         AND opp.payload_id = j.payload_id
         AND opp.metadata_capture_id = j.metadata_capture_id AND opp.side <> j.side
        WHERE j.sdp_team_id IS NULL OR j.team_code IS NULL
           OR j.sdp_team_id <> j.team_code
           OR j.opponent_team_code IS DISTINCT FROM opp.team_code
           OR j.opponent_team_id IS DISTINCT FROM opp.team_id
           OR j.team_code = j.opponent_team_code
        ORDER BY j.season, j.fixture, j.side LIMIT 1
        """
    ).fetchone()
    if mismatch is not None:
        raise SdpIdentityError(
            f"SDP stats teamId disagrees with permanent team_code/reciprocal side: {mismatch!r}"
        )

    bad_provenance = con.execute(
        f"""
        {_SOURCE_CTES}
        SELECT j.season, j.fixture, j.payload_id
        FROM joined AS j JOIN raw_pl_sdp_payload AS raw ON raw.payload_id = j.payload_id
        WHERE raw.provider <> ? OR raw.endpoint <> 'match_stats' OR raw.status_code <> 200
           OR raw.sdp_match_id IS DISTINCT FROM j.sdp_match_id
           OR raw.season IS DISTINCT FROM j.season
           OR raw.fetched_at IS DISTINCT FROM j.source_known_at
        LIMIT 1
        """,
        [PROVIDER],
    ).fetchone()
    if bad_provenance is not None:
        raise SdpIdentityError(f"SDP raw/staging provenance mismatch: {bad_provenance!r}")

    dictionary = load_sdp_metrics()
    destination = set(table_columns(con, _TABLE))
    staged = set(table_columns(con, "stg_pl_sdp_team_match_stats"))
    metrics = [
        metric.local_field
        for metric in dictionary.metrics
        if metric.local_field in destination and metric.local_field in staged
    ]
    mirrors = dictionary.mirror_fields()
    mirrored = [name for name in metrics if mirrors.get(name) in destination]
    columns = [
        "season",
        "gw",
        "fixture",
        "pulse_id",
        "sdp_match_id",
        "kickoff_time",
        "team_id",
        "team_code",
        "opponent_team_id",
        "opponent_team_code",
        "was_home",
        "provider",
        "known_at",
        "capture_id",
        "payload_sha256",
        "source_known_at",
        "metadata_capture_id",
        "metadata_known_at",
        *metrics,
        *[mirrors[name] for name in mirrored],
    ]
    metric_select = ", ".join(
        [*[f'st."{name}"' for name in metrics], *[f'opp."{name}"' for name in mirrored]]
    )
    con.execute(
        f"""
        INSERT INTO {_TABLE} ({", ".join(f'"{column}"' for column in columns)})
        {_SOURCE_CTES}
        SELECT j.season, j.gw, j.fixture, j.pulse_id, j.sdp_match_id, j.kickoff_time,
               j.team_id, j.team_code, j.opponent_team_id, j.opponent_team_code, j.was_home,
               '{PROVIDER}', greatest(j.source_known_at, j.metadata_known_at),
               j.payload_id, raw.sha256, j.source_known_at,
               j.metadata_capture_id, j.metadata_known_at
               {", " if metric_select else ""}{metric_select}
        FROM joined AS j
        JOIN sided AS st
          ON st.sdp_match_id = j.sdp_match_id AND st.payload_id = j.payload_id
         AND st.side = j.side
        JOIN sided AS opp
          ON opp.sdp_match_id = j.sdp_match_id AND opp.payload_id = j.payload_id
         AND opp.side <> j.side
        LEFT JOIN raw_pl_sdp_payload AS raw ON raw.payload_id = j.payload_id
        ON CONFLICT DO NOTHING
        """
    )
    row = con.execute(f"SELECT count(*) FROM {_TABLE} WHERE provider = ?", [PROVIDER]).fetchone()
    return int(row[0]) if row else 0
