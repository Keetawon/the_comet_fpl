"""Network-free tests for the defensive-actions CSV reader.

The reader is a typed ingest boundary, so the tests pin its contract: the happy path, NULL
preservation (blank counts are skipped, never zeroed), and a clear error on every shape
violation (missing/extra column, bad type, negative count, malformed season/date). The
synthetic fixture mimics the FBref shape -- an accented name, a GK, a two-club transfer, and
a blank-count row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fpl.ingest.defensive_actions_csv import (
    DefensiveActionsCsvError,
    count_null_count_rows,
    read_defensive_actions_csv,
)
from fpl.types import Position

FIXTURE = Path(__file__).parent / "fixtures" / "defensive_actions_sample.csv"
HEADER = (
    "season,external_player_id,player_name,team_name,match_date,"
    "tackles,interceptions,blocks,clearances,recoveries"
)


def _write(tmp_path: Path, header: str, rows: list[str]) -> Path:
    path = tmp_path / "da.csv"
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def test_read_fixture_happy_path() -> None:
    rows = read_defensive_actions_csv(FIXTURE)
    # 9 data rows, 1 blank-count row skipped -> 8 complete rows.
    assert len(rows) == 8
    by_id = {row.external_player_id: row for row in rows}
    # Accented name is preserved verbatim (identity joins on normalised names, not stripped).
    assert by_id["fb-raya"].player_name == "David Raya Martín"
    assert by_id["fb-raya"].season == "2025-26"
    # The adapter derives CBI and rebuilds DC exactly as FPL stores them.
    saliba = by_id["fb-saliba"]
    assert saliba.cbi == 8  # interceptions 3 + blocks 1 + clearances 4
    assert saliba.rebuilt_dc(Position.DEF) == 10  # tackles 2 + CBI 8
    assert saliba.rebuilt_dc(Position.MID) == 16  # + recoveries 6


def test_blank_count_row_is_skipped_not_zeroed() -> None:
    rows = read_defensive_actions_csv(FIXTURE)
    names = {row.player_name for row in rows}
    # The blank-count row (Haaland) is dropped, never turned into a zero-count row.
    assert "Erling Haaland" not in names
    # A complete row with real zeros is kept (zero is measured, distinct from blank).
    assert "Bukayo Saka" in names
    assert count_null_count_rows(FIXTURE) == 1


def test_missing_column_errors(tmp_path: Path) -> None:
    header = HEADER.replace(",recoveries", "")
    path = _write(tmp_path, header, ["2025-26,fb-1,N,Team,2025-08-16,1,1,1,1"])
    with pytest.raises(DefensiveActionsCsvError, match="missing columns"):
        read_defensive_actions_csv(path)


def test_extra_column_errors(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        HEADER + ",surprise",
        ["2025-26,fb-1,N,Team,2025-08-16,1,1,1,1,1,x"],
    )
    with pytest.raises(DefensiveActionsCsvError, match="unexpected columns"):
        read_defensive_actions_csv(path)


def test_bad_type_errors(tmp_path: Path) -> None:
    path = _write(tmp_path, HEADER, ["2025-26,fb-1,N,Team,2025-08-16,not-a-number,1,1,1,1"])
    with pytest.raises(DefensiveActionsCsvError, match="tackles"):
        read_defensive_actions_csv(path)


def test_negative_count_errors(tmp_path: Path) -> None:
    path = _write(tmp_path, HEADER, ["2025-26,fb-1,N,Team,2025-08-16,-1,1,1,1,1"])
    with pytest.raises(DefensiveActionsCsvError, match="negative"):
        read_defensive_actions_csv(path)


def test_malformed_season_and_date_errors(tmp_path: Path) -> None:
    bad_season = _write(tmp_path, HEADER, ["2025,fb-1,N,Team,2025-08-16,1,1,1,1,1"])
    with pytest.raises(DefensiveActionsCsvError, match="season"):
        read_defensive_actions_csv(bad_season)
    bad_date = _write(tmp_path, HEADER, ["2025-26,fb-1,N,Team,16/08/2025,1,1,1,1,1"])
    with pytest.raises(DefensiveActionsCsvError, match="match_date"):
        read_defensive_actions_csv(bad_date)


def test_empty_csv_errors(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(DefensiveActionsCsvError, match="empty CSV"):
        read_defensive_actions_csv(path)
