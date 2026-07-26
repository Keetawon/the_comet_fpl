"""Data-quality validation: gotcha 13, and the declared repairs.

The governing principle: validation logs and surfaces, it never silently drops or mutates.
A row that looks wrong may be real -- six of the BPS outliers this suite once flagged were
genuine (a defender with an own goal and a red card at -25 BPS, a hat-trick at 128).
"""

from __future__ import annotations

import duckdb
import pytest

from fpl.config import load_data_quality
from fpl.transform.quality import assert_nullify_expectations, nullify_predicates, validate


def test_nullify_predicates_are_table_qualified() -> None:
    """Predicates are spliced into a three-table join, so every reference needs an alias."""
    predicates = nullify_predicates(alias="d")
    assert "expected_goals" in predicates
    for column, clauses in predicates.items():
        for clause in clauses:
            assert "d.season" in clause, f"{column}: {clause} is not alias-qualified"
            assert "season =" not in clause.replace("d.season =", ""), column


def test_nullify_predicate_targets_the_2022_23_prefix() -> None:
    clauses = nullify_predicates()["expected_goals"]
    assert len(clauses) == 1
    assert "2022-23" in clauses[0]
    assert "<= 15" in clauses[0]


def test_declared_ranges_cover_the_scoring_components() -> None:
    """Every component the calculator reads should have a sanity bound."""
    ranges = load_data_quality().ranges
    for component in (
        "minutes",
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
        "defensive_contribution",
    ):
        assert component in ranges, f"no declared range for {component}"
        assert ranges[component].min <= ranges[component].max


