"""Source revision and unknown-goal boundaries for the descriptive export."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from fpl.publish.sdp_goal_patterns import apply_goal_patterns, validate_goal_patterns


def example() -> dict[str, Any]:
    return {
        "source_version": "a" * 64,
        "kickoff_time": "2026-08-30T13:00:00+00:00",
        "known_at": "2026-09-14T03:00:00+00:00",
        "sdp": {"open_play_goals": 0, "set_piece_goals": None},
        "fpl": {"goals_scored": 3},
        "goal_patterns": {
            "method": "audited_goal_accounting_v1",
            "source_version": "a" * 64,
            "source_known_at": "2026-09-08T03:00:00+00:00",
            "audited_at": "2026-09-14T16:00:00+00:00",
            "raw_payload_sha256": "b" * 64,
            "open_play_goals": 0,
            "confirmed_set_piece_goals": 1,
            "set_piece_goals": None,
            "own_goals_received": 1,
            "unclassified_goals": 1,
            "total_goals": 3,
            "evidence_urls": [],
        },
    }


def test_partial_goal_origins_keep_null_total_and_separate_own_goals() -> None:
    row = example()
    before = deepcopy(row)
    validate_goal_patterns(row)
    assert row == before
    for field, value in (
        ("set_piece_goals", 2),
        ("unclassified_goals", 0),
        ("own_goals_received", 0),
        ("total_goals", 4),
        ("confirmed_set_piece_goals", True),
        ("source_version", None),
        ("audited_at", "2026-08-20T00:00:00+00:00"),
    ):
        invalid = deepcopy(row)
        invalid["goal_patterns"][field] = value
        with pytest.raises(ValueError, match="goal-pattern"):
            validate_goal_patterns(invalid)


def test_exact_audited_zero_is_valid_but_missing_is_not_zero() -> None:
    row = example()
    for key in (
        "open_play_goals",
        "confirmed_set_piece_goals",
        "set_piece_goals",
        "own_goals_received",
        "unclassified_goals",
        "total_goals",
    ):
        row["goal_patterns"][key] = 0
    row["fpl"]["goals_scored"] = 0
    validate_goal_patterns(row)
    row["sdp"]["open_play_goals"] = None
    with pytest.raises(ValueError, match="goal-pattern"):
        validate_goal_patterns(row)


def test_revision_and_identity_changes_do_not_inherit_audited_classification() -> None:
    import json

    from fpl.config import config_dir
    from fpl.publish.sdp_goal_patterns import AUDIT_FILE

    audit = json.loads((config_dir() / AUDIT_FILE).read_text(encoding="utf-8"))
    e = audit["rows"][0]
    row = {
        **e,
        "source_version": "a" * 64,
        "known_at": audit["source_cutoff"],
        "sdp": {"open_play_goals": e["open_play_goals"]},
        "fpl": {"goals_scored": e["total_goals"]},
    }
    source = {
        "endpoint": "match_stats",
        "season": e["season"],
        "sdp_match_id": e["provider_match_id"],
        "sha256": e["raw_payload_sha256"],
        "fetched_at": datetime(2026, 9, 8, tzinfo=UTC),
    }
    original = deepcopy(source)
    apply_goal_patterns([row], [source])
    receipt = deepcopy(row["goal_patterns"])
    assert receipt is not None
    apply_goal_patterns([row], [source])
    assert row["goal_patterns"] == receipt and source == original
    source["sha256"] = "c" * 64
    apply_goal_patterns([row], [source])
    assert row["goal_patterns"] is None
    source["sha256"] = original["sha256"]
    row["team_code"] = 99999
    apply_goal_patterns([row], [source])
    assert row["goal_patterns"] is None
