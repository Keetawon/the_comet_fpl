"""Current official reporting alongside immutable forecast-vintage availability."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

from fpl.ingest.live_snapshot import capture_payload

_FIELDS = {
    "source",
    "season",
    "code",
    "status",
    "chance_of_playing_next_round",
    "news",
    "news_added",
    "captured_at",
    "capture_id",
    "source_sha256",
    "next_gw",
    "semantics",
}


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("current availability timestamp must be an ISO string")
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("current availability timestamp must be timezone-aware")
    return stamp.astimezone(UTC)


def validate_current_availability(player: Mapping[str, Any], *, exported_at: str) -> None:
    """Legacy records may omit the additive object; present objects must be truthful."""
    value = player.get("current_availability")
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("malformed current availability fields")
    if (
        value["source"] != "FPL"
        or value["semantics"] != "current_reported_not_forecast"
        or value["season"] != player["season"]
        or type(value["code"]) is not int
        or value["code"] != player["code"]
    ):
        raise ValueError("current availability identity or semantics mismatch")
    if value["status"] is not None and (
        not isinstance(value["status"], str)
        or value["status"] not in {"a", "d", "i", "s", "u", "n", "x"}
    ):
        raise ValueError("invalid current availability status")
    chance = value["chance_of_playing_next_round"]
    if chance is not None and (type(chance) is not int or not 0 <= chance <= 100):
        raise ValueError("invalid current availability chance")
    next_gw = value["next_gw"]
    if next_gw is not None and (type(next_gw) is not int or not 1 <= next_gw <= 38):
        raise ValueError("invalid current availability next gameweek")
    if value["news"] is not None and not isinstance(value["news"], str):
        raise ValueError("invalid current availability news")
    if not isinstance(value["capture_id"], str) or not value["capture_id"].strip():
        raise ValueError("current availability capture identity missing")
    if not isinstance(value["source_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["source_sha256"]
    ):
        raise ValueError("invalid current availability source hash")
    captured_at = _timestamp(value["captured_at"])
    if captured_at > _timestamp(exported_at):
        raise ValueError("current availability capture postdates export")
    if value["news_added"] is not None and _timestamp(value["news_added"]) > captured_at:
        raise ValueError("current availability news postdates capture")


def current_availability(
    con: duckdb.DuckDBPyConnection, *, as_of: datetime
) -> dict[tuple[str, int], dict[str, Any]]:
    """Select one complete retained bootstrap per season, never fill from older players."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("availability export cutoff must be timezone-aware")
    captures = con.execute(
        """SELECT c.season, c.capture_id, CAST(c.captured_at AS VARCHAR),
                  c.payload_count, CAST(c.manifest AS VARCHAR), c.manifest_sha256
           FROM snapshot_capture c
           WHERE c.captured_at <= ? AND EXISTS (
               SELECT 1 FROM snapshot_payload p WHERE p.capture_id = c.capture_id
               AND p.endpoint = 'bootstrap-static')
           QUALIFY row_number() OVER (
               PARTITION BY c.season ORDER BY c.captured_at DESC, c.capture_id DESC
           ) = 1""",
        [as_of],
    ).fetchall()
    result: dict[tuple[str, int], dict[str, Any]] = {}
    for season, capture_id, captured_at, count, manifest_body, manifest_sha in captures:
        metadata = con.execute(
            """SELECT endpoint, parameter, sha256, byte_count, row_count
               FROM snapshot_payload WHERE capture_id = ? ORDER BY endpoint, parameter""",
            [capture_id],
        ).fetchall()
        manifest = json.loads(manifest_body)
        if (
            not isinstance(manifest, dict)
            or not isinstance(manifest.get("payloads"), list)
            or any(
                not isinstance(p, dict)
                or set(p) != {"endpoint", "parameter", "sha256", "byte_count", "row_count"}
                or not isinstance(p["endpoint"], str)
                or not isinstance(p["parameter"], str)
                for p in manifest["payloads"]
            )
        ):
            raise ValueError("current availability capture manifest is malformed")
        entries = [
            dict(
                zip(
                    ("endpoint", "parameter", "sha256", "byte_count", "row_count"), row, strict=True
                )
            )
            for row in metadata
        ]
        if (
            hashlib.sha256(manifest_body.encode("utf-8")).hexdigest() != manifest_sha
            or manifest.get("schema_version") != "1"
            or count != len(entries)
            or sorted(manifest.get("payloads", []), key=lambda p: (p["endpoint"], p["parameter"]))
            != entries
        ):
            raise ValueError("current availability capture manifest is incomplete or invalid")
        raw = con.execute(
            """SELECT parameter, CAST(payload AS VARCHAR), sha256, byte_count, row_count
               FROM snapshot_payload WHERE capture_id = ? AND endpoint = 'bootstrap-static'""",
            [capture_id],
        ).fetchall()
        if len(raw) != 1 or raw[0][0] != "":
            raise ValueError("current availability requires exactly one bootstrap payload")
        _, body, source_sha, byte_count, row_count = raw[0]
        bootstrap = json.loads(body)
        checked = capture_payload("bootstrap-static", bootstrap)
        if (checked.sha256, checked.byte_count, checked.row_count) != (
            source_sha,
            byte_count,
            row_count,
        ):
            raise ValueError("current availability bootstrap checksum or coverage mismatch")
        if not isinstance(bootstrap, dict):
            raise ValueError("current availability bootstrap must be an object")
        elements, events = bootstrap.get("elements"), bootstrap.get("events")
        if not isinstance(elements, list) or not elements or not isinstance(events, list):
            raise ValueError("current availability bootstrap lacks players or events")
        if any(not isinstance(e, dict) or "id" not in e for e in events):
            raise ValueError("current availability bootstrap has malformed events")
        next_events = [e["id"] for e in events if e.get("is_next") is True]
        if len(next_events) > 1:
            raise ValueError("current availability has ambiguous next gameweek")
        seen_elements: set[int] = set()
        seen_codes: set[int] = set()
        for player in elements:
            if not isinstance(player, dict):
                raise ValueError("current availability bootstrap has malformed players")
            code, element = player.get("code"), player.get("id")
            if (
                type(code) is not int
                or code <= 0
                or type(element) is not int
                or element <= 0
                or code in seen_codes
                or element in seen_elements
            ):
                raise ValueError("current availability has invalid or duplicate player identity")
            seen_codes.add(code)
            seen_elements.add(element)
            value = {
                "source": "FPL",
                "season": season,
                "code": code,
                "status": player.get("status"),
                "chance_of_playing_next_round": player.get("chance_of_playing_next_round"),
                "news": player.get("news"),
                "news_added": player.get("news_added"),
                "captured_at": _timestamp(captured_at).isoformat(),
                "capture_id": capture_id,
                "source_sha256": source_sha,
                "next_gw": next_events[0] if next_events else None,
                "semantics": "current_reported_not_forecast",
            }
            validate_current_availability(
                {"season": season, "code": code, "current_availability": value},
                exported_at=as_of.isoformat(),
            )
            result[(season, code)] = value
    return result


