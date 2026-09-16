"""Current scouting is read-only, immutable and independently source-validated."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fpl.features.player_attacking_usage import build_player_attacking_usage
from fpl.ingest.live_snapshot import capture_payload, write_capture
from fpl.jobs.build_player_attacking_usage import main
from fpl.publish.player_attacking_usage import build_usage_export, load_usage_capture
from fpl.storage.db import initialise

STAMP = datetime(2026, 8, 24, 12, tzinfo=UTC)
CUTOFF = STAMP + timedelta(hours=1)


def _inputs() -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    bootstrap = {
        "events": [
            {"id": 1, "name": "GW1", "finished": True, "deadline_time": "2026-08-21T17:30:00Z"}
        ],
        "teams": [
            {"id": 1, "code": 101, "name": "Home", "short_name": "HOM"},
            {"id": 2, "code": 102, "name": "Away", "short_name": "AWY"},
        ],
        "elements": [
            {"id": 10, "code": 10010, "web_name": "Observed", "element_type": 2, "team": 1},
            {"id": 11, "code": 10011, "web_name": "Unobserved", "element_type": 2, "team": 2},
        ],
    }
    fixtures = [
        {
            "id": 501,
            "event": 1,
            "team_h": 1,
            "team_a": 2,
            "kickoff_time": "2026-08-22T14:00:00Z",
            "finished": True,
        }
    ]
    summary = {
        "history": [
            {
                "element": 10,
                "fixture": 501,
                "round": 1,
                "kickoff_time": "2026-08-22T14:00:00Z",
                "was_home": True,
                "opponent_team": 2,
                "minutes": 90,
                "starts": 1,
                "expected_goals": 0.20,
                "expected_assists": 0.10,
            }
        ]
    }
    return bootstrap, fixtures, summary


def _write(
    db: Path,
    *,
    stamp: datetime = STAMP,
    identity: str = "capture-one",
    bootstrap: dict[str, Any] | None = None,
    fixtures: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
    omit_summary: bool = False,
) -> None:
    base, schedule, history = _inputs()
    captured = [
        capture_payload("bootstrap-static", base if bootstrap is None else bootstrap),
        capture_payload("fixtures", schedule if fixtures is None else fixtures),
        capture_payload("element-summary", history if summary is None else summary, parameter="10"),
    ]
    if not omit_summary:
        captured.append(capture_payload("element-summary", {"history": []}, parameter="11"))
    con = initialise(db)
    try:
        write_capture(
            con,
            captured,
            season="2026-27",
            gw=1,
            mode="player-history",
            captured_at=stamp,
            capture_id=identity,
        )
    finally:
        con.close()


def _load(db: Path, cutoff: datetime = CUTOFF) -> Any:
    import duckdb

    con = duckdb.connect(str(db), read_only=True)
    try:
        return load_usage_capture(con, as_of=cutoff, season="2026-27")
    finally:
        con.close()


def test_export_deterministic_read_only_null_and_filter_isolation(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    original = db.read_bytes()
    first, second = tmp_path / "first", tmp_path / "second"
    build_usage_export(db, first, as_of=CUTOFF, minimum_minutes=0)
    build_usage_export(db, second, as_of=CUTOFF, minimum_minutes=0)
    assert db.read_bytes() == original
    for filename in ("player_attacking_usage.json", "player_attacking_usage.csv", "README.txt"):
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    document = json.loads((first / "player_attacking_usage.json").read_bytes())
    observed, cold = document["players"]
    assert observed["long_xgi90"] == observed["long_xg90"] + observed["long_xa90"]
    assert observed["recent_xgi90"] == observed["long_xgi90"]
    assert cold["recent_usage_percentile"] is None
    assert cold["recent_usage_bucket"] == "UNKNOWN"
    assert cold["exposure_bucket"] == "VERY_LOW"
    assert "REFUTED" in document["methodology"]
    assert document["coverage"]["positive_minute_rows"] == 1
    assert document["coverage"]["players_by_minimum_minutes"]["180"] == 0
    assert document["evidence_class"] == "CURRENT_PROSPECTIVE"
    assert not {"oop_probability", "predicted_xg", "expected_points_delta"}.intersection(observed)
    filtered = tmp_path / "filtered"
    build_usage_export(db, filtered, as_of=CUTOFF, position="MID")
    assert (
        json.loads((filtered / "player_attacking_usage.json").read_bytes())["players"]
        == document["players"]
    )
    assert len((filtered / "player_attacking_usage.csv").read_text().splitlines()) == 1
    manifest = json.loads((first / "manifest.json").read_bytes())
    for name, digest in manifest["files"].items():
        assert hashlib.sha256((first / name).read_bytes()).hexdigest() == digest
    with pytest.raises(ValueError, match="already exists"):
        build_usage_export(db, first, as_of=CUTOFF)
    assert db.read_bytes() == original


def test_later_revision_does_not_enter_earlier_capture(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    before = _load(db)
    _, _, revised = _inputs()
    revised["history"][0]["expected_goals"] = 2.0
    _write(db, stamp=STAMP + timedelta(days=1), identity="revision", summary=revised)
    assert _load(db) == before
    later = _load(db, STAMP + timedelta(days=2))
    assert later.capture_id == "revision"
    assert later.history[0].xg == 2.0
    assert before.history[0].xg == 0.2


@pytest.mark.parametrize("field", ["expected_goals", "expected_assists", "minutes"])
def test_missing_remains_null(tmp_path: Path, field: str) -> None:
    _, _, summary = _inputs()
    summary["history"][0][field] = None
    db = tmp_path / "source.duckdb"
    _write(db, summary=summary)
    capture = _load(db)
    state = build_player_attacking_usage(capture.history, capture.players, CUTOFF)[0]
    assert state.long_usage_percentile is None
    assert state.recent_usage_percentile is None
    assert state.long_xgi90 is None


@pytest.mark.parametrize(
    "kind", ["raw_hash", "manifest_hash", "manifest_entries", "missing_payload"]
)
def test_corrupt_source_fails_before_publish(tmp_path: Path, kind: str) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    con = initialise(db)
    try:
        if kind == "raw_hash":
            con.execute("UPDATE snapshot_payload SET sha256 = 'bad' WHERE endpoint = 'fixtures'")
        elif kind == "manifest_hash":
            con.execute("UPDATE snapshot_capture SET manifest_sha256 = 'bad'")
        elif kind == "manifest_entries":
            con.execute("UPDATE snapshot_capture SET payload_count = 99")
        else:
            con.execute("DELETE FROM snapshot_payload WHERE parameter = '11'")
    finally:
        con.close()
    destination = tmp_path / "export"
    with pytest.raises(ValueError, match=r"checksum|count|reconcile"):
        build_usage_export(db, destination, as_of=CUTOFF)
    assert not destination.exists()


def test_missing_summary_is_not_zero_evidence(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db, omit_summary=True)
    with pytest.raises(ValueError, match="element-summary population"):
        _load(db)


def test_absent_history_key_is_not_empty_history(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db, summary={})
    with pytest.raises(ValueError, match="absent player history"):
        _load(db)


def test_fixture_time_club_survives_transfer(tmp_path: Path) -> None:
    base, _, _ = _inputs()
    base["elements"][0]["team"] = 2
    db = tmp_path / "source.duckdb"
    _write(db, bootstrap=base)
    capture = _load(db)
    assert capture.players[0].team_code == 102
    assert capture.fixture_provenance[0]["team_code"] == 101
    assert capture.fixture_provenance[0]["opponent_team_code"] == 102


def test_position_contradiction_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    base, _, _ = _inputs()
    base["elements"][0]["element_type"] = 3
    _write(db, stamp=STAMP + timedelta(hours=2), identity="changed-position", bootstrap=base)
    assert _load(db).players[0].fpl_position == "DEF"
    with pytest.raises(ValueError, match="position history"):
        _load(db, STAMP + timedelta(days=1))


def test_unfinished_match_excluded_even_after_kickoff(tmp_path: Path) -> None:
    _, fixtures, _ = _inputs()
    fixtures[0]["finished"] = False
    db = tmp_path / "source.duckdb"
    _write(db, fixtures=fixtures)
    assert _load(db).history == ()


def test_duplicate_player_fixture_rejected(tmp_path: Path) -> None:
    _, _, summary = _inputs()
    summary["history"].append(dict(summary["history"][0]))
    db = tmp_path / "source.duckdb"
    _write(db, summary=summary)
    with pytest.raises(ValueError, match="duplicate or contradictory"):
        _load(db)


def test_no_eligible_capture_fails(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    with pytest.raises(ValueError, match="no cutoff-eligible"):
        _load(db, STAMP - timedelta(seconds=1))


def test_cli_current_export_and_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    args = [
        "--db",
        str(db),
        "--output-dir",
        str(tmp_path / "export"),
        "--as-of",
        CUTOFF.isoformat(),
    ]
    assert main(args) == 0
    assert "REFUTED" in capsys.readouterr().out
    assert main(args) == 1
    assert "already exists" in capsys.readouterr().err


def test_historical_season_never_enters_live_export(tmp_path: Path) -> None:
    con = initialise(tmp_path / "source.duckdb")
    try:
        with pytest.raises(ValueError, match="current season only"):
            load_usage_capture(con, as_of=CUTOFF, season="2023-24")
    finally:
        con.close()


def test_reverse_identity_contradiction_fails_closed(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    base, _, _ = _inputs()
    base["elements"][0]["code"] = 99999
    _write(db, stamp=STAMP + timedelta(hours=2), identity="reused-id", bootstrap=base)
    assert _load(db).players[0].player_code == 10010
    with pytest.raises(ValueError, match="element to stable code"):
        _load(db, STAMP + timedelta(days=1))


def test_previous_season_raw_payload_is_not_current_evidence(tmp_path: Path) -> None:
    _, fixtures, summary = _inputs()
    fixtures[0]["kickoff_time"] = "2025-08-22T14:00:00Z"
    summary["history"][0]["kickoff_time"] = "2025-08-22T14:00:00Z"
    db = tmp_path / "source.duckdb"
    _write(db, fixtures=fixtures, summary=summary)
    with pytest.raises(ValueError, match="incompatible season timelines"):
        _load(db)


@pytest.mark.parametrize("field", ["minutes", "starts", "expected_goals", "expected_assists"])
def test_raw_boolean_is_not_a_statistic(tmp_path: Path, field: str) -> None:
    _, _, summary = _inputs()
    summary["history"][0][field] = True
    db = tmp_path / "source.duckdb"
    _write(db, summary=summary)
    with pytest.raises(ValueError, match="numeric type"):
        _load(db)


def test_all_old_season_payloads_cannot_be_relabeled_current(tmp_path: Path) -> None:
    base, fixtures, summary = _inputs()
    base["events"][0]["deadline_time"] = "2025-08-21T17:30:00Z"
    fixtures[0]["kickoff_time"] = "2025-08-22T14:00:00Z"
    summary["history"][0]["kickoff_time"] = "2025-08-22T14:00:00Z"
    db = tmp_path / "source.duckdb"
    _write(db, bootstrap=base, fixtures=fixtures, summary=summary)
    with pytest.raises(ValueError, match="configured current season"):
        _load(db)


def test_mid_publication_failure_leaves_no_partial_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = tmp_path / "source.duckdb"
    _write(db)
    destination = tmp_path / "new-export"
    previous = tmp_path / "previous-export"
    build_usage_export(db, previous, as_of=CUTOFF)
    previous_bytes = {p.name: p.read_bytes() for p in previous.iterdir()}
    real_write = Path.write_bytes

    def fail_csv(path: Path, data: bytes) -> int:
        if path.name == "player_attacking_usage.csv":
            raise OSError("simulated publication failure")
        return real_write(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_csv)
    with pytest.raises(OSError, match="simulated publication failure"):
        build_usage_export(db, destination, as_of=CUTOFF)
    assert not destination.exists()
    assert not list(tmp_path.glob(".attacking-usage-*"))
    assert {p.name: p.read_bytes() for p in previous.iterdir()} == previous_bytes


@pytest.mark.parametrize(
    ("name", "sha256"),
    [
        (
            "attacking_role_premium_v1_development_2026-09-08.json",
            "de2bd6839de4ca246554010cad337445fc30faa9d89d408147d3dce41cec9e08",
        ),
        (
            "attacking_role_premium_v1_cases_2026-09-08.json",
            "3ddf2f7c7b61862195b2b61ba89bfd8d6f2e54aece44c22dc951a21c18f3c3e4",
        ),
    ],
)
def test_refuted_formal_result_and_cases_remain_frozen(name: str, sha256: str) -> None:
    result = Path(__file__).resolve().parents[1] / "results" / name
    assert hashlib.sha256(result.read_bytes()).hexdigest() == sha256
