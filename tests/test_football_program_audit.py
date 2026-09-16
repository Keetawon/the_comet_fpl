"""Small offline inventories, no archive, HTTP, model fitting, or evaluation."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from fpl.jobs import audit_football_program as audit


def _schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE mart_fact_player_fixture (
            season VARCHAR, gw INTEGER, fixture INTEGER, code INTEGER, position VARCHAR,
            minutes INTEGER, yellow_cards INTEGER, red_cards INTEGER
        );
        INSERT INTO mart_fact_player_fixture VALUES
          ('2025-26',22,215,44699,'FWD',0,1,0),
          ('2025-26',22,215,2,'DEF',90,0,1),
          ('2025-26',22,215,3,'MID',90,0,0),
          ('2025-26',22,215,4,'GK',0,NULL,NULL);
        CREATE TABLE stg_player_fixture AS SELECT * FROM mart_fact_player_fixture;
        CREATE TABLE raw_merged_gw (season VARCHAR, minutes VARCHAR,
                                   yellow_cards VARCHAR, red_cards VARCHAR);
        INSERT INTO raw_merged_gw VALUES ('2024-25','90','','0'),
                                        ('2025-26','0','1','0');
        CREATE TABLE mart_target_completeness (
            season VARCHAR, ruleset_id VARCHAR, is_complete BOOLEAN,
            missing_components VARCHAR, row_count INTEGER
        );
        INSERT INTO mart_target_completeness VALUES
          ('2024-25','2026_27',FALSE,'defensive_contribution',20),
          ('2025-26','2026_27',TRUE,'',4);
        CREATE TABLE raw_pl_sdp_payload (
            provider VARCHAR, endpoint VARCHAR, season VARCHAR,
            status_code INTEGER, sdp_match_id BIGINT
        );
        INSERT INTO raw_pl_sdp_payload VALUES
          ('pl_sdp','match_lineups','2025-26',200,12),
          ('pl_sdp','match_lineups','2025-26',200,12),
          ('pl_sdp','match_events','2025-26',404,12),
          ('pl_sdp','match_stats','2025-26',200,12);
        CREATE TABLE stg_example_lineup (match_id BIGINT);
        INSERT INTO stg_example_lineup VALUES (12);
    """)


@pytest.fixture
def inventory() -> dict[str, object]:
    with duckdb.connect(":memory:") as con:
        _schema(con)
        return audit.database_inventory(con)


def test_cards_keep_null_blank_zero_and_recorded_joint_states(inventory: dict) -> None:
    cards = inventory["cards"]
    raw = cards["raw_merged_gw"]["joint_states"]
    assert raw[0]["yellow_cards"] == ""
    assert raw[0]["red_cards"] == "0"
    mart = cards["mart_fact_player_fixture"]["joint_states"]
    assert {(row["yellow_cards"], row["red_cards"]) for row in mart} == {
        (None, None),
        (0, 0),
        (0, 1),
        (1, 0),
    }
    assert sum(row["rows"] for row in mart) == 4
    assert cards["stg_player_fixture"]["joint_states"] == mart


def test_bench_card_is_preserved_not_zeroed_or_filtered(inventory: dict) -> None:
    assert inventory["zero_minute_card_exceptions"] == [
        {
            "season": "2025-26",
            "gw": 22,
            "fixture": 215,
            "code": 44699,
            "position": "FWD",
            "minutes": 0,
            "yellow_cards": 1,
            "red_cards": 0,
        }
    ]


def test_capture_versions_are_not_counted_as_distinct_matches(inventory: dict) -> None:
    captures = inventory["raw_lineup_event_captures"]
    lineups = next(row for row in captures if row["endpoint"] == "match_lineups")
    assert lineups["payload_versions"] == 2
    assert lineups["distinct_matches"] == 1
    assert any(row["status_code"] == 404 for row in captures)
    assert inventory["staging_participation_tables"] == [{"table": "stg_example_lineup", "rows": 1}]


def test_completeness_does_not_claim_readiness(inventory: dict) -> None:
    assert inventory["target_completeness"][0]["is_complete"] is False
    assert audit.prerequisite_status(inventory)[-1]["status"] == "prerequisites_unverified"
    assert all(row["status"] != "ready" for row in audit.prerequisite_status(inventory))


def test_snapshot_coverage_does_not_invent_historical_deadline_registry() -> None:
    with duckdb.connect(":memory:") as con:
        con.execute("SET TimeZone = 'UTC'")
        _schema(con)
        assert audit.database_inventory(con)["versioned_registry_snapshot_coverage"] is None
        con.execute("CREATE TABLE snapshot_capture (season VARCHAR, captured_at TIMESTAMPTZ)")
        con.execute("INSERT INTO snapshot_capture VALUES ('2026-27', '2026-07-27T09:48:30Z')")
        measured = audit.database_inventory(con)["versioned_registry_snapshot_coverage"]
        assert measured == [
            {
                "season": "2026-27",
                "captures": 1,
                "first_capture_utc": "2026-07-27T09:48:30Z",
                "last_capture_utc": "2026-07-27T09:48:30Z",
            }
        ]


