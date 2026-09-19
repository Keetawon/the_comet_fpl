"""Offline contract for the rest-summary job's read boundary.

The job must take club identity, opponent names and the next kickoff from the sources that
already exist, and must never attach an unresolved identity to a scoped club side.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
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
                "period": "FullTime",
                "resultType": "NormalResult",
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
    assert haaland.verdict == "unknown"
    assert haaland.last_appearance is None
    assert haaland.unknown_reasons == [
        "no_witnessed_appearance_in_window",
        "schedule_coverage_unproven",
    ]


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
        "schedule_coverage_unproven",
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


def add_version(
    database: Path,
    *,
    version: str,
    known: datetime,
    valid: bool = True,
    rows: list[dict[str, object]] | None = None,
    kickoff: datetime | None = None,
    competition: int = 2,
    record_extra: dict[str, object] | None = None,
) -> None:
    body = json.loads(
        _bundle(
            match_id=5001,
            valid=valid,
            rows=rows
            if rows is not None
            else [
                _row(
                    code=GAKPO,
                    team_code=LIVERPOOL_CODE,
                    provider_team_id=LIVERPOOL_PROVIDER,
                    minutes=45.0,
                )
            ],
        )
    )
    body.update(record_extra or {})
    with initialise(database) as con:
        con.execute(
            "INSERT INTO sdp_competitive_match_version VALUES (?,?,?,?,?,?,?,?)",
            [
                version,
                "pl_sdp",
                competition,
                SEASON,
                5001,
                known,
                kickoff or datetime(2026, 9, 15, 19, tzinfo=UTC),
                json.dumps(body),
            ],
        )


def test_latest_eligible_revision_and_aba_keep_their_actual_knowledge_times(database: Path) -> None:
    with initialise(database) as con:
        con.execute(
            "UPDATE sdp_competitive_match_version SET record_json=?",
            [_bundle(match_id=5001, rows=[], valid=False)],
        )
    add_version(database, version="v2", known=AS_OF - timedelta(hours=2))
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.verdict == "midweek_played"
    assert row.last_appearance.version_id == "v2"
    assert row.last_appearance.source_known_at == AS_OF - timedelta(hours=2)
    before = job.build(database, as_of=AS_OF).model_dump_json()
    # A later ABA return to invalid/empty is a new event, not the first A timestamp.
    add_version(database, version="v3", known=AS_OF + timedelta(hours=1), rows=[], valid=False)
    assert job.build(database, as_of=AS_OF).model_dump_json() == before
    later = next(
        p for p in job.build(database, as_of=AS_OF + timedelta(hours=2)).players if p.code == GAKPO
    )
    assert later.verdict == "unknown"
    assert later.evidence_versions[0].version_id == "v3"
    assert later.evidence_versions[0].known_at == AS_OF + timedelta(hours=1)
    assert "empty_side_interpretation:5001" in later.unknown_reasons


def test_failed_empty_side_is_not_dropped_after_known_club_mapping(database: Path) -> None:
    add_version(database, version="bad", known=AS_OF - timedelta(hours=1), rows=[], valid=False)
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.verdict == "unknown"
    assert row.last_appearance is None
    assert "roster_not_proven:5001" in row.unknown_reasons
    assert row.evidence_versions[0].roster_proven is False


def test_unresolved_participant_makes_whole_side_unusable(database: Path) -> None:
    add_version(
        database,
        version="unresolved",
        known=AS_OF - timedelta(hours=1),
        rows=[
            _row(code=GAKPO, team_code=LIVERPOOL_CODE, provider_team_id=LIVERPOOL_PROVIDER),
            _row(code=None, team_code=LIVERPOOL_CODE, provider_team_id=LIVERPOOL_PROVIDER),
        ],
    )
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.verdict == "unknown"
    assert row.last_appearance is None
    assert "side_identity_unresolved:5001" in row.unknown_reasons


def test_revised_future_kickoff_cannot_resurrect_old_completed_version(database: Path) -> None:
    add_version(
        database,
        version="reschedule",
        known=AS_OF - timedelta(hours=1),
        kickoff=AS_OF + timedelta(days=2),
    )
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.verdict == "unknown"
    assert row.last_appearance is None


def test_raw_knowledge_time_cannot_postdate_interpretation(database: Path) -> None:
    add_version(
        database,
        version="bad-time",
        known=AS_OF - timedelta(hours=1),
        record_extra={"source_versions": {"lineups": {"known_at": AS_OF.isoformat()}}},
    )
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.verdict == "unknown"
    assert "source_time_contradiction:5001" in row.unknown_reasons


def test_no_capture_table_returns_honest_unknown(database: Path) -> None:
    with initialise(database) as con:
        con.execute("DROP TABLE sdp_competitive_match_version")
    result = job.build(database, as_of=AS_OF)
    assert result.counts["unknown"] == 2
    assert "competitive_participation_not_captured" in result.source_issues


def test_initial_unmapped_failure_reports_provider_match_without_name_guess(database: Path) -> None:
    with initialise(database) as con:
        con.execute(
            "UPDATE sdp_competitive_match_version SET record_json=?",
            [_bundle(match_id=5001, rows=[], valid=False)],
        )
    result = job.build(database, as_of=AS_OF)
    assert result.counts["unknown"] == 2
    assert f"provider_club_unresolved:5001:{LIVERPOOL_PROVIDER}" in result.source_issues


def _official_minutes(
    database: Path,
    *,
    known: datetime,
    minutes: int | None,
    capture: str = "history1",
    code: int = GAKPO,
    fixture: int = 77,
) -> None:
    with initialise(database) as con:
        con.execute(
            "INSERT INTO mart_fact_player_fixture_live "
            "(season,gw,fixture,kickoff_time,code,position,team_id,opponent_team_id,"
            "was_home,minutes,known_at,capture_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                SEASON,
                4,
                fixture,
                datetime(2026, 9, 15, 19, tzinfo=UTC),
                code,
                "MID",
                LIVERPOOL_ID,
                CITY_ID,
                True,
                minutes,
                known,
                capture,
            ],
        )


def _league_comparison(database: Path) -> None:
    with initialise(database) as con:
        con.execute("DELETE FROM sdp_competitive_match_version")
        con.execute(
            "INSERT INTO stg_pl_sdp_fixture_crosswalk VALUES (?,?,?,?,?,?,?,?,?)",
            [SEASON, 77, 5001, "exact", 999, True, True, True, AS_OF - timedelta(hours=3)],
        )
    add_version(
        database,
        version="league",
        competition=8,
        known=AS_OF - timedelta(hours=2),
        rows=[
            _row(
                code=GAKPO,
                team_code=LIVERPOOL_CODE,
                provider_team_id=LIVERPOOL_PROVIDER,
                minutes=45.0,
            ),
            _row(code=HAALAND, team_code=CITY_CODE, provider_team_id=CITY_PROVIDER),
        ],
        record_extra={
            "raw_metadata": {
                "id": 5001,
                "period": "FullTime",
                "resultType": "NormalResult",
                "homeTeam": {"id": LIVERPOOL_PROVIDER, "name": "Liverpool"},
                "awayTeam": {"id": CITY_PROVIDER, "name": "Man City"},
            }
        },
    )


def test_fpl_comparison_uses_exact_fixture_code_and_latest_cutoff_known_value(
    database: Path,
) -> None:
    _league_comparison(database)
    _official_minutes(database, known=AS_OF - timedelta(hours=2), minutes=42)
    _official_minutes(database, known=AS_OF + timedelta(hours=2), minutes=90, capture="future")
    _official_minutes(
        database, known=AS_OF - timedelta(hours=1), minutes=88, capture="wrong-player", code=HAALAND
    )
    _official_minutes(
        database, known=AS_OF - timedelta(hours=1), minutes=89, capture="wrong-fixture", fixture=78
    )
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.last_appearance.nominal_minutes == 45.0
    assert row.last_appearance.fpl_minutes == 42
    assert row.last_appearance.fpl_fixture_id == 77
    assert row.last_appearance.fpl_capture_id == "history1"
    assert row.last_appearance.fpl_known_at == AS_OF - timedelta(hours=2)
    # Latest NULL must not revive the older observed number.
    _official_minutes(
        database, known=AS_OF - timedelta(minutes=30), minutes=None, capture="missing"
    )
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.last_appearance.fpl_minutes is None
    assert row.last_appearance.fpl_capture_id == "missing"


def test_postcutoff_fixture_identity_proof_cannot_enter_comparison(database: Path) -> None:
    _league_comparison(database)
    _official_minutes(database, known=AS_OF - timedelta(hours=2), minutes=42)
    with initialise(database) as con:
        con.execute(
            "UPDATE stg_pl_sdp_fixture_crosswalk SET resolved_at=?", [AS_OF + timedelta(seconds=1)]
        )
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.last_appearance.fpl_minutes is None
    assert row.last_appearance.fpl_fixture_id is None


def test_fpl_comparison_rejects_contradictory_opponent_identity(database: Path) -> None:
    _league_comparison(database)
    _official_minutes(database, known=AS_OF - timedelta(hours=2), minutes=42)
    with initialise(database) as con:
        con.execute("UPDATE mart_fact_player_fixture_live SET opponent_team_id=?", [LIVERPOOL_ID])
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.last_appearance.fpl_minutes is None


def test_missing_optional_fpl_history_keeps_comparison_null(database: Path) -> None:
    _league_comparison(database)
    with initialise(database) as con:
        con.execute("DROP TABLE mart_fact_player_fixture_live")
    row = next(p for p in job.build(database, as_of=AS_OF).players if p.code == GAKPO)
    assert row.last_appearance.nominal_minutes == 45.0
    assert row.last_appearance.fpl_minutes is None
