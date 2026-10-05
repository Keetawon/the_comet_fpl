"""Scheduling policy only; inference and evidence use the unchanged prospective path."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from fpl.artifacts.prospective_points import ForecastArtifactManifest, read_artifact
from fpl.config import load_sources
from fpl.ingest.live_snapshot import _payloads_for_capture, capture_payload
from fpl.jobs import pre_deadline_forecast
from fpl.jobs.build_db import _sha256
from fpl.storage.db import connect


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def source_state(con: duckdb.DuckDBPyConnection, *, now: datetime, season: str) -> dict[str, Any]:
    """Hash actual retained content, never capture time or current ownership/prices.

    This is only a rebuild trigger. The forecaster independently checks point-in-time
    eligibility, identity, source health and the official deadline when recording.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("forecast refresh time must be timezone-aware")
    row = con.execute(
        """SELECT capture_id, CAST(captured_at AS VARCHAR), payload_count,
                  CAST(manifest AS VARCHAR), manifest_sha256
           FROM snapshot_capture WHERE season = ? AND mode = 'player-history'
             AND captured_at <= ? ORDER BY captured_at DESC, capture_id DESC LIMIT 1""",
        [season, now],
    ).fetchone()
    if row is None or now - datetime.fromisoformat(row[1]) > timedelta(hours=8):
        raise ValueError("forecast refresh requires complete FPL history captured within 8 hours")
    capture_id, captured_at, count, body, manifest_sha = row
    payloads = _payloads_for_capture(con, capture_id)
    entries = []
    for (endpoint, parameter), payload in sorted(payloads.items()):
        checked = capture_payload(endpoint, payload, parameter=parameter)
        entries.append(
            {
                "endpoint": endpoint,
                "parameter": parameter,
                "sha256": checked.sha256,
                "byte_count": checked.byte_count,
                "row_count": checked.row_count,
            }
        )
    manifest = json.loads(body)
    if (
        hashlib.sha256(body.encode()).hexdigest() != manifest_sha
        or manifest.get("schema_version") != "1"
        or count != len(entries)
        or sorted(manifest["payloads"], key=lambda p: (p["endpoint"], p["parameter"])) != entries
    ):
        raise ValueError("forecast refresh capture manifest is incomplete or invalid")
    bootstrap = payloads[("bootstrap-static", "")]
    fixtures = payloads[("fixtures", "")]
    players = {str(p["id"]) for p in bootstrap["elements"]}
    histories = {
        parameter: payload["history"]
        for (endpoint, parameter), payload in payloads.items()
        if endpoint == "element-summary"
    }
    if not players or set(histories) != players:
        raise ValueError("forecast refresh requires history for every captured player")
    events = bootstrap["events"]
    deadlines = {
        event["id"]: datetime.fromisoformat(event["deadline_time"].replace("Z", "+00:00"))
        for event in events
    }
    if (
        not deadlines
        or len(deadlines) != len(events)
        or any(
            type(gw) is not int or not 1 <= gw <= 38 or deadline.tzinfo is None
            for gw, deadline in deadlines.items()
        )
    ):
        raise ValueError("invalid official gameweek deadlines")
    future = sorted(gw for gw, deadline in deadlines.items() if deadline > now)
    gw_from = future[0] if future else None
    gw_to = min(gw_from + 4, max(deadlines)) if gw_from is not None else None
    if (
        gw_from is not None
        and gw_to is not None
        and any(gw not in future for gw in range(gw_from, gw_to + 1))
    ):
        raise ValueError("official future gameweek horizon is incomplete")
    # FPL history includes all completed fixture legs, including provisional corrections.
    # Exclude market counters: changes to those are not new football observations.
    market = {"value", "selected", "transfers_balance", "transfers_in", "transfers_out"}
    ended_ids = {f["id"] for f in fixtures if f.get("finished") or f.get("finished_provisional")}
    history = {
        player: sorted(
            (
                {k: v for k, v in r.items() if k not in market}
                for r in rows
                if r["fixture"] in ended_ids
            ),
            key=lambda r: r["fixture"],
        )
        for player, rows in histories.items()
    }
    fixture_fields = ("id", "event", "kickoff_time", "team_h", "team_a")
    schedule = sorted(({k: f[k] for k in fixture_fields} for f in fixtures), key=lambda f: f["id"])
    ended_fields = (
        *fixture_fields,
        "finished",
        "finished_provisional",
        "team_h_score",
        "team_a_score",
        "stats",
    )
    ended = sorted(
        (
            {k: f.get(k) for k in ended_fields}
            for f in fixtures
            if f.get("finished") or f.get("finished_provisional")
        ),
        key=lambda f: f["id"],
    )
    # Raw SDP identities are content-addressed: an identical re-fetch adds no version.
    # Include workload lineups/events as well as EPL stats; no match-list polling noise.
    sdp = con.execute(
        """SELECT payload_id, sha256 FROM raw_pl_sdp_payload
           WHERE fetched_at <= ? AND endpoint IN ('match_stats', 'match_lineups', 'match_events')
           ORDER BY payload_id""",
        [now],
    ).fetchall()
    return {
        "schema_version": 1,
        "season": season,
        "capture_id": capture_id,
        "captured_at": captured_at,
        "gw_from": gw_from,
        "gw_to": gw_to,
        "deadline": deadlines[gw_from].isoformat() if gw_from is not None else None,
        "match_sources_sha256": _hash({"history": history, "ended": ended, "sdp": sdp}),
        "schedule_sha256": _hash(
            {"fixtures": schedule, "deadlines": {k: v.isoformat() for k, v in deadlines.items()}}
        ),
    }


