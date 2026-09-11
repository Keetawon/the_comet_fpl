"""Synthetic source-only checks; no real forecast or outcome population is read."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.ingest.live_snapshot import capture_payload, write_capture
from fpl.storage.db import initialise
from fpl.validate.player_model_gw1_3_sources import inspect_cutoff, load_official_outcomes

SEASON = "2026-27"
CUTOFF = datetime(2026, 8, 28, 17, 30, tzinfo=UTC)


@pytest.fixture
def con() -> Iterator[duckdb.DuckDBPyConnection]:
    connection = initialise(":memory:")
    yield connection
    connection.close()


def _inputs(*, final: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    bootstrap: dict[str, Any] = {
        "events": [
            {"id": 1, "name": "GW1", "finished": True, "deadline_time": "2026-08-21T17:30:00Z"},
            {"id": 2, "name": "GW2", "finished": final, "deadline_time": "2026-08-28T17:30:00Z"},
        ],
        "teams": [
            {"id": 1, "code": 101, "name": "First", "short_name": "FIR"},
            {"id": 2, "code": 102, "name": "Second", "short_name": "SEC"},
        ],
        "elements": [
            {"id": 10, "code": 1010, "web_name": "Transfer", "element_type": 2, "team": 2},
            {"id": 11, "code": 1011, "web_name": "Keeper", "element_type": 1, "team": 2},
        ],
    }
    fixtures = [
        {
            "id": 501,
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-08-22T14:00:00Z",
            "finished": True,
            "team_h_score": 2,
            "team_a_score": 1,
        },
        {
            "id": 502,
            "event": 2,
            "team_h": 2,
            "team_a": 1,
            "kickoff_time": "2026-08-29T14:00:00Z",
            "finished": final,
            "team_h_score": 0 if final else None,
            "team_a_score": 0 if final else None,
        },
    ]
    history = [
        {
            "element": 10,
            "fixture": 501,
            "round": 1,
            "kickoff_time": "2026-08-22T14:00:00Z",
            "was_home": True,
            "opponent_team": 2,
            "total_points": -2,
            "minutes": 90,
            "starts": 1,
            "bonus": 0,
            "bps": -1,
            "goals_scored": 0,
            "assists": 0,
            "defensive_contribution": None,
        }
    ]
    if final:
        history.append(
            {
                "element": 10,
                "fixture": 502,
                "round": 2,
                "kickoff_time": "2026-08-29T14:00:00Z",
                "was_home": True,
                "opponent_team": 1,
                "total_points": 0,
                "minutes": 0,
                "starts": 0,
            }
        )
    return bootstrap, fixtures, {"history": history}


def _write(
    con: duckdb.DuckDBPyConnection,
    *,
    identity: str = "final",
    final: bool = True,
    bootstrap: dict[str, Any] | None = None,
    fixtures: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    omit_summary: bool = False,
    stamp: datetime | None = None,
) -> None:
    base, schedule, history = _inputs(final=final)
    payloads = [
        capture_payload("bootstrap-static", bootstrap or base),
        capture_payload("fixtures", fixtures if fixtures is not None else schedule),
        capture_payload(
            "element-summary", summary if summary is not None else history, parameter="10"
        ),
    ]
    if not omit_summary:
        payloads.append(capture_payload("element-summary", {"history": []}, parameter="11"))
    write_capture(
        con,
        payloads,
        season=SEASON,
        gw=2,
        mode="player-history",
        captured_at=stamp or CUTOFF + timedelta(days=3 if final else -1),
        capture_id=identity,
    )


def _outcomes(con: duckdb.DuckDBPyConnection, **kwargs: Any) -> list[dict[str, Any]]:
    return load_official_outcomes(
        con, season=SEASON, capture_id="final", gameweeks=[1, 2], **kwargs
    )


def test_outcomes_preserve_signed_points_nulls_position_and_transfer_club(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _write(con)
    rows = _outcomes(con)
    assert rows == _outcomes(con)
    assert len(rows) == 2  # The keeper's missing fixture labels are never fabricated DNPs.
    first, second = rows
    assert first["position"] == "DEF"
    assert first["total_points_as_recorded"] == -2
    assert first["bps"] == -1
    assert first["team_code"] == 101  # Current registry club is 102 after a transfer.
    assert first["opponent_team_code"] == 102
    assert (first["team_goals_scored"], first["team_goals_conceded"]) == (2, 1)
    assert first["defensive_contribution"] is None
    assert first["saves"] is None
    assert second["team_code"] == 102
    assert second["minutes"] == 0
    assert len(first["source_provenance"]["summary_sha256"]) == 64


def test_cutoff_metadata_replays_and_excludes_future_capture(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _write(con, final=False, identity="before")
    before = inspect_cutoff(con, season=SEASON, gw=2, cutoff=CUTOFF)
    assert before["registry_count"] == 2
    assert before["fixture_gameweeks"] == {501: 1, 502: 2}
    assert before["target_fixture_ids"] == [502]
    assert before["history_rows"] == 1
    assert before["history_capture_ids"] == ["before"]
    assert before["history_eligible"] is True
    assert before["promoted_team_codes"] is None
    assert before["promoted_team_provenance"] is None
    assert before["freshness"]["covered"] is True
    _write(con)
    assert inspect_cutoff(con, season=SEASON, gw=2, cutoff=CUTOFF) == before
    assert "total_points_as_recorded" not in before


@pytest.mark.parametrize("kind", ["raw_sha", "manifest_sha", "missing_payload", "count"])
def test_corruption_rejected_in_both_paths(con: duckdb.DuckDBPyConnection, kind: str) -> None:
    _write(con, identity="before", final=False)
    if kind == "raw_sha":
        con.execute("UPDATE snapshot_payload SET sha256='invalid' WHERE endpoint='fixtures'")
    elif kind == "manifest_sha":
        con.execute("UPDATE snapshot_capture SET manifest_sha256='invalid'")
    elif kind == "missing_payload":
        con.execute(
            "DELETE FROM snapshot_payload WHERE endpoint='element-summary' AND parameter='11'"
        )
    else:
        con.execute("UPDATE snapshot_capture SET payload_count=99")
    with pytest.raises(ValueError, match=r"checksum|manifest"):
        inspect_cutoff(con, season=SEASON, gw=2, cutoff=CUTOFF)
    with pytest.raises(ValueError, match=r"checksum|manifest"):
        load_official_outcomes(con, season=SEASON, capture_id="before", gameweeks=[1])


def test_complete_capture_requires_all_supported_players(con: duckdb.DuckDBPyConnection) -> None:
    _write(con, omit_summary=True)
    with pytest.raises(ValueError, match="element-summary population"):
        _outcomes(con)


@pytest.mark.parametrize("scope", [[], [1, 1], [0]])
def test_bounded_unique_outcome_scope(con: duckdb.DuckDBPyConnection, scope: list[int]) -> None:
    _write(con)
    with pytest.raises(ValueError, match="scope"):
        load_official_outcomes(con, season=SEASON, capture_id="final", gameweeks=scope)


@pytest.mark.parametrize("kind", ["gameweek", "fixture", "provisional"])
def test_official_finality_required(con: duckdb.DuckDBPyConnection, kind: str) -> None:
    bootstrap, fixtures, history = _inputs()
    if kind == "gameweek":
        bootstrap["events"][1]["finished"] = False
    else:
        fixtures[1]["finished"] = False
        fixtures[1]["finished_provisional"] = kind == "provisional"
    _write(con, bootstrap=bootstrap, fixtures=fixtures, summary=history)
    with pytest.raises(ValueError, match="not finalized"):
        _outcomes(con)


@pytest.mark.parametrize(
    "field", ["total_points", "minutes", "starts", "bonus", "bps", "defensive_contribution"]
)
def test_missing_components_remain_null(con: duckdb.DuckDBPyConnection, field: str) -> None:
    _, _, history = _inputs()
    history["history"][0][field] = None
    _write(con, summary=history)
    key = "total_points_as_recorded" if field == "total_points" else field
    assert _outcomes(con)[0][key] is None


@pytest.mark.parametrize("kind", ["duplicate", "opponent", "kickoff", "round", "element"])
def test_fixture_identity_fails_closed(con: duckdb.DuckDBPyConnection, kind: str) -> None:
    _, _, history = _inputs()
    if kind == "duplicate":
        history["history"].append(dict(history["history"][0]))
    else:
        name, value = {
            "opponent": ("opponent_team", 1),
            "kickoff": ("kickoff_time", "2026-08-23T14:00:00Z"),
            "round": ("round", 2),
            "element": ("element", 11),
        }[kind]
        history["history"][0][name] = value

    # Some loader constraints already reject contradictions; either boundary fails closed.
    def write_and_read() -> None:
        _write(con, summary=history)
        _outcomes(con)

    with pytest.raises((ValueError, duckdb.ConstraintException)):
        write_and_read()


def test_position_contradiction_fails_closed(con: duckdb.DuckDBPyConnection) -> None:
    _write(con, final=False, identity="before")
    bootstrap, _, _ = _inputs()
    bootstrap["elements"][0]["element_type"] = 3
    _write(con, bootstrap=bootstrap)
    with pytest.raises(ValueError, match="identity/position"):
        _outcomes(con)


@pytest.mark.parametrize(
    ("field", "value"),
    [("minutes", True), ("minutes", -1), ("minutes", 121), ("starts", 2), ("bonus", 4)],
)
def test_invalid_numeric_rejected(con: duckdb.DuckDBPyConnection, field: str, value: Any) -> None:
    _, _, history = _inputs()
    history["history"][0][field] = value

    def write_and_read() -> None:
        _write(con, summary=history)
        _outcomes(con)

    with pytest.raises((ValueError, duckdb.ConstraintException)):
        write_and_read()


def test_cutoff_requires_exact_official_deadline(con: duckdb.DuckDBPyConnection) -> None:
    _write(con, final=False)
    with pytest.raises(ValueError, match="official gameweek deadline"):
        inspect_cutoff(con, season=SEASON, gw=2, cutoff=CUTOFF + timedelta(minutes=1))


def test_same_gw_prior_leg_rejected(con: duckdb.DuckDBPyConnection) -> None:
    bootstrap, fixtures, history = _inputs(final=False)
    fixtures[0]["event"] = 2
    history["history"][0]["round"] = 2
    _write(con, final=False, bootstrap=bootstrap, fixtures=fixtures, summary=history)
    with pytest.raises(ValueError, match=r"strictly future|same/later"):
        inspect_cutoff(con, season=SEASON, gw=2, cutoff=CUTOFF)


def test_read_only_source_bytes_unchanged(tmp_path: Path) -> None:
    db = tmp_path / "synthetic.duckdb"
    writer = initialise(db)
    _write(writer, identity="before", final=False)
    _write(writer)
    writer.close()
    before = db.read_bytes()
    reader = duckdb.connect(str(db), read_only=True)
    try:
        inspect_cutoff(reader, season=SEASON, gw=2, cutoff=CUTOFF)
        assert len(_outcomes(reader)) == 2
    finally:
        reader.close()
    assert db.read_bytes() == before


def test_naive_cutoff_and_unwitnessed_season_rejected(con: duckdb.DuckDBPyConnection) -> None:
    _write(con, final=False)
    with pytest.raises(RuntimeError, match="timezone-aware"):
        inspect_cutoff(con, season=SEASON, gw=2, cutoff=CUTOFF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="season/mode"):
        load_official_outcomes(con, season="2025-26", capture_id="final", gameweeks=[1])


def test_goal_counts_nullable_but_boolean_invalid(con: duckdb.DuckDBPyConnection) -> None:
    _, fixtures, _ = _inputs()
    fixtures[0]["team_h_score"] = None
    _write(con, fixtures=fixtures)
    assert _outcomes(con)[0]["team_goals_scored"] is None
    fixtures[0]["team_h_score"] = True
    _write(con, fixtures=fixtures, identity="boolean-score", stamp=CUTOFF + timedelta(days=4))
    with pytest.raises(ValueError, match="invalid official numeric"):
        load_official_outcomes(con, season=SEASON, capture_id="boolean-score", gameweeks=[1])


def test_matching_names_cannot_substitute_for_provider_identity(
    con: duckdb.DuckDBPyConnection,
) -> None:
    bootstrap, _, _ = _inputs()
    bootstrap["elements"][1]["web_name"] = bootstrap["elements"][0]["web_name"]
    _write(con, bootstrap=bootstrap)
    assert {row["code"] for row in _outcomes(con)} == {1010}


@pytest.mark.parametrize("late", [False, True])
def test_promoted_diagnostic_requires_complete_pre_cutoff_prior_clubs(
    con: duckdb.DuckDBPyConnection, late: bool
) -> None:
    _write(con, final=False)
    for team in range(1, 21):
        con.execute(
            "INSERT INTO mart_dim_team(season,team_id,team_code,team_name,short_name) "
            "VALUES ('2025-26',?,?,?,?)",
            [team, 101 if team == 1 else 200 + team, f"Old{team}", f"O{team}"],
        )
    stamp = CUTOFF + timedelta(days=1 if late else -5)
    con.execute(
        "INSERT INTO raw_ingest_log(ingested_at,season,source_table,source_url,row_count,sha256) "
        "VALUES (?,'2025-26','raw_teams','retained-only',20,?)",
        [stamp, "a" * 64],
    )
    info = inspect_cutoff(con, season=SEASON, gw=2, cutoff=CUTOFF)
    if late:
        assert info["promoted_team_codes"] is None
        assert info["promoted_team_provenance"] is None
    else:
        assert info["promoted_team_codes"] == [102]
        assert info["promoted_team_provenance"]["source_sha256"] == "a" * 64
