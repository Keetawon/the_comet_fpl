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


def check_observed_freshness(generation: Path, sidecar: dict[str, Any]) -> dict[str, Any]:
    """Refuse a package whose established routes lag its current FPL sidecar.

    Check identities, not just a new build timestamp. Provisional observations
    can witness display coverage but never become finalized scored outcomes.
    """
    season = max((r["season"] for r in sidecar["gameweeks"]), default=None)
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
        missing = expected - available
        if missing:
            raise ValueError(
                f"stale {scope} actuals: {len(missing)} current FPL fixture rows "
                f"missing from established routes; examples {sorted(missing)[:3]}"
            )
        report[scope] = {"season": season, "matched_current_rows": len(expected)}
    return report


def retain_existing_plans(fresh: Path, previous: Path, output: Path) -> dict[str, Any]:
    current = validate_dashboard_json(fresh)
    old = validate_dashboard_json(previous)
    current_runs = {row["run_id"]: row for row in current["runs"]}
    old_runs = {row["run_id"]: row for row in old["runs"]}
    shutil.copytree(fresh, output)
    retained: list[str] = []
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
        if document[key] and document[key] != original:
            raise ValueError("fresh plans differ; explicit plan-vintage selection required")
        document[key] = original
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

    def public_metadata(value: Any) -> None:
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
                    modes[f"{key}_sha256"] = digest
                    redacted.add(digest)
            for child in value.values():
                public_metadata(child)
        elif isinstance(value, list):
            for child in value:
                public_metadata(child)

    for filename in current["files"]:
        document = json.loads((output / filename).read_bytes())
        indent = None if filename == "player_horizons.json" else 2
        original_payload = _canonical_json_bytes(document, indent=indent)
        public_metadata(document)
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
