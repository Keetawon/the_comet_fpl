"""Source revision and unknown-goal boundaries for the descriptive export."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from fpl.publish.sdp_goal_patterns import (
    apply_goal_patterns,
    apply_source_goal_pattern,
    validate_goal_patterns,
)


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


def test_brighton_throw_in_corroboration_is_bound_to_its_own_review_time() -> None:
    import json

    from fpl.config import config_dir
    from fpl.publish.sdp_goal_patterns import AUDIT_FILE

    audit = json.loads((config_dir() / AUDIT_FILE).read_text(encoding="utf-8"))
    evidence = next(r for r in audit["rows"] if r["fixture"] == 16 and r["team_code"] == 36)
    row = {
        **evidence,
        "source_version": "a" * 64,
        "known_at": audit["source_cutoff"],
        "sdp": {"open_play_goals": 0, "set_piece_goals": None},
        "fpl": {"goals_scored": 3},
    }
    source = {
        "endpoint": "match_stats",
        "season": evidence["season"],
        "sdp_match_id": evidence["provider_match_id"],
        "sha256": evidence["raw_payload_sha256"],
        "fetched_at": datetime(2026, 9, 5, tzinfo=UTC),
    }
    before = deepcopy(source)
    apply_goal_patterns([row], [source])
    receipt = row["goal_patterns"]
    assert receipt["set_piece_goals"] == receipt["confirmed_set_piece_goals"] == 2
    assert receipt["unclassified_goals"] == receipt["open_play_goals"] == 0
    assert receipt["own_goals_received"] == 1
    assert receipt["audited_at"] == evidence["audited_at"] != audit["audited_at"]
    assert any("sahadan.com" in url for url in receipt["evidence_urls"])
    assert receipt["source_known_at"] == source["fetched_at"].isoformat()
    assert row["sdp"]["set_piece_goals"] is None and source == before
    source["sha256"] = "c" * 64
    apply_goal_patterns([row], [source])
    assert row["goal_patterns"] is None


def source_example() -> tuple[dict[str, Any], dict[str, Any]]:
    import json

    row = {
        **example(),
        "season": "2026-27",
        "provider_match_id": 2645230,
        "was_home": True,
        "goal_patterns": None,
        "sdp": {"open_play_goals": 2, "set_piece_goals": None},
        "fpl": {"goals_scored": 4, "goals_conceded": 1},
    }
    source = {
        "endpoint": "match_stats",
        "season": "2026-27",
        "sdp_match_id": 2645230,
        "sha256": "c" * 64,
        "fetched_at": datetime(2026, 9, 10, tzinfo=UTC),
        "body": json.dumps(
            [
                {
                    "side": "Home",
                    "stats": {
                        "goals": 4,
                        "goalsOpenplay": 2,
                        "attPenGoal": 0,
                        "attFreekickGoal": 0,
                        "ownGoals": 0,
                    },
                },
                {
                    "side": "Away",
                    "stats": {
                        "goals": 1,
                        "goalsOpenplay": 1,
                        "attPenGoal": 0,
                        "attFreekickGoal": 0,
                        "ownGoals": 1,
                    },
                },
            ]
        ),
    }
    return row, source


def test_leeds_set_piece_corroboration_keeps_source_time_and_exact_revision() -> None:
    import json

    from fpl.config import config_dir
    from fpl.publish.sdp_goal_patterns import AUDIT_FILE

    audit = json.loads((config_dir() / AUDIT_FILE).read_text(encoding="utf-8"))
    evidence = next(r for r in audit["rows"] if r["fixture"] == 40 and r["team_code"] == 2)
    row, source = source_example()
    row.update(
        season=evidence["season"],
        fixture=40,
        team_code=2,
        opponent_team_code=4,
        kickoff_time=evidence["kickoff_time"],
        known_at="2026-09-17T13:40:49.988338+00:00",
    )
    source.update(
        sha256=evidence["raw_payload_sha256"],
        fetched_at=datetime(2026, 9, 17, 2, 30, 24, 531275, tzinfo=UTC),
    )
    original = deepcopy(source)
    apply_goal_patterns([row], [source])
    receipt = row["goal_patterns"]
    assert receipt["open_play_goals"] == 2
    assert receipt["set_piece_goals"] == receipt["confirmed_set_piece_goals"] == 1
    assert receipt["own_goals_received"] == 1 and receipt["unclassified_goals"] == 0
    assert receipt["audited_at"] == evidence["audited_at"] != audit["audited_at"]
    assert datetime.fromisoformat(receipt["audited_at"]) > source["fetched_at"]
    assert receipt["source_known_at"] == source["fetched_at"].isoformat()
    assert receipt["evidence_urls"] == evidence["evidence_urls"]
    assert row["sdp"]["set_piece_goals"] is None and source == original

    # A revised payload loses this exact-source audit and retains the unknown origin.
    source["sha256"] = "d" * 64
    apply_goal_patterns([row], [source])
    assert row["goal_patterns"] is None
    apply_source_goal_pattern(row, source, interpreted_at=datetime(2026, 9, 18, 5, tzinfo=UTC))
    assert row["goal_patterns"]["unclassified_goals"] == 1
    assert row["goal_patterns"]["set_piece_goals"] is None


def test_new_match_source_counts_separate_unknown_and_opponent_own_goal() -> None:
    import json

    row, source = source_example()
    payload = json.loads(source["body"])
    for side in payload:
        side["stats"] = {key: float(value) for key, value in side["stats"].items()}
    source["body"] = json.dumps(payload)
    original = deepcopy(source)
    stamp = datetime(2026, 9, 17, tzinfo=UTC)
    apply_source_goal_pattern(row, source, interpreted_at=stamp)
    receipt = row["goal_patterns"]
    assert receipt["open_play_goals"] == 2
    assert receipt["own_goals_received"] == receipt["unclassified_goals"] == 1
    assert receipt["confirmed_set_piece_goals"] == 0 and receipt["set_piece_goals"] is None
    assert receipt["method"] == "source_goal_accounting_v1" and "audited_at" not in receipt
    assert receipt["source_known_at"] == source["fetched_at"].isoformat()
    assert source == original and row["sdp"]["set_piece_goals"] is None
    replay, _ = source_example()
    apply_source_goal_pattern(replay, source, interpreted_at=stamp)
    assert replay == row

    away = {
        **row,
        "was_home": False,
        "goal_patterns": None,
        "sdp": {"open_play_goals": 1},
        "fpl": {"goals_scored": 1, "goals_conceded": 4},
    }
    apply_source_goal_pattern(away, source, interpreted_at=stamp)
    assert away["goal_patterns"]["open_play_goals"] == 1
    assert away["goal_patterns"]["set_piece_goals"] == 0
    assert away["goal_patterns"]["own_goals_received"] == 0


@pytest.mark.parametrize("bad", [None, True, -1, 0.5, "0"])
def test_absent_or_invalid_goal_origin_is_not_assumed_zero(bad: Any) -> None:
    import json

    row, source = source_example()
    payload = json.loads(source["body"])
    payload[0]["stats"]["attPenGoal"] = bad
    source["body"] = json.dumps(payload)
    apply_source_goal_pattern(row, source, interpreted_at=datetime(2026, 9, 17, tzinfo=UTC))
    assert row["goal_patterns"] is None


def test_new_capture_reaccounts_without_inheriting_old_audit_or_backdating() -> None:
    import json

    row, source = source_example()
    stamp = datetime(2026, 9, 17, tzinfo=UTC)
    apply_source_goal_pattern(row, source, interpreted_at=stamp)
    original = deepcopy(row["goal_patterns"])
    revised = deepcopy(source)
    payload = json.loads(revised["body"])
    payload[0]["stats"]["attPenGoal"] = 1
    revised.update(body=json.dumps(payload), sha256="d" * 64)
    refreshed, _ = source_example()
    refreshed["source_version"] = "e" * 64
    apply_source_goal_pattern(refreshed, revised, interpreted_at=stamp)
    assert refreshed["goal_patterns"]["set_piece_goals"] == 1
    assert refreshed["goal_patterns"]["unclassified_goals"] == 0
    assert row["goal_patterns"] == original
    pending, _ = source_example()
    apply_source_goal_pattern(pending, source, interpreted_at=datetime(2026, 9, 9, tzinfo=UTC))
    assert pending["goal_patterns"] is None
    wrong, _ = source_example()
    wrong["provider_match_id"] = 999
    apply_source_goal_pattern(wrong, source, interpreted_at=stamp)
    assert wrong["goal_patterns"] is None
    wrong["provider_match_id"] = source["sdp_match_id"]
    wrong["fpl"]["goals_scored"] = 0
    apply_source_goal_pattern(wrong, source, interpreted_at=stamp)
    assert wrong["goal_patterns"] is None
