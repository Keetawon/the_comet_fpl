"""Offline contract for the rest-summary job's read boundary.

The job must take club identity, opponent names and the next kickoff from the sources that
already exist, and must never attach an unresolved identity to a scoped club side.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl.jobs import rest_summary as job
from fpl.jobs.capture_sdp_workload import DDL
from fpl.storage.db import initialise

SEASON = "2026-27"
AS_OF = datetime(2026, 9, 18, 10, 0, tzinfo=UTC)
# Season-scoped FPL team ids, their permanent codes, and the provider's own club ids.
LIVERPOOL_ID, LIVERPOOL_CODE, LIVERPOOL_PROVIDER = 12, 14, 26
CITY_ID, CITY_CODE, CITY_PROVIDER = 13, 43, 11
GAKPO, HAALAND, MANAGER = 111111, 222222, 333333

BOOTSTRAP = {
    "teams": [
        {"id": LIVERPOOL_ID, "code": LIVERPOOL_CODE, "name": "Liverpool", "short_name": "LIV"},
        {"id": CITY_ID, "code": CITY_CODE, "name": "Man City", "short_name": "MCI"},
    ],
    "elements": [
        {"id": 1, "code": GAKPO, "web_name": "Gakpo", "element_type": 3, "team": LIVERPOOL_ID},
        {"id": 2, "code": HAALAND, "web_name": "Haaland", "element_type": 4, "team": CITY_ID},
        {"id": 3, "code": MANAGER, "web_name": "Slot", "element_type": 5, "team": LIVERPOOL_ID},
    ],
    "events": [],
}


def _bundle(*, match_id: int, rows: list[dict[str, object]], valid: bool = True) -> str:
    return json.dumps(
        {
            "valid": valid,
            "errors": [] if valid else ["two goalkeepers in the starting roster"],
            "raw_metadata": {
                "id": match_id,
                "homeTeam": {"id": LIVERPOOL_PROVIDER, "name": "Liverpool"},
                "awayTeam": {"id": 6, "name": "Tottenham"},
            },
            "rows": rows,
        }
    )


def _row(
    *,
    code: int | None,
    team_code: int | None,
    provider_team_id: int,
    appeared: bool | None = True,
    started: bool | None = True,
    minutes: float | None = 90.0,
) -> dict[str, object]:
    return {
        "provider_player_id": 900 + (code or 0) % 100,
        "code": code,
        "team_code": team_code,
        "provider_team_id": provider_team_id,
        "appeared": appeared,
        "started": started,
        "nominal_minutes": minutes,
        "identity_errors": [],
    }


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "operational.duckdb"
    with initialise(path) as con:
        con.execute(DDL)
        con.execute(
            "INSERT INTO snapshot_capture VALUES (?,?,?,?,?,?,?,?)",
            ["cap-1", datetime(2026, 9, 18, 6, 0, tzinfo=UTC), SEASON, 5, "daily", 1, "{}", "x"],
        )
        con.execute(
            "INSERT INTO snapshot_payload VALUES (?,?,?,?,?,?,?)",
            ["cap-1", "bootstrap-static", "", json.dumps(BOOTSTRAP), "sha", 1, 1],
        )
        for team, opponent, home, kickoff, gw in (
            (LIVERPOOL_ID, CITY_ID, True, datetime(2026, 9, 20, 15, 30, tzinfo=UTC), 5),
            (CITY_ID, LIVERPOOL_ID, False, datetime(2026, 9, 20, 15, 30, tzinfo=UTC), 5),
            # A later fixture must never displace the next one.
            (LIVERPOOL_ID, CITY_ID, False, datetime(2026, 9, 27, 13, 0, tzinfo=UTC), 6),
        ):
            con.execute(
                "INSERT INTO mart_team_fixture_live "
                "(season, gw, fixture, pulse_id, kickoff_time, team_id, opponent_team_id, "
                "was_home, fdr, rest_days, known_at, capture_id) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    SEASON,
                    gw,
                    gw * 10 + team,
                    None,
                    kickoff,
                    team,
                    opponent,
                    home,
                    None,
                    None,
                    datetime(2026, 9, 18, 6, 0, tzinfo=UTC),
                    "cap-1",
                ],
            )
        con.execute(
            "INSERT INTO sdp_competitive_match_version VALUES (?,?,?,?,?,?,?,?)",
            [
                "v1",
                "pl_sdp",
                2,
                SEASON,
                5001,
                datetime(2026, 9, 16, 2, 0, tzinfo=UTC),
                datetime(2026, 9, 15, 19, 0, tzinfo=UTC),
                _bundle(
                    match_id=5001,
                    rows=[
                        _row(
                            code=GAKPO,
                            team_code=LIVERPOOL_CODE,
                            provider_team_id=LIVERPOOL_PROVIDER,
                        ),
                        # An unresolved player identity must not reach a scoped side.
                        _row(code=None, team_code=LIVERPOOL_CODE, provider_team_id=26),
                        # A foreign club without an FPL code must not become a scoped side.
                        _row(code=777, team_code=None, provider_team_id=6),
                    ],
                ),
            ],
        )
    return path


def test_the_job_reads_identity_opponents_and_the_next_kickoff_from_existing_sources(
    database: Path,
) -> None:
    document = job.build(database, as_of=AS_OF)
    assert document.season == SEASON
    # Element type 5 is not a player and never enters the population.
    assert {p.code for p in document.players} == {GAKPO, HAALAND}

    gakpo = next(p for p in document.players if p.code == GAKPO)
    assert gakpo.verdict == "midweek_played"
    assert gakpo.last_appearance is not None
    assert gakpo.last_appearance.competition_name == "League Cup"
    assert gakpo.last_appearance.opponent_name == "Tottenham"
    assert gakpo.last_appearance.nominal_minutes == 90.0
    assert gakpo.next_fixture is not None
    assert (gakpo.next_fixture.gw, gakpo.next_fixture.opponent_name) == (5, "Man City")
    assert gakpo.next_fixture.was_home is True
    assert gakpo.rest_days == 5

    haaland = next(p for p in document.players if p.code == HAALAND)
    # City played no fixture in the window at all, so nothing is witnessed and nothing invented.
    assert haaland.verdict == "full_rest"
    assert haaland.last_appearance is None
    assert haaland.unknown_reasons == ["no_witnessed_appearance_in_window"]


def test_an_invalid_interpretation_leaves_the_verdict_unknown(database: Path) -> None:
    with initialise(database) as con:
        con.execute(
            "UPDATE sdp_competitive_match_version SET record_json = ? WHERE version_id = 'v1'",
            [
                _bundle(
                    match_id=5001,
                    rows=[
                        _row(
                            code=GAKPO,
                            team_code=LIVERPOOL_CODE,
                            provider_team_id=LIVERPOOL_PROVIDER,
                        )
                    ],
                    valid=False,
                )
            ],
        )
    gakpo = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert gakpo.verdict == "unknown"
    assert gakpo.unknown_reasons == [
        "no_witnessed_appearance_in_window",
        "roster_not_proven:5001",
    ]


def test_a_fixture_outside_the_window_is_not_read(database: Path) -> None:
    document = job.build(database, as_of=AS_OF, window_hours=24)
    assert next(p for p in document.players if p.code == GAKPO).window_appearances == 0


def test_an_unknown_requested_code_fails_closed(database: Path) -> None:
    with pytest.raises(ValueError, match="absent from the selectable registry"):
        job.build(database, as_of=AS_OF, codes=frozenset({GAKPO, 999999}))


def test_a_code_filter_narrows_the_population(database: Path) -> None:
    document = job.build(database, as_of=AS_OF, codes=frozenset({GAKPO}))
    assert [p.code for p in document.players] == [GAKPO]
    assert document.counts["players"] == 1


def test_the_written_pack_validates_and_is_never_silently_overwritten(
    database: Path, tmp_path: Path
) -> None:
    document = job.build(database, as_of=AS_OF)
    out = tmp_path / "rest"
    result = job.write(document, out)
    written = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
    assert job.validate_rest_summary(written).counts == document.counts
    assert "National-team call-ups are not captured" in Path(result["text"]).read_text(
        encoding="utf-8"
    )
    with pytest.raises(FileExistsError):
        job.write(document, out)


def test_the_code_file_ignores_comments_and_blank_lines(tmp_path: Path) -> None:
    target = tmp_path / "squad.txt"
    target.write_text(f"# my squad\n{GAKPO}\n\n{HAALAND}  # captain\n", encoding="utf-8")
    parsed = job._codes(argparse.Namespace(codes=None, code_file=target))
    assert parsed == frozenset({GAKPO, HAALAND})
