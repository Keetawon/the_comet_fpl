"""Hand-computable role probability checks; no provider access or historical scoring."""

from __future__ import annotations

from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from fpl.validate.player_role_history import (
    COMPLETION_MARGIN_HOURS,
    EVIDENCE_CLASS,
    NAME,
    PRIOR_STRENGTH,
    RAW_ROLES,
    ROLES,
    WEIGHTS,
    RoleHistoryRow,
    RoleTarget,
    forecast_role_batch,
    observed_starting_role,
    walk_forward_role_forecasts,
)

ORIGIN = datetime(2025, 8, 1, tzinfo=UTC)
CAPTURE = datetime(2026, 9, 7, tzinfo=UTC)


def observation(
    index: int, role: str | None, *, code: int = 1, team: int = 3, started: bool | None = True
) -> RoleHistoryRow:
    return RoleHistoryRow(
        "2025-26",
        8,
        1000 + index,
        index,
        code,
        team,
        ORIGIN + timedelta(days=index),
        True,
        started,
        role,
        100 + code,
        f"p{100 + code}",
        "verified-season-opta-crosswalk",
        f"capture-{index}",
        "a" * 64,
        CAPTURE,
        CAPTURE,
    )


def target(index: int = 10, *, code: int = 1, team: int = 3) -> RoleTarget:
    cutoff = ORIGIN + timedelta(days=index)
    return RoleTarget("2025-26", index, index, code, team, cutoff, cutoff, "archive-roster-proxy")


def test_hand_calculated_two_start_transition_and_shrinkage() -> None:
    history = [observation(1, "Defender"), observation(2, "Midfielder")]
    batch = forecast_role_batch(history, [target()])
    row = batch.predictions[0]
    assert batch.global_prior == (0, 0.5, 0.5, 0)
    assert batch.transition_counts[1] == (0, 0, 1, 0)
    assert batch.transition_matrix[1] == pytest.approx((0, 1 / 3, 2 / 3, 0))
    assert batch.transition_matrix[2] == (0, 0.5, 0.5, 0)
    p_def = 0.707 / 1.707
    p_mid = 1 / 1.707
    assert row.recent_distribution == pytest.approx((0, p_def, p_mid, 0))
    assert row.recent_weight == 0.5
    assert row.probabilities == pytest.approx(
        (0, 0.5 * (p_def / 3 + p_mid / 2) + 0.25, 0.5 * (2 * p_def / 3 + p_mid / 2) + 0.25, 0)
    )
    assert row.smoothed_last_role_baseline == pytest.approx((0, 1 / 3, 2 / 3, 0))
    assert row.recent_state_persistence_baseline == pytest.approx(
        (0, 0.5 * p_def + 0.25, 0.5 * p_mid + 0.25, 0)
    )


def test_last_five_measured_start_cap_and_exact_newest_weights() -> None:
    history = [observation(i, "Defender" if i <= 5 else "Forward") for i in range(1, 7)]
    row = forecast_role_batch(history, [target()]).predictions[0]
    assert [source.match_id for source in row.recent_sources] == [1006, 1005, 1004, 1003, 1002]
    assert row.recent_measured_starts == 5
    assert row.recent_weight == 5 / 7
    assert row.recent_distribution == pytest.approx(
        (0, sum(WEIGHTS[1:]) / sum(WEIGHTS), 0, 1 / sum(WEIGHTS))
    )


@pytest.mark.parametrize("started", [False, None])
@pytest.mark.parametrize(
    "position", ["Goalkeeper", "Defender", "Midfielder", "Forward", "Substitute", None]
)
def test_nonstarting_rows_never_supply_role_targets(
    started: bool | None, position: str | None
) -> None:
    assert observed_starting_role(position, started) is None
    row = forecast_role_batch([observation(1, position, started=started)], [target()])
    assert row.prior_role_targets == 0
    assert row.predictions[0].recent_distribution is None
    assert row.predictions[0].probabilities == (0.25, 0.25, 0.25, 0.25)