def test_missing_tables_remain_missing_not_empty_measurements() -> None:
    with duckdb.connect(":memory:") as con:
        result = audit.database_inventory(con)
    assert result["zero_minute_card_exceptions"] is None
    assert result["target_completeness"] is None
    assert result["raw_lineup_event_captures"] is None
    assert audit.prerequisite_status(result)[-1]["status"] == "blocked_no_complete_target"


def test_frozen_evidence_records_hash_metrics_provenance_and_missing_files(tmp_path: Path) -> None:
    root = tmp_path / "results"
    root.mkdir()
    path = root / "v2_team_environment_development.json"
    payload = {
        "git": {"head": "old"},
        "gk_saves": {"overall": {"score": 2.0}},
        "harness": {"overall": {"score": 1.0}, "predictions": [{"pmf": [1]}]},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = audit.repository_inventory(tmp_path)
    record = result["frozen_evidence"]["results/v2_team_environment_development.json"]
    assert record["sha256"] == audit.file_sha256(path)
    assert record["retained_summary"]["git"] == {"head": "old"}
    assert record["retained_summary"]["gk_saves"] == payload["gk_saves"]
    assert record["retained_summary"]["harness"] == {"overall": {"score": 1.0}}
    assert result["frozen_evidence"]["results/v2_dc_development.json"] == {"status": "missing"}


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "source.duckdb"
    with duckdb.connect(str(path)) as con:
        _schema(con)
    return path


def _git_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "_git", lambda _repo: {"head": "test", "clean_worktree": False})


def test_file_audit_is_read_only_and_write_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _database(tmp_path)
    before = source.read_bytes()
    output = tmp_path / "reports" / "new.json"
    _git_stub(monkeypatch)
    report = audit.run_audit(source, output, repo=tmp_path)
    assert source.read_bytes() == before
    assert not Path(f"{source}.wal").exists()
    assert report["database"]["sha256_before"] == report["database"]["sha256_after"]
    assert report["database"]["read_only"] is True
    assert report["readiness_claim"] is False
    assert report["evaluation_performed"] is False
    assert json.loads(output.read_text()) == report
    with pytest.raises(FileExistsError):
        audit.run_audit(source, output, repo=tmp_path)


def test_wal_refused_without_modifying_database_or_sidecar(tmp_path: Path) -> None:
    source = _database(tmp_path)
    before = source.read_bytes()
    wal = Path(f"{source}.wal")
    wal.write_bytes(b"unresolved")
    output = tmp_path / "audit.json"
    with pytest.raises(RuntimeError, match="unresolved WAL"):
        audit.run_audit(source, output, repo=tmp_path)
    assert source.read_bytes() == before
    assert wal.read_bytes() == b"unresolved"
    assert not output.exists()


def test_report_cannot_be_a_database_sidecar(tmp_path: Path) -> None:
    source = _database(tmp_path)
    with pytest.raises(ValueError, match="WAL sidecar"):
        audit.run_audit(source, Path(f"{source}.wal"), repo=tmp_path)
    assert not Path(f"{source}.wal").exists()


def test_changed_database_hash_refuses_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _database(tmp_path)
    hashes = iter(("before", "after"))
    monkeypatch.setattr(audit, "file_sha256", lambda _path: next(hashes))
    _git_stub(monkeypatch)
    output = tmp_path / "audit.json"
    with pytest.raises(RuntimeError, match="database changed"):
        audit.run_audit(source, output, repo=tmp_path)
    assert not output.exists()


def test_cli_requires_explicit_database_and_output() -> None:
    with pytest.raises(SystemExit):
        audit.main([])


def test_connection_rejects_writes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _database(tmp_path)
    _git_stub(monkeypatch)
    original = audit.database_inventory

    def verify_read_only(con: duckdb.DuckDBPyConnection) -> dict:
        with pytest.raises(duckdb.InvalidInputException, match="read-only"):
            con.execute("CREATE TABLE forbidden_write (i INTEGER)")
        return original(con)

    monkeypatch.setattr(audit, "database_inventory", verify_read_only)
    audit.run_audit(source, tmp_path / "audit.json", repo=tmp_path)


def test_changed_repository_refuses_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _database(tmp_path)
    _git_stub(monkeypatch)
    versions = iter(({"sha256": "old"}, {"sha256": "new"}))
    monkeypatch.setattr(audit, "repository_inventory", lambda _repo: next(versions))
    output = tmp_path / "audit.json"
    with pytest.raises(RuntimeError, match="repository evidence changed"):
        audit.run_audit(source, output, repo=tmp_path)
    assert not output.exists()


def test_malformed_evidence_is_not_silently_omitted(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    (tmp_path / "results/v2_dc_development.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="not a JSON object"):
        audit.repository_inventory(tmp_path)