def refresh_current_availability(
    con: duckdb.DuckDBPyConnection, source: Path, output: Path, *, as_of: datetime
) -> dict[str, Any]:
    """Reseal a copied generation; all existing player fields and other files stay intact."""
    from fpl.publish.dashboard_json import _manifest_content_sha256, validate_dashboard_json
    from fpl.publish.export import _canonical_json_bytes, _sha256_bytes

    manifest = validate_dashboard_json(source)
    available = current_availability(con, as_of=as_of)
    document = json.loads((source / "players.json").read_bytes())
    matched = 0
    changed = 0
    changed_players: set[tuple[str, int]] = set()
    for player in document["players"]:
        key = (player["season"], player["code"])
        value = available.get(key)
        player["current_availability"] = value
        matched += value is not None
        if value is not None and (
            value["status"] != player.get("availability_status")
            or value["chance_of_playing_next_round"] != player.get("chance_of_playing")
        ):
            changed += 1
            changed_players.add(key)
    shutil.copytree(source, output)
    payload = _canonical_json_bytes(document, indent=2)
    (output / "players.json").write_bytes(payload)
    manifest["files"]["players.json"]["sha256"] = _sha256_bytes(payload)
    manifest["content_sha256"] = _manifest_content_sha256(manifest)
    (output / "manifest.json").write_bytes(_canonical_json_bytes(manifest, indent=2))
    validate_dashboard_json(output)
    return {
        "source": "retained_official_fpl_bootstrap",
        "matched_player_rows": matched,
        "unavailable_player_rows": len(document["players"]) - matched,
        "changed_from_forecast_player_rows": changed,
        "changed_from_forecast_players": len(changed_players),
        "sources": list(
            {
                v["season"]: {
                    k: v[k]
                    for k in ("season", "capture_id", "captured_at", "source_sha256", "next_gw")
                }
                for _, v in sorted(available.items())
            }.values()
        ),
        "forecast_fields_changed": False,
    }
