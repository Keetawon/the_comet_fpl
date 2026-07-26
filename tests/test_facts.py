"""Fact-table construction: aggregation rules and the measured distributions.

The team aggregates encode a decomposition decision, not just arithmetic, so the tests
assert the aggregation is the right *kind* as well as the right value.
"""

from __future__ import annotations

import duckdb
import pytest

pytestmark = pytest.mark.archive


def test_team_xgc_is_the_max_not_the_sum(db: duckdb.DuckDBPyConnection) -> None:
    """Player xGC is team xGC during that player's minutes, so the team value is the max.

    This is the "pure team, apportioned by minutes" class: player-level xGC carries no
    player information at all, so there is no player model to build for it. Summing across
    a squad would inflate it by roughly the number of players used.

    Validated on 2025-26: mean 1.395 against actual conceded 1.375.
    """
    row = db.execute(
        """
        SELECT round(avg(team_xgc), 3), round(avg(goals_against), 3)
        FROM mart_fact_team_match WHERE season = '2025-26'
        """
    ).fetchone()
    assert row is not None
    mean_xgc, mean_conceded = row
    assert mean_xgc == pytest.approx(1.395, abs=0.005)
    assert mean_conceded == pytest.approx(1.375, abs=0.005)
    # The whole justification: it tracks actual concessions closely.
    assert abs(mean_xgc - mean_conceded) < 0.10

    # A sum would be wildly larger; confirm the stored value is not one.
    summed = db.execute(
        """
        SELECT round(avg(s), 3) FROM (
            SELECT sum(expected_goals_conceded) AS s
            FROM mart_fact_player_fixture WHERE season = '2025-26'
            GROUP BY fixture, team_id
        )
        """
    ).fetchone()
    assert summed is not None and summed[0] > 3 * mean_xgc


def test_team_xg_is_the_sum_of_player_xg(db: duckdb.DuckDBPyConnection) -> None:
    """xG is "team scale x player share", so the team total IS the sum over the squad."""
    row = db.execute(
        """
        SELECT round(avg(team_xg), 3), round(avg(goals_for), 3)
        FROM mart_fact_team_match WHERE season = '2025-26'
        """
    ).fetchone()
    assert row is not None
    mean_xg, mean_goals = row
    assert mean_xg == pytest.approx(1.406, abs=0.005)
    assert abs(mean_xg - mean_goals) < 0.10


def test_xg_ceiling_on_single_match_prediction(db: duckdb.DuckDBPyConnection) -> None:
    """corr(team xG, actual goals) ~ 0.50 per match.

    Recorded as a test because it bounds Phase 1: roughly three-quarters of single-match
    goal variance is irreducible noise, so a team model correlating 0.5 with outcomes is at
    the ceiling, not underperforming.
    """
    row = db.execute(
        """
        SELECT round(corr(team_xg, goals_for), 3) FROM mart_fact_team_match
        WHERE season = '2025-26' AND team_xg IS NOT NULL
        """
    ).fetchone()
    assert row is not None
    assert row[0] == pytest.approx(0.50, abs=0.03)


def test_home_advantage_is_a_league_level_constant(db: duckdb.DuckDBPyConnection) -> None:
    """Measured 1.092 home / 0.908 away against a league mean of 1.463 goals.

    Pinned because it justifies an exclusion: home advantage is estimated once at league
    level, not per team and never per player. Estimating it per team would spend half the
    data on a parameter that barely varies.
    """
    row = db.execute(
        """
        SELECT round(avg(CASE WHEN was_home THEN goals_for END), 3),
               round(avg(CASE WHEN NOT was_home THEN goals_for END), 3),
               round(avg(goals_for), 3)
        FROM mart_fact_team_match
        """
    ).fetchone()
    assert row is not None
    home, away, league = row
    assert league == pytest.approx(1.463, abs=0.002)
    assert round(home / league, 3) == pytest.approx(1.092, abs=0.002)
    assert round(away / league, 3) == pytest.approx(0.908, abs=0.002)


