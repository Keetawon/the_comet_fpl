"""SDP landing, staging, and the MEASURED fixture-identity crosswalk.

The identity tests are the important ones. `pulse_id == sdp_match_id` is a hypothesis this
repository refuses to assume, and the consequence of getting it wrong is silent: one club's
football metrics attached to another club's fixture, with no downstream check that would catch
it. So ambiguity and contradiction must fail closed, and these tests construct both.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.ingest.pl_sdp import RawPayload
from fpl.storage.db import initialise
from fpl.transform import pl_sdp as sdp
from fpl.transform.pl_sdp import SdpIdentityError

FIXTURES = Path(__file__).parent / "fixtures" / "pl_sdp"
KICKOFF = datetime(2025, 11, 25, 15, 0, tzinfo=UTC)


def _fixture(name: str) -> Any:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _raw(endpoint: str, payload: Any, *, path: str = "/api/v2/x", **params: Any) -> RawPayload:
    text = json.dumps(payload)
    import hashlib

    return RawPayload(
        endpoint=endpoint,
        path=path,
        params=params,
        fetched_at=datetime(2025, 11, 26, 8, 0, tzinfo=UTC),
        status_code=200,
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        byte_count=len(text.encode()),
        payload=payload,
    )


@pytest.fixture
def con(tmp_path: Path) -> duckdb.DuckDBPyConnection:
    connection = initialise(tmp_path / "v2.duckdb")
    yield connection
    connection.close()


def _seed_fpl_fixture(
    connection: duckdb.DuckDBPyConnection,
    *,
    season: str = "2025-26",
    fixture: int = 7,
    pulse_id: int | None = 116001,
    kickoff: datetime = KICKOFF,
    home_score: int | None = 2,
    away_score: int | None = 1,
) -> None:
    connection.execute(
        """
        INSERT INTO stg_fixture (season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
                                 team_h_score, team_a_score, finished)
        VALUES (?, ?, ?, 12, ?, 1, 4, ?, ?, TRUE)
        """,
        [season, fixture, pulse_id, kickoff, home_score, away_score],
    )
    for team_id, team_code, name, short in ((1, 3, "Arsenal", "ARS"), (4, 8, "Chelsea", "CHE")):
        connection.execute(
            """
            INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name)
            VALUES (?, ?, ?, ?, ?)
            """,
            [season, team_id, team_code, name, short],
        )


def _stage_sdp_match(
    connection: duckdb.DuckDBPyConnection, *, match_id: int = 116001, kickoff: datetime = KICKOFF
) -> None:
    payload = _fixture("matches_page")
    payload["content"][0]["id"] = match_id
    payload["content"][0]["kickoff"] = {"millis": int(kickoff.timestamp() * 1000)}
    del payload["content"][1]
    sdp.land_payload(connection, _raw("matches", payload, season="2025-26"), season="2025-26")
    sdp.stage_matches(connection, season_labels={719: "2025-26"})


# -- landing ----------------------------------------------------------------------------


def test_landing_is_idempotent_for_identical_content(con: duckdb.DuckDBPyConnection) -> None:
    raw = _raw("match_stats", _fixture("match_stats"), match_id=116001)
    first_id, first_new = sdp.land_payload(con, raw, sdp_match_id=116001)
    second_id, second_new = sdp.land_payload(con, raw, sdp_match_id=116001)
    assert first_id == second_id
    assert first_new is True and second_new is False
    assert con.execute("SELECT count(*) FROM raw_pl_sdp_payload").fetchone() == (1,)


def test_a_provider_restatement_lands_beside_the_original(con: duckdb.DuckDBPyConnection) -> None:
    """An overwrite would destroy the knowledge time a point-in-time model depends on."""
    original = _fixture("match_stats")
    sdp.land_payload(con, _raw("match_stats", original, match_id=1), sdp_match_id=1)
    revised = json.loads(json.dumps(original))
    revised[0]["stats"]["expected_goals"] = 1.91
    sdp.land_payload(con, _raw("match_stats", revised, match_id=1), sdp_match_id=1)
    assert con.execute("SELECT count(*) FROM raw_pl_sdp_payload").fetchone() == (2,)


def test_raw_payload_retains_exact_bytes(con: duckdb.DuckDBPyConnection) -> None:
    raw = _raw("match_stats", _fixture("match_stats"), match_id=1)
    sdp.land_payload(con, raw, sdp_match_id=1)
    stored = con.execute("SELECT payload, sha256, byte_count FROM raw_pl_sdp_payload").fetchone()
    assert stored is not None
    assert json.loads(stored[0]) == raw.payload
    assert stored[1] == raw.sha256
    assert stored[2] == raw.byte_count


# -- staging ----------------------------------------------------------------------------


def test_every_provider_field_reaches_the_tall_store(con: duckdb.DuckDBPyConnection) -> None:
    """A field the dictionary does not claim must be retained, not dropped."""
    sdp.land_payload(
        con, _raw("match_stats", _fixture("match_stats_unknown_fields"), match_id=5), sdp_match_id=5
    )
    report = sdp.stage_team_stats(con)
    assert "brand_new_upstream_metric" in report.unmapped_provider_fields
    stored = con.execute(
        """
        SELECT value_numeric FROM stg_pl_sdp_team_match_metric
        WHERE provider_field = 'brand_new_upstream_metric' AND side = 'home'
        """
    ).fetchone()
    assert stored == (42.0,)
    mapped = con.execute(
        "SELECT local_field FROM stg_pl_sdp_team_match_metric "
        "WHERE provider_field = 'brand_new_upstream_metric'"
    ).fetchall()
    assert all(row[0] is None for row in mapped), "an unmapped field must not claim a local name"


def test_mapped_fields_reach_their_typed_columns(con: duckdb.DuckDBPyConnection) -> None:
    sdp.land_payload(con, _raw("match_stats", _fixture("match_stats"), match_id=5), sdp_match_id=5)
    sdp.stage_team_stats(con)
    row = con.execute(
        """
        SELECT goals, expected_goals, shots_on_target, touches_in_opposition_box, possession
        FROM stg_pl_sdp_team_match_stats WHERE side = 'home'
        """
    ).fetchone()
    assert row == (2, 1.84, 7, 31, 58.4)


def test_percent_is_stored_on_a_0_100_scale(con: duckdb.DuckDBPyConnection) -> None:
    """Both sides of a match must sum to ~100 for the consistency check to mean anything."""
    sdp.land_payload(con, _raw("match_stats", _fixture("match_stats"), match_id=5), sdp_match_id=5)
    sdp.stage_team_stats(con)
    total = con.execute("SELECT sum(possession) FROM stg_pl_sdp_team_match_stats").fetchone()
    assert total is not None and abs(float(total[0]) - 100.0) < 0.5


def test_staging_is_rebuildable_from_raw_without_refetching(
    con: duckdb.DuckDBPyConnection,
) -> None:
    sdp.land_payload(con, _raw("match_stats", _fixture("match_stats"), match_id=5), sdp_match_id=5)
    first = sdp.stage_team_stats(con)
    second = sdp.stage_team_stats(con)
    assert first.team_sides_staged == second.team_sides_staged == 2
    assert con.execute("SELECT count(*) FROM stg_pl_sdp_team_match_stats").fetchone() == (2,)


def test_a_match_with_no_resolvable_season_is_skipped_not_guessed(
    con: duckdb.DuckDBPyConnection,
) -> None:
    payload = {"content": [{"id": 999, "kickoff": "2025-11-25T15:00:00Z"}]}
    sdp.land_payload(con, _raw("matches", payload))
    report = sdp.stage_matches(con, season_labels={})
    assert report.matches_staged == 0
    assert any("no resolvable season label" in failure for failure in report.schema_failures)


# -- identity ----------------------------------------------------------------------------


def test_pulse_id_match_is_measured_and_corroborated(con: duckdb.DuckDBPyConnection) -> None:
    _seed_fpl_fixture(con)
    _stage_sdp_match(con)
    audit = sdp.resolve_crosswalk(con, team_name_codes=sdp.team_name_code_map(con))
    assert audit.matched_by_pulse_id == 1
    assert audit.pulse_id_match_rate == 1.0
    assert audit.kickoff_corroborated == 1
    assert audit.teams_corroborated == 1
    assert audit.score_corroborated == 1
    row = con.execute(
        "SELECT sdp_match_id, match_method FROM stg_pl_sdp_fixture_crosswalk"
    ).fetchone()
    assert row == (116001, sdp.MATCH_METHOD_PULSE_ID)


def test_pulse_id_match_rate_is_none_when_no_fixture_carries_one(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """'The question could not be asked' is a different finding from 'the answer is no'."""
    _seed_fpl_fixture(con, pulse_id=None)
    _stage_sdp_match(con)
    audit = sdp.resolve_crosswalk(con)
    assert audit.pulse_id_present == 0
    assert audit.pulse_id_match_rate is None
    assert audit.matched_by_identity_fallback == 1


def test_a_contradicting_pulse_id_fails_closed(con: duckdb.DuckDBPyConnection) -> None:
    """A pulse_id pointing at a match with the wrong score is not the same match."""
    _seed_fpl_fixture(con, home_score=5, away_score=0)
    _stage_sdp_match(con)
    with pytest.raises(SdpIdentityError, match="contradiction"):
        sdp.resolve_crosswalk(con)


def test_a_contradiction_is_recorded_when_failures_are_allowed(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_fpl_fixture(con, home_score=5, away_score=0)
    _stage_sdp_match(con)
    audit = sdp.resolve_crosswalk(con, strict=False)
    assert audit.contradictions
    assert "score" in audit.contradictions[0]


def test_two_candidates_at_the_same_kickoff_are_ambiguous_not_guessed(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """Choosing between two identical-looking matches is exactly the silent failure to avoid."""
    _seed_fpl_fixture(con, pulse_id=None)
    payload = _fixture("matches_page")
    for index, match_id in enumerate((500001, 500002)):
        payload["content"][index]["id"] = match_id
        payload["content"][index]["kickoff"] = {"millis": int(KICKOFF.timestamp() * 1000)}
        payload["content"][index]["score"] = {"homeScore": 2, "awayScore": 1}
    sdp.land_payload(con, _raw("matches", payload, season="2025-26"), season="2025-26")
    sdp.stage_matches(con, season_labels={719: "2025-26"})
    with pytest.raises(SdpIdentityError, match="ambiguit"):
        sdp.resolve_crosswalk(con)


def test_one_sdp_match_cannot_be_claimed_by_two_fixtures(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_fpl_fixture(con, fixture=7, pulse_id=116001)
    con.execute(
        """
        INSERT INTO stg_fixture (season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
                                 team_h_score, team_a_score, finished)
        VALUES ('2025-26', 8, 116001, 12, ?, 1, 4, 2, 1, TRUE)
        """,
        [KICKOFF],
    )
    _stage_sdp_match(con)
    with pytest.raises(SdpIdentityError, match="claimed by both"):
        sdp.resolve_crosswalk(con)


def test_a_kickoff_a_day_out_is_not_corroborated(con: duckdb.DuckDBPyConnection) -> None:
    """Slack wide enough to span a day would let two different matches corroborate."""
    _seed_fpl_fixture(con, pulse_id=None)
    _stage_sdp_match(con, kickoff=KICKOFF + timedelta(days=1))
    audit = sdp.resolve_crosswalk(con, strict=False)
    assert audit.matched_by_identity_fallback == 0
    assert audit.unmatched_fpl_fixtures == 1


def test_team_name_map_drops_a_name_used_by_two_clubs(con: duckdb.DuckDBPyConnection) -> None:
    """Corroboration that can be wrong is worse than corroboration that is absent."""
    con.execute(
        """
        INSERT INTO mart_dim_team (season, team_id, team_code, team_name, short_name) VALUES
            ('2024-25', 1, 3, 'Arsenal', 'ARS'),
            ('2025-26', 1, 3, 'Arsenal', 'ARS'),
            ('2025-26', 2, 91, 'Ambiguous FC', 'AMB'),
            ('2024-25', 2, 43, 'Ambiguous FC', 'AMB')
        """
    )
    mapping = sdp.team_name_code_map(con)
    assert mapping["arsenal"] == 3
    assert "ambiguous fc" not in mapping
