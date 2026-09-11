"""Coverage-only tests: the study stops before score construction or evaluation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pytest
import yaml

from fpl.jobs.audit_attacking_role_premium_feasibility import (
    audit,
    coverage,
    exposure_bins,
    main,
    select_history,
)
from fpl.jobs.competitive_participation_pilot import file_sha256

CUTOFF = datetime(2026, 9, 4, 17, 30, tzinfo=UTC)


def row(**changes: Any) -> dict[str, Any]:
    return {
        "season": "2026-27",
        "code": 101,
        "element": 1,
        "fixture": 1,
        "gw": 1,
        "position": "DEF",
        "team_id": 2,
        "capture_id": "a",
        "kickoff_time": "2026-08-21T19:00:00Z",
        "known_at": "2026-08-25T15:00:00Z",
        "minutes": 90,
        "expected_goals": 0.1,
        "expected_assists": None,
        **changes,
    }


@pytest.mark.parametrize(
    "field", ["minutes", "expected_goals", "expected_assists", "formation_band"]
)
def test_target_observation_never_changes_prior_feature_inventory(field: str) -> None:
    past = row()
    target = row(fixture=3, gw=3, kickoff_time="2026-09-04T19:00:00Z")
    before = select_history([past, target], as_of=CUTOFF, target_batch=("2026-27", 3))
    target[field] = 999
    assert (
        select_history([past, target], as_of=CUTOFF, target_batch=("2026-27", 3))
        == before
        == [past]
    )


def test_whole_gameweek_excludes_earlier_double_gameweek_leg() -> None:
    earlier_leg = row(fixture=3, gw=3)
    assert select_history([earlier_leg], as_of=CUTOFF, target_batch=("2026-27", 3)) == []


def test_latest_cutoff_known_whole_version_and_future_truncation() -> None:
    old = row(expected_assists=0.2)
    correction = row(capture_id="b", known_at="2026-09-01T00:00:00Z", expected_goals=0.3)
    future = row(capture_id="c", known_at="2026-09-05T00:00:00Z", expected_goals=50.0)
    truncated = select_history([old, correction], as_of=CUTOFF)
    full = select_history([future, correction, old], as_of=CUTOFF)
    assert json.dumps(full, sort_keys=True) == json.dumps(truncated, sort_keys=True)
    assert full == [correction]
    assert full[0]["expected_assists"] is None  # no cherry-picking from an older payload


def test_known_unavailable_revision_does_not_revive_old_available_payload() -> None:
    old = row()
    failed = row(capture_id="b", known_at="2026-09-01T00:00:00Z", source_available=False)
    assert select_history([old, failed], as_of=CUTOFF) == []
    unseen = {**failed, "available_at": "2026-09-05T00:00:00Z"}
    assert select_history([old, unseen], as_of=CUTOFF) == [old]


def test_microsecond_boundary_is_exact() -> None:
    from fpl.jobs.audit_attacking_role_premium_feasibility import epoch_instant

    exact = epoch_instant(1_788_542_999_999_999)
    assert exact.microsecond == 999999
    assert select_history([row(known_at=exact)], as_of=exact) == [row(known_at=exact)]


@pytest.mark.parametrize(
    "changes",
    [
        {"known_at": None},
        {"known_at": "2026-09-05T00:00:00Z"},
        {"available_at": None},
        {"available_at": "2026-09-05T00:00:00Z"},
        {"source_available": False},
        {"kickoff_time": CUTOFF.isoformat()},
    ],
)
def test_unavailable_source_rejected(changes: dict[str, Any]) -> None:
    assert select_history([row(**changes)], as_of=CUTOFF) == []


def test_naive_time_and_duplicate_source_identity_fail_closed() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        select_history([row()], as_of=CUTOFF.replace(tzinfo=None))
    with pytest.raises(ValueError, match="duplicate"):
        select_history([row(), row(expected_goals=0.3)], as_of=CUTOFF)
    with pytest.raises(ValueError, match="contradictory"):
        select_history([row(), row(code=102)], as_of=CUTOFF)


def test_identity_is_season_qualified_and_transfers_retain_stable_code() -> None:
    older = row(season="2025-26", code=999)
    current = row(team_id=8)
    transferred = row(fixture=2, gw=2, team_id=9)
    selected = select_history([older, transferred, current], as_of=CUTOFF)
    assert [(r["season"], r["code"], r["team_id"]) for r in selected] == [
        ("2025-26", 999, 2),
        ("2026-27", 101, 8),
        ("2026-27", 101, 9),
    ]


def test_missing_is_unavailable_and_explicit_zero_is_measured() -> None:
    missing = row(minutes=None, expected_goals=None)
    measured = row(code=102, minutes=0, expected_goals=0.0)
    stats = coverage([missing, measured])
    assert stats["fields"]["expected_goals"]["measured_valid_rows"] == 1
    assert stats["fields"]["expected_goals"]["null_or_absent_rows"] == 1
    assert stats["fields"]["shots"]["field_present_rows"] == 0
    assert stats["fields"]["shots"]["null_or_absent_rows"] == 2
    assert stats["appeared_rows"] == 0
    assert missing["expected_goals"] is None and missing["minutes"] is None


def test_nonfinite_negative_boolean_values_are_not_valid_numeric_evidence() -> None:
    values = [None, float("nan"), float("inf"), -1.0, True, 0.0]
    stats = coverage([row(expected_goals=value) for value in values])["fields"]["expected_goals"]
    assert stats["measured_valid_rows"] == 1
    assert stats["invalid_numeric_rows"] == 4
    assert stats["null_or_absent_rows"] == 1


def test_invalid_minutes_do_not_enter_exposure_or_appearance_totals() -> None:
    records = [row(minutes=v) for v in (None, float("nan"), float("inf"), -1, True)]
    stats = coverage(records)
    assert stats["appeared_rows"] == 0
    assert stats["total_measured_minutes"] is None
    assert all(value == 0 for value in exposure_bins(records).values())


def test_low_exposure_is_reported_without_inventing_shrinkage_or_band() -> None:
    assert exposure_bins([row(minutes=45)]) == {
        "players_with_at_least_90_minutes": 0,
        "players_with_at_least_180_minutes": 0,
        "players_with_at_least_360_minutes": 0,
        "players_with_at_least_720_minutes": 0,
    }
    assert select_history([row()], as_of=CUTOFF)[0].get("formation_band") is None


@pytest.fixture
def sources(tmp_path: Path) -> tuple[Path, Path, Path]:
    database, role, config = (
        tmp_path / "source.duckdb",
        tmp_path / "role.json",
        tmp_path / "audit.yaml",
    )
    with duckdb.connect(str(database)) as con:
        con.execute("""CREATE TABLE mart_fact_player_fixture(season VARCHAR,gw INTEGER,
            fixture INTEGER,code INTEGER,position VARCHAR,team_id INTEGER,minutes INTEGER,
            starts INTEGER,expected_goals DOUBLE,expected_assists DOUBLE,
            kickoff_time TIMESTAMPTZ)""")
        con.execute("""INSERT INTO mart_fact_player_fixture VALUES
            ('2025-26',38,380,101,'DEF',2,90,1,NULL,NULL,'2026-05-24T15:00:00Z')""")
        con.execute("""CREATE TABLE stg_live_player_fixture_version AS SELECT *,
            'capture'::VARCHAR AS capture_id,1::INTEGER AS element,
            '2026-08-25T15:00:00Z'::TIMESTAMPTZ AS known_at
            FROM mart_fact_player_fixture WHERE false""")
        con.execute("""INSERT INTO stg_live_player_fixture_version VALUES
            ('2026-27',1,1,101,'DEF',2,90,1,0.1,0.2,'2026-08-21T19:00:00Z',
             'capture',1,'2026-08-25T15:00:00Z')""")
        for table in ("raw_merged_gw", "raw_players", "raw_teams", "raw_fixtures"):
            con.execute(
                f"CREATE TABLE {table} AS SELECT "
                "'2026-08-19T09:00:00Z'::TIMESTAMPTZ AS _ingested_at"
            )
        con.execute("""CREATE TABLE raw_ingest_log AS SELECT '2025-26' AS season,
            'raw_merged_gw' AS source_table,'2026-08-19T09:00:00Z'::TIMESTAMPTZ AS ingested_at,
            'hash' AS sha256""")
        con.execute("""CREATE TABLE snapshot_capture AS SELECT 'bootstrap' AS capture_id,
            '2026-27' AS season,'2026-08-20T00:00:00Z'::TIMESTAMPTZ AS captured_at""")
        con.execute("""CREATE TABLE snapshot_payload(capture_id VARCHAR,parameter VARCHAR,
            endpoint VARCHAR,payload JSON,sha256 VARCHAR)""")
        con.execute(
            "INSERT INTO snapshot_payload VALUES ('bootstrap','','bootstrap-static',?,'hash')",
            [json.dumps({"events": [{"id": 1, "deadline_time": "2026-08-21T17:30:00Z"}]})],
        )
        con.execute("""CREATE TABLE stg_live_player_version AS SELECT '2026-27' AS season,
            101 AS code,'DEF' AS position,2 AS team_id,'bootstrap' AS capture_id,
            '2026-08-20T00:00:00Z'::TIMESTAMPTZ AS known_at""")
        con.execute("""CREATE TABLE stg_live_team_version AS SELECT '2026-27' AS season,
            2 AS team_id,42 AS team_code,'bootstrap' AS capture_id,
            '2026-08-20T00:00:00Z'::TIMESTAMPTZ AS known_at""")
        con.execute("""CREATE TABLE mart_dim_team AS SELECT '2025-26' AS season,
            2 AS team_id,42 AS team_code""")
        con.execute("""CREATE TABLE raw_pl_sdp_payload(payload_id VARCHAR,endpoint VARCHAR,
            payload JSON,sha256 VARCHAR)""")
    role.write_text(
        json.dumps({"sample_matches": 23, "interpretation_known_at": "2026-09-08T05:08:40Z"}),
        encoding="utf-8",
    )
    config.write_text(
        yaml.safe_dump(
            {
                "study_id": "attacking_role_premium_feasibility_v1",
                "contract_version": "1.0",
                "evidence_policy": "strict_known_at",
                "database_sha256": file_sha256(database),
                "role_result_sha256": file_sha256(role),
                "inventory_as_of": "2026-09-08T06:34:33Z",
                "decision": "INSUFFICIENT_DATA_FOR_ATTACKING_ROLE_PREMIUM_STUDY",
            }
        ),
        encoding="utf-8",
    )
    return database, role, config


def test_inventory_is_deterministic_read_only_and_leaves_unestimated_scores_null(
    sources: tuple[Path, Path, Path],
) -> None:
    before = [file_sha256(path) for path in sources]
    first = audit(*sources)
    second = audit(*sources)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert [file_sha256(path) for path in sources] == before
    assert first["source_hashes_unchanged"] is True
    assert first["formal_evaluation"] is False and first["model_fitting"] is False
    assert first["feasibility"]["attacking_role_premium"] is None
    assert first["feasibility"]["regime_shift_count"] is None
    assert first["formation_support"]["eligible_in_completed_live_batches"] == 0
    batch = first["live"]["completed_gameweek_batches"][0]
    assert batch["identity_eligible_observed_target_rows"] == 1
    assert batch["prior_archive_outfield_rows"] == 1
    assert batch["prior_live_outfield_rows"] == 0
    assert batch["cold_no_positive_measured_history"] == 1


def test_cli_publication_cannot_overwrite_original(
    sources: tuple[Path, Path, Path],
    tmp_path: Path,
) -> None:
    database, role, config = sources
    output = tmp_path / "result.json"
    args = [
        "--db",
        str(database),
        "--role-result",
        str(role),
        "--config",
        str(config),
        "--output",
        str(output),
    ]
    assert main(args) == 0
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        main(args)
    assert output.read_bytes() == original


def test_source_pin_and_unresolved_wal_fail_closed(sources: tuple[Path, Path, Path]) -> None:
    database, role, config = sources
    wal = Path(str(database) + ".wal")
    wal.write_bytes(b"unresolved")
    with pytest.raises(ValueError, match="pin/WAL"):
        audit(database, role, config)
    wal.unlink()
    role.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="pin/WAL"):
        audit(database, role, config)
