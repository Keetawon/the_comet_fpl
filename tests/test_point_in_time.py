"""R4: point-in-time correctness, enforced structurally.

Three independent mechanisms, because any one of them can be defeated by a determined
author and leakage is silent when it happens:

  1. A static AST scan of `features/`, so a leaking feature cannot be written at all.
  2. Truncation equivalence, which catches a forgotten `kickoff_time` filter.
  3. Capability restriction, so the target tables are unreachable rather than discouraged.
"""

from __future__ import annotations

import ast
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import polars as pl
import pytest

from fpl.config import repo_root
from fpl.features.pit import (
    OUTCOME_COLUMNS,
    SCHEDULE_COLUMNS,
    AsOf,
    FeatureSource,
    LeakageError,
    PointInTimeView,
    assert_no_outcome_columns,
)
from fpl.storage.db import default_db_path

from .conftest import make_truncated_db

FEATURES_DIR = repo_root() / "src" / "fpl" / "features"

# A sweep spanning several seasons, mid-season and mid-gameweek.
AS_OF_SWEEP = (
    datetime(2022, 1, 15, 12, 0, tzinfo=UTC),
    datetime(2023, 9, 30, 14, 30, tzinfo=UTC),
    datetime(2024, 12, 26, 12, 0, tzinfo=UTC),
    datetime(2025, 11, 8, 17, 30, tzinfo=UTC),
    datetime(2026, 5, 1, 0, 0, tzinfo=UTC),
)


# --------------------------------------------------------------------------------------
# 1. AsOf refuses to be ambiguous
# --------------------------------------------------------------------------------------


def test_as_of_rejects_naive_datetime() -> None:
    """A naive boundary would silently shift the cutoff by the local UTC offset."""
    with pytest.raises(LeakageError, match="timezone-aware"):
        AsOf(datetime(2026, 8, 21, 17, 30))


def test_as_of_accepts_aware_datetime() -> None:
    assert AsOf(datetime(2026, 8, 21, 17, 30, tzinfo=UTC)).ts.tzinfo is not None


def test_view_rejects_a_bare_datetime() -> None:
    """Passing a datetime where an AsOf belongs is the easiest way to skip validation."""
    with pytest.raises(TypeError, match="AsOf"):
        PointInTimeView(FeatureSource(duckdb.connect(":memory:")), datetime.now(UTC))  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# 2. Static guard: a leaking feature cannot be written
# --------------------------------------------------------------------------------------

_FORBIDDEN_CALLS = {"execute", "sql", "query", "read_csv", "read_parquet", "connect"}
_FORBIDDEN_IMPORTS = {"duckdb"}


