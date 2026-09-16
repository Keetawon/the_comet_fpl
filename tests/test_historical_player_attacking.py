"""Synthetic source contracts only; no historical backfill or model evaluation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.validate.historical_player_attacking import (
    BackfillScope,
    HistoricalPlayerAttackingObservation,
    SnapshotEvidence,
    earliest_eligible_observations,
    historical_eligible,
    parse_snapshot,
)

COMMIT = "a" * 40
KICKOFF = datetime(2023, 8, 11, 19, tzinfo=UTC)
SOURCE = datetime(2023, 8, 16, 2, tzinfo=UTC)
CAPTURE = datetime(2026, 9, 8, 8, tzinfo=UTC)
SCOPE = BackfillScope(("2023-24",), (1,), (COMMIT,))


def csv_bytes(rows: list[dict[str, str]]) -> bytes:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue().encode()


def parts(**changes: str) -> dict[str, bytes]:
    return {
        "stats": csv_bytes(
            [
                {
                    "element": "1",
                    "fixture": "8",
                    "GW": "1",
                    "round": "1",
                    "kickoff_time": KICKOFF.isoformat(),
                    "opponent_team": "2",
                    "was_home": "True",
                    "position": "DEF",
                    "team": "Home",
                    "minutes": "90",
                    "starts": "1",
                    "expected_goals": "0.10",
                    "expected_assists": "0.20",
                    "expected_goal_involvements": "0.30",
                    "goals_scored": "0",
                    "assists": "0",
                    "total_points": "-1",
                    "influence": "-0.4",
                    "creativity": "10.4",
                    "threat": "5.0",
                    "ict_index": "1.5",
                    **changes,
                }
            ]
        ),
        # End-of-snapshot club intentionally differs from the observed fixture club.
        "registry": csv_bytes([{"id": "1", "code": "101", "element_type": "2", "team": "2"}]),
        "fixtures": csv_bytes(
            [
                {
                    "id": "8",
                    "event": "1.0",
                    "kickoff_time": KICKOFF.isoformat(),
                    "team_h": "1",
                    "team_a": "2",
                    "finished": "True",
                }
            ]
        ),
        "teams": csv_bytes(
            [{"id": "1", "code": "10", "name": "Home"}, {"id": "2", "code": "20", "name": "Away"}]
        ),
    }


def evidence(raw: dict[str, bytes]) -> SnapshotEvidence:
    return SnapshotEvidence(
        season="2023-24",
        snapshot_id=COMMIT,
        evidence_class="ARCHIVED_AS_OF",
        author_at=SOURCE,
        committer_at=SOURCE,
        capture_known_at=CAPTURE,
        expected_hashes=tuple((key, hashlib.sha256(body).hexdigest()) for key, body in raw.items()),
        audited_source_witness="frozen-source-audit-sha256",
    )


def parse(
    raw: dict[str, bytes],
    witness: SnapshotEvidence | None = None,
    scope: BackfillScope = SCOPE,
) -> tuple[HistoricalPlayerAttackingObservation, ...]:
    return parse_snapshot(
        stats_bytes=raw["stats"],
        registry_bytes=raw["registry"],
        fixtures_bytes=raw["fixtures"],
        teams_bytes=raw["teams"],
        evidence=witness or evidence(raw),
        scope=scope,
    )


def eligible(row: HistoricalPlayerAttackingObservation, as_of: datetime = SOURCE) -> bool:
    return historical_eligible(row, as_of=as_of, target_season="2023-24", target_gameweek=2)


def test_historical_position_stable_code_and_temporal_club_preserved() -> None:
    row = parse(parts())[0]
    assert (row.player_code, row.fpl_position, row.team_code, row.opponent_team_code) == (
        101,
        "DEF",
        10,
        20,
    )
    assert row.minutes == 90 and row.started is True
    assert row.total_points == -1 and row.influence == -0.4


def test_cross_season_element_churn_does_not_merge_identities() -> None:
    old = parse(parts())[0]
    raw = parts(position="MID")
    raw["registry"] = csv_bytes([{"id": "1", "code": "999", "element_type": "3", "team": "1"}])
    witness = replace(evidence(raw), season="2024-25")
    current = parse(raw, witness, replace(SCOPE, seasons=("2024-25",)))[0]
    assert (old.player_code, current.player_code) == (101, 999)
    assert (old.fpl_position, current.fpl_position) == ("DEF", "MID")


def test_missing_statistics_remain_null_and_explicit_zero_remains_zero() -> None:
    row = parse(parts(expected_assists="", expected_goals="0.00", starts="", minutes=""))[0]
    assert row.expected_assists is None
    assert row.expected_goals == 0.0
    assert row.minutes is None and row.starts is None and row.started is None
    assert row.shots is row.shots_on_target is row.box_touches is row.key_passes is None


def test_known_archive_zero_prefix_remains_unmeasured() -> None:
    raw = parts(expected_goals="0.00", expected_assists="0.00", expected_goal_involvements="0.00")
    row = parse(
        raw, replace(evidence(raw), season="2022-23"), replace(SCOPE, seasons=("2022-23",))
    )[0]
    assert row.expected_goals is row.expected_assists is row.expected_goal_involvements is None


def test_current_capture_does_not_replace_historical_availability() -> None:
    raw = parts()
    row = parse(raw)[0]
    assert row.source_known_at == row.available_at == SOURCE
    assert row.capture_known_at == CAPTURE
    assert eligible(row)
    assert not eligible(row, SOURCE - timedelta(microseconds=1))
    with pytest.raises(ValueError, match="audited source witness"):
        parse(raw, replace(evidence(raw), audited_source_witness=None))


def test_late_committer_time_cannot_be_hidden_behind_old_author_time() -> None:
    raw = parts()
    row = parse(raw, replace(evidence(raw), committer_at=CAPTURE))[0]
    assert row.available_at == CAPTURE
    assert not eligible(row)


@pytest.mark.parametrize("kind", ["RETROSPECTIVE_DEVELOPMENT", "CURRENT_PROSPECTIVE"])
def test_nonhistorical_classes_never_pass_historical_gate(kind: str) -> None:
    raw = parts()
    row = parse(raw, replace(evidence(raw), evidence_class=kind, audited_source_witness=None))[0]
    assert row.source_known_at is None
    assert row.available_at == CAPTURE
    assert not eligible(row, CAPTURE + timedelta(days=1))


def test_same_target_gameweek_and_fixture_are_never_history() -> None:
    row = parse(parts())[0]
    assert not historical_eligible(row, as_of=SOURCE, target_season="2023-24", target_gameweek=1)
    assert not historical_eligible(
        row, as_of=SOURCE, target_season="2023-24", target_gameweek=2, target_fixture=8
    )


def test_source_round_is_corroborated_with_gameweek_when_available() -> None:
    with pytest.raises(ValueError, match="round/gameweek contradiction"):
        parse(parts(round="2"))
    assert parse(parts(round=""))[0].gameweek == 1


def test_target_match_postkickoff_observation_cannot_pass_prekickoff_cutoff() -> None:
    row = parse(parts())[0]
    assert not eligible(row, KICKOFF - timedelta(microseconds=1))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected_goals", "NaN"),
        ("expected_assists", "inf"),
        ("expected_goals", "-0.1"),
        ("minutes", "121"),
        ("starts", "2"),
        ("goals_scored", "1.5"),
    ],
)
def test_invalid_numeric_evidence_fails_closed(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=r"numeric|impossible|non-integer"):
        parse(parts(**{field: value}))


@pytest.mark.parametrize(
    "changes",
    [
        {"position": "MID"},
        {"element": "99"},
        {"team": "home"},
        {"opponent_team": "1"},
        {"was_home": "unknown"},
        {"fixture": "99"},
    ],
)
def test_identity_and_position_fail_closed_without_fuzzy_matching(changes: dict[str, str]) -> None:
    with pytest.raises(ValueError, match=r"contradiction|unmapped|invalid boolean"):
        parse(parts(**changes))


def test_duplicate_rows_fail_even_when_identical() -> None:
    raw = parts()
    lines = raw["stats"].splitlines(keepends=True)
    raw["stats"] += lines[1]
    with pytest.raises(ValueError, match="duplicate fixture/player"):
        parse(raw)


def test_duplicate_stable_code_mapping_rejected() -> None:
    raw = parts()
    raw["registry"] = csv_bytes(
        [
            {"id": "1", "code": "101", "element_type": "2"},
            {"id": "2", "code": "101", "element_type": "2"},
        ]
    )
    with pytest.raises(ValueError, match="duplicate stable player"):
        parse(raw)


def test_raw_content_hash_and_immutability() -> None:
    raw = parts()
    original = raw.copy()
    witness = evidence(raw)
    parsed = parse(raw, witness)
    assert raw == original
    assert parsed[0].source_sha256 == hashlib.sha256(raw["stats"]).hexdigest()
    raw["stats"] += b"\n"
    with pytest.raises(ValueError, match="content hash mismatch"):
        parse(raw, witness)


@pytest.mark.parametrize(
    "scope",
    [
        replace(SCOPE, seasons=("2025-26",)),
        replace(SCOPE, gameweeks=(2,)),
        replace(SCOPE, allowed_snapshot_ids=("b" * 40,)),
    ],
)
def test_frozen_scope_enforcement(scope: BackfillScope) -> None:
    with pytest.raises(ValueError, match="scope"):
        parse(parts(), scope=scope)


def test_future_rows_do_not_alter_earlier_availability_and_replay_is_identical() -> None:
    raw = parts()
    row = parse(raw)[0]
    future = replace(row, source_known_at=CAPTURE, available_at=CAPTURE, expected_goals=100.0)
    before = json.dumps([asdict(r) for r in [row] if eligible(r)], default=str, sort_keys=True)
    after = json.dumps(
        [asdict(r) for r in [row, future] if eligible(r)], default=str, sort_keys=True
    )
    replay = json.dumps([asdict(r) for r in parse(raw)], default=str, sort_keys=True)
    assert before == after == replay


def test_earliest_selector_preserves_first_version_nulls_despite_later_corrections() -> None:
    original = parse(parts(expected_assists=""))[0]
    correction = replace(
        original,
        source_snapshot_id="b" * 40,
        source_known_at=SOURCE + timedelta(days=1),
        available_at=SOURCE + timedelta(days=1),
        expected_assists=0.5,
    )
    selected = earliest_eligible_observations(
        [correction, original],
        as_of=SOURCE + timedelta(days=2),
        target_season="2023-24",
        target_gameweek=2,
    )
    assert selected == (original,)
    assert selected[0].expected_assists is None


def test_earliest_selector_rejects_conflicting_version_and_is_future_invariant() -> None:
    original = parse(parts())[0]
    future = replace(
        original,
        source_snapshot_id="b" * 40,
        source_known_at=CAPTURE,
        available_at=CAPTURE,
        expected_goals=100.0,
    )
    selected = earliest_eligible_observations(
        [future, original, original], as_of=SOURCE, target_season="2023-24", target_gameweek=2
    )
    truncated = earliest_eligible_observations(
        [original], as_of=SOURCE, target_season="2023-24", target_gameweek=2
    )
    assert json.dumps([asdict(row) for row in selected], default=str, sort_keys=True) == json.dumps(
        [asdict(row) for row in truncated], default=str, sort_keys=True
    )
    with pytest.raises(ValueError, match="contradictory values"):
        earliest_eligible_observations(
            [original, replace(original, expected_assists=0.7)],
            as_of=SOURCE,
            target_season="2023-24",
            target_gameweek=2,
        )


def test_naive_or_impossible_timestamps_rejected() -> None:
    raw = parts()
    with pytest.raises(ValueError, match="timezone-aware"):
        parse(raw, replace(evidence(raw), author_at=SOURCE.replace(tzinfo=None)))
    with pytest.raises(ValueError, match="postdate"):
        parse(raw, replace(evidence(raw), capture_known_at=SOURCE - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="precede source"):
        parse(raw, replace(evidence(raw), author_at=KICKOFF, committer_at=KICKOFF))
    with pytest.raises(ValueError, match="timezone-aware"):
        eligible(parse(raw)[0], SOURCE.replace(tzinfo=None))


def test_frozen_feasibility_artifact_unchanged() -> None:
    from pathlib import Path

    result = (
        Path(__file__).parents[1] / "results/attacking_role_premium_feasibility_2026-09-08.json"
    )
    assert hashlib.sha256(result.read_bytes()).hexdigest() == (
        "65b950bfb95c965f4c776964f4b18074fa60aa74e4b7224b355ef969e0e31ed7"
    )
