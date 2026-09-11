"""One new dismissal alias; original V2 semantics and source bytes stay frozen."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import duckdb
import pytest
import yaml

from fpl.config import repo_root
from fpl.jobs import restage_competitive_participation_v3 as job
from fpl.storage.competitive_workload import (
    append_match,
    append_receipt,
    append_report,
    apply_workload_schema,
    semantic_identity,
)
from fpl.storage.db import connect
from fpl.transform.competitive_participation import ParticipationError
from fpl.transform.competitive_participation_v2 import parse_participation_v2
from fpl.transform.competitive_participation_v3 import INTERPRETATION_ID, parse_participation_v3
from tests.test_competitive_participation_v2 import CAPTURE, INTERPRETED, event, sample
from tests.test_competitive_workload_staging import interpreted, synthetic


def test_straight_red_is_dismissal_but_raw_type_and_input_objects_unchanged() -> None:
    data = sample()
    card = event(60, type="StraightRed", playerId="1")
    data[2]["homeTeam"]["cards"] = [card]
    original = deepcopy(data)
    with pytest.raises(ParticipationError, match="unknown card type"):
        parse_participation_v2(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    result = parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    assert data == original
    row = next(r for r in result["sides"][0]["rows"] if r["provider_player_id"] == 1)
    assert row["nominal_minutes"] == 60 and row["started"] and row["appeared"]
    assert result["raw_events"] == data[2]
    assert result["sides"][0]["discipline"][0]["raw"] == card
    assert result["source_enum_alias_log"][0]["raw_event"] == card
    assert result["interpretation_id"] == INTERPRETATION_ID
    assert result["known_at"] == CAPTURE.isoformat()


@pytest.mark.parametrize("kind", ["Yellow", "SecondYellow", "Red"])
def test_existing_card_semantics_are_bit_exact_without_alias(kind: str) -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(60, type=kind, playerId="1")]
    old = parse_participation_v2(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    new = parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    assert new["sides"] == old["sides"]
    assert new["raw_events"] == old["raw_events"]
    assert new["source_enum_alias_log"] == []


@pytest.mark.parametrize("actor", [None, "99999"])
def test_unknown_dismissal_actor_stays_unknown_not_dropped_or_invented(actor: str | None) -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(60, type="StraightRed", playerId=actor)]
    result = parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    assert result["sides"][0]["errors"] == ["unknown dismissal actor; side duration unavailable"]
    assert all(r["nominal_minutes"] is None for r in result["sides"][0]["rows"])
    assert result["sides"][0]["discipline"][0]["context"] == "unattributed"


def test_bench_straight_red_does_not_fake_an_appearance() -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(60, type="StraightRed", playerId="12")]
    result = parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    row = next(r for r in result["sides"][0]["rows"] if r["provider_player_id"] == 12)
    assert row["appeared"] is False and row["nominal_minutes"] == 0
    assert result["sides"][0]["discipline"][0]["context"] == "bench"


def test_already_substituted_player_red_does_not_change_prior_minutes() -> None:
    data = sample()
    data[2]["homeTeam"]["subs"] = [event(60, playerOnId="12", playerOffId="1")]
    data[2]["homeTeam"]["cards"] = [event(70, type="StraightRed", playerId="1")]
    result = parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    row = next(r for r in result["sides"][0]["rows"] if r["provider_player_id"] == 1)
    assert row["nominal_minutes"] == 60
    assert result["sides"][0]["discipline"][0]["context"] == "already_off"


@pytest.mark.parametrize("kind", ["straightRed", "Straight Red", "Unknown"])
def test_no_case_fuzzy_or_broad_card_aliases(kind: str) -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(60, type=kind, playerId="1")]
    with pytest.raises(ParticipationError, match="unknown card type"):
        parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)


def test_duplicate_events_still_fail_closed() -> None:
    data = sample()
    card = event(60, type="StraightRed", playerId="1")
    data[2]["homeTeam"]["cards"] = [card, deepcopy(card)]
    with pytest.raises(ParticipationError, match="duplicate event"):
        parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)


def test_null_substitute_identity_still_rejected_after_alias() -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(60, type="StraightRed", playerId="1")]
    data[2]["homeTeam"]["subs"] = [event(70, playerOnId=None, playerOffId="2")]
    with pytest.raises(ParticipationError, match="playerOnId"):
        parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)


def test_existing_nominal_stoppage_clipping_not_changed_to_fpl_minutes() -> None:
    data = sample()
    data[2]["homeTeam"]["cards"] = [event(50, period="FirstHalf", type="StraightRed", playerId="1")]
    result = parse_participation_v3(*data, known_at=CAPTURE, interpretation_known_at=INTERPRETED)
    row = next(r for r in result["sides"][0]["rows"] if r["provider_player_id"] == 1)
    assert row["nominal_minutes"] == 45


def test_new_version_appends_beside_unchanged_v2_and_repeats_idempotently() -> None:
    _, payloads, reference = synthetic()
    payloads["events"]["homeTeam"]["cards"] = [event(60, type="StraightRed", playerId="1")]
    old = interpreted(payloads=payloads)
    original = deepcopy(old)
    new = job.reinterpret(
        old,
        payloads,
        reference,
        {3: 303, 31: 3131},
        interpreted_at=INTERPRETED + timedelta(hours=1),
        parser_sha256="v3",
    )
    assert old == original and new["version_id"] != old["version_id"]
    later = job.reinterpret(
        old,
        payloads,
        reference,
        {3: 303, 31: 3131},
        interpreted_at=INTERPRETED + timedelta(hours=2),
        parser_sha256="v3",
    )
    assert later["semantic_sha256"] == new["semantic_sha256"]
    with duckdb.connect(":memory:") as con:
        apply_workload_schema(con)
        append_match(con, old)
        append_match(con, new)
        assert not append_match(con, later)
        assert job.source_rows(con, old["interpretation_id"]) == [original]
        assert len(job.source_rows(con, INTERPRETATION_ID)) == 1


def test_card_source_audit_precedes_normalization_and_pins_30_of_30() -> None:
    root = repo_root()
    config = yaml.safe_load((root / job.CONFIG).read_bytes())
    path = root / config["source_audit"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == config["source_audit_sha256"]
    audit = json.loads(path.read_bytes())
    assert (
        audit["pl_exact_identified_events"]
        == audit["pl_exact_identified_events_with_fpl_red_card"]
        == 30
    )
    assert len(audit["pl_unattributed_events"]) == 2
    assert audit["normalization_or_parser_v3_run"] is False
    assert audit["model_fitting"] is False and audit["network_requests"] is False
    old = root / "src/fpl/transform/competitive_participation_v2.py"
    assert hashlib.sha256(old.read_bytes()).hexdigest() == config["original_v2_parser_sha256"]


def test_new_restage_refuses_existing_report_directory(tmp_path: Path) -> None:
    report = tmp_path / "old"
    report.mkdir()
    (report / "evidence").write_text("preserve")
    with pytest.raises(ValueError, match="new nonsymlink"):
        job.run(
            root=repo_root(),
            source_db=tmp_path / "source",
            database=tmp_path / "copy",
            results=report,
        )
    assert (report / "evidence").read_text() == "preserve"


def test_full_synthetic_restage_preserves_source_and_old_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = tmp_path / "V2.duckdb"
    destination = tmp_path / "V3.duckdb"
    output = tmp_path / "report"
    _, payloads, reference = synthetic()
    payloads["events"]["homeTeam"]["cards"] = [event(60, type="StraightRed", playerId="1")]
    old = interpreted(payloads=payloads)
    with connect(source) as con:
        apply_workload_schema(con)
        rids = []
        for endpoint, payload in payloads.items():
            body = json.dumps(payload).encode()
            sha = hashlib.sha256(body).hexdigest()
            path = f"https://sdp-prem-prod.premier-league-prod.pulselive.com/api/v1/matches/1/{endpoint}"
            receipt = {
                "url": path,
                "sha256": sha,
                "bytes": len(body),
                "status": 200,
                "captured_at_utc": old["capture_known_at"],
            }
            rids.append(append_receipt(con, receipt=receipt, body=body, source_path="retained.raw"))
            old["source_versions"][endpoint]["sha256"] = sha
        old["receipt_ids"] = rids
        old["semantic_sha256"] = semantic_identity(old)
        append_match(con, old)
        append_report(
            con, "dev_competitive_ingestion", "V2", {"provider_to_team_code": {3: 303, 31: 3131}}
        )
    original_hash = job.file_sha256(source)
    (root / "config").mkdir()
    (root / "results").mkdir()
    audit = root / "results/audit.json"
    audit.write_text('{"synthetic":true}')
    v2 = "src/fpl/transform/competitive_participation_v2.py"
    v3 = "src/fpl/transform/competitive_participation_v3.py"
    (root / v2).parent.mkdir(parents=True)
    (root / v2).write_text("frozen V2")
    (root / v3).write_text("new V3")
    config = {
        "branch": "synthetic",
        "season": "2025-26",
        "source_database_sha256": original_hash,
        "source_interpretation_id": old["interpretation_id"],
        "expected_source_versions": 1,
        "source_audit": "results/audit.json",
        "source_audit_sha256": job.file_sha256(audit),
        "original_v2_parser_sha256": job.file_sha256(root / v2),
    }
    (root / job.CONFIG).write_text(json.dumps(config))
    monkeypatch.setattr(job, "SOURCE_FILES", (job.CONFIG, v2, v3, "results/audit.json"))
    monkeypatch.setattr(job.capture, "_head", lambda *_: "synthetic-clean-sha")
    monkeypatch.setattr(job, "reference_data", lambda *_: reference)
    result = job.run(root=root, source_db=source, database=destination, results=output)
    assert result["completed"] and result["original_v2_versions_preserved"]
    assert result["previous_valid_matches"] == 0 and result["new_valid_matches"] == 1
    assert result["newly_valid_match_ids"] == [1] and result["regressed_match_ids"] == []
    assert result["counts"]["dev_competitive_raw_receipt"] == 2
    assert job.file_sha256(source) == original_hash
    with connect(destination, read_only=True) as con:
        assert job.source_rows(con, old["interpretation_id"]) == [old]
        new = job.source_rows(con, INTERPRETATION_ID)
        assert new[0]["rows"][0]["nominal_minutes"] == 60
        assert new[0]["source_enum_alias_log"][0]["raw_event"]["type"] == "StraightRed"