@pytest.mark.parametrize("position", [None, "Substitute", "WingBack", "unknown"])
def test_unlicensed_starting_label_is_missing_not_fpl_position(position: str | None) -> None:
    assert observed_starting_role(position, True) is None
    batch = forecast_role_batch([observation(1, position)], [target()])
    assert batch.role_counts == (0, 0, 0, 0)


def test_bench_does_not_interrupt_next_start_transition() -> None:
    batch = forecast_role_batch(
        [
            observation(1, "Defender"),
            observation(2, "Substitute", started=False),
            observation(3, "Forward"),
        ],
        [target()],
    )
    assert batch.transition_counts[1][3] == 1
    assert batch.predictions[0].recent_measured_starts == 2


@pytest.mark.parametrize("started", [True, None])
def test_unmeasured_possible_start_breaks_observed_transition(started: bool | None) -> None:
    batch = forecast_role_batch(
        [
            observation(1, "Defender"),
            observation(2, None, started=started),
            observation(3, "Forward"),
        ],
        [target()],
    )
    assert sum(map(sum, batch.transition_counts)) == 0
    assert batch.predictions[0].recent_measured_starts == 2


def test_transfer_resets_without_old_club_history_reuse() -> None:
    history = [observation(1, "Defender", team=3), observation(2, "Midfielder", team=7)]
    row = forecast_role_batch(history, [target(team=3)]).predictions[0]
    assert row.recent_measured_starts == 0
    assert not row.witnessed_current_club_spell
    assert row.probabilities == row.pooled_prior_baseline


def test_returning_club_uses_only_latest_witnessed_spell() -> None:
    history = [
        observation(1, "Defender", team=3),
        observation(2, "Forward", team=7),
        observation(3, "Midfielder", team=3),
    ]
    batch = forecast_role_batch(history, [target(team=3)])
    assert batch.predictions[0].recent_measured_starts == 1
    assert batch.predictions[0].recent_sources == (history[-1],)
    assert sum(map(sum, batch.transition_counts)) == 0


def test_prior_bench_membership_can_witness_transfer_without_role_target() -> None:
    history = [
        observation(1, "Defender", team=3),
        observation(2, "Substitute", team=7, started=False),
    ]
    batch = forecast_role_batch(history, [target(team=7)])
    assert batch.prior_role_targets == 1
    assert batch.predictions[0].witnessed_current_club_spell
    assert batch.predictions[0].recent_measured_starts == 0


def test_same_club_season_boundary_keeps_observed_history_only() -> None:
    row = replace(observation(1, "Defender"), season="2024-25")
    predicted = forecast_role_batch([row], [target()]).predictions[0]
    assert predicted.recent_sources == (row,)
    assert predicted.recent_measured_starts == 1


def test_future_truncation_equivalence_and_preserved_late_known_at() -> None:
    prior = observation(1, "Defender")
    before = forecast_role_batch([prior], [target()])
    after = forecast_role_batch(
        [prior, observation(10, "Midfielder"), observation(11, "Forward")], [target()]
    )
    assert after == before
    assert after.late_capture_rows == 1
    assert after.predictions[0].maximum_source_known_at == CAPTURE
    assert after.predictions[0].evidence_class == EVIDENCE_CLASS
    assert not after.predictions[0].promotion_permitted


def test_target_gw_excluded_even_if_corrupt_earlier_kickoff_supplied() -> None:
    future_batch = replace(observation(2, "Forward"), gw=10)
    expected = forecast_role_batch([observation(1, "Defender")], [target()])
    assert forecast_role_batch([observation(1, "Defender"), future_batch], [target()]) == expected


def test_all_dgw_legs_share_one_fit_and_no_within_batch_absorption() -> None:
    first = target()
    later = replace(first, fixture=99, kickoff=first.kickoff + timedelta(days=4))
    target_outcome = observation(10, "Forward")
    batch = forecast_role_batch([observation(1, "Defender"), target_outcome], [first, later])
    assert batch.prior_role_targets == 1
    assert batch.predictions[0].probabilities == batch.predictions[1].probabilities
    assert batch.predictions[0].recent_sources == batch.predictions[1].recent_sources


