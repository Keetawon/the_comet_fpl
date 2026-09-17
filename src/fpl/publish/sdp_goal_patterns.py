"""Bounded, source-bound descriptive goal classification. Never used by inference."""

from __future__ import annotations

import json
import math
import re
from datetime import datetime
from typing import Any, cast

from fpl.config import config_dir
from fpl.ingest.pl_sdp import SdpSchemaError, parse_team_stats

AUDIT_FILE = "sdp_goal_pattern_display_audit.json"
METHOD = "audited_goal_accounting_v1"
SOURCE_METHOD = "source_goal_accounting_v1"
DESCRIPTION = (
    "SDP goal accounting, with match-report corroboration where separately audited. "
    "Automatic accounting confirms explicit penalty and direct free-kick goals only; "
    "other origins require evidence. Opponent own goals are separate. "
    "An incomplete classification stays unavailable, never zero. Display-only; "
    "not a provider-supplied set-piece total. See each match's goal-pattern evidence."
)


def apply_source_goal_pattern(
    row: dict[str, Any], source: dict[str, Any], *, interpreted_at: datetime
) -> None:
    """Account only explicit counts from the identity-validated export source.

    The caller supplies the exact raw payload used to construct this match side,
    never an independently selected latest payload. No residual is called open play
    or set piece. A future capture is reinterpreted afresh; manual audits stay pinned.
    """
    if row["goal_patterns"] is not None:
        return
    if (
        source["endpoint"] != "match_stats"
        or source["season"] != row["season"]
        or source["sdp_match_id"] != row["provider_match_id"]
        or source["fetched_at"] > interpreted_at
    ):
        return
    try:
        sides = parse_team_stats(json.loads(source["body"]), match_id=row["provider_match_id"])
    except (SdpSchemaError, ValueError, TypeError):
        return
    own = next(s.stats for s in sides if s.side == ("home" if row["was_home"] else "away"))
    other = next(s.stats for s in sides if s.side != ("home" if row["was_home"] else "away"))
    values = [
        own.get("goals"),
        own.get("goalsOpenplay"),
        own.get("attPenGoal"),
        own.get("attFreekickGoal"),
        other.get("ownGoals"),
        other.get("goals"),
    ]
    # Missing, fractional or contradictory counts are not observed zeroes.
    if any(
        not isinstance(v, (int, float))
        or isinstance(v, bool)
        or not math.isfinite(v)
        or v < 0
        or int(v) != v
        for v in values
    ):
        return
    total, open_play, penalties, free_kicks, own_received, conceded = map(
        int, cast(list[float], values)
    )
    if (
        total != row["fpl"]["goals_scored"]
        or conceded != row["fpl"]["goals_conceded"]
        or open_play != row["sdp"]["open_play_goals"]
    ):
        return
    confirmed = penalties + free_kicks
    unknown = total - open_play - confirmed - own_received
    if unknown < 0:
        return
    row["goal_patterns"] = {
        "method": SOURCE_METHOD,
        "source_version": row["source_version"],
        "source_known_at": source["fetched_at"].isoformat(),
        "interpreted_at": interpreted_at.isoformat(),
        "raw_payload_sha256": source["sha256"],
        "open_play_goals": open_play,
        "confirmed_set_piece_goals": confirmed,
        "set_piece_goals": None if unknown else confirmed,
        "own_goals_received": own_received,
        "unclassified_goals": unknown,
        "total_goals": total,
        "evidence_urls": [],
    }
    validate_goal_patterns(row)


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
    if not isinstance(p, dict):
        raise ValueError("invalid goal-pattern display evidence")
    interpreted_field = "interpreted_at" if p.get("method") == SOURCE_METHOD else "audited_at"
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
            interpreted_field,
            "method",
        }
        or any(type(p[k]) is not int or p[k] < 0 for k in counts)
        or p["method"] not in (METHOD, SOURCE_METHOD)
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
    for field in ("source_known_at", interpreted_field):
        stamp = datetime.fromisoformat(p[field])
        if stamp.tzinfo is None:
            raise ValueError("goal-pattern timestamp requires timezone")
    source = datetime.fromisoformat(p["source_known_at"])
    if not datetime.fromisoformat(row["kickoff_time"]) < source <= datetime.fromisoformat(
        row["known_at"]
    ) or source > datetime.fromisoformat(p[interpreted_field]):
        raise ValueError("goal-pattern source availability mismatch")
