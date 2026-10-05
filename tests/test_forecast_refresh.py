"""Automation triggers never change the frozen forecaster or admit future evidence."""

import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import duckdb
import pytest

from fpl.ingest.live_snapshot import _manifest, capture_payload
from fpl.jobs import forecast_refresh as job

NOW = datetime(2026, 10, 5, 12, tzinfo=UTC)
SEASON = "2026-27"


@pytest.fixture
def con():
    with duckdb.connect() as connection:
        connection.execute("""CREATE TABLE snapshot_capture(capture_id VARCHAR, captured_at
            TIMESTAMPTZ, payload_count INT, manifest VARCHAR, manifest_sha256 VARCHAR,
            season VARCHAR, mode VARCHAR)""")
        connection.execute("""CREATE TABLE snapshot_payload(capture_id VARCHAR, endpoint VARCHAR,
            parameter VARCHAR, payload VARCHAR, sha256 VARCHAR)""")
        connection.execute("""CREATE TABLE raw_pl_sdp_payload(payload_id VARCHAR, sha256 VARCHAR,
            fetched_at TIMESTAMPTZ, endpoint VARCHAR)""")
        yield connection


def payloads():
    return {
        ("bootstrap-static", ""): {
            "elements": [{"id": 1, "now_cost": 50}],
            "events": [
                {"id": gw, "deadline_time": (NOW + timedelta(days=7 * (gw - 5) - 2)).isoformat()}
                for gw in range(1, 39)
            ],
        },
        ("fixtures", ""): [
            {
                "id": 1,
                "event": 5,
                "kickoff_time": NOW.isoformat(),
                "team_h": 1,
                "team_a": 2,
                "finished": False,
                "finished_provisional": True,
                "team_h_score": 2,
                "team_a_score": 1,
                "team_h_difficulty": 4,
            }
        ],
        ("element-summary", "1"): {
            "history": [{"fixture": 1, "minutes": 90, "expected_goals": "0.4", "value": 50}],
            "fixtures": [],
        },
    }


def capture(con, data=None, stamp=NOW, identity="one"):
    items = [capture_payload(k[0], v, parameter=k[1]) for k, v in (data or payloads()).items()]
    body, sha = _manifest(items)
    con.execute(
        "INSERT INTO snapshot_capture VALUES (?, ?, ?, ?, ?, ?, 'player-history')",
        [identity, stamp, len(items), body, sha, SEASON],
    )
    for item in items:
        con.execute(
            "INSERT INTO snapshot_payload VALUES (?, ?, ?, ?, ?)",
            [identity, item.endpoint, item.parameter, item.payload_json, item.sha256],
        )
    return job.source_state(con, now=NOW, season=SEASON)


def test_content_stable_across_captures_and_market_changes(con):
    first = capture(con, stamp=NOW - timedelta(hours=2))
    changed = payloads()
    changed[("bootstrap-static", "")]["elements"][0]["now_cost"] = 52
    changed[("element-summary", "1")]["history"][0]["value"] = 52
    changed[("fixtures", "")][0]["team_h_difficulty"] = 5
    second = capture(con, changed, identity="two")
    assert first["capture_id"] != second["capture_id"]
    assert first["match_sources_sha256"] == second["match_sources_sha256"]
    assert first["schedule_sha256"] == second["schedule_sha256"]
    # GW5 is underway; selecting it from latest completed-match number would be wrong.
    assert (second["gw_from"], second["gw_to"]) == (6, 10)


@pytest.mark.parametrize("change", ["correction", "new_match", "sdp_stats", "workload", "schedule"])
def test_new_football_evidence_triggers_without_waiting_for_daily_age(con, change):
    first = capture(con, stamp=NOW - timedelta(hours=2))
    changed = payloads()
    if change == "correction":
        changed[("element-summary", "1")]["history"][0]["expected_goals"] = "0.8"
    elif change == "new_match":
        row = copy.deepcopy(changed[("fixtures", "")][0])
        row["id"] = 2
        changed[("fixtures", "")].append(row)
    elif change == "schedule":
        changed[("fixtures", "")][0]["event"] = 6
    else:
        con.execute(
            "INSERT INTO raw_pl_sdp_payload VALUES ('new', 'hash', ?, ?)",
            [NOW, "match_stats" if change == "sdp_stats" else "match_lineups"],
        )
    second = capture(con, changed, identity="two")
    latest = SimpleNamespace(season=SEASON, gw_from=6, gw_to=10, as_of=NOW)
    due = job.reasons(second, latest, first, now=NOW)
    assert (
        "official_schedule_changed" if change == "schedule" else "completed_match_sources_changed"
    ) in due


