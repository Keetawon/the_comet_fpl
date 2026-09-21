"""Synthetic venue/missingness/causality contracts; no historical candidate scoring."""

from __future__ import annotations

import gzip
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fpl.validate import chance_creation as chance
from fpl.validate import dev_v2_chance_creation as legacy
from fpl.validate.audit_json import canonical
from fpl.validate.dev_team_venue_form import compare, publish
from fpl.validate.metrics import poisson_pmf
from fpl.validate.tactical_state import TacticalObservation, current_state
from fpl.validate.team_venue_form import (
    ARMS,
    form_state,
    interpreted_observations,
    style_walk_forward,
    weighted_summary,
)

START = datetime(2024, 8, 1, tzinfo=UTC)


def obs(i: int, value: float | None, *, home: bool = True, team: int = 10) -> TacticalObservation:
    return TacticalObservation(
        "2024-25",
        i,
        i,
        team,
        20 if team == 10 else 10,
        home,
        START + timedelta(days=7 * i),
        1,
        1,
        (value, value, value, value, value),
        1000 + i,
        f"capture-{i}",
        START + timedelta(days=1000),
        f"sha-{i}",
    )


def state(rows: list[TacticalObservation], arm: Any = "C", home: bool = True) -> Any:
    return form_state(rows, 10, "2024-25", START + timedelta(days=100), 99, home, arm)


def test_fixed_windows_missing_does_not_pull_older_match_and_zero_counts() -> None:
    rows = [obs(i, float(i)) for i in range(1, 8)]
    rows[-1] = obs(7, None)
    rows[-2] = obs(6, 0)
    s, d = state(rows, "A")
    assert s.recent_raw[0] == pytest.approx((0 * 0.30 + 5 * 0.20 + 4 * 0.07 + 3 * 0.03) / 0.60)
    assert s.counts == (4,) * 5
    assert [key[1] for key in d["overall_keys"]] == [7, 6, 5, 4, 3]
    assert rows[-1].values[0] is None


def test_venue_order_age_and_all_five_dimensions() -> None:
    rows = [obs(i, i / 10, home=i % 2 == 0) for i in range(1, 10)]
    a, details = state(rows)
    b, _ = state(list(reversed(rows)))
    assert a == b
    assert [k[1] for k in details["venue_keys"]] == [8, 6, 4, 2]
    assert details["venue_matches"] == 4
    assert details["venue_age_days"] == 86
    assert len(set(a.values)) == 1


def test_hybrid_hand_calculation_and_b_venue_prior() -> None:
    rows = [obs(1, 0.2), obs(2, 0.8, home=False), obs(3, 0.4)]
    a, _ = state(rows, "A")
    c, d = state(rows, "C")
    b, _ = state(rows, "B")
    raw = (0.4 * 0.4 + 0.2 * 0.3) / 0.7
    assert d["venue_valid_counts"] == [2] * 5
    assert c.values[0] == pytest.approx(0.4 * raw + 0.6 * a.values[0])
    assert b.values[0] == pytest.approx(0.4 * raw + 0.6 * 0.3)


def test_weighted_median_midpoint_and_missing_weight_renormalization() -> None:
    rows = [obs(5, 1), obs(4, 2), obs(3, 9), obs(2, 3), obs(1, 4)]
    assert weighted_summary(rows, 0, median=True) == (2, 5)
    # Missing .3 consumes its slot: .4 alone exceeds half of the retained .7.
    rows = [obs(5, 1), obs(4, None), obs(3, 9), obs(2, 9), obs(1, 9)]
    assert weighted_summary(rows, 0, median=True) == (1, 4)
    # .3 == .2+.07+.03, midpoint between 1 and 9.
    rows = [obs(5, None), obs(4, 1), obs(3, 9), obs(2, 9), obs(1, 9)]
    assert weighted_summary(rows, 0, median=True) == (5, 4)


