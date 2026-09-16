"""Raw revision -> rebuild -> identical old-cutoff football and tactical observations.

Synthetic payloads exercise the real landing, staging and measured-crosswalk path. They are
offline regression cases, not new evidence about the live provider's football semantics.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest

from fpl.features.pit import AsOf, FeatureSource, LeakageError, PointInTimeView
from fpl.ingest.pl_sdp import RawPayload
from fpl.storage.db import initialise
from fpl.transform import football_v2
from fpl.transform import pl_sdp as sdp

from .test_football_v2 import KICKOFF, _seed
from .test_pl_sdp_transform import (
    LIVE_FIXTURE,
    LIVE_KICKOFF,
    LIVE_SEASON,
    _seed_live_fixture_capture,
)

SEASON = "2025-26"
CAPTURED = KICKOFF + timedelta(days=23)
OLD_CUTOFF = CAPTURED + timedelta(days=1)
REVISED = CAPTURED + timedelta(days=2)
NEW_CUTOFF = REVISED + timedelta(days=1)


@pytest.fixture
def con(tmp_path: Path) -> Iterator[duckdb.DuckDBPyConnection]:
    connection = initialise(tmp_path / "revision-pit.duckdb")
    try:
        yield connection
    finally:
        connection.close()


def _raw(endpoint: str, payload: Any, known_at: datetime, match_id: int = 0) -> RawPayload:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return RawPayload(
        endpoint=endpoint,
        path=f"/api/v3/matches/{match_id}/stats" if match_id else "/api/v2/matches",
        params={"match_id": match_id} if match_id else {"season": 2025},
        fetched_at=known_at,
        status_code=200,
        text=text,
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        byte_count=len(text.encode()),
        payload=payload,
    )


def _seed_matches(con: duckdb.DuckDBPyConnection, *, matches: int = 4) -> None:
    _seed(con, matches=matches)
    con.execute(
        """
        INSERT INTO stg_fixture (
            season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
            team_h_score, team_a_score, finished
        ) SELECT season, fixture, pulse_id, gw, kickoff_time, team_id,
                 opponent_team_id, goals_for, goals_against, TRUE
          FROM mart_fact_team_match WHERE was_home
        """
    )
    records = []
    for index in range(matches):
        home, away = (3, 8) if index % 2 == 0 else (8, 3)
        records.append(
            {
                "id": 300100 + index,
                "season": {"id": 2025},
                "matchweek": index + 1,
                "kickoff": {
                    "millis": int((KICKOFF + timedelta(days=7 * index)).timestamp() * 1000)
                },
                "status": "COMPLETE",
                "teams": [{"team": {"id": code}} for code in (home, away)],
                "score": {"homeScore": 2, "awayScore": 1},
            }
        )
    sdp.land_payload(con, _raw("matches", {"content": records}, CAPTURED), season=SEASON)


def _stats(
    con: duckdb.DuckDBPyConnection,
    fixture: int,
    arsenal_sot: int | None,
    *,
    known_at: datetime = CAPTURED,
    chelsea_sot: int | None = 3,
) -> tuple[str, str]:
    home, away = (3, 8) if fixture % 2 == 0 else (8, 3)
    payload = [
        {
            "side": side,
            "team": {"id": team},
            "stats": {
                "goals": 2 if side == "Home" else 1,
                "totalScoringAtt": 20,
                "ontargetScoringAtt": arsenal_sot if team == 3 else chelsea_sot,
                "expectedGoals": 1.8 if team == 3 else 0.7,
            },
        }
        for side, team in (("Home", home), ("Away", away))
    ]
    raw = _raw("match_stats", payload, known_at, 300000 + fixture)
    identifier, _ = sdp.land_payload(con, raw, season=SEASON, sdp_match_id=300000 + fixture)
    return identifier, raw.sha256


def _rebuild(
    con: duckdb.DuckDBPyConnection, *, season: str = SEASON, season_id: int = 2025
) -> None:
    assert not sdp.stage_matches(con, season_labels={season_id: season}).schema_failures
    assert not sdp.stage_team_stats(con).schema_failures
    audit = sdp.resolve_crosswalk(con, seasons=[season])
    assert not audit.contradictions and not audit.ambiguities
    assert audit.matched_by_pulse_id == 0
    assert audit.unmatched_fpl_fixtures == 0
    assert football_v2.build_all(con).skipped_reason is None


def _read(con: duckdb.DuckDBPyConnection, cutoff: datetime) -> tuple[pl.DataFrame, pl.DataFrame]:
    view = PointInTimeView(FeatureSource(con), AsOf(cutoff))
    return (
        view.observed_team_football(providers=["pl_sdp"]).sort(["season", "fixture", "team_code"]),
        view.observed_team_tactical_form(providers=["pl_sdp"]).sort(
            ["season", "gw", "team_code", "window"]
        ),
    )


def _form(frame: pl.DataFrame, gw: int, window: str = "last_3") -> dict[str, Any]:
    return frame.filter(
        (pl.col("team_code") == 3) & (pl.col("gw") == gw) & (pl.col("window") == window)
    ).row(0, named=True)


def test_later_revision_and_rebuild_preserve_both_old_cutoff_frames(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con)
    for fixture, sot in ((100, 2), (101, 4), (102, 6), (103, 8)):
        _stats(con, fixture, sot)
    _rebuild(con)
    before = _read(con, OLD_CUTOFF)

    original = con.execute(
        "SELECT payload_id, sha256 FROM raw_pl_sdp_payload ORDER BY payload_id"
    ).fetchall()
    revision_id, revision_sha = _stats(con, 100, 10, known_at=REVISED, chelsea_sot=7)
    _rebuild(con)
    after_old = _read(con, OLD_CUTOFF)
    after_new = _read(con, NEW_CUTOFF)

    assert all(a.equals(b) for a, b in zip(before, after_old, strict=True))
    assert after_new[0].height == before[0].height == 8
    revised_match = after_new[0].filter(pl.col("fixture") == 100)
    assert revised_match["shots_on_target"].to_list() == [10, 7]
    assert revised_match["shots_on_target_allowed"].to_list() == [7, 10]
    assert _form(before[1], 3)["shots_on_target_per_match"] == 4
    assert _form(after_new[1], 3)["shots_on_target_per_match"] == pytest.approx(20 / 3)
    # Revision of GW1 changes a containing window, but never becomes an extra match in GW4.
    assert _form(after_new[1], 4)["matches"] == 3
    assert _form(after_new[1], 4)["shots_on_target_per_match"] == 6
    assert _form(after_new[1], 4, "season_to_date")["matches"] == 4
    assert _form(after_new[1], 4, "season_to_date")["shot_accuracy"] == pytest.approx(28 / 80)
    retained = con.execute(
        "SELECT payload_id, sha256 FROM raw_pl_sdp_payload ORDER BY payload_id"
    ).fetchall()
    assert set(original) <= set(retained)
    assert (revision_id, revision_sha) in retained
    assert con.execute("SELECT count(*) FROM stg_pl_sdp_team_match_stats").fetchone() == (10,)
    assert con.execute("SELECT count(*) FROM mart_fact_team_match_stats_v2_version").fetchone() == (
        10,
    )
    provenance = (
        PointInTimeView(FeatureSource(con), AsOf(NEW_CUTOFF))
        .observed_team_football(
            team_codes=[3],
            providers=["pl_sdp"],
            columns=["fixture", "capture_id", "payload_sha256", "source_known_at", "known_at"],
        )
        .filter(pl.col("fixture") == 100)
        .row(0, named=True)
    )
    assert provenance["capture_id"] == revision_id
    assert provenance["payload_sha256"] == revision_sha
    assert provenance["source_known_at"] == provenance["known_at"] == REVISED

    again = _read(con, OLD_CUTOFF)
    _rebuild(con)
    assert all(a.equals(b) for a, b in zip(again, _read(con, OLD_CUTOFF), strict=True))


def test_newly_discovered_older_match_reorders_window_only_after_capture(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con)
    for fixture, sot in ((100, 2), (102, 6), (103, 8)):
        _stats(con, fixture, sot)
    _rebuild(con)
    before = _read(con, OLD_CUTOFF)
    assert _form(before[1], 4)["shots_on_target_per_match"] == pytest.approx(16 / 3)

    _stats(con, 101, 4, known_at=REVISED)
    _rebuild(con)
    assert all(a.equals(b) for a, b in zip(before, _read(con, OLD_CUTOFF), strict=True))
    football, tactical = _read(con, NEW_CUTOFF)
    assert football.height == 8
    assert _form(tactical, 4)["matches"] == 3
    assert _form(tactical, 4)["shots_on_target_per_match"] == 6


def test_provider_reversion_a_b_a_retains_three_vintages_through_both_pit_accessors(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con, matches=2)
    first_id, first_sha = _stats(con, 100, 2)
    _stats(con, 101, 4)
    _rebuild(con)
    first_frames = _read(con, OLD_CUTOFF)

    middle_id, middle_sha = _stats(con, 100, 10, known_at=REVISED)
    _rebuild(con)
    middle_frames = _read(con, NEW_CUTOFF)
    assert all(a.equals(b) for a, b in zip(first_frames, _read(con, OLD_CUTOFF), strict=True))

    reverted_at = NEW_CUTOFF + timedelta(days=1)
    reverted_id, reverted_sha = _stats(con, 100, 2, known_at=reverted_at)
    _rebuild(con)
    reverted_frames = _read(con, reverted_at)
    assert len({first_id, middle_id, reverted_id}) == 3
    assert first_sha == reverted_sha != middle_sha
    assert all(a.equals(b) for a, b in zip(first_frames, _read(con, OLD_CUTOFF), strict=True))
    assert all(a.equals(b) for a, b in zip(middle_frames, _read(con, NEW_CUTOFF), strict=True))

    for frames, expected_sot, expected_mean in (
        (first_frames, 2, 3.0),
        (middle_frames, 10, 7.0),
        (reverted_frames, 2, 3.0),
    ):
        football, tactical = frames
        assert football.height == 4
        assert football.filter((pl.col("fixture") == 100) & (pl.col("team_code") == 3))[
            "shots_on_target"
        ].to_list() == [expected_sot]
        assert _form(tactical, 2)["matches"] == 2
        assert _form(tactical, 2)["shots_on_target_per_match"] == expected_mean

    assert con.execute(
        "SELECT payload_id, sha256 FROM raw_pl_sdp_payload "
        "WHERE sdp_match_id = 300100 ORDER BY fetched_at"
    ).fetchall() == [(first_id, first_sha), (middle_id, middle_sha), (reverted_id, reverted_sha)]
    for table in ("stg_pl_sdp_team_match_stats", "mart_fact_team_match_stats_v2_version"):
        assert con.execute(
            f"SELECT count(*) FROM {table} WHERE sdp_match_id = 300100"
        ).fetchone() == (6,)
    provenance = (
        PointInTimeView(FeatureSource(con), AsOf(reverted_at))
        .observed_team_football(
            team_codes=[3],
            providers=["pl_sdp"],
            columns=["fixture", "capture_id", "payload_sha256", "source_known_at"],
        )
        .filter(pl.col("fixture") == 100)
        .row(0, named=True)
    )
    assert provenance == {
        "fixture": 100,
        "capture_id": reverted_id,
        "payload_sha256": first_sha,
        "source_known_at": reverted_at,
    }


@pytest.mark.parametrize("new_sot", [None, 0])
def test_revision_null_and_explicit_zero_do_not_fall_back_to_previous_value(
    con: duckdb.DuckDBPyConnection, new_sot: int | None
) -> None:
    _seed_matches(con, matches=1)
    _stats(con, 100, 2)
    _rebuild(con)
    before = _read(con, OLD_CUTOFF)
    _stats(con, 100, new_sot, known_at=REVISED)
    _rebuild(con)
    assert all(a.equals(b) for a, b in zip(before, _read(con, OLD_CUTOFF), strict=True))
    football, tactical = _read(con, NEW_CUTOFF)
    assert football.filter(pl.col("team_code") == 3)["shots_on_target"].to_list() == [new_sot]
    assert football.filter(pl.col("team_code") == 8)["shots_on_target_allowed"].to_list() == [
        new_sot
    ]
    assert _form(tactical, 1)["shots_on_target_per_match"] == new_sot
    assert _form(tactical, 1)["shot_accuracy"] == (None if new_sot is None else 0)


def test_same_capture_time_tie_selects_one_deterministic_whole_payload(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con, matches=1)
    one = _stats(con, 100, 2, chelsea_sot=3)[0]
    two = _stats(con, 100, 10, chelsea_sot=7, known_at=CAPTURED + timedelta(microseconds=1))[0]
    # New landing rejects ambiguous simultaneous changes. A database can nevertheless
    # retain legacy ties, so construct that reader-only fixture explicitly before staging.
    con.execute(
        "UPDATE raw_pl_sdp_payload SET fetched_at = ? WHERE payload_id = ?", [CAPTURED, two]
    )
    _rebuild(con)
    before = _read(con, OLD_CUTOFF)
    expected = [2, 3] if one > two else [10, 7]
    assert before[0]["shots_on_target"].to_list() == expected
    assert before[0]["shots_on_target_allowed"].to_list() == list(reversed(expected))
    assert _form(before[1], 1)["matches"] == 1
    # Physical insertion order must not become an implicit provider-version policy.
    con.execute(
        "CREATE TEMP TABLE reversed_raw AS "
        "SELECT * FROM raw_pl_sdp_payload ORDER BY payload_id DESC"
    )
    con.execute("DELETE FROM raw_pl_sdp_payload")
    con.execute("INSERT INTO raw_pl_sdp_payload SELECT * FROM reversed_raw")
    _rebuild(con)
    assert all(a.equals(b) for a, b in zip(before, _read(con, OLD_CUTOFF), strict=True))


def test_double_gameweek_keeps_two_legs_and_one_tactical_anchor(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con)
    con.execute("UPDATE stg_fixture SET gw = 3 WHERE fixture = 103")
    con.execute("UPDATE mart_fact_team_match SET gw = 3 WHERE fixture = 103")
    for fixture, sot in ((100, 2), (101, 4), (102, 6), (103, 8)):
        _stats(con, fixture, sot)
    _rebuild(con)
    before = _read(con, OLD_CUTOFF)
    _stats(con, 102, 12, known_at=REVISED)
    _rebuild(con)
    assert all(a.equals(b) for a, b in zip(before, _read(con, OLD_CUTOFF), strict=True))
    football, tactical = _read(con, NEW_CUTOFF)
    assert football.filter((pl.col("team_code") == 3) & (pl.col("gw") == 3)).height == 2
    assert tactical.filter((pl.col("team_code") == 3) & (pl.col("gw") == 3)).height == 4
    assert _form(tactical, 3)["matches"] == 3
    assert _form(tactical, 3)["shots_on_target_per_match"] == 8


def test_event_and_capture_cutoffs_are_independent_and_strict(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con, matches=2)
    con.execute(
        "UPDATE raw_pl_sdp_payload SET fetched_at = ? WHERE endpoint = 'matches'",
        [KICKOFF - timedelta(hours=2)],
    )
    _stats(con, 100, 2, known_at=KICKOFF - timedelta(hours=1))
    _stats(con, 101, 4, known_at=REVISED)
    _rebuild(con)
    # Deliberately early captured synthetic stats cannot expose a target-match result.
    assert _read(con, KICKOFF)[0].is_empty()
    assert _read(con, KICKOFF)[1].is_empty()
    assert _read(con, KICKOFF + timedelta(microseconds=1))[0].height == 2
    assert _read(con, REVISED - timedelta(microseconds=1))[0].height == 2
    assert _read(con, REVISED)[0].height == 4


def test_physically_truncated_raw_rebuild_equals_full_database_at_old_cutoff(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con)
    for fixture, sot in ((100, 2), (102, 6), (103, 8)):
        _stats(con, fixture, sot)
    _stats(con, 100, 10, known_at=REVISED)
    _stats(con, 101, 4, known_at=REVISED)
    _rebuild(con)
    full = _read(con, OLD_CUTOFF)
    con.execute("DELETE FROM raw_pl_sdp_payload WHERE fetched_at > ?", [OLD_CUTOFF])
    con.execute(
        "DELETE FROM mart_fact_team_match_stats_v2_version WHERE known_at > ?", [OLD_CUTOFF]
    )
    _rebuild(con)
    truncated = _read(con, OLD_CUTOFF)
    assert all(a.equals(b) for a, b in zip(full, truncated, strict=True))


def test_filters_keep_provider_and_stable_team_identity_isolated(
    con: duckdb.DuckDBPyConnection,
) -> None:
    _seed_matches(con, matches=1)
    _stats(con, 100, 2)
    _rebuild(con)
    view = PointInTimeView(FeatureSource(con), AsOf(OLD_CUTOFF))
    frame = view.observed_team_football(team_codes=[3], seasons=[SEASON], providers=["pl_sdp"])
    assert frame.height == 1
    assert frame["team_id"].to_list() == [1]
    assert frame["team_code"].to_list() == [3]
    assert frame["sdp_match_id"].to_list() == [300100]
    assert frame["pulse_id"].to_list() != frame["sdp_match_id"].to_list()
    assert (
        view.observed_team_football(providers=["fpl_archive"])["shots_on_target"].null_count() == 2
    )
    assert view.observed_team_football(seasons=["2026-27"]).is_empty()
    for filters in ({"providers": []}, {"seasons": []}, {"team_codes": []}):
        assert view.observed_team_football(**filters).is_empty()
        assert view.observed_team_tactical_form(**filters).is_empty()


@pytest.mark.parametrize("drop_companion", [False, True])
def test_missing_revision_migration_fails_closed_even_before_latest_report_capture(
    con: duckdb.DuckDBPyConnection, drop_companion: bool
) -> None:
    _seed_matches(con, matches=1)
    _stats(con, 100, 2)
    _stats(con, 100, 10, known_at=REVISED)
    _rebuild(con)
    view = PointInTimeView(FeatureSource(con), AsOf(OLD_CUTOFF))
    assert view.observed_team_football(providers=["pl_sdp"]).height == 2
    assert con.execute(
        "SELECT count(*) FROM mart_fact_team_match_stats_v2 "
        "WHERE provider = 'pl_sdp' AND known_at <= ?",
        [OLD_CUTOFF],
    ).fetchone() == (0,)

    if drop_companion:
        con.execute("DROP TABLE mart_fact_team_match_stats_v2_version")
    else:
        con.execute("DELETE FROM mart_fact_team_match_stats_v2_version")
    # A latest-only report has no witness for the older raw payload. Returning empty here
    # would conceal an incomplete migration, not correctly reject future information.
    with pytest.raises(LeakageError, match="revision read model is missing"):
        view.observed_team_football(providers=["pl_sdp"])
    with pytest.raises(LeakageError, match="revision read model is missing"):
        view.observed_team_tactical_form(providers=["pl_sdp"])
    assert view.observed_team_football(providers=["fpl_archive"]).height == 2


def test_later_live_fixture_metadata_cannot_rewrite_an_earlier_cutoff(
    con: duckdb.DuckDBPyConnection,
) -> None:
    """A retained stats body alone cannot protect against a latest-only schedule join."""
    stats_known = LIVE_KICKOFF + timedelta(days=1)
    cutoff = stats_known + timedelta(hours=1)
    live_revision = stats_known + timedelta(days=1)
    match_id = 400101
    _seed_live_fixture_capture(
        con,
        capture_id="live-original",
        known_at=LIVE_KICKOFF - timedelta(days=1),
        match_pulse_id=999101,
        kickoff=LIVE_KICKOFF,
        home_score=2,
        away_score=1,
        home_team_pulse_id=1,
        away_team_pulse_id=4,
    )
    metadata = {
        "content": [
            {
                "id": match_id,
                "season": {"id": 2026},
                "matchweek": 1,
                "kickoff": {"millis": int(LIVE_KICKOFF.timestamp() * 1000)},
                "status": "COMPLETE",
                "teams": [{"team": {"id": 3}}, {"team": {"id": 8}}],
                "score": {"homeScore": 2, "awayScore": 1},
            }
        ]
    }
    sdp.land_payload(con, _raw("matches", metadata, stats_known), season=LIVE_SEASON)
    payload = [
        {"side": "Home", "team": {"id": 3}, "stats": {"ontargetScoringAtt": 6}},
        {"side": "Away", "team": {"id": 8}, "stats": {"ontargetScoringAtt": 2}},
    ]
    sdp.land_payload(
        con,
        _raw("match_stats", payload, stats_known, match_id),
        season=LIVE_SEASON,
        sdp_match_id=match_id,
    )
    _rebuild(con, season=LIVE_SEASON, season_id=2026)
    before = _read(con, cutoff)
    assert before[0].height == 2

    _seed_live_fixture_capture(
        con,
        capture_id="live-revised",
        known_at=live_revision,
        match_pulse_id=999101,
        kickoff=LIVE_KICKOFF + timedelta(minutes=1),
        home_score=2,
        away_score=1,
        home_team_pulse_id=1,
        away_team_pulse_id=4,
    )
    con.execute("UPDATE mart_team_fixture_live SET gw = 2 WHERE capture_id = 'live-revised'")
    con.execute("UPDATE stg_live_fixture_version SET gw = 2 WHERE capture_id = 'live-revised'")
    _rebuild(con, season=LIVE_SEASON, season_id=2026)
    assert all(a.equals(b) for a, b in zip(before, _read(con, cutoff), strict=True))
    new_football, _ = _read(con, live_revision + timedelta(seconds=1))
    assert new_football["fixture"].to_list() == [LIVE_FIXTURE, LIVE_FIXTURE]
    assert new_football["gw"].to_list() == [2, 2]
    assert new_football["kickoff_time"].to_list() == [LIVE_KICKOFF + timedelta(minutes=1)] * 2
    assert new_football["known_at"].min() >= live_revision
    assert con.execute(
        "SELECT count(DISTINCT metadata_capture_id), count(*) "
        "FROM mart_fact_team_match_stats_v2_version"
    ).fetchone() == (2, 4)
    provenance = (
        PointInTimeView(FeatureSource(con), AsOf(live_revision))
        .observed_team_football(
            team_codes=[3],
            providers=["pl_sdp"],
            columns=["source_known_at", "metadata_known_at", "metadata_capture_id"],
        )
        .row(0, named=True)
    )
    assert provenance == {
        "source_known_at": stats_known,
        "metadata_known_at": live_revision,
        "metadata_capture_id": "live-revised",
    }
