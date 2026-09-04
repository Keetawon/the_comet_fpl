"""The V2 football fact and the descriptive tactical-state mart.

`mart_fact_team_match_stats_v2` is deliberately provider-tagged rather than provider-specific.
Two providers write to it:

  * `fpl_archive` -- derived from marts already in this repository. Available for every season,
    so the V2 engine is runnable and evaluable before any external capture exists.
  * `pl_sdp` -- the Premier League backend, once captured. Richer, but network-dependent.

They occupy the same grain so they can be COMPARED. Where both measure the same concept by
different routes the two values are kept in different columns and neither is used to fill the
other -- `expected_goals_allowed` (the opponent's xG, mirrored across the fixture) and
`expected_goals_conceded_measured` (FPL's own per-player xGC) are the standing example.

Opponent mirrors are derived by pairing the two sides of a fixture, and ONLY where the mirror
is semantically valid. `shots_allowed` is the opponent's `shots`; there is no meaningful mirror
of `possession`, because the opponent's possession is not a different quantity -- it is
`100 - possession`, and inventing a column for it would double-count one measurement.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import duckdb

from fpl.config import load_sdp_metrics
from fpl.storage.db import table_columns, table_exists
from fpl.transform.pl_sdp import ARCHIVE_PROVIDER, PROVIDER

# Rolling windows, matching mart_fact_player_form / mart_fact_team_form exactly so a reader
# does not have to learn a second window vocabulary.
WINDOWS: Final[tuple[tuple[str, int | None], ...]] = (
    ("last_3", 3),
    ("last_5", 5),
    ("last_10", 10),
    ("season_to_date", None),
)

# Metrics the archive provider can populate, and the SQL that derives each. Everything else
# stays NULL for this provider: unmeasured, not zero.
#
# `shots_on_target_allowed_proxy` is the load-bearing one. A goalkeeper's `saves +
# goals_conceded` is the count of on-target shots he dealt with, so summing it over a club's
# goalkeeper rows in a fixture gives a measured team-level shots-on-target-allowed from
# 2021-22 -- which is what lets GK Saves V2 be evaluated with no external data at all. It is
# NULL, not zero, when a club fielded no recorded goalkeeper in a fixture, and NULL when
# either component is unmeasured, because a keeper with unrecorded saves faced an unknown
# number of shots rather than none.
_ARCHIVE_METRIC_SQL: Final[dict[str, str]] = {
    "goals": "t.goals_for",
    "expected_goals": "t.team_xg",
    "expected_goals_conceded_measured": "t.team_xgc",
    "bps": "t.team_bps",
    "shots_on_target_allowed_proxy": "gk.shots_on_target_faced",
    "defensive_actions": "actions.defensive_actions",
    "yellow_cards": "cards.yellow_cards",
    "red_cards": "cards.red_cards",
    "saves": "gk.saves",
}

# Which archive-derived metrics get an opponent mirror. `goals -> goals_allowed` and
# `expected_goals -> expected_goals_allowed` are the pairs whose mirror is a genuinely
# different measurement of the opponent's output rather than a restatement of this side's.
# `saves` is deliberately absent: the opponent's saves is not "saves allowed", it is the
# opponent's own goalkeeping, and a column implying otherwise would be read wrongly.
_ARCHIVE_MIRRORED: Final[tuple[str, ...]] = ("goals", "expected_goals")


@dataclass(frozen=True, slots=True)
class FootballV2Counts:
    team_match_stats_rows: int = 0
    tactical_form_rows: int = 0
    providers: tuple[str, ...] = ()
    # Set when the optional V2 layer could not be built. A rebuild reports it and continues.
    skipped_reason: str | None = None


def _available(con: duckdb.DuckDBPyConnection, table: str, columns: Sequence[str]) -> list[str]:
    present = set(table_columns(con, table))
    return [column for column in columns if column in present]


def build_team_match_stats_archive(con: duckdb.DuckDBPyConnection) -> int:
    """Populate the `fpl_archive` provider rows from marts already in this repository.

    Grain is guaranteed by construction: the row set is `mart_fact_team_match`, which is built
    from the fixture list rather than by grouping player rows, so a club with no player rows in
    some match still gets its row and the two sides of every fixture are always present.

    `known_at` is the fixture's kickoff. That is the honest knowledge time for an archive-derived
    observation: it is what the row describes, and the archive carries no capture timestamp that
    could say when it actually became available.
    """
    dictionary = load_sdp_metrics()
    mirrors = dictionary.mirror_fields()
    mart_columns = set(table_columns(con, "mart_fact_team_match_stats_v2"))
    metrics = [name for name in _ARCHIVE_METRIC_SQL if name in mart_columns]
    mirror_columns = [
        mirrors[name] for name in _ARCHIVE_MIRRORED if name in mirrors and name in metrics
    ]

    con.execute("DELETE FROM mart_fact_team_match_stats_v2 WHERE provider = ?", [ARCHIVE_PROVIDER])

    metric_select = ",\n               ".join(
        f'{_ARCHIVE_METRIC_SQL[name]} AS "{name}"' for name in metrics
    )
    mirror_select = ",\n               ".join(
        f'opp."{name}" AS "{mirrors[name]}"'
        for name in _ARCHIVE_MIRRORED
        if mirrors.get(name) in mirror_columns
    )
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
        *metrics,
        *mirror_columns,
    ]
    con.execute(
        f"""
        INSERT INTO mart_fact_team_match_stats_v2 ({", ".join(f'"{c}"' for c in columns)})
        WITH gk AS (
            -- On-target shots a club faced, measured through its goalkeepers. Both components
            -- must be measured for the row to count; SUM over an all-NULL group is NULL, which
            -- is exactly right and is why this is SQL rather than Polars.
            SELECT season, fixture, team_id,
                   sum(saves + goals_conceded) AS shots_on_target_faced,
                   sum(saves) AS saves
            FROM mart_fact_player_fixture
            WHERE position = 'GK' AND minutes > 0
            GROUP BY season, fixture, team_id
        ),
        actions AS (
            SELECT season, fixture, team_id,
                   sum(tackles + recoveries + clearances_blocks_interceptions)
                       AS defensive_actions
            FROM mart_fact_player_fixture
            GROUP BY season, fixture, team_id
        ),
        cards AS (
            SELECT season, fixture, team_id,
                   sum(yellow_cards) AS yellow_cards,
                   sum(red_cards) AS red_cards
            FROM mart_fact_player_fixture
            GROUP BY season, fixture, team_id
        ),
        base AS (
            SELECT t.season, t.gw, t.fixture, t.pulse_id, t.kickoff_time,
                   t.team_id, dt.team_code, t.opponent_team_id, dopp.team_code
                       AS opponent_team_code,
                   t.was_home,
                   {metric_select}
            FROM mart_fact_team_match AS t
            LEFT JOIN mart_dim_team AS dt ON dt.season = t.season AND dt.team_id = t.team_id
            LEFT JOIN mart_dim_team AS dopp
                   ON dopp.season = t.season AND dopp.team_id = t.opponent_team_id
            LEFT JOIN gk ON gk.season = t.season AND gk.fixture = t.fixture
                        AND gk.team_id = t.team_id
            LEFT JOIN actions ON actions.season = t.season AND actions.fixture = t.fixture
                             AND actions.team_id = t.team_id
            LEFT JOIN cards ON cards.season = t.season AND cards.fixture = t.fixture
                           AND cards.team_id = t.team_id
        )
        SELECT b.season, b.gw, b.fixture, b.pulse_id, NULL AS sdp_match_id, b.kickoff_time,
               b.team_id, b.team_code, b.opponent_team_id, b.opponent_team_code, b.was_home,
               '{ARCHIVE_PROVIDER}' AS provider, b.kickoff_time AS known_at,
               {", ".join(f'b."{name}"' for name in metrics)}
               {"," if mirror_select else ""}
               {mirror_select}
        FROM base AS b
        LEFT JOIN base AS opp
               ON opp.season = b.season AND opp.fixture = b.fixture
              AND opp.team_id = b.opponent_team_id
        """
    )
    row = con.execute(
        "SELECT count(*) FROM mart_fact_team_match_stats_v2 WHERE provider = ?",
        [ARCHIVE_PROVIDER],
    ).fetchone()
    return int(row[0]) if row else 0


def build_team_match_stats_sdp(con: duckdb.DuckDBPyConnection) -> int:
    """Populate the `pl_sdp` provider rows, joined through the measured fixture crosswalk.

    Only fixtures the crosswalk resolved contribute. An SDP match with no crosswalk row is not
    guessed into place: the identity audit is the single place that decides what maps to what,
    and a mart that quietly disagreed with it would make the audit meaningless.
    """
    if not table_exists(con, "stg_pl_sdp_fixture_crosswalk"):
        return 0
    dictionary = load_sdp_metrics()
    mart_columns = set(table_columns(con, "mart_fact_team_match_stats_v2"))
    staged_columns = set(table_columns(con, "stg_pl_sdp_team_match_stats"))
    metrics = [
        metric.local_field
        for metric in dictionary.metrics
        if metric.local_field in mart_columns and metric.local_field in staged_columns
    ]
    mirrors = dictionary.mirror_fields()
    mirrored = [name for name in metrics if mirrors.get(name) in mart_columns]

    con.execute("DELETE FROM mart_fact_team_match_stats_v2 WHERE provider = ?", [PROVIDER])
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
        *metrics,
        *[mirrors[name] for name in mirrored],
    ]
    metric_select = ", ".join(f'st."{name}"' for name in metrics)
    mirror_select = ", ".join(f'opp."{name}" AS "{mirrors[name]}"' for name in mirrored)
    con.execute(
        f"""
        INSERT INTO mart_fact_team_match_stats_v2 ({", ".join(f'"{c}"' for c in columns)})
        WITH latest AS (
            SELECT *, row_number() OVER (
                PARTITION BY sdp_match_id, side ORDER BY known_at DESC, payload_id DESC
            ) AS version_rank
            FROM stg_pl_sdp_team_match_stats
        ),
        sided AS (SELECT * FROM latest WHERE version_rank = 1),
        archive_anchor AS (
            SELECT t.season, t.gw, t.fixture, t.pulse_id, t.kickoff_time,
                   t.team_id, dt.team_code, t.opponent_team_id,
                   dopp.team_code AS opponent_team_code, t.was_home
            FROM mart_fact_team_match AS t
            LEFT JOIN mart_dim_team AS dt
              ON dt.season = t.season AND dt.team_id = t.team_id
            LEFT JOIN mart_dim_team AS dopp
              ON dopp.season = t.season AND dopp.team_id = t.opponent_team_id
        ),
        live_capture AS (
            SELECT season, fixture, capture_id, known_at,
                   row_number() OVER (
                       PARTITION BY season, fixture ORDER BY known_at DESC, capture_id DESC
                   ) AS version_rank
            FROM mart_team_fixture_live
            GROUP BY season, fixture, capture_id, known_at
        ),
        live_anchor AS (
            SELECT l.season, l.gw, l.fixture, l.pulse_id, l.kickoff_time,
                   l.team_id, dt.team_code, l.opponent_team_id,
                   dopp.team_code AS opponent_team_code, l.was_home
            FROM live_capture AS c
            JOIN mart_team_fixture_live AS l
              ON l.season = c.season AND l.fixture = c.fixture
             AND l.capture_id = c.capture_id
            LEFT JOIN stg_live_team_version AS dt
              ON dt.season = l.season AND dt.team_id = l.team_id
             AND dt.capture_id = l.capture_id
            LEFT JOIN stg_live_team_version AS dopp
              ON dopp.season = l.season AND dopp.team_id = l.opponent_team_id
             AND dopp.capture_id = l.capture_id
            WHERE c.version_rank = 1 AND l.kickoff_time IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM mart_fact_team_match AS a
                  WHERE a.season = l.season AND a.fixture = l.fixture
              )
        ),
        anchor AS (
            SELECT * FROM archive_anchor
            UNION ALL
            SELECT * FROM live_anchor
        )
        SELECT t.season, t.gw, t.fixture, t.pulse_id, x.sdp_match_id, t.kickoff_time,
               t.team_id, t.team_code, t.opponent_team_id, t.opponent_team_code,
               t.was_home, '{PROVIDER}' AS provider, st.known_at
               {", " if metric_select else ""}{metric_select}
               {", " if mirror_select else ""}{mirror_select}
        FROM anchor AS t
        JOIN stg_pl_sdp_fixture_crosswalk AS x
          ON x.season = t.season AND x.fixture = t.fixture
        JOIN sided AS st
          ON st.sdp_match_id = x.sdp_match_id
         AND st.side = CASE WHEN t.was_home THEN 'home' ELSE 'away' END
        LEFT JOIN sided AS opp
          ON opp.sdp_match_id = x.sdp_match_id
         AND opp.side = CASE WHEN t.was_home THEN 'away' ELSE 'home' END
        """
    )
    row = con.execute(
        "SELECT count(*) FROM mart_fact_team_match_stats_v2 WHERE provider = ?", [PROVIDER]
    ).fetchone()
    return int(row[0]) if row else 0


# --------------------------------------------------------------------------------------
# Tactical form
# --------------------------------------------------------------------------------------

# Derived ratio indices: (column, numerator expression, denominator expression).
#
# Every one is NULL when an input is unmeasured or the denominator is zero. These are
# DESCRIPTIVE interpretations of style, not model quantities and not objective truth -- an
# index earns its way into a model only by improving a proper score, which is what
# config/v2_team_environment_evaluation.yaml is for.
_DERIVED_INDICES: Final[tuple[tuple[str, str, str], ...]] = (
    ("shot_accuracy", "shots_on_target", "shots"),
    ("shot_quality", "expected_goals", "shots"),
    ("finishing_quality", "expected_goals_on_target", "expected_goals"),
    ("pass_accuracy", "accurate_passes", "passes"),
    ("forward_pass_ratio", "forward_passes", "passes"),
    ("long_pass_ratio", "long_passes", "passes"),
    ("cross_accuracy", "accurate_crosses", "crosses"),
    ("tackle_success_rate", "tackles_won", "tackles"),
    ("duel_win_rate", "duels_won", "duels_won + duels_lost"),
    ("aerial_win_rate", "aerial_duels_won", "aerial_duels_won + aerial_duels_lost"),
    (
        "high_press_share",
        "possession_won_attacking_third",
        "possession_won_attacking_third + possession_won_middle_third "
        "+ possession_won_defensive_third",
    ),
    (
        "low_block_share",
        "possession_won_defensive_third",
        "possession_won_attacking_third + possession_won_middle_third "
        "+ possession_won_defensive_third",
    ),
    (
        "defensive_volume",
        "tackles + interceptions + clearances + blocks + recoveries",
        "1",
    ),
    (
        "territorial_dominance",
        "touches_in_opposition_box",
        "touches_in_opposition_box + touches_in_own_box_allowed",
    ),
)


def build_team_tactical_form(con: duckdb.DuckDBPyConnection) -> int:
    """Rolling descriptive team state per `team_code`, anchored on observed gameweeks.

    Anchoring is identical to `mart_fact_team_form`: the window ends at the anchor gameweek
    inclusive, its cutoff is that gameweek's latest kickoff, both legs of a double gameweek
    count, and no row is fabricated for a blank gameweek. Keying on `team_code` rather than
    `team_id` is not a preference -- `team_id` is reassigned every season and a cross-season
    rolling window built on it silently splices two clubs together.

    This mart is DESCRIPTIVE. It is registered as feature-readable and its columns are
    registered as outcomes, so a point-in-time view hard-filters it like any other observation.
    """
    if not table_exists(con, "mart_fact_team_match_stats_v2"):
        return 0
    dictionary = load_sdp_metrics()
    mart_columns = set(table_columns(con, "mart_fact_team_match_stats_v2"))
    form_columns = set(table_columns(con, "mart_fact_team_tactical_form_v2"))
    metrics = [
        name
        for name in (
            *[metric.local_field for metric in dictionary.all_fields()],
            *dictionary.mirror_fields().values(),
        )
        if name in mart_columns and f"{name}_per_match" in form_columns
    ]
    derived = [
        (column, numerator, denominator)
        for column, numerator, denominator in _DERIVED_INDICES
        if column in form_columns
        and all(
            token in mart_columns
            for token in _referenced_columns(numerator) | _referenced_columns(denominator)
        )
    ]

    con.execute("DELETE FROM mart_fact_team_tactical_form_v2")
    total = 0
    for window_name, length in WINDOWS:
        # A rolling mean over the trailing `length` matches, or the season to date. `RANGE`
        # over the anchor's kickoff rather than `ROWS` so both legs of a double gameweek fall
        # inside the same anchor rather than one of them being cut off mid-gameweek.
        frame = (
            f"ROWS BETWEEN {length - 1} PRECEDING AND CURRENT ROW"
            if length is not None
            else "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW"
        )
        averages = ", ".join(f'avg("{name}") OVER w AS "{name}_per_match"' for name in metrics)
        derived_select = ", ".join(
            f"CASE WHEN sum({denominator}) OVER w > 0 "
            f"THEN sum({numerator}) OVER w / CAST(sum({denominator}) OVER w AS DOUBLE) "
            f'ELSE NULL END AS "{column}"'
            for column, numerator, denominator in derived
        )
        columns = [
            "season",
            "gw",
            "team_code",
            "provider",
            '"window"',
            "as_at_kickoff",
            "matches",
            *[f'"{name}_per_match"' for name in metrics],
            *[f'"{column}"' for column, _, _ in derived],
        ]
        con.execute(
            f"""
            INSERT INTO mart_fact_team_tactical_form_v2 ({", ".join(columns)})
            WITH rolled AS (
                SELECT season, gw, team_code, provider, kickoff_time,
                       count(*) OVER w AS matches
                       {", " if averages else ""}{averages}
                       {", " if derived_select else ""}{derived_select}
                FROM mart_fact_team_match_stats_v2
                WHERE team_code IS NOT NULL AND gw IS NOT NULL
                WINDOW w AS (
                    PARTITION BY provider, team_code, season
                    ORDER BY kickoff_time, fixture
                    {frame}
                )
            ),
            anchored AS (
                SELECT *, row_number() OVER (
                    PARTITION BY provider, team_code, season, gw
                    ORDER BY kickoff_time DESC
                ) AS leg_rank
                FROM rolled
            )
            SELECT season, gw, team_code, provider, '{window_name}', kickoff_time, matches
                   {", " if metrics else ""}
                   {", ".join(f'"{name}_per_match"' for name in metrics)}
                   {", " if derived else ""}
                   {", ".join(f'"{column}"' for column, _, _ in derived)}
            FROM anchored WHERE leg_rank = 1
            """
        )
        row = con.execute(
            'SELECT count(*) FROM mart_fact_team_tactical_form_v2 WHERE "window" = ?',
            [window_name],
        ).fetchone()
        total += int(row[0]) if row else 0
    return total


def _referenced_columns(expression: str) -> set[str]:
    """Column names an index expression depends on, so a missing input skips the index."""
    tokens = {
        token.strip()
        for token in expression.replace("+", " ").replace("-", " ").replace("*", " ").split()
    }
    return {token for token in tokens if token and not token.isdigit()}


# Tables and columns the archive provider derives from. The V2 layer is OPTIONAL: a rebuild
# whose component marts are absent or not yet in their current shape must degrade to "no V2
# rows" rather than failing, because V2 is an addition to a pipeline that has to keep working
# without it. The check is on the specific columns used, not merely on table existence, so a
# legacy database cloned by the failure-atomic rebuild is recognised before it produces a
# confusing binder error deep inside a CTE.
_ARCHIVE_SOURCE_REQUIREMENTS: Final[dict[str, tuple[str, ...]]] = {
    "mart_fact_team_match": ("season", "fixture", "team_id", "was_home", "kickoff_time"),
    "mart_fact_player_fixture": ("season", "fixture", "team_id", "position", "minutes"),
    "mart_dim_team": ("season", "team_id", "team_code"),
    "mart_fact_team_match_stats_v2": ("season", "fixture", "team_id", "provider"),
}


def archive_sources_ready(con: duckdb.DuckDBPyConnection) -> str | None:
    """`None` when the archive provider can be built, else why it cannot."""
    for table, required in _ARCHIVE_SOURCE_REQUIREMENTS.items():
        if not table_exists(con, table):
            return f"{table} does not exist"
        missing = sorted(set(required) - set(table_columns(con, table)))
        if missing:
            return f"{table} is missing column(s) {missing}"
    return None


def build_all(con: duckdb.DuckDBPyConnection) -> FootballV2Counts:
    """Rebuild the whole V2 football layer from whatever providers have data."""
    blocked = archive_sources_ready(con)
    if blocked is not None:
        return FootballV2Counts(skipped_reason=blocked)
    archive_rows = build_team_match_stats_archive(con)
    sdp_rows = build_team_match_stats_sdp(con)
    form_rows = build_team_tactical_form(con)
    providers = tuple(
        str(row[0])
        for row in con.execute(
            "SELECT DISTINCT provider FROM mart_fact_team_match_stats_v2 ORDER BY provider"
        ).fetchall()
    )
    return FootballV2Counts(
        team_match_stats_rows=archive_rows + sdp_rows,
        tactical_form_rows=form_rows,
        providers=providers,
    )