@pytest.mark.parametrize(("n", "weight"), [(3, 0.5), (5, 0.625)])
def test_per_dimension_venue_count_controls_fixed_hybrid_weight(n: int, weight: float) -> None:
    rows = [obs(i, i / 10) for i in range(1, n + 1)]
    # Latest precision alone is missing; other dimensions retain n observations.
    rows[-1] = replace(rows[-1], values=(None, *rows[-1].values[1:]))
    a, _ = state(rows, "A")
    c, detail = state(rows, "C")
    assert detail["venue_valid_counts"] == [n - 1, n, n, n, n]
    for d in range(1, 5):
        assert c.values[d] == pytest.approx(
            weight * detail["venue_raw"][d] + (1 - weight) * a.values[d]
        )


@pytest.mark.parametrize("arm", ARMS)
def test_same_gw_future_season_and_identity_exclusions(arm: Any) -> None:
    base = [obs(1, 0.2), obs(2, 0.4, home=False)]
    cutoff = START + timedelta(days=35)
    forbidden = [obs(5, 0.99), replace(obs(3, 0.99), gw=5), obs(6, 0.99)]
    expected = form_state(base, 10, "2024-25", cutoff, 5, True, arm)
    assert form_state(base + forbidden, 10, "2024-25", cutoff, 5, True, arm) == expected
    foreign = replace(obs(3, 0.9), team_code=30)
    _, details = state([*base, foreign], arm)
    assert all(k[2] == 10 for k in details["venue_keys"])
    # Earlier-season observations affect league prior, not recent team form.
    old = replace(obs(1, 0.9), season="2023-24", kickoff=START - timedelta(days=20))
    _, details = state([old, *base], arm)
    assert len(details["overall_keys"]) == 2


def test_c0_c1_exact_original_state_and_cold_start() -> None:
    rows = [obs(i, i / 10) for i in range(1, 4)]
    for arm in ("C0", "C1"):
        assert state(rows, arm)[0] == current_state(
            rows, 10, "2024-25", START + timedelta(days=100), 99
        )
    for arm in ARMS:
        assert state([], arm)[0].values == (None,) * 5
    a, _ = state([obs(1, 0.4, home=False)], "A")
    assert state([obs(1, 0.4, home=False)], "C")[0].values == a.values


def test_interpretation_hash_fail_closed_raw_unchanged() -> None:
    r = obs(1, None)
    source = {
        "season": r.season,
        "fixture": r.fixture,
        "team_code": r.team_code,
        "opponent_team_code": r.opponent_team_code,
        "was_home": r.was_home,
        "capture_id": r.capture_id,
        "payload_sha256": r.payload_sha256,
        "source_known_at": r.source_known_at,
        "sdp_match_id": r.sdp_match_id,
        "shots_on_target": None,
        "shots_on_target_corroborated": 0,
        "sot_interpretation": "independent_report_zero",
        "shots": 6,
    }
    fixed = interpreted_observations([r], [source], [source])
    assert fixed[0].values == (0, None, None, None, None)
    assert r.values == (None,) * 5
    with pytest.raises(ValueError, match="identity differs"):
        interpreted_observations([r], [{**source, "payload_sha256": "wrong"}], [source])
    with pytest.raises(ValueError, match="uncorroborated"):
        interpreted_observations(
            [r], [{**source, "sot_interpretation": "opponent_pair_only"}], [source]
        )


def synthetic(count: int = 5) -> list[TacticalObservation]:
    return [
        obs(i, (i % 4 + 1) / 10, home=(team == 10) == (i % 2 == 0), team=team)
        for i in range(1, count + 1)
        for team in (10, 20)
    ]


def test_whole_batch_future_truncation_replay_and_opponent_venue() -> None:
    rows = synthetic()
    a = style_walk_forward(rows, "C")
    assert canonical(a) == canonical(style_walk_forward(list(reversed(rows)), "C"))
    prefix = style_walk_forward(rows[:6], "C")
    assert canonical(a["rows"][:6]) == canonical(prefix["rows"])
    for r in a["rows"]:
        assert r["form"]["target_venue"] != r["opponent_form"]["target_venue"]
        assert all(k[1] < r["fixture"] for k in r["form"]["overall_keys"])