@pytest.mark.parametrize("defect", ["missing_player", "tampered", "manifest", "stale"])
def test_unusable_capture_fails_closed(con, defect):
    capture(con)
    if defect == "missing_player":
        changed = payloads()
        changed[("bootstrap-static", "")]["elements"].append({"id": 2})
        con.execute("DELETE FROM snapshot_capture")
        with pytest.raises(ValueError, match="every captured player"):
            capture(con, changed, identity="two")
        return
    if defect == "tampered":
        con.execute("UPDATE snapshot_payload SET sha256='bad'")
    elif defect == "manifest":
        con.execute("UPDATE snapshot_capture SET payload_count=500")
    else:
        con.execute("UPDATE snapshot_capture SET captured_at=?", [NOW - timedelta(hours=9)])
    with pytest.raises(ValueError, match=r"checksum|manifest|within 8 hours"):
        job.source_state(con, now=NOW, season=SEASON)


def test_future_sources_never_change_trigger(con):
    first = capture(con)
    con.execute(
        "INSERT INTO raw_pl_sdp_payload VALUES ('future', 'hash', ?, 'match_stats')",
        [NOW + timedelta(minutes=1)],
    )
    capture(con, stamp=NOW + timedelta(minutes=1), identity="future")
    assert job.source_state(con, now=NOW, season=SEASON) == first


def test_unfinished_match_updates_wait_for_ended_evidence(con):
    data = payloads()
    data[("fixtures", "")][0]["finished_provisional"] = False
    first = capture(con, data, stamp=NOW - timedelta(hours=1))
    data[("element-summary", "1")]["history"][0]["minutes"] = 43
    second = capture(con, data, identity="during")
    assert first["match_sources_sha256"] == second["match_sources_sha256"]


def test_daily_boundary_noop_rollover_and_season_end(con):
    state = capture(con)
    latest = SimpleNamespace(
        season=SEASON, gw_from=6, gw_to=10, as_of=NOW - timedelta(hours=24) + timedelta(seconds=1)
    )
    assert job.reasons(state, latest, state, now=NOW) == []
    latest.as_of -= timedelta(seconds=1)
    assert job.reasons(state, latest, state, now=NOW) == ["forecast_at_least_24_hours_old"]
    latest.as_of = NOW
    latest.gw_from = 5
    assert job.reasons(state, latest, state, now=NOW) == ["next_gameweek_changed"]
    assert job.reasons(state, None, None, now=NOW) == ["no_registered_forecast"]
    assert "source_baseline_missing" in job.reasons(state, latest, None, now=NOW)
    state["gw_from"] = None
    assert job.reasons(state, latest, None, now=NOW) == []


def test_end_of_season_horizon_and_no_future_gameweek(con):
    changed = payloads()
    for event in changed[("bootstrap-static", "")]["events"]:
        event["deadline_time"] = (NOW + timedelta(days=event["id"] - 37)).isoformat()
    state = capture(con, changed, stamp=NOW - timedelta(hours=1))
    assert (state["gw_from"], state["gw_to"]) == (38, 38)
    changed[("bootstrap-static", "")]["events"][-1]["deadline_time"] = NOW.isoformat()
    assert capture(con, changed, identity="ended")["gw_from"] is None


def test_deadline_budget_defers_without_starting_inference(tmp_path, monkeypatch):
    database = tmp_path / "db.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE ledger_sdp_evidence_pair(id INT)")
    state = {"gw_from": 6, "deadline": (datetime.now(UTC) + timedelta(minutes=45)).isoformat()}
    monkeypatch.setattr(job, "source_state", lambda *a, **kw: state)
    monkeypatch.setattr(
        job.pre_deadline_forecast,
        "generate_from_capture",
        lambda **kw: pytest.fail("too close to deadline"),
    )
    report = job.refresh(
        database=database,
        destination=tmp_path,
        forecasts=tmp_path,
        capture_root=tmp_path,
        capture_status=0,
        started_at=NOW,
    )
    assert report["status"] == "DEFERRED_DEADLINE"
    assert not report["forecast_regenerated"]


