"""Prospective witnessed competitive exposure. Unproved completeness never means rest."""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from typing import Any

from fpl.features.pit import AsOf


def workload_features(
    versions: list[dict[str, Any]], *, code: int, team_code: int, cutoff: datetime
) -> dict[str, Any]:
    AsOf(cutoff)
    result: dict[str, Any] = {
        "code": code,
        "cutoff": cutoff.isoformat(),
        "evidence": "prospective_witnessed_nominal_exposure",
        "minutes_last_72h": None,
        "minutes_last_7d": None,
        "minutes_last_14d": None,
        "days_since_last_start": None,
        "days_since_last_appearance": None,
        "player_rest_hours": None,
        "team_rest_hours": None,
        "started_midweek": None,
        "played90": None,
        "played120": None,
        "limitations": [
            "no_verified_continuous_membership_or_whistle_times",
            "captured_competitions_are_not_all_possible_player_exposure",
        ],
    }
    selected: dict[tuple[str, int, int], dict[str, Any]] = {}
    for version in versions:
        known = datetime.fromisoformat(version["known_at"])
        kickoff = datetime.fromisoformat(version["kickoff_time"])
        AsOf(known)
        AsOf(kickoff)
        if known > cutoff or kickoff >= cutoff:
            continue
        key = version["season"], version["competition"], version["provider_match_id"]
        old = selected.get(key)
        if old is None or (known, version["version_id"]) > (
            datetime.fromisoformat(old["known_at"]),
            old["version_id"],
        ):
            selected[key] = version
    witnesses = []
    unavailable = []
    for version in selected.values():
        kickoff = datetime.fromisoformat(version["kickoff_time"])
        rows = [r for r in version["rows"] if r["code"] == code]
        affected = team_code in version["provider_team_ids"] or bool(rows)
        if affected and (not version["valid"] or len(rows) != 1):
            unavailable.append(kickoff)
            continue
        if not rows:
            continue
        row = rows[0]
        minutes = row.get("nominal_minutes")
        if (
            minutes is None
            or isinstance(minutes, bool)
            or not math.isfinite(minutes)
            or not 0 <= minutes <= 120
            or row.get("appeared") is None
        ):
            unavailable.append(kickoff)
            continue
        if row["appeared"] and minutes > 0:
            witnesses.append((kickoff, row, version))
    witnesses.sort(key=lambda value: (value[0], value[2]["version_id"]))
    for label, hours in (("72h", 72), ("7d", 168), ("14d", 336)):
        start = cutoff - timedelta(hours=hours)
        measured = [(time, row, v) for time, row, v in witnesses if time >= start]
        failed = any(time >= start for time in unavailable)
        result[f"witnessed_minutes_last_{label}_lower_bound"] = (
            math.fsum(row["nominal_minutes"] for _, row, _ in measured)
            if measured and not failed
            else None
        )
        result[f"workload_{label}_unavailable"] = failed or not measured
    if witnesses:
        time, row, _ = witnesses[-1]
        result["days_since_last_observed_appearance"] = (cutoff - time).total_seconds() / 86400
        starts = [time for time, row, _ in witnesses if row["started"] is True]
        result["days_since_last_observed_start"] = (
            (cutoff - starts[-1]).total_seconds() / 86400 if starts else None
        )
        if not any(t >= time for t in unavailable):
            result["played90"] = row["nominal_minutes"] >= 90
            result["played120"] = row["nominal_minutes"] == 120
        midweek = [
            row
            for time, row, _ in witnesses
            if time >= cutoff - timedelta(days=7) and time.weekday() in {1, 2, 3}
        ]
        if any(row["started"] is True for row in midweek):
            result["started_midweek"] = True
    result["source_version_ids"] = sorted({v["version_id"] for _, _, v in witnesses})
    return result