def test_dgw_opposite_venues_have_distinct_states_and_are_both_excluded() -> None:
    rows = synthetic()
    # Fixtures 4 and 5 become the same GW, one home and one away for each club.
    rows = [replace(r, gw=4) if r.fixture == 5 else r for r in rows]
    result = style_walk_forward(rows, "B")
    batch = [r for r in result["rows"] if r["gw"] == 4 and r["team_code"] == 10]
    assert batch[0]["as_of"] == batch[1]["as_of"]
    assert batch[0]["current_state"] != batch[1]["current_state"]
    assert all(k[1] < 4 for r in batch for k in r["form"]["overall_keys"])


def test_full_style_to_chance_integration_with_actual_fits() -> None:
    raw = synthetic(85)  # Fits start after the frozen 160-row minimum.
    upstream = style_walk_forward(raw, "C")
    cache = {legacy_key(r): (1.2, poisson_pmf(1.2, max_goals=10)) for r in raw}
    targets = [
        {
            "key": legacy_key(r),
            "season": r.season,
            "gw": r.gw,
            "fixture": r.fixture,
            "team_code": r.team_code,
            "opponent_team_code": r.opponent_team_code,
            "was_home": r.was_home,
            "kickoff_time": r.kickoff,
            "goals": r.goals,
            "shots": 8,
            "expected_goals": 0.8,
            "capture_id": r.capture_id,
            "source_known_at": r.source_known_at,
            "payload_sha256": r.payload_sha256,
            "sdp_match_id": r.sdp_match_id,
        }
        for r in raw
    ]
    inputs = legacy.make_observations(targets, upstream, cache)
    experiment = chance.run_chance_walk_forward(inputs, ("2024-25",))
    assert any(f["stage_fits"]["volume"]["model"] is not None for f in experiment["folds"])
    assert upstream["folds"][-1]["style_fits"]["control"]["model"] is not None
    assert all(
        r.maximum_state_source_event is None or r.maximum_state_source_event < r.as_of
        for r in inputs
    )


def legacy_key(r: TacticalObservation) -> str:
    return f"{r.season}:{r.fixture}:{r.team_code}"


def test_write_once_compressed_byte_replay(tmp_path: Path) -> None:
    obj = {1: {10: (1, None, 0), 2: START}}
    a, b = tmp_path / "a.json.gz", tmp_path / "b.json.gz"
    assert publish(a, obj) == publish(b, json.loads(canonical(obj)))
    assert json.loads(gzip.decompress(a.read_bytes())) == json.loads(canonical(obj))
    with pytest.raises(FileExistsError):
        publish(a, {"mutation": True})


def test_paired_population_mismatch_rejected() -> None:
    with pytest.raises(ValueError, match="populations differ"):
        compare({"C": {"history_rows": [{"key": "a"}]}, "C0": {"history_rows": []}}, "C", "C0", {})


def test_paired_scoring_binds_requested_arm_after_json_roundtrip() -> None:
    from tests.test_chance_creation_runner import _experiment, _fixture

    experiment, _, _, _ = _experiment()
    control = json.loads(canonical(experiment))
    for group in (control["rows"], control["history_rows"]):
        for row in group:
            row["distributions"]["candidate"] = list(poisson_pmf(0.5, max_goals=10))
            row["clean_sheet_probabilities"]["candidate"] = poisson_pmf(0.5, max_goals=10)[0]
    contract = _fixture()[2]
    result = compare({"C": json.loads(canonical(experiment)), "C0": control}, "C", "C0", contract)
    assert result["overall"]["incumbent"]["predicted_rate_mean"] == pytest.approx(0.5)
    assert result["overall"]["candidate"]["predicted_rate_mean"] == pytest.approx(1.2)
    assert result["paired_uncertainty"]["log_score"]["paired_mean"] != 0