def _scan_module(source: str, filename: str) -> list[str]:
    """Return the leakage vectors found in a feature module.

    `pit.py` is the sanctioned exception; every other module in the package must reach data
    only through the view it provides.
    """
    violations: list[str] = []
    tree = ast.parse(source, filename=filename)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _FORBIDDEN_IMPORTS:
                    violations.append(f"{filename}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in _FORBIDDEN_IMPORTS:
                violations.append(f"{filename}:{node.lineno} imports from {node.module}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_CALLS:
                violations.append(f"{filename}:{node.lineno} calls .{func.attr}()")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if any(token in lowered for token in ("mart_", "stg_", "raw_")):
                violations.append(f"{filename}:{node.lineno} names a table: {node.value!r}")
    return violations


def test_feature_modules_cannot_reach_data_directly() -> None:
    """Scan every module in `features/` except the access layer itself."""
    offenders: list[str] = []
    for path in sorted(FEATURES_DIR.glob("*.py")):
        if path.name in {"pit.py", "__init__.py"}:
            continue
        offenders.extend(_scan_module(path.read_text("utf-8"), path.name))
    assert offenders == [], "feature modules bypassing PointInTimeView:\n" + "\n".join(offenders)


def test_the_static_guard_actually_catches_a_leaking_feature(tmp_path: Path) -> None:
    """Prove the scanner works, rather than passing because `features/` is nearly empty.

    Without this, the guard above would be vacuous today and would stay vacuous if the
    scanner silently broke.
    """
    leaking = textwrap.dedent(
        '''
        """A feature that cheats in every way we know how to detect."""
        import duckdb

        def rolling_minutes(code: int) -> float:
            con = duckdb.connect("data/fpl.duckdb")
            rows = con.execute("SELECT minutes FROM mart_fact_player_fixture").fetchall()
            return sum(r[0] for r in rows) / len(rows)
        '''
    )
    path = tmp_path / "leaky.py"
    path.write_text(leaking, "utf-8")
    violations = _scan_module(path.read_text("utf-8"), path.name)

    assert any("imports duckdb" in v for v in violations)
    assert any("calls .connect()" in v for v in violations)
    assert any("calls .execute()" in v for v in violations)
    assert any("names a table" in v for v in violations)


# --------------------------------------------------------------------------------------
# 3. Capability restriction: targets are unreachable
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_feature_source_refuses_target_tables() -> None:
    """The feature builder receives a capability, not a connection.

    Reading a target from a feature is label leakage rather than point-in-time leakage, and
    equally fatal -- the model would be predicting from its own answer.
    """
    with FeatureSource.open(default_db_path()) as source:
        with pytest.raises(LeakageError, match="target table"):
            source._check_table("mart_target_player_fixture")
        with pytest.raises(LeakageError, match="target table"):
            source._check_table("mart_target_completeness")
        # Staging carries recorded points, so it is equally out of bounds.
        with pytest.raises(LeakageError, match="not feature-readable"):
            source._check_table("stg_player_fixture")


@pytest.mark.archive
def test_feature_source_permits_exactly_the_component_tables() -> None:
    with FeatureSource.open(default_db_path()) as source:
        assert source.readable_tables() == {
            "mart_fact_player_fixture",
            "mart_fact_team_match",
            "mart_dim_player",
            "mart_dim_team",
            "mart_fact_player_fixture_live",
            "mart_team_fixture_live",
            "stg_live_player_version",
            # V2 football layer. Feature-readable because a team-strength model must read it;
            # safe because every post-match column on both tables is registered in
            # OUTCOME_COLUMNS, which test_every_v2_metric_column_is_an_outcome pins against
            # the metric dictionary.
            "mart_fact_team_match_stats_v2",
            "mart_fact_team_tactical_form_v2",
        }
        for table in source.readable_tables():
            source._check_table(table)  # must not raise


@pytest.mark.archive
def test_view_exposes_no_connection_attribute() -> None:
    """There must be no public route back to a raw connection."""
    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, AsOf(AS_OF_SWEEP[0]))
        public = [name for name in dir(view) if not name.startswith("_")]
        for name in public:
            assert not isinstance(getattr(view, name, None), duckdb.DuckDBPyConnection), name
        # The connection is name-mangled on the source, not merely underscore-prefixed.
        assert not hasattr(source, "con")
        assert not hasattr(source, "_con")


# --------------------------------------------------------------------------------------
# 4. Truncation equivalence -- the real leak test
# --------------------------------------------------------------------------------------


@pytest.mark.archive
@pytest.mark.parametrize("as_of_ts", AS_OF_SWEEP)
def test_observed_rows_are_invariant_to_future_data(as_of_ts: datetime) -> None:
    """The testable form of "shifting as_of never changes an already-computed value".

    A value computed at time T must be invariant to whether data after T exists at all. So:
    query the full database with `as_of = T`, and query a database physically truncated to
    T with the same `as_of`. Any accessor that forgot its filter returns extra rows from the
    full database and the two disagree.
    """
    as_of = AsOf(as_of_ts)
    truncated = make_truncated_db(as_of_ts)
    try:
        with FeatureSource.open(default_db_path()) as full_source:
            full_view = PointInTimeView(full_source, as_of)
            trunc_view = PointInTimeView(FeatureSource(truncated), as_of)

            for accessor in ("observed_player_fixtures", "observed_team_matches"):
                from_full = getattr(full_view, accessor)()
                from_trunc = getattr(trunc_view, accessor)()
                assert from_full.height == from_trunc.height, (
                    f"{accessor} at {as_of_ts}: full DB returned {from_full.height} rows, "
                    f"truncated DB {from_trunc.height} -- a filter is missing"
                )
                # Compare content, not just cardinality.
                sort_keys = ["season", "fixture"] + (
                    ["code"] if "player" in accessor else ["team_id"]
                )
                assert from_full.sort(sort_keys).equals(from_trunc.sort(sort_keys))
    finally:
        truncated.close()


@pytest.mark.archive
def test_no_observed_row_is_at_or_after_as_of() -> None:
    """The direct statement of R4, checked on every accessor."""
    for as_of_ts in AS_OF_SWEEP:
        as_of = AsOf(as_of_ts)
        with FeatureSource.open(default_db_path()) as source:
            view = PointInTimeView(source, as_of)
            for frame in (view.observed_player_fixtures(), view.observed_team_matches()):
                if frame.height:
                    assert frame["kickoff_time"].max() < as_of_ts


@pytest.mark.archive
def test_observed_rows_are_monotone_in_as_of() -> None:
    """Later `as_of` sees a superset. A non-monotone accessor is filtering on the wrong side."""
    with FeatureSource.open(default_db_path()) as source:
        heights = [
            PointInTimeView(source, AsOf(ts)).observed_player_fixtures(columns=["code"]).height
            for ts in AS_OF_SWEEP
        ]
    assert heights == sorted(heights)
    assert heights[0] > 0 and heights[-1] > heights[0]


# --------------------------------------------------------------------------------------
# 5. The schedule accessor: future rows, no outcomes
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_schedule_returns_no_outcome_columns() -> None:
    """Future fixtures are visible, but a future outcome is absent, not merely filtered."""
    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, AsOf(AS_OF_SWEEP[1]))
        frame = view.schedule()
        assert frame.height > 0
        assert set(frame.columns) <= set(SCHEDULE_COLUMNS)
        assert not set(frame.columns) & OUTCOME_COLUMNS


