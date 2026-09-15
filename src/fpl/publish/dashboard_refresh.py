"""Refresh observed read models, retaining only explicitly pinned existing plans.

The operational database already contains immutable forecasts. A legacy complete
dashboard supplies its plans, never its old actuals, schedule or player history.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from fpl.publish.dashboard_json import (
    _file_row_count,
    _manifest_content_sha256,
    validate_dashboard_json,
)
from fpl.publish.export import _canonical_json_bytes, _sha256_bytes
from fpl.publish.public_dashboard import PUBLIC_SQUAD_RULES_PATH
from fpl.publish.team_form import refresh_team_forms


def check_observed_freshness(generation: Path, sidecar: dict[str, Any]) -> dict[str, Any]:
    """Refuse a package whose established routes lag its current FPL sidecar.

    Check identities, not just a new build timestamp. Provisional observations
    can witness display coverage but never become finalized scored outcomes.
    Established player routes contain only published forecast players. Newly
    registered source-only players remain in the descriptive sidecar and are
    reported separately; refreshing observations must not require a new forecast.
    """
    season = max((r["season"] for r in sidecar["gameweeks"]), default=None)
    forecast_players = {
        (r["season"], r["code"])
        for r in json.loads((generation / "players.json").read_bytes())["players"]
    }
    report: dict[str, Any] = {}
    for scope, plural, identity in (("player", "players", "code"), ("team", "teams", "team_code")):
        available: set[tuple[str, int, int]] = set()
        for suffix in ("actuals", "provisional_actuals"):
            document = json.loads((generation / f"{scope}_{suffix}.json").read_bytes())
            available.update(
                (r["season"], a["fixture"], r[identity])
                for r in document[plural]
                for a in r["actuals"]
            )
        expected = {
            (r["season"], r["fixture"], r[identity])
            for r in sidecar[f"{scope}_matches"]
            if r["season"] == season
            and r.get(identity) is not None
            and any(v is not None for v in r.get("fpl", {}).values())
        }
        source_only = (
            {key for key in expected if (key[0], key[2]) not in forecast_players}
            if scope == "player"
            else set()
        )
        expected -= source_only
        missing = expected - available
        if missing:
            raise ValueError(
                f"stale {scope} actuals: {len(missing)} current FPL fixture rows "
                f"missing from established routes; examples {sorted(missing)[:3]}"
            )
        report[scope] = {
            "season": season,
            "matched_current_rows": len(expected),
            "source_only_rows_outside_forecast_population": sorted(source_only),
        }
    matrix = json.loads((generation / "fixture_matrix.json").read_bytes())
    final = json.loads((generation / "team_actuals.json").read_bytes())
    provisional = json.loads((generation / "team_provisional_actuals.json").read_bytes())
    refreshed = refresh_team_forms(matrix["teams"], final["teams"], provisional["teams"])
    if list(refreshed) != matrix["teams"]:
        raise ValueError("stale team form: summaries disagree with published ended fixtures")
    report["team_form"] = {"reconciled_rows": len(refreshed), "source": "published_team_actuals"}
    return report


def _public_metadata(value: Any, redacted: set[str]) -> None:
    if isinstance(value, dict):
        modes = value.get("component_modes")
        if isinstance(modes, dict):
            for key in ("football_environment.provenance", "player_history.provenance"):
                if key not in modes:
                    continue
                body = modes.pop(key)
                if not isinstance(body, str):
                    raise ValueError("unexpected serialized source provenance")
                digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
                existing = modes.get(f"{key}_sha256")
                if existing is not None and existing != digest:
                    raise ValueError("source provenance digest mismatch")
                modes[f"{key}_sha256"] = digest
                redacted.add(digest)
        for child in value.values():
            _public_metadata(child, redacted)
    elif isinstance(value, list):
        for child in value:
            _public_metadata(child, redacted)


def _public_plan_identity(plan: dict[str, Any]) -> dict[str, Any]:
    """Compare internal/public copies using the existing publication transport."""
    result: dict[str, Any] = json.loads(json.dumps(plan))
    _public_metadata(result, set())
    provenance = result.get("provenance")
    if isinstance(provenance, dict) and "squad_rules_path" in provenance:
        provenance["squad_rules_path"] = PUBLIC_SQUAD_RULES_PATH
    return result


def retain_existing_plans(fresh: Path, previous: Path, output: Path) -> dict[str, Any]:
    current = validate_dashboard_json(fresh)
    old = validate_dashboard_json(previous)
    current_runs = {row["run_id"]: row for row in current["runs"]}
    old_runs = {row["run_id"]: row for row in old["runs"]}
    shutil.copytree(fresh, output)
    retained: list[str] = []
    selected_platform: set[str] = set()
    for filename, key in (
        ("next_gw.json", "plans"),
        ("optimizer_audit.json", "plans"),
        ("summary.json", "optimizer_plans"),
    ):
        original = json.loads((previous / filename).read_bytes())[key]
        for plan in original:
            run_id = plan["forecast_run_id"]
            if run_id not in old_runs or current_runs.get(run_id) != old_runs[run_id]:
                raise ValueError("retained plan's exact forecast vintage is absent or changed")
        document = json.loads((fresh / filename).read_bytes())
        merged = {p["optimizer_run_id"]: p for p in document[key]}
        for plan in original:
            identity = plan["optimizer_run_id"]
            if identity in merged and _public_plan_identity(
                merged[identity]
            ) != _public_plan_identity(plan):
                raise ValueError("immutable optimizer plan changed across generations")
            merged[identity] = plan
        # The existing public contract carries one plan per platform role.
        # Pick from next_gw once, then use the exact same identities in all three
        # documents. Original artifacts and previous generations remain intact.
        if filename == "next_gw.json":
            selected_platform = {
                max(
                    (p for p in merged.values() if p.get("plan_kind") == kind),
                    key=lambda p: (p["as_of"], p["optimizer_run_id"]),
                )["optimizer_run_id"]
                for kind in ("platform_default", "platform_diagnostic")
                if any(p.get("plan_kind") == kind for p in merged.values())
            }
        document[key] = [
            merged[k]
            for k in sorted(merged)
            if merged[k].get("plan_kind") not in ("platform_default", "platform_diagnostic")
            or k in selected_platform
        ]
        payload = _canonical_json_bytes(document, indent=2)
        (output / filename).write_bytes(payload)
        current["files"][filename] = {
            "row_count": _file_row_count(document, filename),
            "sha256": _sha256_bytes(payload),
        }
        retained.append(filename)
    current["content_sha256"] = _manifest_content_sha256(current)
    (output / "manifest.json").write_bytes(_canonical_json_bytes(current, indent=2))
    validate_dashboard_json(output)
    # Every other file must come from this refresh, byte for byte. This prevents
    # an old complete base from silently replacing newly captured GW actuals.
    for filename in current["files"]:
        if (
            filename not in retained
            and (fresh / filename).read_bytes() != (output / filename).read_bytes()
        ):
            raise ValueError("fresh observed/forecast read model was replaced")
    # Public component labels must not carry serialized internal source bodies,
    # paths and team PMFs. Keep their digest, not their contents. This is transport
    # redaction on a new export; the ledger/source generation remains immutable.
    redacted: set[str] = set()

    for filename in current["files"]:
        document = json.loads((output / filename).read_bytes())
        indent = None if filename == "player_horizons.json" else 2
        original_payload = _canonical_json_bytes(document, indent=indent)
        _public_metadata(document, redacted)
        payload = _canonical_json_bytes(document, indent=indent)
        if payload == original_payload:
            continue
        (output / filename).write_bytes(payload)
        current["files"][filename]["sha256"] = _sha256_bytes(payload)
    current["content_sha256"] = _manifest_content_sha256(current)
    (output / "manifest.json").write_bytes(_canonical_json_bytes(current, indent=2))
    validate_dashboard_json(output)
    return {
        "plan_source_manifest_sha256": old["content_sha256"],
        "plan_source_generated_at": old["generated_at"],
        "fresh_source_manifest_sha256": validate_dashboard_json(fresh)["content_sha256"],
        "retained_plan_documents": retained,
        "observations_refreshed": True,
        "forecasts_regenerated": False,
        "internal_provenance_digests": sorted(redacted),
    }


def publication_status(generation: Path, sidecar: dict[str, Any]) -> dict[str, Any]:
    """Small public freshness receipt; no outcomes, PMFs, paths or private plan data."""
    manifest = validate_dashboard_json(generation)
    players = json.loads((generation / "player_forecast_vs_actual.json").read_bytes())
    teams = json.loads((generation / "team_forecast_vs_actual.json").read_bytes())
    plans = json.loads((generation / "next_gw.json").read_bytes())["plans"]
    runs = players["runs"]
    primary = [
        r
        for r in runs
        if (r.get("component_modes") or {}).get("football_environment.primary") == "sdp_v2"
    ]
    latest = max(primary or runs, key=lambda r: (r["as_of"], r["run_id"]), default=None)
    season = (
        latest["season"]
        if latest
        else max((r["season"] for r in sidecar["gameweeks"]), default=None)
    )
    gws = [r for r in sidecar["gameweeks"] if r["season"] == season]
    current_plans = [
        p
        for p in plans
        if p.get("plan_kind") == "platform_default"
        and latest
        and p["forecast_run_id"] == latest["run_id"]
    ]
    next_fixture_gw = min(
        (r["gw"] for r in gws if r["fixtures_total"] > r["fixtures_completed"]), default=None
    )
    score_status = {}
    for name, document in (("player", players), ("team", teams)):
        score_status[name] = max(
            (s["gw"] for r in document["runs"] if r["season"] == season for s in r["by_gw"]),
            default=None,
        )
    return {
        "schema": "fpl.dashboard-publication-status/v1",
        "data_manifest_sha256": manifest["content_sha256"],
        "exported_at": manifest["generated_at"],
        "season": season,
        "source_known_at": max((r["source_known_at"] for r in gws), default=None),
        "latest_finalized_gw": max((r["gw"] for r in gws if r["finished"]), default=None),
        "awaiting_finality": [
            {k: r[k] for k in ("gw", "fixtures_completed", "fixtures_total")}
            for r in gws
            if not r["finished"] and r["fixtures_completed"]
        ],
        "latest_forecast": {k: latest[k] for k in ("run_id", "as_of", "gw_from", "gw_to")}
        if latest
        else None,
        "current_platform_plan": bool(current_plans),
        "next_fixture_gw": next_fixture_gw,
        "forecast_rollover_required": bool(
            latest and next_fixture_gw is not None and latest["gw_from"] != next_fixture_gw
        ),
        "latest_scored_gw": score_status,
        "meaning": (
            "Capture, forecast, plan and finalized scores have independent timestamps. "
            "No forecast regenerated."
        ),
    }