@pytest.mark.parametrize("baseline", ["valid", "truncated", "wrong_hash"])
def test_registered_baseline_controls_repeat_and_recovers_partial_receipt(
    tmp_path, monkeypatch, baseline
):
    from fpl.jobs import refresh_dashboard

    now = datetime.now(UTC)
    database = tmp_path / "db.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE ledger_sdp_evidence_pair(id INT)")
        con.execute("INSERT INTO ledger_sdp_evidence_pair VALUES (1)")
    primary = tmp_path / "primary.jsonl"
    primary.write_bytes(b"registered")
    state = {
        "schema_version": 1,
        "season": SEASON,
        "gw_from": 6,
        "gw_to": 10,
        "deadline": (now + timedelta(days=2)).isoformat(),
        "match_sources_sha256": "match",
        "schedule_sha256": "schedule",
    }
    sidecar = primary.with_suffix(".refresh.json")
    sidecar.write_text(
        json.dumps(
            {**state, "artifact_sha256": job._sha256(primary) if baseline == "valid" else "wrong"}
        )
    )
    if baseline == "truncated":
        sidecar.write_text('{"schema_version":')
    original = sidecar.read_bytes()
    monkeypatch.setattr(job, "source_state", lambda *a, **kw: state)
    monkeypatch.setattr(refresh_dashboard, "latest_primary", lambda *a: (primary, SEASON, "run"))
    monkeypatch.setattr(
        job,
        "read_artifact",
        lambda *a: SimpleNamespace(
            manifest=SimpleNamespace(season=SEASON, gw_from=6, gw_to=10, as_of=now)
        ),
    )

    def start(*a, **kw):
        raise RuntimeError("new build requested")

    monkeypatch.setattr(job.pre_deadline_forecast, "_refresh_receipt", start)
    kwargs = {
        "database": database,
        "destination": tmp_path,
        "forecasts": tmp_path,
        "capture_root": tmp_path,
        "capture_status": 0,
        "started_at": now,
    }
    if baseline == "valid":
        assert job.refresh(**kwargs)["status"] == "NOT_DUE"
    elif baseline == "truncated":
        with pytest.raises(RuntimeError, match="new build requested"):
            job.refresh(**kwargs)
    else:
        with pytest.raises(ValueError, match="binding mismatch"):
            job.refresh(**kwargs)
    assert sidecar.read_bytes() == original


@pytest.mark.parametrize("status", [0, 1])
def test_rebuild_reuses_capture_and_only_marks_registered_success(tmp_path, monkeypatch, status):
    from fpl.jobs import refresh_dashboard

    database = tmp_path / "db.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute("CREATE TABLE ledger_sdp_evidence_pair(id INT)")
    state = {
        "schema_version": 1,
        "gw_from": 6,
        "gw_to": 10,
        "season": SEASON,
        "deadline": (datetime.now(UTC) + timedelta(days=3)).isoformat(),
    }
    monkeypatch.setattr(job, "source_state", lambda *a, **kw: state)
    calls = []
    output = []

    def bundle(root, code):
        calls.append("receipt")
        assert root == tmp_path / "capture"
        return tmp_path / "receipt.json", code

    def generate(**kw):
        calls.append("forecast_and_record")
        assert kw["gw_from"] == 6 and kw["gw_to"] == 10
        assert kw["status"] == 1  # SDP gap stays explicit for existing incumbent fallback.
        kw["output"].write_bytes(b"new immutable artifact")
        output.append(kw["output"])
        return status

    monkeypatch.setattr(job.pre_deadline_forecast, "_refresh_receipt", bundle)
    monkeypatch.setattr(job.pre_deadline_forecast, "generate_from_capture", generate)
    monkeypatch.setattr(
        refresh_dashboard, "latest_primary", lambda *a: (output[0], SEASON, "registered")
    )
    result = job.refresh(
        database=database,
        destination=tmp_path,
        forecasts=tmp_path / "predictions",
        capture_root=tmp_path / "capture",
        capture_status=1,
        started_at=NOW,
    )
    assert calls == ["receipt", "forecast_and_record"]
    assert result["forecast_regenerated"] is (status == 0)
    sidecar = output[0].with_suffix(".refresh.json")
    assert sidecar.exists() is (status == 0)
    if status == 0:
        assert json.loads(sidecar.read_text())["artifact_sha256"] == job._sha256(output[0])