@pytest.mark.archive
def test_the_built_database_has_no_range_violations(db: duckdb.DuckDBPyConnection) -> None:
    """A clean build should trip no range check.

    Bounds were widened once, deliberately: the observed BPS range is [-25, 128] and both
    ends are genuine football, so the bound sits just outside rather than at the observed
    extreme. If this fails, look at the row before widening the bound again.
    """
    quality = load_data_quality()
    violations: list[str] = []
    staged = {
        row[0]
        for row in db.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'stg_player_fixture'
            """
        ).fetchall()
    }
    for column, bounds in quality.ranges.items():
        if column not in staged:
            continue
        row = db.execute(
            f"""
            SELECT count(*) FROM stg_player_fixture
            WHERE {column} IS NOT NULL AND ({column} < ? OR {column} > ?)
            """,
            [bounds.min, bounds.max],
        ).fetchone()
        assert row is not None
        if row[0]:
            violations.append(f"{column}: {row[0]} row(s) outside [{bounds.min}, {bounds.max}]")
    assert violations == [], "; ".join(violations)


@pytest.mark.archive
def test_cards_without_an_appearance_are_systematic_not_a_glitch(
    db: duckdb.DuckDBPyConnection,
) -> None:
    """Gotcha 13 in its real form: an "anomaly" that is correct FPL behaviour.

    Ten rows across five seasons have zero minutes and non-zero points, and every one is a
    card shown to an unused substitute -- nine yellows at -1 and one red at -3 (Matheus,
    2022-23 GW28, bps -9). All ten recompute exactly.

    Two consequences:
      * The Barnes row that a 99.997% replay treats as an unreproducible glitch is one
        instance of a recurring rule, not a one-off. Cards are simply not gated on minutes.
      * The red card independently confirms the same holds for `red_cards`, which no
        yellow-only example could establish.
    """
    rows = db.execute(
        """
        SELECT s.season, s.gw, s.minutes, s.yellow_cards, s.red_cards, s.total_points,
               t.points_under_rules_2025_26
        FROM stg_player_fixture AS s
        JOIN mart_target_player_fixture AS t
          ON t.season = s.season AND t.code = s.code AND t.fixture = s.fixture
        WHERE s.minutes = 0 AND s.total_points <> 0
        ORDER BY s.season, s.gw
        """
    ).fetchall()
    assert len(rows) == 10

    yellows_seen = reds_seen = 0
    for season, gw, minutes, yellow, red, recorded, recomputed in rows:
        assert minutes == 0
        # Exactly one card, and it fully explains the score.
        assert yellow + red == 1, f"{season} GW{gw}: expected a single card"
        expected = -1 if yellow else -3
        assert recorded == expected, f"{season} GW{gw}: recorded {recorded}, expected {expected}"
        assert recomputed == recorded, f"{season} GW{gw}: calculator disagreed with the record"
        yellows_seen += yellow
        reds_seen += red

    assert yellows_seen == 9
    assert reds_seen == 1, "the red-card case is what proves red_cards is also minutes-ungated"

    # Exactly one of the ten is the 2025-26 row the specification calls a glitch.
    assert sum(1 for row in rows if row[0] == "2025-26") == 1

    declared = {anomaly.id for anomaly in load_data_quality().expected_anomalies}
    assert "card-without-appearance" in declared


@pytest.mark.archive
def test_no_goals_without_minutes(db: duckdb.DuckDBPyConnection) -> None:
    """The specification's observed glitch -- a goalkeeper with 11 goals and 0 minutes.

    Absent from the archive, but the check runs on every ingest because pre-season live
    payloads are where it appeared.
    """
    row = db.execute(
        "SELECT count(*) FROM stg_player_fixture WHERE minutes = 0 AND goals_scored > 0"
    ).fetchone()
    assert row is not None and row[0] == 0


@pytest.mark.archive
def test_consistency_checks_find_nothing_in_a_clean_build(
    db: duckdb.DuckDBPyConnection,
) -> None:
    for rule in load_data_quality().consistency:
        row = db.execute(
            f"SELECT count(*) FROM stg_player_fixture WHERE {rule.predicate}"
        ).fetchone()
        assert row is not None
        assert row[0] == 0, f"{rule.id}: {row[0]} row(s) matched -- {rule.description}"


def test_validate_records_anomalies_without_dropping_rows() -> None:
    """A synthetic bad row must be logged and left in place.

    The distinction matters: silently dropping a glitch loses a real fixture, and silently
    repairing it invents data. Logging leaves the decision to a human.
    """
    con = duckdb.connect(":memory:")
    from fpl.storage.db import apply_schema

    apply_schema(con)
    con.execute(
        """
        INSERT INTO stg_player_fixture
            (season, element, code, fixture, gw, kickoff_time, position, team_id,
             opponent_team_id, was_home, minutes, goals_scored, assists, clean_sheets,
             goals_conceded, saves, penalties_saved, penalties_missed, own_goals,
             yellow_cards, red_cards, bonus, bps, total_points)
        VALUES ('2026-27', 1, 999, 1, 1, '2026-08-21 19:00:00+00', 'GK', 1, 2, true,
                0, 11, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        """
    )
    try:
        found = validate(con)
        check_ids = {anomaly.check_id for anomaly in found}
        assert "range:goals_scored" in check_ids  # 11 goals exceeds the declared max
        assert "goals-without-minutes" in check_ids

        logged = con.execute("SELECT count(*) FROM ingest_anomaly").fetchone()
        assert logged is not None and logged[0] >= 2

        # The row is still there. Validation observes; it does not mutate.
        surviving = con.execute("SELECT count(*) FROM stg_player_fixture").fetchone()
        assert surviving is not None and surviving[0] == 1
    finally:
        con.close()


def test_nullify_expectations_fail_loudly_when_a_repair_stops_working() -> None:
    """A repair that silently stops matching is worse than no repair.

    The config still asserts it happened, so a reader would trust NULLs that are now zeros.
    """
    con = duckdb.connect(":memory:")
    from fpl.storage.db import apply_schema

    apply_schema(con)
    # A 2022-23 GW1 row that kept its expected_goals value: the repair did not fire.
    con.execute(
        """
        INSERT INTO stg_player_fixture
            (season, element, code, fixture, gw, kickoff_time, position, team_id,
             opponent_team_id, was_home, minutes, expected_goals)
        VALUES ('2022-23', 1, 999, 1, 1, '2022-08-05 19:00:00+00', 'MID', 1, 2, true, 90, 0.4)
        """
    )
    try:
        with pytest.raises(AssertionError, match="should be NULL through GW15"):
            assert_nullify_expectations(con)
    finally:
        con.close()


@pytest.mark.archive
def test_ingest_log_records_provenance(db: duckdb.DuckDBPyConnection) -> None:
    """Every landed file has a URL, a row count and a checksum.

    `raw_ingest_log` is a log: it accumulates one entry per file per build, so provenance
    history survives a rebuild. The per-build shape is therefore checked against the most
    recent `ingested_at` rather than the whole table.
    """
    rows = db.execute(
        """
        SELECT source_table, count(*), count(DISTINCT sha256), count(DISTINCT season)
        FROM raw_ingest_log
        WHERE ingested_at = (SELECT max(ingested_at) FROM raw_ingest_log)
        GROUP BY source_table ORDER BY source_table
        """
    ).fetchall()
    assert len(rows) == 4  # merged_gw, fixtures, teams, players_raw
    for table, count, distinct_hashes, distinct_seasons in rows:
        assert count == 5, f"{table}: expected one entry per season in the latest build"
        assert distinct_seasons == 5, f"{table}: seasons missing from the latest build"
        assert distinct_hashes == 5, f"{table}: seasons share a checksum -- same file landed twice?"

    empty = db.execute("SELECT count(*) FROM raw_ingest_log WHERE row_count <= 0").fetchone()
    assert empty is not None and empty[0] == 0

    missing_url = db.execute(
        "SELECT count(*) FROM raw_ingest_log WHERE source_url IS NULL OR source_url = ''"
    ).fetchone()
    assert missing_url is not None and missing_url[0] == 0

    # A rebuild must not lose the earlier record of what was ingested.
    builds = db.execute("SELECT count(DISTINCT ingested_at) FROM raw_ingest_log").fetchone()
    assert builds is not None and builds[0] >= 1
