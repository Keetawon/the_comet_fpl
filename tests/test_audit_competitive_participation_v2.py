"""Offline synthetic runner guards; never replay a real participation bundle here."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fpl.config import repo_root
from fpl.jobs import audit_competitive_participation_v2 as audit
from fpl.jobs.capture_competitive_workload import RetainedInputs
from fpl.transform.competitive_participation import ParticipationError

CAPTURE = datetime(2026, 9, 7, tzinfo=UTC)


def synthetic() -> tuple[RetainedInputs, dict[str, Any], dict[str, Any]]:
    match = {
        "matchId": "1",
        "season": "2025",
        "competitionId": "8",
        "kickoff": "2025-09-14T15:00:00Z",
        "period": "FullTime",
        "resultType": "NormalResult",
        "clock": "95",
        "homeTeam": {"id": "3", "score": 1},
        "awayTeam": {"id": "99", "score": 0},
    }
    lineups, events, facts, registry = {}, {}, [], []
    for side, node, team, shift in (("home", "homeTeam", 3, 0), ("away", "awayTeam", 99, 100)):
        players = [
            {"id": str(pid + shift), "position": "Midfielder" if pid <= 11 else "Substitute"}
            for pid in range(1, 14)
        ]
        lineups[f"{side}_team"] = {
            "teamId": str(team),
            "players": players,
            "formation": {
                "teamId": str(team),
                "lineup": [[str(pid + shift) for pid in range(1, 12)]],
                "subs": [str(12 + shift), str(13 + shift)],
            },
        }
        events[node] = {"id": str(team), "subs": [], "cards": [], "goals": []}
        for pid in range(1, 14):
            registry.append(
                {"season": "2025-26", "code": pid + shift, "opta_code": f"p{pid + shift}"}
            )
            facts.append(
                {
                    "fixture": 100,
                    "code": pid + shift,
                    "team_code": team,
                    "minutes": 90 if pid <= 11 else 0,
                    "starts": int(pid <= 11),
                    "kickoff_utc": "2025-09-14T15:00:00+00:00",
                }
            )
    versions = {
        endpoint: {"known_at": CAPTURE.isoformat()}
        for endpoint in ("metadata", "lineups", "events")
    }
    manifest = {
        "selected_match_record": match,
        "source_versions": versions,
        "identity_evidence_observed_at_utc": CAPTURE.isoformat(),
    }
    files = {
        "capture-1.json": json.dumps(manifest).encode(),
        "lineups.raw": json.dumps(lineups).encode(),
        "events.raw": json.dumps(events).encode(),
    }
    inputs = RetainedInputs(
        {1: match},
        {},
        {
            (1, endpoint): {"receipt": {"raw_file": f"{endpoint}.raw"}}
            for endpoint in ("lineups", "events")
        },
        files,
        {},
        {},
    )
    reference = {
        "season": "2025-26",
        "registry": registry,
        "facts": facts,
        "identity_observed_at_utc": CAPTURE.isoformat(),
        "crosswalk": {
            "1": {
                "fixture": 100,
                "kickoff_utc": "2025-09-14T15:00:00+00:00",
                "home_team_code": 3,
                "away_team_code": 99,
                "home_score": 1,
                "away_score": 0,
            }
        },
    }
    contract = {"clubs": [{"team_code": 3}], "season": "2025-26", "expected_pl_match_ids": [1]}
    return inputs, reference, contract


def test_config_pin_is_exact() -> None:
    assert audit.load_contract(repo_root())["parent_result_remains_failed"] is True


def test_config_mutation_rejected(tmp_path: Path) -> None:
    path = tmp_path / audit.CONFIG
    path.parent.mkdir(parents=True)
    path.write_text("modified: true")
    with pytest.raises(ParticipationError, match="frozen contract"):
        audit.load_contract(tmp_path)


def test_fresh_interpretation_preserves_old_bytes_and_knowledge_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "EXPECTED_MATCHES", 1)
    inputs, reference, contract = synthetic()
    original = deepcopy(inputs.files)
    result = audit.interpret(inputs, reference, contract, interpretation_known_at=CAPTURE)
    assert result["passed"]
    assert result["parsed_matches"] == 1
    assert len(result["team_side_summaries"]) == 2
    assert result["validation"]["pl_comparison_rows"] == 13
    assert result["validation"]["duration_rows"] == 11
    assert result["matches"][0]["known_at"] == CAPTURE.isoformat()
    assert (
        result["matches"][0]["source_versions"]
        == json.loads(original["capture-1.json"])["source_versions"]
    )
    assert inputs.files == original


@pytest.mark.parametrize("selected", [False, True])
def test_unknown_opponent_roster_is_retained_not_zero_or_global_complete(
    monkeypatch: pytest.MonkeyPatch, selected: bool
) -> None:
    monkeypatch.setattr(audit, "EXPECTED_MATCHES", 1)
    inputs, reference, contract = synthetic()
    lineups = json.loads(inputs.files["lineups.raw"])
    lineups["away_team"]["players"].append({"id": "114", "position": "Goalkeeper"})
    inputs.files["lineups.raw"] = json.dumps(lineups).encode()
    if selected:
        contract["clubs"].append({"team_code": 99})
    result = audit.interpret(inputs, reference, contract, interpretation_known_at=CAPTURE)
    assert result["passed"] is not selected
    assert result["all_fixture_roster_exposure_known"] is False
    assert len(result["unknown_roster_or_duration_rows"]) == 1
    assert result["unknown_roster_or_duration_rows"][0]["nominal_minutes"] is None
    assert len(result["selected_club_unknown_rows"]) == int(selected)


def test_raw_event_failure_retained_and_denominator_not_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit, "EXPECTED_MATCHES", 1)
    inputs, reference, contract = synthetic()
    events = json.loads(inputs.files["events.raw"])
    events["homeTeam"]["id"] = "99"
    inputs.files["events.raw"] = json.dumps(events).encode()
    report = audit.interpret(inputs, reference, contract, interpretation_known_at=CAPTURE)
    assert report["selected_matches"] == 1
    assert report["parsed_matches"] == 0
    assert len(report["failures"]) == 1
    assert not report["passed"]


@pytest.mark.parametrize("changed", ["population", "crosswalk", "score"])
def test_original_fixture_population_and_identity_are_exact(
    monkeypatch: pytest.MonkeyPatch, changed: str
) -> None:
    monkeypatch.setattr(audit, "EXPECTED_MATCHES", 1)
    inputs, reference, contract = synthetic()
    if changed == "population":
        contract["expected_pl_match_ids"] = [2]
    elif changed == "crosswalk":
        reference["crosswalk"] = {}
    else:
        reference["crosswalk"]["1"]["home_score"] = 3
    with pytest.raises(ParticipationError):
        audit.interpret(inputs, reference, contract, interpretation_known_at=CAPTURE)


def fake_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    root, retained, evidence_dir, results = (
        tmp_path / name for name in ("repo", "retained", "evidence", "new-output")
    )
    for directory in (root, retained, evidence_dir):
        directory.mkdir()
    db = tmp_path / "reference.duckdb"
    db.write_bytes(b"read-only reference")
    evidence = evidence_dir / "source-resolution.json"
    evidence.write_bytes(b"{}")
    source = root / "source.py"
    source.write_text("unchanged")
    inputs, reference, old_contract = synthetic()
    inputs.files["pilot-result.json"] = json.dumps(
        {"provenance": {"database_sha256": audit.parent.file_sha256(db)}}
    ).encode()
    (retained / "result.json").write_bytes(inputs.files["pilot-result.json"])
    monkeypatch.setattr(
        audit, "OLD_RESULT_SHA256", hashlib.sha256(inputs.files["pilot-result.json"]).hexdigest()
    )
    monkeypatch.setattr(audit, "SOURCE_FILES", ("source.py",))
    monkeypatch.setattr(audit, "EXPECTED_MATCHES", 1)
    monkeypatch.setattr(audit, "load_contract", lambda root: {"frozen": True})
    monkeypatch.setattr(
        audit.retained_loader,
        "load_contract",
        lambda root: {"retained_report_sha256": audit.OLD_RESULT_SHA256},
    )
    monkeypatch.setattr(audit.retained_loader, "_head", lambda root, contract: "clean-sha")
    monkeypatch.setattr(audit.parent, "git_clean_head", lambda root: "clean-sha")
    monkeypatch.setattr(audit.parent, "load_contract", lambda root: old_contract)
    monkeypatch.setattr(audit.retained_loader, "load_retained", lambda *args: inputs)
    monkeypatch.setattr(
        audit,
        "source_evidence",
        lambda path, contract: {str(evidence): audit.parent.file_sha256(evidence)},
    )
    monkeypatch.setattr(audit.parent, "reference_data", lambda db, season: reference)

    def readonly_connection(db: Path, *, read_only: bool) -> SimpleNamespace:
        assert read_only is True
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(audit, "connect", readonly_connection)
    return {"root": root, "db": db, "retained": retained, "evidence": evidence, "results": results}


def test_guarded_success_is_write_once_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = fake_run(tmp_path, monkeypatch)
    original = kwargs["db"].read_bytes()
    report = audit.run(**kwargs)
    assert report["completed"] and report["passed"]
    assert report["provenance"]["network_requests"] == 0
    assert report["provenance"]["original_pilot_remains_passed"] is False
    assert kwargs["db"].read_bytes() == original
    assert json.loads((kwargs["results"] / "result.json").read_bytes())["passed"]
    with pytest.raises(ParticipationError, match="no overwrite"):
        audit.run(**kwargs)


def test_dirty_start_refuses_before_reading_retained_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = fake_run(tmp_path, monkeypatch)

    def dirty(*args: Any) -> str:
        raise ParticipationError("dirty worktree")

    monkeypatch.setattr(audit.retained_loader, "_head", dirty)
    with pytest.raises(ParticipationError, match="dirty"):
        audit.run(**kwargs)
    assert not kwargs["results"].exists()


def test_dirty_postflight_retains_failed_new_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = fake_run(tmp_path, monkeypatch)

    def dirty(*args: Any) -> str:
        raise ParticipationError("dirty after interpretation")

    monkeypatch.setattr(audit.parent, "git_clean_head", dirty)
    report = audit.run(**kwargs)
    assert report["completed"] is report["passed"] is False
    assert report["postflight_failure"]
    assert (kwargs["results"] / "result.json").exists()


def test_changed_database_is_rejected_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = fake_run(tmp_path, monkeypatch)
    kwargs["db"].write_bytes(b"different reference")
    with pytest.raises(ParticipationError, match="differs from original"):
        audit.run(**kwargs)
    assert not kwargs["results"].exists()


def test_wal_refuses_and_outputs_cannot_enter_original_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = fake_run(tmp_path, monkeypatch)
    with pytest.raises(ParticipationError, match="external"):
        audit.run(**(kwargs | {"results": kwargs["retained"] / "nested"}))
    Path(str(kwargs["db"]) + ".wal").write_bytes(b"unresolved")
    with pytest.raises(ParticipationError, match="without WAL"):
        audit.run(**kwargs)


def test_source_report_and_raw_bytes_are_hash_bound(tmp_path: Path) -> None:
    raw = tmp_path / "official.raw"
    raw.write_bytes(b"official report")
    report = {
        "new_source_captures": {
            "responses": [
                {
                    "raw_file": raw.name,
                    "sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
                    "bytes": raw.stat().st_size,
                }
            ]
        }
    }
    path = tmp_path / "source-resolution.json"
    path.write_text(json.dumps(report))
    contract = {"source_resolution_report_sha256": audit.parent.file_sha256(path)}
    assert len(audit.source_evidence(path, contract)) == 2
    raw.write_bytes(b"changed")
    with pytest.raises(ParticipationError, match="raw bytes"):
        audit.source_evidence(path, contract)
