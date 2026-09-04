"""Offline contracts for evidence-rich Premier League SDP audit reports."""

from __future__ import annotations

from datetime import UTC, datetime

from fpl.jobs.audit_pl_sdp import (
    _difference_summary,
    build_identity_details,
    build_metric_inventory,
    build_reconciliation,
)
from fpl.storage.db import initialise

KNOWN_AT = datetime(2026, 9, 4, 12, tzinfo=UTC)
KICKOFF = datetime(2026, 8, 21, 20, tzinfo=UTC)


def test_difference_summary_reports_distribution_not_only_mean() -> None:
    summary = _difference_summary([-2.0, 0.0, 1.0, 5.0])
    assert summary == {
        "rows": 4,
        "mean": 1.0,
        "mean_absolute": 2.0,
        "quantiles": {
            "p00": -2.0,
            "p10": -1.4,
            "p25": -0.5,
            "p50": 0.5,
            "p75": 2.0,
            "p90": 3.8,
            "p100": 5.0,
        },
    }


def test_metric_inventory_keeps_unmapped_numeric_fields_with_examples() -> None:
    con = initialise(":memory:")
    try:
        con.executemany(
            """
            INSERT INTO stg_pl_sdp_team_match_stats (
                sdp_match_id, side, payload_id, known_at, stats_json,
                metric_count, mapped_count
            ) VALUES (?, ?, 'p1', ?, '{}', 1, ?)
            """,
            [(1, "home", KNOWN_AT, 1), (1, "away", KNOWN_AT, 0)],
        )
        con.executemany(
            """
            INSERT INTO stg_pl_sdp_team_match_metric (
                sdp_match_id, side, payload_id, provider_field, local_field,
                value_numeric, value_text
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (1, "home", "p1", "expectedGoals", "expected_goals", 1.25, None),
                (1, "away", "p1", "newProviderCount", None, 7.0, None),
            ],
        )
        report = build_metric_inventory(con)
    finally:
        con.close()

    assert report["summary"] == {
        "provider_fields": 2,
        "mapped_fields": 1,
        "unmapped_numeric_fields": 1,
    }
    assert report["unmapped_numeric_fields"] == [
        {
            "provider_field": "newProviderCount",
            "example_value": 7.0,
            "numeric_values": 1,
            "matches": 1,
        }
    ]
    mapped = next(
        field for field in report["provider_fields"] if field["provider_field"] == "expectedGoals"
    )
    assert mapped["mapped_local_field"] == "expected_goals"
    assert mapped["verified_semantics"] is False


def test_score_and_identity_reports_enumerate_real_exceptions() -> None:
    con = initialise(":memory:")
    try:
        for fixture, match_id, fpl_score, sdp_score in (
            (101, 9001, (3, 0), (3, 0)),
            (102, 9002, (2, 1), (2, 2)),
        ):
            con.execute(
                """
                INSERT INTO stg_fixture (
                    season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
                    team_h_score, team_a_score, finished
                ) VALUES ('2026-27', ?, ?, 1, ?, 1, 2, ?, ?, TRUE)
                """,
                [fixture, match_id, KICKOFF, *fpl_score],
            )
            con.execute(
                """
                INSERT INTO stg_pl_sdp_match (
                    sdp_match_id, payload_id, known_at, season, sdp_season_id,
                    matchweek, kickoff_time, home_score, away_score
                ) VALUES (?, ?, ?, '2026-27', 2026, 1, ?, ?, ?)
                """,
                [match_id, f"p-{match_id}", KNOWN_AT, KICKOFF, *sdp_score],
            )
            con.execute(
                """
                INSERT INTO stg_pl_sdp_fixture_crosswalk (
                    season, fixture, sdp_match_id, match_method, pulse_id,
                    corroborated_kickoff, corroborated_teams, corroborated_score, resolved_at
                ) VALUES ('2026-27', ?, ?, 'pulse_id', ?, TRUE, TRUE, ?, ?)
                """,
                [fixture, match_id, match_id, fpl_score == sdp_score, KNOWN_AT],
            )

        reconciliation = build_reconciliation(con)
        identity = build_identity_details(con)
    finally:
        con.close()

    assert reconciliation["score"]["rows_compared"] == 2
    assert reconciliation["score"]["exact_agreements"] == 1
    assert reconciliation["score"]["exceptions"] == [
        {
            "season": "2026-27",
            "fixture": 102,
            "sdp_match_id": 9002,
            "sdp_score": "2-2",
            "fpl_score": "2-1",
        }
    ]
    assert identity["valid_pulse_id_resolutions"] == 2
    assert identity["score_agreements"] == 1
    assert identity["duplicate_sdp_claims"] == []
