"""Bounded, source-bound descriptive goal classification. Never used by inference."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from fpl.config import config_dir

AUDIT_FILE = "sdp_goal_pattern_display_audit.json"
METHOD = "audited_goal_accounting_v1"
DESCRIPTION = (
    "Audited SDP goal accounting with match-report corroboration. Includes penalties, "
    "corners, free-kick and throw-in phases; opponent own goals are separate. "
    "An incomplete classification stays unavailable, never zero. Display-only; "
    "not a provider-supplied set-piece total. See each match's goal-pattern evidence."
)


def public_evidence_urls() -> set[str]:
    audit = json.loads((config_dir() / AUDIT_FILE).read_text(encoding="utf-8"))
    return {url for row in audit["rows"] for url in row["evidence_urls"]}


def apply_goal_patterns(rows: list[dict[str, Any]], raw: list[dict[str, Any]]) -> None:
    """Only the exact audited payload and fixture/side can receive an interpretation."""
    audit = json.loads((config_dir() / AUDIT_FILE).read_text(encoding="utf-8"))
    evidence = {(r["season"], r["fixture"], r["team_code"]): r for r in audit["rows"]}
    if len(evidence) != len(audit["rows"]):
        raise ValueError("duplicate goal-pattern evidence")
    latest: dict[tuple[str, int], dict[str, Any]] = {}
    for captured in raw:
        if captured["endpoint"] != "match_stats":
            continue
        key = (captured["season"], captured["sdp_match_id"])
        if key not in latest or captured["fetched_at"] > latest[key]["fetched_at"]:
            latest[key] = captured
    for row in rows:
        row["goal_patterns"] = None
        e = evidence.get((row["season"], row["fixture"], row["team_code"]))
        source = latest.get((row["season"], row["provider_match_id"]))
        if e is None or source is None:
            continue
        if (
            e["raw_payload_sha256"] != source["sha256"]
            or any(
                e[k] != row[k]
                for k in ("provider_match_id", "kickoff_time", "opponent_team_code", "was_home")
            )
            or e["open_play_goals"] != row["sdp"]["open_play_goals"]
            or e["total_goals"] != row["fpl"]["goals_scored"]
        ):
            continue
        row["goal_patterns"] = {
            **{
                k: e[k]
                for k in (
                    "open_play_goals",
                    "set_piece_goals",
                    "confirmed_set_piece_goals",
                    "own_goals_received",
                    "unclassified_goals",
                    "total_goals",
                    "raw_payload_sha256",
                    "evidence_urls",
                )
            },
            "source_version": row["source_version"],
            "source_known_at": source["fetched_at"].isoformat(),
            # A newly corroborated match side does not redate unrelated interpretations.
            "audited_at": e.get("audited_at", audit["audited_at"]),
            "method": METHOD,
        }
        validate_goal_patterns(row)


def validate_goal_patterns(row: dict[str, Any]) -> None:
    p = row["goal_patterns"]
    if p is None:
        return
    counts = (
        "open_play_goals",
        "confirmed_set_piece_goals",
        "own_goals_received",
        "unclassified_goals",
        "total_goals",
    )
    if (
        not isinstance(p, dict)
        or set(p)
        != set(counts)
        | {
            "set_piece_goals",
            "raw_payload_sha256",
            "evidence_urls",
            "source_version",
            "source_known_at",
            "audited_at",
            "method",
        }
        or any(type(p[k]) is not int or p[k] < 0 for k in counts)
        or p["method"] != METHOD
        or p["source_version"] != row["source_version"]
        or not isinstance(p["source_version"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", p["source_version"])
        or not isinstance(p["raw_payload_sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", p["raw_payload_sha256"])
        or not isinstance(p["evidence_urls"], list)
        or any(not isinstance(u, str) or not u.startswith("https://") for u in p["evidence_urls"])
        or p["open_play_goals"] != row["sdp"]["open_play_goals"]
        or p["total_goals"] != row["fpl"]["goals_scored"]
        or sum(p[k] for k in counts[:-1]) != p["total_goals"]
        or (p["set_piece_goals"] is not None and type(p["set_piece_goals"]) is not int)
        or p["set_piece_goals"]
        != (None if p["unclassified_goals"] else p["confirmed_set_piece_goals"])
    ):
        raise ValueError("invalid goal-pattern display evidence")
    for field in ("source_known_at", "audited_at"):
        stamp = datetime.fromisoformat(p[field])
        if stamp.tzinfo is None:
            raise ValueError("goal-pattern timestamp requires timezone")
    source = datetime.fromisoformat(p["source_known_at"])
    if not datetime.fromisoformat(row["kickoff_time"]) < source <= datetime.fromisoformat(
        row["known_at"]
    ) or source > datetime.fromisoformat(p["audited_at"]):
        raise ValueError("goal-pattern source availability mismatch")
