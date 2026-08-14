"""stg_ -> mart_: the modelling-ready tables.

The mart is split by table role, not by layer:

  mart_fact_player_fixture   components only, no points column of any kind. The only
                             player-level table the feature builder may read.
  mart_target_player_fixture recorded points plus points recomputed under each configured
                             ruleset. Read by the validation harness and the dashboard.

The split exists because recorded `total_points` is denominated in whichever season's
rules applied at the time. It is not a cross-season quantity, so it cannot be a model
target -- R1 restated. Models predict, and backtests score against,
`points_under_rules_2026_27`; `total_points_as_recorded` is retained only to benchmark
against FPL's own `ep_next`, which was produced under contemporaneous rules.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import polars as pl

from fpl.config import ScoringRules, available_rulesets, load_scoring_rules
from fpl.models.scoring import calculate_points, components_required_by
from fpl.storage.db import points_column_for
from fpl.types import PlayerMatchStats, Position, RulesetId, Season

# Components carried into the fact table. `total_points` is deliberately absent, and
# tests/test_grain.py asserts no column here matches "points" at all.
_COMPONENT_COLUMNS: tuple[str, ...] = (
    "minutes",
    "starts",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "penalties_saved",
    "penalties_missed",
    "own_goals",
    "yellow_cards",
    "red_cards",
    "bonus",
    "bps",
    "expected_goals",
    "expected_assists",
    "expected_goals_conceded",
    "threat",
    "creativity",
    "influence",
    "defensive_contribution",
    "tackles",
    "recoveries",
    "clearances_blocks_interceptions",
    "value",
    "selected",
    "transfers_in",
    "transfers_out",
)


@dataclass(frozen=True, slots=True)
class FactCounts:
    player_fixture_rows: int
    team_match_rows: int
    target_rows: int
    player_form_rows: int = 0


class PlayerFormSourceError(ValueError):
    """A player-form source mart cannot support its declared player-fixture grain."""


def build_dimensions(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("DELETE FROM mart_dim_player")
    con.execute(
        """
        INSERT INTO mart_dim_player
            (code, season, element_id, web_name, position, team_id, opta_code)
        SELECT code, season, element, web_name, position, team_id, opta_code
        FROM stg_player
        """
    )
    con.execute("DELETE FROM mart_dim_team")
    con.execute(
        """
        INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name, pulse_id)
        SELECT season, team_id, team_code, team_name, short_name, pulse_id FROM stg_team
        """
    )


def build_player_stints(con: duckdb.DuckDBPyConnection) -> int:
    """One row per club spell a player had inside a season.

    `mart_dim_player` carries only the club a player finished the season at, which is wrong
    for about half of all transfer stints -- measured 242 stints across five seasons, of
    which the dimension matches 120. Eze played GW1-2 for Crystal Palace and GW3-38 for
    Arsenal; Buonanotte had three clubs in 2025-26.

    Getting this wrong is not cosmetic. A player's attacking *share* travels with him but the
    team *scale* does not, and defensive-contribution rates are a property of the team system
    rather than the player -- measured team hit rates range from 0.333 to 0.146. Resolving a
    transferred player's club through the dimension attributes the wrong team strength and
    the wrong DC environment to roughly 25 players per season, silently.

    Built from the fact rows, whose `team_id` is correct per fixture (verified: zero rows
    where the recorded team is not one of the two sides of that fixture).
    """
    con.execute("DELETE FROM mart_dim_player_stint")
    con.execute(
        """
        INSERT INTO mart_dim_player_stint (
            season, code, team_id, stint_index, first_gw, last_gw,
            first_kickoff, last_kickoff, appearances, minutes
        )
        WITH spells AS (
            SELECT season, code, team_id,
                   min(gw) AS first_gw, max(gw) AS last_gw,
                   min(kickoff_time) AS first_kickoff, max(kickoff_time) AS last_kickoff,
                   count(*) AS appearances,
                   sum(minutes) AS minutes
            FROM mart_fact_player_fixture
            GROUP BY season, code, team_id
        )
        SELECT season, code, team_id,
               CAST(row_number() OVER (
                   PARTITION BY season, code ORDER BY first_kickoff
               ) AS INTEGER) AS stint_index,
               first_gw, last_gw, first_kickoff, last_kickoff,
               CAST(appearances AS INTEGER), CAST(minutes AS INTEGER)
        FROM spells
        """
    )
    return _scalar(con, "SELECT count(*) FROM mart_dim_player_stint")


def build_player_fixture(con: duckdb.DuckDBPyConnection) -> int:
    """Components only. Expected: 138,707 rows."""
    columns = ", ".join(_COMPONENT_COLUMNS)
    con.execute("DELETE FROM mart_fact_player_fixture")
    con.execute(
        f"""
        INSERT INTO mart_fact_player_fixture (
            season, gw, fixture, pulse_id, kickoff_time, code, position,
            team_id, opponent_team_id, was_home, {columns}
        )
        SELECT s.season, s.gw, s.fixture, f.pulse_id, s.kickoff_time, s.code, s.position,
               s.team_id, s.opponent_team_id, s.was_home,
               {", ".join(f"s.{column}" for column in _COMPONENT_COLUMNS)}
        FROM stg_player_fixture AS s
        LEFT JOIN stg_fixture AS f ON f.season = s.season AND f.fixture = s.fixture
        """
    )
    return _scalar(con, "SELECT count(*) FROM mart_fact_player_fixture")


def build_team_match(con: duckdb.DuckDBPyConnection) -> int:
    """One row per team per fixture. Expected: exactly 3,800.

    Built from `stg_fixture` rather than by grouping player rows, so the grain is
    guaranteed by construction -- two sides per fixture, 380 fixtures per season -- and a
    team with no player rows in some match still gets its row.

    Aggregates are null-guarded. SQL `SUM`/`MAX` return NULL for an all-NULL group, which
    is what we need: 2021-22 has no xG columns at all, and a 0.0 there would be a
    measurement claim we cannot make (gotcha 5). Polars' `sum()` returns 0.0 in that case,
    which is exactly the trap that dragged an early audit's team_xg mean to 1.08 against a
    true 1.41 -- hence building this in SQL.
    """
    con.execute("DELETE FROM mart_fact_team_match")
    con.execute(
        """
        INSERT INTO mart_fact_team_match (
            season, gw, fixture, pulse_id, kickoff_time, team_id, opponent_team_id,
            was_home, goals_for, goals_against, team_xg, team_xgc, team_bps, rest_days, fdr
        )
        WITH sides AS (
            SELECT season, fixture, pulse_id, gw, kickoff_time,
                   team_h AS team_id, team_a AS opponent_team_id, TRUE AS was_home,
                   team_h_score AS goals_for, team_a_score AS goals_against,
                   team_h_difficulty AS fdr
            FROM stg_fixture
            UNION ALL
            SELECT season, fixture, pulse_id, gw, kickoff_time,
                   team_a AS team_id, team_h AS opponent_team_id, FALSE AS was_home,
                   team_a_score AS goals_for, team_h_score AS goals_against,
                   team_a_difficulty AS fdr
            FROM stg_fixture
        ),
        player_agg AS (
            SELECT season, fixture, team_id,
                   sum(expected_goals) AS team_xg,
                   -- Player xGC is literally team xGC during that player's minutes, so
                   -- the team value is the maximum over the squad, not the sum.
                   -- Validated on 2025-26: mean 1.395 against actual conceded 1.375.
                   max(expected_goals_conceded) AS team_xgc,
                   sum(bps) AS team_bps
            FROM stg_player_fixture
            GROUP BY season, fixture, team_id
        ),
        with_rest AS (
            -- `AT TIME ZONE 'UTC'` converts each TIMESTAMPTZ to a naive UTC TIMESTAMP
            -- before the diff. Without it, date_diff('day', ...) counts calendar-day
            -- boundaries in the *session* timezone, so this column's value would depend on
            -- the machine that ran the build: the same pair of kickoffs measures 2 days
            -- apart under UTC and 1 under Asia/Bangkok. The connection is already pinned to
            -- UTC; this makes the column correct regardless of that setting.
            SELECT s.*,
                   date_diff(
                       'day',
                       lag(s.kickoff_time AT TIME ZONE 'UTC') OVER (
                           PARTITION BY s.season, s.team_id ORDER BY s.kickoff_time
                       ),
                       s.kickoff_time AT TIME ZONE 'UTC'
                   ) AS rest_days
            FROM sides AS s
        )
        SELECT w.season, w.gw, w.fixture, w.pulse_id, w.kickoff_time, w.team_id,
               w.opponent_team_id, w.was_home, w.goals_for, w.goals_against,
               a.team_xg, a.team_xgc, CAST(a.team_bps AS INTEGER), w.rest_days, w.fdr
        FROM with_rest AS w
        LEFT JOIN player_agg AS a
          ON a.season = w.season AND a.fixture = w.fixture AND a.team_id = w.team_id
        """
    )
    return _scalar(con, "SELECT count(*) FROM mart_fact_team_match")


def build_targets(
    con: duckdb.DuckDBPyConnection, ruleset_ids: list[RulesetId] | None = None
) -> int:
    """Build mart_target_player_fixture and its completeness report.

    Recomputation runs through `calculate_points`, so the target table and the replay
    test exercise the same code path.
    """
    rulesets = ruleset_ids or available_rulesets()
    con.execute("DELETE FROM mart_target_player_fixture")
    con.execute(
        """
        INSERT INTO mart_target_player_fixture
            (season, gw, fixture, kickoff_time, code, position, total_points_as_recorded)
        SELECT season, gw, fixture, kickoff_time, code, position, total_points
        FROM stg_player_fixture
        """
    )

    for ruleset_id in rulesets:
        rules = load_scoring_rules(ruleset_id)
        _recompute_points(con, rules)
        _record_completeness(con, rules)

    return _scalar(con, "SELECT count(*) FROM mart_target_player_fixture")


def build_player_form(con: duckdb.DuckDBPyConnection) -> int:
    """Materialize descriptive player form at ``(season, gw, code, window)`` grain.

    A ``mart_fact_player_fixture`` row is the rostered population.  Availability therefore counts
    every such row, including zero-minute rows; productivity measures deliberately use only rows
    with ``minutes >= 1``.  The four windows are anchored on observed gameweeks rather than an
    assumed ``1..38`` sequence.  Their cutoff is the last observed kickoff in the anchor gameweek,
    so a double gameweek is complete at its one player-gameweek row while a later gameweek cannot
    leak backwards.

    ``expected_goals`` and ``expected_assists`` retain their measurement coverage: their sums and
    per-90 denominators include only appeared rows where the respective signal is non-NULL.  A
    starts total is NULL if any rostered source row in the window has unmeasured starts; treating
    the entirely unmeasured 2021-22 column as zero would manufacture availability data.
    """
    _assert_player_form_source_grain(con)
    con.execute("DELETE FROM mart_fact_player_form")
    con.execute(
        """
        INSERT INTO mart_fact_player_form (
            season, gw, code, "window", rostered_fixtures, appearances, starts, did_not_play,
            minutes, goals_scored, assists, bonus, bps, defensive_contribution, expected_goals,
            expected_assists, expected_goals_per_90, expected_assists_per_90,
            points_under_rules_2026_27
        )
        WITH rostered AS (
            SELECT
                f.season,
                f.gw,
                f.fixture,
                f.kickoff_time,
                f.code,
                f.minutes,
                f.starts,
                f.goals_scored,
                f.assists,
                f.bonus,
                f.bps,
                f.defensive_contribution,
                f.expected_goals,
                f.expected_assists,
                t.points_under_rules_2026_27
            FROM mart_fact_player_fixture AS f
            LEFT JOIN mart_target_player_fixture AS t
              ON t.season = f.season
             AND t.code = f.code
             AND t.fixture = f.fixture
        ),
        gameweek_cutoffs AS (
            SELECT season, gw, max(kickoff_time) AS last_kickoff
            FROM rostered
            GROUP BY season, gw
        ),
        anchors AS (
            SELECT DISTINCT r.season, r.gw, r.code, c.last_kickoff
            FROM rostered AS r
            JOIN gameweek_cutoffs AS c
              ON c.season = r.season
             AND c.gw = r.gw
        ),
        windows AS (
            SELECT 'last_3' AS window_label, 3 AS fixture_limit
            UNION ALL SELECT 'last_5', 5
            UNION ALL SELECT 'last_10', 10
            UNION ALL SELECT 'season_to_date', NULL
        ),
        ranked AS (
            SELECT
                a.season,
                a.gw,
                a.code,
                w.window_label,
                w.fixture_limit,
                r.minutes,
                r.starts,
                r.goals_scored,
                r.assists,
                r.bonus,
                r.bps,
                r.defensive_contribution,
                r.expected_goals,
                r.expected_assists,
                r.points_under_rules_2026_27,
                row_number() OVER (
                    PARTITION BY a.season, a.gw, a.code, w.window_label
                    ORDER BY r.kickoff_time DESC, r.fixture DESC
                ) AS recency_rank
            FROM anchors AS a
            CROSS JOIN windows AS w
            JOIN rostered AS r
              ON r.season = a.season
             AND r.code = a.code
             AND r.gw <= a.gw
             AND r.kickoff_time <= a.last_kickoff
        ),
        selected AS (
            SELECT *
            FROM ranked
            WHERE fixture_limit IS NULL OR recency_rank <= fixture_limit
        )
        SELECT
            season,
            gw,
            code,
            window_label,
            CAST(count(*) AS INTEGER) AS rostered_fixtures,
            CAST(count(*) FILTER (WHERE minutes >= 1) AS INTEGER) AS appearances,
            CASE
                WHEN count(starts) = count(*) THEN CAST(sum(starts) AS INTEGER)
            END AS starts,
            CAST(count(*) FILTER (WHERE minutes = 0) AS INTEGER) AS did_not_play,
            CAST(sum(minutes) AS INTEGER) AS minutes,
            CAST(sum(goals_scored) FILTER (WHERE minutes >= 1) AS INTEGER) AS goals_scored,
            CAST(sum(assists) FILTER (WHERE minutes >= 1) AS INTEGER) AS assists,
            CAST(sum(bonus) FILTER (WHERE minutes >= 1) AS INTEGER) AS bonus,
            CAST(sum(bps) FILTER (WHERE minutes >= 1) AS INTEGER) AS bps,
            CAST(
                sum(defensive_contribution) FILTER (WHERE minutes >= 1) AS INTEGER
            ) AS defensive_contribution,
            sum(expected_goals) FILTER (WHERE minutes >= 1) AS expected_goals,
            sum(expected_assists) FILTER (WHERE minutes >= 1) AS expected_assists,
            CASE
                WHEN sum(
                    CASE WHEN minutes >= 1 AND expected_goals IS NOT NULL THEN minutes END
                ) > 0
                THEN 90.0 * sum(expected_goals) FILTER (WHERE minutes >= 1)
                    / sum(
                        CASE WHEN minutes >= 1 AND expected_goals IS NOT NULL THEN minutes END
                    )
            END AS expected_goals_per_90,
            CASE
                WHEN sum(
                    CASE WHEN minutes >= 1 AND expected_assists IS NOT NULL THEN minutes END
                ) > 0
                THEN 90.0 * sum(expected_assists) FILTER (WHERE minutes >= 1)
                    / sum(
                        CASE WHEN minutes >= 1 AND expected_assists IS NOT NULL THEN minutes END
                    )
            END AS expected_assists_per_90,
            CASE
                WHEN count(*) FILTER (WHERE minutes >= 1) = 0 THEN NULL
                WHEN count(points_under_rules_2026_27) FILTER (WHERE minutes >= 1)
                    <> count(*) FILTER (WHERE minutes >= 1) THEN NULL
                ELSE CAST(
                    sum(points_under_rules_2026_27) FILTER (WHERE minutes >= 1) AS INTEGER
                )
            END AS points_under_rules_2026_27
        FROM selected
        GROUP BY season, gw, code, window_label
        """
    )
    return _scalar(con, "SELECT count(*) FROM mart_fact_player_form")


def _assert_player_form_source_grain(con: duckdb.DuckDBPyConnection) -> None:
    """Fail closed if a hand-built or migrated source would fan out the form aggregation."""
    for table in ("mart_fact_player_fixture", "mart_target_player_fixture"):
        duplicate_keys = _scalar(
            con,
            f"""
            SELECT count(*) FROM (
                SELECT season, code, fixture
                FROM {table}
                GROUP BY season, code, fixture
                HAVING count(*) > 1
            )
            """,
        )
        if duplicate_keys:
            raise PlayerFormSourceError(
                f"{table} has {duplicate_keys} duplicate player-fixture key(s); "
                "a form window cannot deduplicate real double gameweeks"
            )
    null_minutes = _scalar(
        con, "SELECT count(*) FROM mart_fact_player_fixture WHERE minutes IS NULL"
    )
    if null_minutes:
        raise PlayerFormSourceError(
            f"mart_fact_player_fixture has {null_minutes} NULL minutes value(s); "
            "rostered availability cannot be reported without a measured minutes outcome"
        )


def _recompute_points(con: duckdb.DuckDBPyConnection, rules: ScoringRules) -> None:
    """Fill `points_under_rules_<ruleset>` from components, via the calculator.

    Deliberately routed through `calculate_points` one row at a time rather than
    reimplemented as SQL. A vectorised copy of the scoring logic would be a second
    implementation to keep in step with the first, and the replay test would no longer
    cover the code path that builds the targets.
    """
    column = points_column_for(rules.ruleset_id)
    frame = con.execute(
        """
        SELECT season, code, fixture, position, minutes, goals_scored, assists,
               clean_sheets, goals_conceded, saves, penalties_saved, penalties_missed,
               own_goals, yellow_cards, red_cards, bonus, defensive_contribution
        FROM stg_player_fixture
        """
    ).pl()

    positions = {label: Position(label) for label in frame["position"].unique().to_list()}
    points: list[int] = []
    for row in frame.iter_rows(named=True):
        stats = PlayerMatchStats(
            minutes=_zero_if_null(row["minutes"]),
            goals_scored=_zero_if_null(row["goals_scored"]),
            assists=_zero_if_null(row["assists"]),
            clean_sheets=_zero_if_null(row["clean_sheets"]),
            goals_conceded=_zero_if_null(row["goals_conceded"]),
            saves=_zero_if_null(row["saves"]),
            penalties_saved=_zero_if_null(row["penalties_saved"]),
            penalties_missed=_zero_if_null(row["penalties_missed"]),
            own_goals=_zero_if_null(row["own_goals"]),
            yellow_cards=_zero_if_null(row["yellow_cards"]),
            red_cards=_zero_if_null(row["red_cards"]),
            bonus=_zero_if_null(row["bonus"]),
            # Preserved as None: unmeasured before 2025-26, and a zero here would be a
            # claim that the player made no defensive actions.
            defensive_contribution=row["defensive_contribution"],
        )
        points.append(calculate_points(stats, rules, positions[row["position"]]))

    recomputed = frame.select("season", "code", "fixture").with_columns(
        pl.Series("points", points, dtype=pl.Int32)
    )
    con.register("_recomputed", recomputed)
    try:
        con.execute(
            f"""
            UPDATE mart_target_player_fixture AS t
            SET "{column}" = r.points
            FROM _recomputed AS r
            WHERE t.season = r.season AND t.code = r.code AND t.fixture = r.fixture
            """
        )
    finally:
        con.unregister("_recomputed")


def _record_completeness(con: duckdb.DuckDBPyConnection, rules: ScoringRules) -> None:
    """Record, per season, which components this ruleset needs but the season lacks.

    Without this the recomputed target is quietly biased: applying 2026/27 rules to
    2021-22 understates every defender, because `defensive_contribution` did not exist
    then. The bias is real and unavoidable; recording it means the validation harness can
    exclude or weight those seasons instead of trusting a broken target.
    """
    required = sorted(components_required_by(rules))
    # One pass: non-null count per required component per season.
    counts = ", ".join(f'count("{component}") AS "{component}"' for component in required)
    rows = con.execute(
        f"""
        SELECT season, count(*) AS row_count, {counts}
        FROM stg_player_fixture GROUP BY season ORDER BY season
        """
    ).pl()

    con.execute("DELETE FROM mart_target_completeness WHERE ruleset_id = ?", [rules.ruleset_id])
    for row in rows.iter_rows(named=True):
        missing = [component for component in required if row[component] == 0]
        con.execute(
            """
            INSERT INTO mart_target_completeness
                (season, ruleset_id, missing_components, is_complete, row_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            [row["season"], rules.ruleset_id, ",".join(missing), not missing, row["row_count"]],
        )


def build_all(con: duckdb.DuckDBPyConnection) -> FactCounts:
    build_dimensions(con)
    player_fixture_rows = build_player_fixture(con)
    # After the facts: stints are derived from them, because the fact row's team_id is the
    # only per-fixture-correct record of which club a player turned out for.
    build_player_stints(con)
    team_match_rows = build_team_match(con)
    target_rows = build_targets(con)
    player_form_rows = build_player_form(con)
    return FactCounts(
        player_fixture_rows=player_fixture_rows,
        team_match_rows=team_match_rows,
        target_rows=target_rows,
        player_form_rows=player_form_rows,
    )


def _zero_if_null(value: int | None) -> int:
    """Basic components are always measured in the archive; treat a NULL as 0 defensively.

    This applies ONLY to components the archive always records. It is deliberately not
    applied to `defensive_contribution`, where NULL means "not measured" and must survive.
    """
    return 0 if value is None else int(value)


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[object] | None = None) -> int:
    row = con.execute(sql, params or []).fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def target_points_column(season: Season) -> str:
    """The R1-safe target column for a season's ruleset."""
    from fpl.types import ruleset_id_for_season

    return points_column_for(ruleset_id_for_season(season))
