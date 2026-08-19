"""Failure-atomic orchestration for full archive database rebuilds."""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from fpl.jobs import build_db
from fpl.storage.db import table_columns
from fpl.transform.crosswalk import CrosswalkReport
from fpl.transform.facts import FactCounts


def _create_original_database(path: Path) -> bytes:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE original_marker (value VARCHAR)")
        con.execute("INSERT INTO original_marker VALUES ('keep me')")
    finally:
        con.close()
    return path.read_bytes()


def _temporary_files(target: Path) -> list[Path]:
    return sorted(target.parent.glob(f".{target.name}.*.tmp*"))


def _noop(*args: object, **kwargs: object) -> None:
    return None


def _stub_successful_pipeline(
    monkeypatch: pytest.MonkeyPatch, *, unmatched_element_rows: int = 0
) -> None:
    report = CrosswalkReport(
        raw_rows=1,
        duplicate_rows_removed=0,
        manager_rows_excluded=0,
        unmatched_element_rows=unmatched_element_rows,
        staged_rows=1,
    )

    def build_player_fixture(*args: object, **kwargs: object) -> CrosswalkReport:
        return report

    def build_facts(con: duckdb.DuckDBPyConnection) -> FactCounts:
        con.execute(
            "CREATE OR REPLACE TABLE replacement_marker AS SELECT 'complete'::VARCHAR AS value"
        )
        return FactCounts(player_fixture_rows=1, team_match_rows=2, target_rows=3)

    monkeypatch.setattr(build_db, "download_archive", lambda **kwargs: [])
    monkeypatch.setattr(build_db, "land_raw", _noop)
    monkeypatch.setattr(build_db.crosswalk, "build_dimensions", _noop)
    monkeypatch.setattr(build_db.crosswalk, "build_player_fixture", build_player_fixture)
    monkeypatch.setattr(build_db.quality, "assert_nullify_expectations", _noop)
    monkeypatch.setattr(build_db.quality, "validate", lambda *args, **kwargs: [])
    monkeypatch.setattr(build_db.facts, "build_all", build_facts)


def test_exception_preserves_original_database_and_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fpl.duckdb"
    original_bytes = _create_original_database(target)

    def fail_landing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected landing failure")

    monkeypatch.setattr(build_db, "download_archive", lambda **kwargs: [])
    monkeypatch.setattr(build_db, "land_raw", fail_landing)

    with pytest.raises(RuntimeError, match="injected landing failure"):
        build_db.build(db_path=target)

    assert target.read_bytes() == original_bytes
    assert _temporary_files(target) == []
    con = duckdb.connect(str(target), read_only=True)
    try:
        assert con.execute("SELECT value FROM original_marker").fetchone() == ("keep me",)
    finally:
        con.close()


def test_strict_crosswalk_failure_preserves_original_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fpl.duckdb"
    original_bytes = _create_original_database(target)
    _stub_successful_pipeline(monkeypatch, unmatched_element_rows=1)

    assert build_db.build(db_path=target, strict=True) == 1
    assert target.read_bytes() == original_bytes
    assert _temporary_files(target) == []


def test_success_atomically_replaces_database_and_remains_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fpl.duckdb"
    _create_original_database(target)
    _stub_successful_pipeline(monkeypatch)

    assert build_db.build(db_path=target) == 0
    assert build_db.build(db_path=target) == 0
    assert _temporary_files(target) == []

    con = duckdb.connect(str(target), read_only=True)
    try:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "original_marker" in tables
        assert con.execute("SELECT value FROM original_marker").fetchone() == ("keep me",)
        assert con.execute("SELECT value FROM replacement_marker").fetchone() == ("complete",)
        assert con.execute(
            "SELECT value FROM build_metadata WHERE key = 'player_fixture_rows'"
        ).fetchone() == ("1",)
    finally:
        con.close()


def test_rebuild_applies_additive_schema_migrations_to_a_cloned_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cloned pre-Opta database must gain new nullable columns before rebuilding."""
    target = tmp_path / "fpl.duckdb"
    migrated_columns = {
        "stg_player_fixture": {"threat", "creativity", "influence"},
        "stg_live_player_fixture_version": {"threat", "creativity", "influence"},
        "mart_fact_player_fixture": {"threat", "creativity", "influence"},
        "mart_fact_player_fixture_live": {"threat", "creativity", "influence"},
        "mart_dim_team": {"team_code"},
        "mart_fact_player_form": {
            "clean_sheets",
            "goals_conceded",
            "saves",
            "expected_goals_conceded",
        },
    }
    con = duckdb.connect(str(target))
    try:
        for table in migrated_columns:
            con.execute(f"CREATE TABLE {table} (legacy_marker INTEGER)")
        con.execute("INSERT INTO mart_fact_player_form (legacy_marker) VALUES (1)")
    finally:
        con.close()
    _stub_successful_pipeline(monkeypatch)

    assert build_db.build(db_path=target) == 0
    con = duckdb.connect(str(target), read_only=True)
    try:
        for table, expected in migrated_columns.items():
            columns = set(table_columns(con, table))
            assert expected <= columns
        assert con.execute(
            """
            SELECT clean_sheets, goals_conceded, saves, expected_goals_conceded
            FROM mart_fact_player_form
            WHERE legacy_marker = 1
            """
        ).fetchone() == (None, None, None, None)
    finally:
        con.close()


def test_existing_target_wal_blocks_replacement_without_deleting_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fpl.duckdb"
    original_bytes = _create_original_database(target)
    target_wal = Path(f"{target}.wal")
    target_wal.write_text("existing writer or recovery evidence", encoding="utf-8")
    _stub_successful_pipeline(monkeypatch)

    with pytest.raises(RuntimeError, match="close active writers or recover"):
        build_db.build(db_path=target)

    assert target.read_bytes() == original_bytes
    assert target_wal.read_text("utf-8") == "existing writer or recovery evidence"
    assert _temporary_files(target) == []


def test_concurrent_target_update_aborts_promotion_and_preserves_new_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "fpl.duckdb"
    _create_original_database(target)
    _stub_successful_pipeline(monkeypatch)
    original_build_facts = build_db.facts.build_all

    def build_facts_and_capture(con: duckdb.DuckDBPyConnection) -> FactCounts:
        counts = original_build_facts(con)
        live = duckdb.connect(str(target))
        try:
            live.execute("INSERT INTO original_marker VALUES ('concurrent capture')")
        finally:
            live.close()
        return counts

    monkeypatch.setattr(build_db.facts, "build_all", build_facts_and_capture)

    with pytest.raises(RuntimeError, match="changed during rebuild"):
        build_db.build(db_path=target)

    assert _temporary_files(target) == []
    con = duckdb.connect(str(target), read_only=True)
    try:
        assert con.execute("SELECT value FROM original_marker ORDER BY value").fetchall() == [
            ("concurrent capture",),
            ("keep me",),
        ]
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert "replacement_marker" not in tables
    finally:
        con.close()
