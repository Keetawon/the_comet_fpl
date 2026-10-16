"""Bound the public browser view without changing the immutable forecast archive.

Planning and monitoring have separate populations: current selectable forecasts,
versus complete stored accuracy blocks for six recent scored forecast windows.
No prediction, observation, probability or score is recalculated here.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Final

from fpl.publish.dashboard_json import DashboardJsonError

MAX_ACTIVE_RUNS: Final = 4
MONITORING_WINDOWS: Final = 6
# Uncompressed JSON limits, checked before publication (gzip is not a heap limit).
PUBLIC_PAYLOAD_LIMITS: Final[dict[str, int]] = {
    "players.json": 15_000_000,
    "player_horizons.json": 2_000_000,
    "fixture_matrix.json": 2_000_000,
    "player_actuals.json": 15_000_000,
    "player_forecast_vs_actual.json": 20_000_000,
    "team_forecast_vs_actual.json": 2_000_000,
}


def validate_public_payload_sizes(directory: Path) -> None:
    """Fail before parsing/uploading an oversized generation, leaving live data intact."""
    for filename, limit in PUBLIC_PAYLOAD_LIMITS.items():
        size = (directory / filename).stat().st_size
        if size > limit:
            raise DashboardJsonError(
                f"public payload {filename} is {size} bytes; mobile limit is {limit}"
            )


def _order(run: dict[str, Any]) -> tuple[datetime, datetime, str]:
    return (
        datetime.fromisoformat(run["as_of"]),
        datetime.fromisoformat(run.get("created_at", run["as_of"])),
        str(run["run_id"]),
    )


def scope_public_documents(documents: dict[str, dict[str, Any]], manifest: dict[str, Any]) -> None:
    """Project validated, already-sanitized documents in place; callers reseal hashes.

    Retain Summary's exact default, both formal plan bindings, and the latest
    same-cutoff/horizon incumbent shadow. Accuracy keeps whole run blocks, one
    latest non-shadow and one shadow per recent scored starting-GW window, plus
    the active runs. Older runs remain in the source generation and ledger.
    """
    latest = documents["summary.json"].get("latest_run")
    if not isinstance(latest, dict):
        raise DashboardJsonError("public planning scope requires an explicit latest forecast")
    records = {r["run_id"]: r for r in manifest["runs"]}
    accuracy = documents["player_forecast_vs_actual.json"]["runs"]
    team_accuracy = documents["team_forecast_vs_actual.json"]["runs"]
    runs = {r["run_id"]: r for r in accuracy}
    team_runs = {r["run_id"]: r for r in team_accuracy}
    if (
        set(runs) != set(team_runs)
        or len(runs) != len(accuracy)
        or len(team_runs) != len(team_accuracy)
    ):
        raise DashboardJsonError("public player/team monitoring run populations disagree")
    for run_id, run in runs.items():
        for other in (team_runs[run_id], records.get(run_id, run)):
            if (
                any(run[k] != other[k] for k in ("season", "gw_from", "gw_to"))
                or _order(run)[0] != _order(other)[0]
            ):
                raise DashboardJsonError("public forecast metadata disagrees across read models")
    if latest["run_id"] in runs and any(
        latest[k] != runs[latest["run_id"]][k] for k in ("season", "as_of", "gw_from", "gw_to")
    ):
        raise DashboardJsonError("public Summary forecast identity disagrees with monitoring")
    active = {latest["run_id"]}
    for filename, key in (
        ("next_gw.json", "plans"),
        ("optimizer_audit.json", "plans"),
        ("summary.json", "optimizer_plans"),
    ):
        active.update(p["forecast_run_id"] for p in documents[filename][key])
    shadows = [
        r
        for r in accuracy
        if r.get("component_modes", {}).get("forecast_role") == "shadow_incumbent"
        and all(r[k] == latest[k] for k in ("season", "gw_from", "gw_to"))
        and _order(r)[0] == _order(latest)[0]
    ]
    if shadows:
        active.add(max(shadows, key=_order)["run_id"])
    if len(active) > MAX_ACTIVE_RUNS or not active <= records.keys() or not active <= runs.keys():
        raise DashboardJsonError("public active forecast/plan bindings are absent or unbounded")

    season_start = int(latest["season"].split("-")[0])
    seasons = {latest["season"], f"{season_start - 1}-{str(season_start)[-2:]}"}
    if any(records[r]["season"] not in seasons for r in active):
        raise DashboardJsonError("public formal plan requires an expired forecast season")
    scored = [
        r
        for r in accuracy
        if r["season"] in seasons
        and _order(r)[0] <= _order(latest)[0]
        and (r["coverage"]["scored_rows"] or team_runs[r["run_id"]]["coverage"]["scored_rows"])
    ]
    windows = sorted({(r["season"], r["gw_from"]) for r in scored})[-MONITORING_WINDOWS:]
    selected: dict[tuple[str, int, bool], dict[str, Any]] = {}
    for run in sorted(scored, key=_order):
        window = (run["season"], run["gw_from"])
        if window in windows:
            shadow = run.get("component_modes", {}).get("forecast_role") == "shadow_incumbent"
            selected[(*window, shadow)] = run
    monitoring = active | {r["run_id"] for r in selected.values()}
    for filename in ("player_forecast_vs_actual.json", "team_forecast_vs_actual.json"):
        document = documents[filename]
        document["runs"] = [r for r in document["runs"] if r["run_id"] in monitoring]
        document["has_outcomes"] = any(r["coverage"]["scored_rows"] > 0 for r in document["runs"])
    for filename, key in (
        ("players.json", "players"),
        ("player_horizons.json", "players"),
        ("fixture_matrix.json", "teams"),
    ):
        documents[filename][key] = [r for r in documents[filename][key] if r["run_id"] in active]
    for prefix, key in (("player", "players"), ("team", "teams")):
        identity = "code" if prefix == "player" else "team_code"
        roster = documents["players.json" if prefix == "player" else "fixture_matrix.json"][key]
        codes = {r[identity] for r in roster}
        for suffix in ("actuals", "provisional_actuals"):
            document = documents[f"{prefix}_{suffix}.json"]
            document[key] = [
                r for r in document[key] if r["season"] in seasons and r[identity] in codes
            ]
    manifest["runs"] = [r for r in manifest["runs"] if r["run_id"] in active]
    manifest["run_ids"] = [r["run_id"] for r in manifest["runs"]]
