"""Offline receipt and publication guards; no retained real audit or model is rerun."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.config import repo_root
from fpl.jobs import audit_player_role_source as audit
from tests.test_player_role_source import CAPTURE, registry, structural_sample


def test_checked_body_preserves_null_and_exact_bytes() -> None:
    body = b'{ "position": null, "lineup": [["1"], ["3", "2"]] }\n'
    assert audit.checked_body(body, hashlib.sha256(body).hexdigest(), len(body), 200) == {
        "position": None,
        "lineup": [["1"], ["3", "2"]],
    }
    assert body.endswith(b" }\n")


@pytest.mark.parametrize("defect", ["hash", "byte_count", "status", "changed_body"])
def test_checked_body_rejects_receipt_contradictions(defect: str) -> None:
    body = b'{"position":null}'
    sha, size, status = hashlib.sha256(body).hexdigest(), len(body), 200
    if defect == "hash":
        sha = "0" * 64
    elif defect == "byte_count":
        size += 1
    elif defect == "status":
        status = 503
    else:
        body = b'{"position":true}'
    with pytest.raises(ValueError, match="status/bytes/hash mismatch"):
        audit.checked_body(body, sha, size, status)


def test_valid_receipt_does_not_license_malformed_json() -> None:
    body = b'{"lineup":'
    with pytest.raises(json.JSONDecodeError):
        audit.checked_body(body, hashlib.sha256(body).hexdigest(), len(body), 200)


def test_schema_inventory_uses_observed_parents_and_distinguishes_missing_from_null() -> None:
    sample = [
        {
            "match": {"matchId": "1", "clock": None},
            "lineups": {
                "home_team": {
                    "players": [
                        {"id": "1", "position": None},
                        {"id": 2, "position": "Defender"},
                        {"id": "3"},
                    ],
                    "formation": {"lineup": [["1"], ["3", "2"]], "subs": []},
                },
                "away_team": {"players": [], "formation": None},
            },
            "events": {"homeTeam": {"subs": []}, "awayTeam": {}},
        }
    ]
    before = deepcopy(sample)
    result = audit.schema_inventory(sample)
    assert result["lineup.side.players[]"] == {
        "objects": 3,
        "fields": {
            "id": {"present": 3, "missing": 0, "null": 0, "types": {"int": 1, "str": 2}},
            "position": {
                "present": 2,
                "missing": 1,
                "null": 1,
                "types": {"NoneType": 1, "str": 1},
            },
        },
    }
    assert result["lineup.side"]["fields"]["formation"] == {
        "present": 2,
        "missing": 0,
        "null": 1,
        "types": {"NoneType": 1, "dict": 1},
    }
    assert result["lineup.side.formation"]["objects"] == 1
    assert result["lineup.side.formation"]["fields"]["lineup"]["types"] == {"list": 1}
    assert result["event.side"]["fields"]["subs"]["missing"] == 1
    assert result == audit.schema_inventory(sample)
    assert sample == before


def test_existing_output_is_rejected_before_opening_inputs(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_bytes(b"original immutable report")
    with pytest.raises(FileExistsError, match="immutable"):
        audit.run(
            root=tmp_path / "absent-repository",
            retained=tmp_path / "absent-retained",
            database=tmp_path / "absent.duckdb",
            output=output,
        )
    assert output.read_bytes() == b"original immutable report"


@pytest.fixture
def synthetic_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """Exercise the real read-only DB/publication boundary with no football observations."""
    root = tmp_path / "repo"
    config = root / audit.CONFIG
    config.parent.mkdir(parents=True)
    config.write_bytes((repo_root() / audit.CONFIG).read_bytes())
    for name in (
        "src/fpl/jobs/audit_player_role_source.py",
        "src/fpl/transform/player_role_source.py",
        "src/fpl/transform/competitive_participation.py",
        "src/fpl/transform/competitive_participation_v2.py",
        "src/fpl/jobs/capture_competitive_workload.py",
        "src/fpl/ingest/pl_sdp.py",
    ):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic source fingerprint witness\n")
    database = tmp_path / "source.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE original_evidence AS SELECT 'immutable' AS payload")
    monkeypatch.setattr(audit, "DATABASE_SHA256", audit.file_sha256(database))
    monkeypatch.setattr(audit, "load_sample", lambda *_args: [])
    monkeypatch.setattr(audit, "registries", lambda *_args: {})
    monkeypatch.setattr(audit.subprocess, "check_output", lambda *_args, **_kwargs: "a" * 40)
    return {
        "root": root,
        "retained": tmp_path / "retained",
        "database": database,
        "output": tmp_path / "report.json",
    }


def test_run_preserves_database_and_identical_input_replay(synthetic_run: dict[str, Path]) -> None:
    original = audit.file_sha256(synthetic_run["database"])
    result = audit.run(**synthetic_run)
    replay = audit.run(
        **{**synthetic_run, "output": synthetic_run["output"].with_name("replay.json")},
        replay_of=synthetic_run["output"],
    )
    assert replay == result
    assert result["sample_matches"] == 0
    assert result["network_requests"] == 0
    assert result["production_mutations"] is False
    assert audit.file_sha256(synthetic_run["database"]) == original
    assert not Path(str(synthetic_run["database"]) + ".wal").exists()


def test_run_connection_cannot_write_source_database(
    synthetic_run: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def attempted_write(
        _root: Path, _retained: Path, con: duckdb.DuckDBPyConnection
    ) -> list[dict[str, Any]]:
        con.execute("DELETE FROM original_evidence")
        return []

    monkeypatch.setattr(audit, "load_sample", attempted_write)
    with pytest.raises(duckdb.InvalidInputException, match="read-only"):
        audit.run(**synthetic_run)
    assert not synthetic_run["output"].exists()
    with duckdb.connect(str(synthetic_run["database"]), read_only=True) as con:
        assert con.execute("SELECT payload FROM original_evidence").fetchall() == [("immutable",)]


def test_source_change_during_run_prevents_publication(
    synthetic_run: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    def changed_source(*_args: object) -> list[dict[str, Any]]:
        (synthetic_run["root"] / "src/fpl/ingest/pl_sdp.py").write_bytes(b"changed source")
        return []

    monkeypatch.setattr(audit, "load_sample", changed_source)
    with pytest.raises(ValueError, match="source/config/implementation changed"):
        audit.run(**synthetic_run)
    assert not synthetic_run["output"].exists()


def test_retained_state_change_during_run_prevents_publication(
    synthetic_run: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    samples = iter([[], [{"unexpected_source_version": True}]])
    monkeypatch.setattr(audit, "load_sample", lambda *_args: next(samples))
    with pytest.raises(ValueError, match="raw source state changed"):
        audit.run(**synthetic_run)
    assert not synthetic_run["output"].exists()


def test_tampered_replay_does_not_publish_a_new_report(synthetic_run: dict[str, Path]) -> None:
    report = audit.run(**synthetic_run)
    original = synthetic_run["output"].read_bytes()
    report["model_fitting"] = True
    forged = synthetic_run["output"].with_name("forged.json")
    forged.write_text(json.dumps(report), encoding="utf-8")
    output = synthetic_run["output"].with_name("rejected-replay.json")
    with pytest.raises(ValueError, match="replay differed"):
        audit.run(**{**synthetic_run, "output": output}, replay_of=forged)
    assert not output.exists()
    assert synthetic_run["output"].read_bytes() == original


def test_changed_generic_rules_fail_before_interpretation(synthetic_run: dict[str, Path]) -> None:
    (synthetic_run["root"] / audit.CONFIG).write_bytes(b"oop: invented\n")
    with pytest.raises(ValueError, match="generic source rules changed"):
        audit.run(**synthetic_run)
    assert not synthetic_run["output"].exists()


@pytest.fixture
def historical_fixture() -> Iterator[tuple[duckdb.DuckDBPyConnection, dict[str, Any]]]:
    with duckdb.connect() as con:
        con.execute(
            """CREATE TABLE stg_pl_sdp_fixture_crosswalk (
                season VARCHAR, sdp_match_id INTEGER, fixture INTEGER,
                corroborated_kickoff BOOLEAN, corroborated_teams BOOLEAN, corroborated_score BOOLEAN
            )"""
        )
        con.execute(
            "INSERT INTO stg_pl_sdp_fixture_crosswalk VALUES ('2025-26',9001,77,true,true,true)"
        )
        con.execute(
            """CREATE TABLE stg_fixture (
                season VARCHAR, fixture INTEGER, kickoff_time TIMESTAMPTZ,
                team_h INTEGER, team_a INTEGER, team_h_score INTEGER, team_a_score INTEGER
            )"""
        )
        con.execute(
            """INSERT INTO stg_fixture VALUES
                ('2025-26',77,'2025-09-14T15:00:00Z',2,8,1,0)"""
        )
        con.execute("CREATE TABLE mart_dim_team (season VARCHAR,team_id INTEGER,team_code INTEGER)")
        con.execute(
            """INSERT INTO mart_dim_team VALUES
                ('2025-26',2,3),('2025-26',8,31),('2024-25',2,99),('2024-25',8,100)"""
        )
        yield (
            con,
            {
                "season": "2025-26",
                "match": {
                    "matchId": "9001",
                    "competitionId": "8",
                    "season": "2025",
                    "kickoff": "2025-09-14T15:00:00Z",
                    "homeTeam": {"id": "3", "name": "Different provider display name", "score": 1},
                    "awayTeam": {"id": "31", "name": "Away display name", "score": 0},
                },
            },
        )


def test_fixture_identity_rechecks_season_qualified_sides_and_preserves_witness(
    historical_fixture: tuple[duckdb.DuckDBPyConnection, dict[str, Any]],
) -> None:
    con, entry = historical_fixture
    fixture, evidence = audit.fixture_identity(con, entry, {"known_at": CAPTURE.isoformat()})
    assert fixture == 77
    assert evidence == {
        "fixture": 77,
        "provider_match_id": 9001,
        "home_provider_team_id": 3,
        "home_fpl_team_code": 3,
        "away_provider_team_id": 31,
        "away_fpl_team_code": 31,
        "method": "existing_corroborated_crosswalk_and_archive_fixture",
        "known_at": CAPTURE.isoformat(),
        "historical_deadline_known_at": None,
    }


@pytest.mark.parametrize("witness", ["kickoff", "teams", "score"])
def test_missing_fixture_corroboration_fails_closed(
    historical_fixture: tuple[duckdb.DuckDBPyConnection, dict[str, Any]], witness: str
) -> None:
    con, entry = historical_fixture
    con.execute(f"UPDATE stg_pl_sdp_fixture_crosswalk SET corroborated_{witness}=false")
    with pytest.raises(ValueError, match="no unique corroborated fixture crosswalk"):
        audit.fixture_identity(con, entry, {"known_at": CAPTURE.isoformat()})


def test_duplicate_fixture_claim_is_not_arbitrarily_selected(
    historical_fixture: tuple[duckdb.DuckDBPyConnection, dict[str, Any]],
) -> None:
    con, entry = historical_fixture
    con.execute(
        "INSERT INTO stg_pl_sdp_fixture_crosswalk SELECT * FROM stg_pl_sdp_fixture_crosswalk"
    )
    with pytest.raises(ValueError, match="no unique corroborated fixture crosswalk"):
        audit.fixture_identity(con, entry, {"known_at": CAPTURE.isoformat()})


@pytest.mark.parametrize("defect", ["kickoff", "score", "team"])
def test_independent_fixture_contradiction_cannot_be_rescued_by_crosswalk_or_name(
    historical_fixture: tuple[duckdb.DuckDBPyConnection, dict[str, Any]], defect: str
) -> None:
    con, entry = historical_fixture
    if defect == "kickoff":
        entry["match"]["kickoff"] = "2025-09-14T15:01:00Z"
    elif defect == "score":
        entry["match"]["homeTeam"]["score"] = 2
    else:
        entry["match"]["homeTeam"]["id"] = "99"
    with pytest.raises(ValueError, match="independent identity contradiction"):
        audit.fixture_identity(con, entry, {"known_at": CAPTURE.isoformat()})


def test_cup_numeric_team_overlap_does_not_create_a_club_identity_anchor(
    synthetic_run: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    match, lineups, events = structural_sample()
    match["competitionId"] = "1"
    match["homeTeam"]["name"] = "Home"
    match["awayTeam"]["name"] = "Away"
    sources = {
        endpoint: {"captured_at_utc": CAPTURE.isoformat(), "retained_known_at": CAPTURE.isoformat()}
        for endpoint in ("metadata", "lineups", "events")
    }
    sample = [
        {
            "sample_group": "synthetic",
            "season": "2025-26",
            "match": match,
            "lineups": lineups,
            "events": events,
            "sources": sources,
        }
    ]
    identities = {
        "2025-26": {
            "known_at": CAPTURE.isoformat(),
            "rows": registry(),
            "team_codes": [3, 31],
            "provenance": {"source": "synthetic_registry"},
        }
    }
    monkeypatch.setattr(audit, "load_sample", lambda *_args: deepcopy(sample))
    monkeypatch.setattr(audit, "registries", lambda *_args: identities)
    report = audit.run(**synthetic_run)
    assert not report["failures"]
    assert report["interpreted_matches"] == 1
    observed = report["matches"][0]
    assert observed["fixture"] is None
    assert observed["provenance"]["club_identity_witnesses"] == [None, None]
    players = [row for side in observed["sides"] for row in side["rows"]]
    assert players
    assert all(row["fpl_code"] is not None for row in players)
    assert all(row["team_code"] is None for row in players)