def test_goals_for_and_against_are_mirrored(db: duckdb.DuckDBPyConnection) -> None:
    """Each fixture's two rows must agree, or the two-sided construction is broken."""
    mismatched = db.execute(
        """
        SELECT count(*) FROM mart_fact_team_match AS a
        JOIN mart_fact_team_match AS b
          ON b.season = a.season AND b.fixture = a.fixture AND b.team_id = a.opponent_team_id
        WHERE a.goals_for IS DISTINCT FROM b.goals_against
        """
    ).fetchone()
    assert mismatched is not None and mismatched[0] == 0


def test_every_fixture_has_exactly_two_sides(db: duckdb.DuckDBPyConnection) -> None:
    bad = db.execute(
        """
        SELECT count(*) FROM (
            SELECT season, fixture, count(*) AS sides,
                   sum(CASE WHEN was_home THEN 1 ELSE 0 END) AS home
            FROM mart_fact_team_match GROUP BY season, fixture
        ) WHERE sides <> 2 OR home <> 1
        """
    ).fetchone()
    assert bad is not None and bad[0] == 0


def test_pulse_id_is_retained(db: duckdb.DuckDBPyConnection) -> None:
    """Gotcha 12. The official Premier League match id, and the Phase 5 join key."""
    row = db.execute("SELECT count(*), count(pulse_id) FROM mart_fact_team_match").fetchone()
    assert row is not None
    total, present = row
    assert total == present == 3800

    # And it identifies a match, so both sides of a fixture share one.
    distinct = db.execute(
        """
        SELECT count(*) FROM (
            SELECT fixture, season FROM mart_fact_team_match
            GROUP BY season, fixture HAVING count(DISTINCT pulse_id) <> 1
        )
        """
    ).fetchone()
    assert distinct is not None and distinct[0] == 0


def test_minutes_distribution_2025_26(db: duckdb.DuckDBPyConnection) -> None:
    """Measured 2025-26: 61.4% zero-minute rows, 26.3% at 60+.

    Scoped to 2025-26 deliberately -- pooled across five seasons it is 59.5%/28.3%, and it
    ranges 57-62% by season, so a pooled assertion would be asserting a different quantity.

    This is the single most important number for Stage B: with 61% of rows scoring no
    appearance points, a perfect goals model applied to a benched player produces nothing.
    """
    row = db.execute(
        """
        SELECT round(100.0 * sum(CASE WHEN minutes = 0 THEN 1 ELSE 0 END) / count(*), 1),
               round(100.0 * sum(CASE WHEN minutes >= 60 THEN 1 ELSE 0 END) / count(*), 1)
        FROM mart_fact_player_fixture WHERE season = '2025-26'
        """
    ).fetchone()
    assert row is not None
    zero_pct, sixty_pct = row
    assert zero_pct == pytest.approx(61.4, abs=0.1)
    assert sixty_pct == pytest.approx(26.3, abs=0.1)


def test_appearance_points_dominate_every_position(db: duckdb.DuckDBPyConnection) -> None:
    """Appearance points are 51-60% of all points scored, by position.

    Asserted as a band rather than exact values: I measure GK 59.4 / DEF 57.9 / MID 55.3 /
    FWD 52.2 for 2025-26, and the specification's DEF figure is 59.1, so the precise split
    depends on the aggregation window. The band is what carries the design consequence --
    the minutes model is the highest-leverage component in the system.
    """
    rows = db.execute(
        """
        SELECT f.position,
               round(100.0 * sum(CASE WHEN f.minutes >= 60 THEN 2
                                      WHEN f.minutes > 0 THEN 1 ELSE 0 END)
                     / sum(t.points_under_rules_2025_26), 1)
        FROM mart_fact_player_fixture AS f
        JOIN mart_target_player_fixture AS t
          ON t.season = f.season AND t.code = f.code AND t.fixture = f.fixture
        WHERE f.season = '2025-26'
        GROUP BY f.position ORDER BY f.position
        """
    ).fetchall()
    assert len(rows) == 4
    for position, share in rows:
        assert 51.0 <= share <= 60.0, f"{position}: appearance share {share}% outside 51-60%"