def test_sequential_predictions_absorb_prior_gw_only_after_its_batch() -> None:
    history = [observation(1, "Defender"), observation(2, "Midfielder"), observation(3, "Forward")]
    batches = walk_forward_role_forecasts(history, [target(3), target(2)])
    assert [batch.gw for batch in batches] == [2, 3]
    assert [batch.prior_role_targets for batch in batches] == [1, 2]
    assert batches[0].transition_counts[1][2] == 0
    assert batches[1].transition_counts[1][2] == 1


def test_postponed_older_gw_after_cutoff_is_not_visible() -> None:
    delayed = replace(observation(12, "Forward"), gw=1)
    assert forecast_role_batch(
        [observation(1, "Defender"), delayed], [target()]
    ) == forecast_role_batch([observation(1, "Defender")], [target()])


def test_completed_cup_start_participates_without_inventing_fpl_gw() -> None:
    cup = replace(observation(2, "Midfielder"), competition_id=2, gw=None)
    batch = forecast_role_batch([observation(1, "Defender"), cup], [target()])
    assert batch.prior_role_targets == 2
    assert batch.transition_counts[1][2] == 1


@pytest.mark.parametrize("completed", [False, None])
def test_unfinished_or_unknown_match_not_absorbed(completed: bool | None) -> None:
    row = replace(observation(1, "Forward"), completed=completed)
    assert forecast_role_batch([row], [target()]) == forecast_role_batch([], [target()])


@pytest.mark.parametrize(("seconds", "expected"), [(1, 0), (0, 0), (-1, 1)])
def test_unverified_completion_margin_is_strict(seconds: int, expected: int) -> None:
    cutoff = target().as_of
    row = replace(
        observation(1, "Defender"),
        kickoff=cutoff - timedelta(hours=COMPLETION_MARGIN_HOURS) + timedelta(seconds=seconds),
    )
    batch = forecast_role_batch([row], [target()])
    assert batch.prior_role_targets == expected
    assert batch.completion_time_proxy_rows == expected
    if expected:
        assert batch.predictions[0].completion_time_proxy
        assert batch.predictions[0].recent_sources[0].verified_end_at is None


@pytest.mark.parametrize(("seconds", "expected"), [(-1, 1), (0, 0), (1, 0)])
def test_verified_completion_end_is_strict(seconds: int, expected: int) -> None:
    cutoff = target().as_of
    row = replace(
        observation(1, "Defender"),
        kickoff=cutoff - timedelta(hours=2),
        verified_end_at=cutoff + timedelta(seconds=seconds),
    )
    batch = forecast_role_batch([row], [target()])
    assert batch.prior_role_targets == expected
    assert batch.completion_time_proxy_rows == 0
    assert not batch.predictions[0].completion_time_proxy


@pytest.mark.parametrize(("seconds", "expected"), [(-1, 1), (0, 0), (1, 0)])
def test_retained_future_event_excludes_even_old_completed_match(
    seconds: int, expected: int
) -> None:
    row = replace(
        observation(1, "Defender"), max_event_at=target().as_of + timedelta(seconds=seconds)
    )
    batch = forecast_role_batch([row], [target()])
    assert batch.prior_role_targets == expected
    if expected:
        assert batch.predictions[0].maximum_retained_event == row.max_event_at


@pytest.mark.parametrize("field", ["max_event_at", "verified_end_at"])
def test_event_metadata_requires_aware_timestamp_not_before_kickoff(field: str) -> None:
    row = observation(1, "Defender")
    with pytest.raises(ValueError, match="timezone aware"):
        replace(row, **{field: row.kickoff.replace(tzinfo=None)})
    with pytest.raises(ValueError, match="cannot precede kickoff"):
        replace(row, **{field: row.kickoff - timedelta(seconds=1)})


def test_event_after_independently_verified_end_is_contradiction() -> None:
    row = observation(1, "Defender")
    with pytest.raises(ValueError, match="cannot follow verified match end"):
        replace(
            row,
            verified_end_at=row.kickoff + timedelta(hours=2),
            max_event_at=row.kickoff + timedelta(hours=3),
        )


