"""Offline contracts for evidence-rich Premier League SDP audit reports."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fpl.jobs import audit_pl_sdp
from fpl.jobs.audit_pl_sdp import (
    _difference_summary,
    _staging_evidence,
    _write,
    build_coverage,
    build_identity_details,
    build_metric_inventory,
    build_reconciliation,
    main,
)
from fpl.storage.db import initialise
from fpl.transform.pl_sdp import StagingReport

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
                (1, "away", "p1", "expected_goals", "expected_goals", 0.75, None),
                (1, "away", "p1", "newProviderCount", None, 7.0, None),
            ],
        )
        report = build_metric_inventory(con)
    finally:
        con.close()

    assert report["summary"] == {
        "provider_fields": 3,
        "mapped_fields": 2,
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
    assert mapped["verified_semantics"] is True
    fallback = next(
        field for field in report["provider_fields"] if field["provider_field"] == "expected_goals"
    )
    assert fallback["mapped_local_field"] == "expected_goals"
    assert fallback["verified_semantics"] is False
    assert fallback["notes"] == "unverified fallback alias; verified live key is expectedGoals"


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


def test_coverage_emits_configured_zero_seasons_and_capturable_denominator() -> None:
    con = initialise(":memory:")
    try:
        con.executemany(
            """
            INSERT INTO stg_fixture (
                season, fixture, pulse_id, gw, kickoff_time, team_h, team_a,
                team_h_score, team_a_score, finished
            ) VALUES ('2026-27', ?, ?, 1, ?, 1, 2, ?, ?, ?)
            """,
            [
                (101, 9001, KICKOFF, 2, 1, True),
                (102, 9002, datetime(2026, 9, 20, tzinfo=UTC), None, None, False),
            ],
        )
        report = build_coverage(con)
    finally:
        con.close()

    assert set(report["providers"]["pl_sdp"]) == {
        "2021-22",
        "2022-23",
        "2023-24",
        "2024-25",
        "2025-26",
        "2026-27",
    }
    block = report["providers"]["pl_sdp"]["2026-27"]
    assert block["fixtures_expected_all"] == 2
    assert block["fixtures_expected_capturable"] == 1
    assert block["team_rows_available"] == 0
    assert block["metrics"]["shots"]["non_null"] == 0


def test_staging_evidence_keeps_failures_and_physical_counts() -> None:
    con = initialise(":memory:")
    try:
        con.execute(
            """
            INSERT INTO raw_pl_sdp_payload VALUES (
                'raw-1', 'pl_sdp', 'match_stats', '/stats', '{}', '2026-27', 9001,
                ?, 200, '{}', 'abc', 2
            )
            """,
            [KNOWN_AT],
        )
        con.execute(
            """
            INSERT INTO stg_pl_sdp_match (
                sdp_match_id,payload_id,known_at,season
            ) VALUES (9001,'raw-1',?,'2026-27')
            """,
            [KNOWN_AT],
        )
        evidence = _staging_evidence(
            con,
            match_report=StagingReport(
                payloads_read=2, matches_staged=1, schema_failures=("bad match",)
            ),
            stats_report=StagingReport(
                payloads_read=1,
                team_sides_staged=0,
                metric_rows_staged=0,
                schema_failures=("bad stats",),
            ),
        )
    finally:
        con.close()

    assert evidence["match"]["schema_failures"] == ["bad match"]
    assert evidence["stats"]["schema_failures"] == ["bad stats"]
    assert evidence["row_counts"]["raw"] == {
        "payload_versions": 1,
        "match_payload_versions": 0,
        "stats_payload_versions": 1,
        "distinct_stats_matches": 1,
    }
    assert evidence["row_counts"]["staging"]["match_version_rows"] == 1


def test_reconciliation_reports_row_level_sanity_violations() -> None:
    con = initialise(":memory:")
    try:
        con.executemany(
            """
            INSERT INTO mart_fact_team_match_stats_v2 (
                season,gw,fixture,sdp_match_id,kickoff_time,team_id,opponent_team_id,
                was_home,provider,known_at,shots,shots_on_target,shots_inside_box,
                shots_outside_box,possession,passes,accurate_passes,crosses,
                accurate_crosses,tackles,tackles_won,saves
            ) VALUES ('2026-27',1,?,?,?,?,?,?, 'pl_sdp',?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    101,
                    9001,
                    KICKOFF,
                    1,
                    2,
                    True,
                    KNOWN_AT,
                    2,
                    3,
                    1,
                    3,
                    110,
                    10,
                    11,
                    2,
                    3,
                    1,
                    2,
                    -1,
                ),
                (
                    101,
                    9001,
                    KICKOFF,
                    2,
                    1,
                    False,
                    KNOWN_AT,
                    5,
                    2,
                    3,
                    2,
                    10,
                    12,
                    10,
                    4,
                    3,
                    3,
                    2,
                    1,
                ),
                (
                    102,
                    9002,
                    KICKOFF,
                    1,
                    2,
                    True,
                    KNOWN_AT,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )
        checks = build_reconciliation(con)["sanity_checks"]
    finally:
        con.close()

    assert checks["status"] == "violations_found"
    expected = {
        "shots_on_target_le_shots": 1,
        "shots_inside_plus_outside_approximately_shots": 1,
        "possession_in_zero_to_100": 1,
        "two_side_possession_sums_to_100": 1,
        "accurate_passes_le_passes": 1,
        "accurate_crosses_le_crosses": 1,
        "tackles_won_le_tackles": 1,
        "no_negative_count_metrics": 1,
        "exactly_two_team_sides": 1,
    }
    assert {name: block["violation_count"] for name, block in checks["checks"].items()} == expected


def test_report_write_is_atomic_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "report.json"
    destination.write_text("old", encoding="utf-8")

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(audit_pl_sdp.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        _write(destination, {"new": True})

    assert destination.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [destination]


def test_non_stage_audit_preserves_existing_detailed_identity(tmp_path: Path) -> None:
    database = tmp_path / "audit.duckdb"
    initialise(database).close()
    results = tmp_path / "results"
    results.mkdir()
    identity = results / "pl_sdp_identity_audit.json"
    identity.write_text(json.dumps({"schema_version": 3, "evidence": "keep"}), encoding="utf-8")

    assert main(["--db", str(database), "--results", str(results), "--quiet"]) == 0
    assert json.loads(identity.read_text(encoding="utf-8")) == {
        "schema_version": 3,
        "evidence": "keep",
    }