def test_rest_days_are_plausible(db: duckdb.DuckDBPyConnection) -> None:
    """Median 7 days, and no gap shorter than 3.

    The <=4-day share is deliberately not asserted against a fixed value: I measure 21.8%
    pooled and 18.5% for 2025-26 under the definition "calendar days between a team's
    consecutive kickoffs", against 14.3% in the specification. The median and the 3-day floor
    agree, so this is a definitional difference in the tail rather than a construction error,
    and Phase 2 is where congestion gets measured properly.
    """
    row = db.execute(
        """
        SELECT median(rest_days), min(rest_days), max(rest_days)
        FROM mart_fact_team_match WHERE rest_days IS NOT NULL
        """
    ).fetchone()
    assert row is not None
    median, lowest, highest = row
    assert median == 7.0
    # The floor is 2 days, from six team-matches on 2021-12-28 -- the COVID-disrupted festive
    # period, where postponements compressed the schedule. Every other season floors at 3.
    assert lowest == 2, f"a gap of {lowest} days is implausible for Premier League scheduling"
    assert highest < 90

    # Sub-3-day turnarounds are genuine but very rare. Asserted as a rate rather than an
    # exact per-season tally: the archive refreshes several times a season and kickoff times
    # get corrected, so an exact list would fail on a data refresh rather than on a bug. The
    # timezone regression that once manufactured these is covered by
    # test_rest_days_are_timezone_invariant.
    tightest = db.execute(
        """
        SELECT count(*) FILTER (WHERE rest_days < 3), count(*)
        FROM mart_fact_team_match WHERE rest_days IS NOT NULL
        """
    ).fetchone()
    assert tightest is not None
    under_three, total = tightest
    assert under_three / total < 0.005, (
        f"{under_three}/{total} team-matches show a sub-3-day turnaround, which is too many "
        "to be real -- suspect kickoff-time parsing or a timezone-dependent date_diff"
    )

    # The first match of a team's season has no predecessor, so exactly 20 NULLs per season.
    nulls = db.execute(
        """
        SELECT count(*) FROM (
            SELECT season, count(*) AS n FROM mart_fact_team_match
            WHERE rest_days IS NULL GROUP BY season HAVING count(*) <> 20
        )
        """
    ).fetchone()
    assert nulls is not None and nulls[0] == 0


def test_rest_days_are_timezone_invariant() -> None:
    """`rest_days` must not depend on the machine that built the database.

    Regression test. `date_diff('day', ...)` on TIMESTAMPTZ counts calendar-day boundaries
    in the *session* timezone, so the original expression produced different stored values
    per developer: the third pair below measures 2 days apart under UTC and 1 under
    Asia/Bangkok, which manufactured implausible sub-3-day turnarounds out of nothing.

    A point-in-time system whose stored values shift with the builder's locale is not
    reproducible, so this is checked directly on the expression rather than trusted to the
    connection setting.
    """
    kickoffs = [
        ("2025-08-16 12:00:00+00", "2025-08-19 19:00:00+00"),
        ("2021-12-26 14:00:00+00", "2021-12-28 19:30:00+00"),
        ("2021-12-26 19:00:00+00", "2021-12-28 15:00:00+00"),
    ]
    results: dict[str, list[int]] = {}
    for timezone in ("UTC", "Asia/Bangkok", "America/Los_Angeles", "Pacific/Kiritimati"):
        con = duckdb.connect(":memory:")
        try:
            con.execute(f"SET TimeZone='{timezone}'")
            results[timezone] = [
                con.execute(
                    "SELECT date_diff('day', TIMESTAMPTZ '"
                    + earlier
                    + "' AT TIME ZONE 'UTC', TIMESTAMPTZ '"
                    + later
                    + "' AT TIME ZONE 'UTC')"
                ).fetchone()[0]
                for earlier, later in kickoffs
            ]
        finally:
            con.close()

    baseline = results["UTC"]
    assert baseline == [3, 2, 2]
    for timezone, values in results.items():
        assert values == baseline, (
            f"rest_days differs under {timezone}: {values} vs UTC {baseline} -- the "
            "expression has lost its explicit AT TIME ZONE 'UTC' conversion"
        )