def test_deterministic_order_probabilities_and_full_declared_roster() -> None:
    history = [
        observation(i, role, code=i)
        for i, role in enumerate(["Goalkeeper", "Defender", "Midfielder", "Forward"], 1)
    ]
    targets = [target(code=i) for i in (1, 2, 3, 4, 99)]
    batch = forecast_role_batch(history, targets)
    assert batch == forecast_role_batch(list(reversed(history)), list(reversed(targets)))
    assert len(batch.predictions) == 5
    for row in batch.predictions:
        assert sum(row.probabilities) == pytest.approx(1)
        assert all(p >= 0 for p in row.probabilities)
    assert batch.predictions[-1].recent_measured_starts == 0


def test_target_projection_has_no_start_outcome_or_fpl_position() -> None:
    names = {field.name for field in fields(RoleTarget)}
    assert not names & {
        "started",
        "on_bench",
        "minutes",
        "position",
        "raw_position",
        "role",
        "goals",
    }


def test_duplicate_versions_and_simultaneous_player_fixtures_refused() -> None:
    row = observation(1, "Defender")
    with pytest.raises(ValueError, match="duplicate role revision"):
        forecast_role_batch([row, replace(row, capture_id="later")], [target()])
    with pytest.raises(ValueError, match="ambiguous simultaneous"):
        forecast_role_batch([row, replace(row, match_id=9000, team_code=7)], [target()])


def test_batch_cutoff_and_club_conflicts_refused() -> None:
    first = target()
    with pytest.raises(ValueError, match="share one cutoff"):
        forecast_role_batch(
            [], [first, replace(first, fixture=99, as_of=first.as_of - timedelta(hours=1))]
        )
    with pytest.raises(ValueError, match="club ambiguity"):
        forecast_role_batch([], [first, replace(first, fixture=99, team_code=7)])
    with pytest.raises(ValueError, match="first kickoff"):
        forecast_role_batch([], [replace(first, as_of=first.as_of - timedelta(hours=1))])


def test_identity_timestamp_and_explicit_pl_gw_boundary() -> None:
    row = observation(1, "Defender")
    with pytest.raises(ValueError, match="exact crosswalk"):
        replace(row, fpl_opta_anchor="someone_else")
    with pytest.raises(ValueError, match="timezone aware"):
        replace(row, kickoff=row.kickoff.replace(tzinfo=None))
    with pytest.raises(ValueError, match="verified FPL GW"):
        replace(row, gw=None)
    with pytest.raises(ValueError, match="six explicitly licensed"):
        replace(row, competition_id=999)


def test_conflicting_same_fixture_kickoffs_fail() -> None:
    first = target()
    with pytest.raises(ValueError, match="contradictory kickoffs"):
        forecast_role_batch(
            [], [first, replace(first, code=2, kickoff=first.kickoff + timedelta(hours=1))]
        )


def test_fixed_algorithm_config_does_not_authorize_formal_scoring() -> None:
    path = Path(__file__).resolve().parents[1] / "config/player_role_history_v1.yaml"
    pairs = yaml.compose(path.read_text(encoding="utf-8")).value
    keys = [key.value for key, _ in pairs]
    assert len(keys) == len(set(keys))
    policy = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert policy["identity"] == NAME
    assert policy["evidence_class"] == EVIDENCE_CLASS
    assert tuple(policy["roles"]) == ROLES
    assert policy["provider_labels"] == RAW_ROLES
    assert tuple(policy["current_state"]["newest_first_weights"]) == WEIGHTS
    assert policy["transitions"]["prior_strength"] == PRIOR_STRENGTH
    assert policy["formal_evaluation_authorized"] is False
    assert policy["promotion_permitted"] is False
    assert (
        policy["fixed_diagnostic"]["recent_state_persistence"]
        == "alpha * q_recent + (1 - alpha) * p_global"
    )
    assert policy["completion_eligibility"]["conservative_margin_hours"] == COMPLETION_MARGIN_HOURS
    assert (
        policy["coverage_based_evaluation_requirements"]["minimum_season_starting_label_coverage"]
        == 0.95
    )