@pytest.mark.archive
def test_schedule_can_see_past_as_of_but_observed_cannot() -> None:
    """The asymmetry that makes the split worth having."""
    as_of_ts = AS_OF_SWEEP[1]
    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, AsOf(as_of_ts))
        upcoming = view.upcoming_fixtures()
        assert upcoming.height > 0
        assert upcoming["kickoff_time"].min() >= as_of_ts

        observed = view.observed_team_matches(columns=["kickoff_time"])
        assert observed["kickoff_time"].max() < as_of_ts


@pytest.mark.archive
def test_schedule_rejects_naive_until() -> None:
    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, AsOf(AS_OF_SWEEP[0]))
        with pytest.raises(LeakageError, match="timezone-aware"):
            view.schedule(until=datetime(2025, 1, 1))


def test_assert_no_outcome_columns_helper() -> None:
    assert_no_outcome_columns(["season", "team_id", "fdr"])
    with pytest.raises(LeakageError, match="goals_scored"):
        assert_no_outcome_columns(["season", "goals_scored"])


# --------------------------------------------------------------------------------------
# 6. Column allowlisting: no caller SQL
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_unknown_columns_are_rejected() -> None:
    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, AsOf(AS_OF_SWEEP[0]))
        with pytest.raises(ValueError, match="unknown column"):
            view.observed_player_fixtures(columns=["minutes", "total_points"])
        with pytest.raises(ValueError, match="unknown column"):
            view.observed_player_fixtures(columns=["1; DROP TABLE mart_dim_team"])


@pytest.mark.archive
def test_entity_filters_are_bound_not_interpolated() -> None:
    """Caller values are parameters. There is no path for caller-supplied SQL."""
    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, AsOf(AS_OF_SWEEP[3]))
        frame = view.observed_player_fixtures(codes=[118748], columns=["code", "minutes"])
        assert frame.height > 0
        assert frame["code"].unique().to_list() == [118748]


@pytest.mark.archive
def test_returned_frames_are_polars() -> None:
    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, AsOf(AS_OF_SWEEP[2]))
        assert isinstance(view.observed_team_matches(), pl.DataFrame)


def test_empty_filters_return_empty_frames() -> None:
    """An empty allowlist means no entities, never invalid `IN ()` SQL or all entities."""
    con = duckdb.connect(":memory:")
    try:
        con.execute(
            """
            CREATE TABLE mart_fact_player_fixture (
                season VARCHAR, code INTEGER, fixture INTEGER, kickoff_time TIMESTAMPTZ
            )
            """
        )
        view = PointInTimeView(FeatureSource(con), AsOf(AS_OF_SWEEP[0]))
        assert view.observed_player_fixtures(codes=[]).is_empty()
        assert view.observed_player_fixtures(seasons=[]).is_empty()
    finally:
        con.close()


# --------------------------------------------------------------------------------------
# 7. A realistic feature, to prove the API is usable and still safe
# --------------------------------------------------------------------------------------


@pytest.mark.archive
def test_a_rolling_feature_is_expressible_and_leak_free() -> None:
    """R6 in miniature: rolling minutes from history only.

    Included because an access layer that makes leakage awkward is worthless if it also
    makes legitimate features awkward. This is the shape Phase 1+ features will take.
    """
    as_of_ts = datetime(2026, 3, 1, tzinfo=UTC)
    as_of = AsOf(as_of_ts)

    def rolling_minutes(view: PointInTimeView, code: int, window: int = 5) -> float | None:
        history = view.observed_player_fixtures(
            codes=[code], columns=["kickoff_time", "minutes"]
        ).sort("kickoff_time")
        if history.is_empty():
            return None
        recent = history.tail(window)["minutes"].drop_nulls()
        return float(recent.mean()) if recent.len() else None

    with FeatureSource.open(default_db_path()) as source:
        view = PointInTimeView(source, as_of)
        value = rolling_minutes(view, 118748)
        assert value is not None and 0 <= value <= 120

        # Same computation against a truncated database must agree exactly.
        truncated = make_truncated_db(as_of_ts)
        try:
            assert (
                rolling_minutes(PointInTimeView(FeatureSource(truncated), as_of), 118748) == value
            )
        finally:
            truncated.close()


@pytest.mark.archive
def test_feature_computed_early_is_unchanged_by_later_data() -> None:
    """Compute at T1, then again at T1 from a database that also holds T2 data.

    The specification's phrasing, made operational: an already-computed value must not move
    because time passed and more matches were played.
    """
    early, late = AS_OF_SWEEP[1], AS_OF_SWEEP[4]
    truncated_early = make_truncated_db(early)
    truncated_late = make_truncated_db(late)
    try:
        view_from_early_db = PointInTimeView(FeatureSource(truncated_early), AsOf(early))
        view_from_late_db = PointInTimeView(FeatureSource(truncated_late), AsOf(early))
        keys = ["season", "fixture", "code"]
        assert (
            view_from_early_db.observed_player_fixtures()
            .sort(keys)
            .equals(view_from_late_db.observed_player_fixtures().sort(keys))
        )
    finally:
        truncated_early.close()
        truncated_late.close()