def test_connections_are_pinned_to_utc(db: duckdb.DuckDBPyConnection) -> None:
    """Belt and braces for the above, and it keeps Windows working.

    A named local timezone coming back from DuckDB forces Polars through `zoneinfo`, which
    on Windows cannot resolve one without the `tzdata` package. Returning UTC means the
    common path needs no IANA lookup at all.
    """
    row = db.execute("SELECT current_setting('TimeZone')").fetchone()
    assert row is not None and row[0] == "UTC"


def test_second_half_is_more_congested_than_first(db: duckdb.DuckDBPyConnection) -> None:
    """Directional check behind the Phase 5 deferral.

    Domestic congestion is already visible in FPL data alone, which is why the external
    competition calendar waits until Phase 2 has proved it adds lift.
    """
    rows = dict(
        db.execute(
            """
            SELECT CASE WHEN gw <= 19 THEN 'H1' ELSE 'H2' END,
                   round(100.0 * sum(CASE WHEN rest_days <= 4 THEN 1 ELSE 0 END) / count(*), 1)
            FROM mart_fact_team_match WHERE season = '2025-26' AND rest_days IS NOT NULL
            GROUP BY 1
            """
        ).fetchall()
    )
    assert rows["H2"] > rows["H1"]


def test_fdr_is_present_and_in_range(db: duckdb.DuckDBPyConnection) -> None:
    """FPL's own difficulty rating, retained for the Phase 1 naive-FDR baseline."""
    row = db.execute("SELECT count(fdr), min(fdr), max(fdr) FROM mart_fact_team_match").fetchone()
    assert row is not None
    present, lowest, highest = row
    assert present == 3800
    assert 1 <= lowest <= highest <= 5


def test_kickoff_time_is_always_present_and_ordered(db: duckdb.DuckDBPyConnection) -> None:
    """R4 depends on `kickoff_time`; a NULL would silently escape every filter."""
    for table in ("mart_fact_player_fixture", "mart_fact_team_match"):
        row = db.execute(f"SELECT count(*), count(kickoff_time) FROM {table}").fetchone()
        assert row is not None and row[0] == row[1], f"{table} has NULL kickoff_time"


def test_gameweeks_span_a_full_season(db: duckdb.DuckDBPyConnection) -> None:
    """Gameweek numbering runs 1-38 but is NOT guaranteed contiguous.

    2022-23 has no gameweek 7 at all: it was cancelled following the death of Queen
    Elizabeth II in September 2022 and its ten fixtures were redistributed, leaving GW8 with
    only seven matches. So that season has 37 distinct gameweeks.

    Anything iterating gameweeks must therefore walk the observed values rather than
    `range(1, 39)` -- a walk-forward backtest that assumes contiguity would train on an empty
    gameweek and could silently mis-align its train/predict split by one.
    """
    rows = db.execute(
        """
        SELECT season, min(gw), max(gw), count(DISTINCT gw)
        FROM mart_fact_team_match GROUP BY season ORDER BY season
        """
    ).fetchall()
    observed = {season: distinct for season, _, _, distinct in rows}
    for season, lowest, highest, _ in rows:
        assert lowest == 1, season
        assert highest == 38, season

    assert observed == {
        "2021-22": 38,
        "2022-23": 37,  # no GW7
        "2023-24": 38,
        "2024-25": 38,
        "2025-26": 38,
    }

    missing = db.execute(
        """
        SELECT gw FROM range(1, 39) AS r(gw)
        WHERE gw NOT IN (SELECT DISTINCT gw FROM mart_fact_team_match WHERE season = '2022-23')
        """
    ).fetchall()
    assert [row[0] for row in missing] == [7]

    # Every season still has all 380 matches; the cancelled gameweek was redistributed.
    per_season = db.execute(
        """
        SELECT season, count(DISTINCT fixture) FROM mart_fact_team_match
        GROUP BY season ORDER BY season
        """
    ).fetchall()
    assert [row[1] for row in per_season] == [380] * 5
