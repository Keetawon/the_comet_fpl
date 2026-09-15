"""Display-only archive sums: no partial SUM, fuzzy joins, or historical PIT invention."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import duckdb
import pytest

from fpl.publish.fpl_team_xg import TABLES, apply_team_xg_supplements, archive_team_xg

CAPTURE = datetime(2026, 8, 19, tzinfo=UTC)
CUTOFF = datetime(2026, 9, 11, tzinfo=UTC)
KICKOFF = "2024-01-01T12:00:00+00:00"


def source() -> dict[str, list[dict[str, str | None]]]:
    players: list[dict[str, str | None]] = []
    history: list[dict[str, str | None]] = []
    for team in (1, 2):
        for member in range(12):
            element = str(team * 100 + member)
            players.append(
                {
                    "id": element,
                    "code": str(team * 1000 + member),
                    "element_type": "1" if member == 0 else "2",
                    "team": "999",
                }
            )
            history.append(
                {
                    "element": element,
                    "fixture": "1",
                    "GW": "20",
                    "kickoff_time": KICKOFF,
                    "team": f"Team {team}",
                    "was_home": str(team == 1),
                    "opponent_team": str(3 - team),
                    "minutes": "90" if member < 11 else "0",
                    "starts": "1" if member < 11 else "0",
                    "expected_goals": "0.1" if member < 11 else "0",
                }
            )
    return {
        "raw_players": players,
        "raw_merged_gw": history,
        "raw_fixtures": [
            {
                "id": "1",
                "event": "20",
                "kickoff_time": KICKOFF,
                "team_h": "1",
                "team_a": "2",
                "finished": "True",
            }
        ],
        "raw_teams": [{"id": str(t), "code": str(t * 10), "name": f"Team {t}"} for t in (1, 2)],
    }


def database(
    data: dict[str, list[dict[str, str | None]]], season: str = "2023-24"
) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE raw_ingest_log (season VARCHAR, source_table VARCHAR, "
        "ingested_at TIMESTAMPTZ, row_count BIGINT, sha256 VARCHAR)"
    )
    for table, rows in data.items():
        keys = list(rows[0])
        columns = ",".join(f'"{key}" VARCHAR' for key in keys)
        con.execute(f"CREATE TABLE {table} (season VARCHAR,_ingested_at TIMESTAMPTZ,{columns})")
        marks = ",".join("?" for _ in range(len(keys) + 2))
        con.executemany(
            f"INSERT INTO {table} VALUES ({marks})",
            [[season, CAPTURE, *(row.get(k) for k in keys)] for row in rows],
        )
        con.execute(
            "INSERT INTO raw_ingest_log VALUES (?,?,?,?,?)",
            [
                season,
                table,
                CAPTURE,
                len(rows),
                hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest(),
            ],
        )
    return con


def test_all_recorded_players_including_gk_exact_repeat_and_transfer_identity() -> None:
    data = source()
    data["raw_merged_gw"].append(deepcopy(data["raw_merged_gw"][0]))
    with database(data) as con:
        rows, _ = archive_team_xg(con, seasons=["2023-24"], cutoff=CUTOFF)
        repeated, _ = archive_team_xg(con, seasons=["2023-24"], cutoff=CUTOFF)
    assert rows == repeated
    assert len(rows) == 2
    home = rows["2023-24", 1, 10]
    assert home["value"] == 1.1  # includes goalkeeper's 0.1, excludes exact duplicate
    assert home["player_rows"] == 12 and home["appeared_players"] == home["starters"] == 11
    assert home["source_known_at"] == CAPTURE.isoformat()  # not kickoff or legacy mart known_at
    assert home["evidence_class"] == "retrospective_descriptive"
    assert set(home["source_sha256"]) == set(TABLES)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("expected_goals", None),
        ("expected_goals", "nan"),
        ("expected_goals", "-0.1"),
        ("minutes", None),
        ("minutes", "0"),
        ("starts", None),
        ("starts", "0"),
        ("element", "99999"),
        ("team", "Team One"),
        ("opponent_team", "1"),
        ("was_home", "maybe"),
        ("GW", "21"),
        ("kickoff_time", "2024-01-02T12:00:00Z"),
    ],
)
def test_missing_inconsistent_or_unresolved_row_rejects_pair(key: str, value: str | None) -> None:
    data = source()
    data["raw_merged_gw"][0][key] = value
    with database(data) as con:
        rows, notes = archive_team_xg(con, seasons=["2023-24"], cutoff=CUTOFF)
    assert rows == {}
    assert "0/1" in notes[0]


def test_conflicting_duplicate_and_missing_appearance_fail_closed() -> None:
    for conflict in (True, False):
        data = source()
        if conflict:
            duplicate = deepcopy(data["raw_merged_gw"][0])
            duplicate["expected_goals"] = "0.2"
            data["raw_merged_gw"].append(duplicate)
        else:
            data["raw_merged_gw"].pop(0)
        with database(data) as con:
            assert not archive_team_xg(con, seasons=["2023-24"], cutoff=CUTOFF)[0]


def test_prefix_placeholder_zero_is_not_measured() -> None:
    data = source()
    data["raw_fixtures"][0]["event"] = "15"
    for r in data["raw_merged_gw"]:
        r["GW"], r["expected_goals"] = "15", "0"
    with database(data, "2022-23") as con:
        assert not archive_team_xg(con, seasons=["2022-23"], cutoff=CUTOFF)[0]


@pytest.mark.parametrize(
    "fault", ["cutoff", "receipt", "raw_stamp", "unfinished", "future_match", "stable_code"]
)
def test_availability_and_receipt_identity(fault: str) -> None:
    data = source()
    if fault == "unfinished":
        data["raw_fixtures"][0]["finished"] = "False"
    if fault == "future_match":
        data["raw_fixtures"][0]["kickoff_time"] = "2027-01-01T12:00:00Z"
    if fault == "stable_code":
        data["raw_players"][1]["code"] = data["raw_players"][0]["code"]
    with database(data) as con:
        if fault == "receipt":
            con.execute("UPDATE raw_ingest_log SET row_count=0")
        if fault == "raw_stamp":
            con.execute("UPDATE raw_merged_gw SET _ingested_at=_ingested_at + INTERVAL 1 DAY")
        cutoff = datetime(2024, 2, 1, tzinfo=UTC) if fault == "cutoff" else CUTOFF
        assert not archive_team_xg(con, seasons=["2023-24"], cutoff=cutoff)[0]


def test_supplement_keeps_raw_health_and_sdp_priority_and_mirrors_opponent() -> None:
    data = source()
    data["raw_merged_gw"][12]["expected_goals"] = "1.1"
    rows: list[dict[str, Any]] = [
        {
            "season": "2023-24",
            "fixture": 1,
            "gw": 20,
            "kickoff_time": KICKOFF,
            "team_code": 10,
            "opponent_team_code": 20,
            "was_home": True,
            "known_at": KICKOFF,
            "sdp": {"expected_goals": None, "expected_goals_allowed": None},
            "status": "UNAVAILABLE",
            "dashboard_status": "INCOMPLETE",
        }
    ]
    with database(data) as con:
        apply_team_xg_supplements(con, rows, cutoff=CUTOFF, current="2026-27")
        assert rows[0]["display_supplements"]["expected_goals"]["value"] == 1.1
        assert rows[0]["display_supplements"]["expected_goals_allowed"]["value"] == 2.1
        assert rows[0]["sdp"] == {"expected_goals": None, "expected_goals_allowed": None}
        assert rows[0]["dashboard_status"] == "INCOMPLETE"
        assert rows[0]["known_at"] == CAPTURE.isoformat()
        rows[0]["sdp"]["expected_goals"] = 0.0
        apply_team_xg_supplements(con, rows, cutoff=CUTOFF, current="2026-27")
        assert "expected_goals" not in rows[0]["display_supplements"]
        rows[0]["opponent_team_code"] = 999
        apply_team_xg_supplements(con, rows, cutoff=CUTOFF, current="2026-27")
        assert not rows[0]["display_supplements"]