def reasons(
    state: dict[str, Any],
    latest: ForecastArtifactManifest | None,
    previous: dict[str, Any] | None,
    *,
    now: datetime,
) -> list[str]:
    if state["gw_from"] is None:
        return []
    if latest is None:
        return ["no_registered_forecast"]
    if latest.as_of > now:
        raise ValueError("registered forecast cutoff is in the future")
    result = []
    if (latest.season, latest.gw_from, latest.gw_to) != (
        state["season"],
        state["gw_from"],
        state["gw_to"],
    ):
        result.append("next_gameweek_changed")
    if now - latest.as_of >= timedelta(hours=24):
        result.append("forecast_at_least_24_hours_old")
    if previous is None or previous.get("schema_version") != 1:
        result.append("source_baseline_missing")
    else:
        for key, reason in (
            ("match_sources_sha256", "completed_match_sources_changed"),
            ("schedule_sha256", "official_schedule_changed"),
        ):
            if previous.get(key) != state[key]:
                result.append(reason)
    return result


def refresh(
    *,
    database: Path,
    destination: Path,
    forecasts: Path,
    capture_root: Path,
    capture_status: int,
    started_at: datetime,
) -> dict[str, Any]:
    """Caller holds the cycle lock. Only a registered pair becomes publishable."""
    from fpl.jobs.refresh_dashboard import latest_primary

    now = datetime.now(UTC)
    with connect(database, read_only=True) as con:
        state = source_state(con, now=now, season=load_sources().current_season.season)
        registered = con.execute("SELECT count(*) FROM ledger_sdp_evidence_pair").fetchone()
    latest = None
    previous = None
    if registered and registered[0]:
        path, _, _ = latest_primary(database, forecasts)
        latest = read_artifact(path).manifest
        sidecar = path.with_suffix(".refresh.json")
        if sidecar.exists():
            try:
                previous = json.loads(sidecar.read_text(encoding="utf-8"))
            except ValueError:
                # An interrupted scheduling receipt must not stop fresh inference.
                # Keep its bytes; absence of a baseline requests a new immutable run.
                previous = None
            if previous is not None and (
                not isinstance(previous, dict) or previous.get("artifact_sha256") != _sha256(path)
            ):
                raise ValueError("forecast refresh baseline artifact binding mismatch")
    due = reasons(state, latest, previous, now=now)
    report: dict[str, Any] = {
        "status": "NOT_DUE",
        "reasons": due,
        "sources": state,
        "forecast_regenerated": False,
    }
    if not due:
        if state["gw_from"] is None:
            report["status"] = "NO_FUTURE_GAMEWEEK"
        return report
    # Avoid starting a long simulation immediately before its evidence window closes.
    # The recorder still enforces the actual deadline, regardless of this budget.
    if datetime.fromisoformat(state["deadline"]) - now < timedelta(hours=1):
        report["status"] = "DEFERRED_DEADLINE"
        return report
    refresh_report, status = pre_deadline_forecast._refresh_receipt(capture_root, capture_status)
    forecasts.mkdir(parents=True, exist_ok=True)
    output = forecasts / ("scheduled-" + now.strftime("%Y%m%dT%H%M%S.%fZ") + ".jsonl")
    report["artifact"] = str(output)
    status = pre_deadline_forecast.generate_from_capture(
        database=database,
        receipt_root=destination,
        refresh_report=refresh_report,
        status=status,
        started_at=started_at,
        gw_from=state["gw_from"],
        gw_to=state["gw_to"],
        output=output,
    )
    if status:
        report["status"] = "FAILED"
        report["exit_code"] = status
        return report
    selected, _, run_id = latest_primary(database, forecasts)
    if _sha256(selected) != _sha256(output):
        raise ValueError("new forecast did not become the registered primary")
    with output.with_suffix(".refresh.json").open("x", encoding="utf-8") as handle:
        json.dump({**state, "artifact_sha256": _sha256(output)}, handle, sort_keys=True)
    report.update(status="COMPLETE", forecast_regenerated=True, forecast_run_id=run_id)
    return report
