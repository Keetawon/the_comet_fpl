"""Offline tests for the hybrid BPS / bonus match-simulator (development-only deliverable).

No network, no built database: every test is a deterministic unit or property test over the
model, the tie-break rule, the residual estimator, and the bonus metrics.
"""

from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from fpl.config import BpsRules, BpsSource, load_scoring_rules
from fpl.models.bps_bonus import (
    BpsSimConfig,
    PlayerRow,
    PositionAccumulator,
    ResidualModel,
    _fit_positional,
    award_bonus,
    exact_bps,
    fit_residual_model,
    positional_from_accumulator,
    simulate_fixture_bonus,
)
from fpl.validate.bonus_metrics import BonusRecord, score_bonus_predictions

BPS = load_scoring_rules("2026_27").bps
assert BPS is not None


def _row(**overrides: object) -> PlayerRow:
    base: dict[str, object] = {
        "code": 1,
        "position": "MID",
        "minutes": 90,
        "goals_scored": 0,
        "assists": 0,
        "clean_sheets": 0,
        "penalties_saved": 0,
        "clearances_blocks_interceptions": None,
        "influence": 20.0,
        "creativity": 10.0,
        "bps": 0,
        "bonus": 0,
    }
    base.update(overrides)
    return PlayerRow(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------------------
# Exact part
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "goals", "expected"),
    [("FWD", 1, 24), ("MID", 1, 18), ("DEF", 1, 12), ("GK", 1, 12), ("FWD", 2, 48)],
)
def test_exact_goal_values(position: str, goals: int, expected: int) -> None:
    assert exact_bps(_row(position=position, goals_scored=goals), BPS) == expected


def test_exact_assist_value() -> None:
    assert exact_bps(_row(assists=1), BPS) == 9
    assert exact_bps(_row(assists=2), BPS) == 18


def test_exact_clean_sheet_gk_def_only_and_gated_at_60() -> None:
    assert exact_bps(_row(position="DEF", clean_sheets=1, minutes=90), BPS) == 12
    assert exact_bps(_row(position="GK", clean_sheets=1, minutes=90), BPS) == 12
    # MID/FWD earn no clean-sheet BPS.
    assert exact_bps(_row(position="MID", clean_sheets=1, minutes=90), BPS) == 0
    assert exact_bps(_row(position="FWD", clean_sheets=1, minutes=90), BPS) == 0
    # Under 60 minutes: no clean-sheet BPS even for a defender.
    assert exact_bps(_row(position="DEF", clean_sheets=1, minutes=59), BPS) == 0


def test_exact_cbi_per_three_integer_division() -> None:
    assert exact_bps(_row(clearances_blocks_interceptions=2), BPS) == 0
    assert exact_bps(_row(clearances_blocks_interceptions=3), BPS) == 1
    assert exact_bps(_row(clearances_blocks_interceptions=8), BPS) == 2


def test_exact_cbi_null_is_not_zero_and_never_crashes() -> None:
    # A NULL CBI contributes nothing (unmeasured), distinct from a measured 0.
    assert (
        exact_bps(_row(clearances_blocks_interceptions=None, goals_scored=1, position="MID"), BPS)
        == 18
    )
    assert (
        exact_bps(_row(clearances_blocks_interceptions=0, goals_scored=1, position="MID"), BPS)
        == 18
    )


def test_exact_penalty_save() -> None:
    assert exact_bps(_row(position="GK", penalties_saved=1), BPS) == 7


def test_exact_combines_components() -> None:
    row = _row(
        position="DEF",
        goals_scored=1,
        assists=1,
        clean_sheets=1,
        minutes=90,
        clearances_blocks_interceptions=6,
    )
    # 12 (goal) + 9 (assist) + 12 (clean sheet) + 2 (CBI 6/3) = 35
    assert exact_bps(row, BPS) == 35


# --------------------------------------------------------------------------------------
# Tie-break award (exhaustive on the documented cases)
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([50, 40, 30], [3, 2, 1]),
        ([50, 50, 30, 20], [3, 3, 1, 0]),  # tie for 1st -> 3,3, next gets 1 (2 skipped)
        ([50, 30, 30, 20], [3, 2, 2, 0]),  # tie for 2nd -> 3,2,2, no 1
        ([50, 40, 30, 30], [3, 2, 1, 1]),  # tie for 3rd -> 3,2,1,1
        ([30, 30, 30, 10], [3, 3, 3, 0]),  # three-way tie for 1st
        ([30, 30, 30, 30], [3, 3, 3, 3]),  # four-way tie for 1st -> all 3
        ([10], [3]),  # single player wins
        ([], []),  # empty
        ([5, 5], [3, 3]),  # two-way tie, both win
    ],
)
def test_award_bonus_cases(values: list[float], expected: list[int]) -> None:
    assert award_bonus(values) == expected


def test_award_bonus_only_depends_on_strictly_greater_count() -> None:
    # 50 -> 3 (0 greater); 40 -> 2 (1 greater); the two 30s -> 1 (2 greater); 20 -> 0 (4 greater).
    assert award_bonus([50, 40, 30, 30, 20]) == [3, 2, 1, 1, 0]
    # Reordering the same multiset yields the same award per value.
    assert award_bonus([20, 30, 50, 30, 40]) == [0, 1, 3, 1, 2]


def test_award_matches_bisect_fast_path_property() -> None:
    """The simulator's inline bisect award must equal award_bonus on random integer draws."""
    import bisect

    rng = random.Random(7)
    for _ in range(500):
        n = rng.randint(1, 12)
        values = [rng.randint(-5, 40) for _ in range(n)]
        reference = award_bonus(values)
        ordered = sorted(values)
        fast = []
        for value in values:
            greater = n - bisect.bisect_right(ordered, value)
            fast.append((3, 2, 1)[greater] if greater < 3 else 0)
        assert fast == reference


# --------------------------------------------------------------------------------------
# Residual model: NULL-safety, determinism, incremental == batch
# --------------------------------------------------------------------------------------


def _training_rows(n: int, seed: int = 0) -> list[PlayerRow]:
    rng = random.Random(seed)
    rows: list[PlayerRow] = []
    for i in range(n):
        position = ("GK", "DEF", "MID", "FWD")[i % 4]
        rows.append(
            _row(
                code=100 + (i % 17),
                position=position,
                minutes=90 if i % 5 else 0,
                goals_scored=1 if i % 11 == 0 else 0,
                clearances_blocks_interceptions=None if i % 3 == 0 else (i % 9),
                influence=rng.uniform(0, 80),
                creativity=rng.uniform(0, 60),
                bps=rng.randint(-3, 60),
                bonus=0,
                order_key=(float(i), "2024-25", i),
            )
        )
    return rows


def test_fit_residual_model_null_safe_and_predicts() -> None:
    rows = _training_rows(120)
    model = fit_residual_model(
        rows,
        BPS,
        prior_strength=10.0,
        trailing_window=10,
        ridge_lambda=1.0,
        sigma_floor=2.0,
        sd_floor=1e-6,
        minimum_position_rows=5,
    )
    prediction = model.predict_mean(_row(position="MID", influence=30.0, creativity=20.0))
    assert isinstance(prediction, float)
    assert model.sigma("MID") >= 2.0


def test_incremental_positional_equals_batch() -> None:
    rng = random.Random(3)
    residuals = [rng.gauss(4, 5) for _ in range(300)]
    influences = [rng.gauss(25, 10) for _ in range(300)]
    creativities = [rng.gauss(18, 7) for _ in range(300)]
    batch = _fit_positional(
        residuals, influences, creativities, ridge_lambda=1.0, sigma_floor=2.0, sd_floor=1e-6
    )
    acc = PositionAccumulator()
    for residual, influence, creativity in zip(residuals, influences, creativities, strict=True):
        acc.add(residual, influence, creativity)
    incremental = positional_from_accumulator(acc, ridge_lambda=1.0, sigma_floor=2.0, sd_floor=1e-6)
    for attribute in (
        "mean",
        "beta_influence",
        "beta_creativity",
        "sigma",
        "influence_sd",
        "creativity_sd",
    ):
        assert getattr(batch, attribute) == pytest.approx(getattr(incremental, attribute), abs=1e-9)


def _model_from_rows(rows: list[PlayerRow]) -> ResidualModel:
    return fit_residual_model(
        rows,
        BPS,
        prior_strength=10.0,
        trailing_window=10,
        ridge_lambda=1.0,
        sigma_floor=2.0,
        sd_floor=1e-6,
        minimum_position_rows=5,
    )


def test_simulation_is_deterministic() -> None:
    model = _model_from_rows(_training_rows(120))
    fixture = [
        _row(code=1, position="FWD", goals_scored=3, bps=90, bonus=3, influence=90, minutes=90),
        _row(code=2, position="MID", assists=1, bps=30, bonus=2, influence=40, minutes=90),
        _row(code=3, position="DEF", clean_sheets=1, bps=28, bonus=1, influence=25, minutes=90),
        _row(code=4, position="GK", clean_sheets=1, bps=20, bonus=0, influence=18, minutes=90),
    ]
    config = BpsSimConfig(monte_carlo_draws=200)
    first = simulate_fixture_bonus(fixture, model, BPS, config, fixture_seed=42)
    second = simulate_fixture_bonus(fixture, model, BPS, config, fixture_seed=42)
    assert [p.distribution for p in first.predictions] == [
        p.distribution for p in second.predictions
    ]
    # The hat-trick forward with a huge exact part almost always wins the 3 bonus.
    forward = next(p for p in first.predictions if p.code == 1)
    assert forward.distribution[3] > 0.8


def test_simulation_empty_and_single_player_fixtures() -> None:
    model = _model_from_rows(_training_rows(120))
    config = BpsSimConfig(monte_carlo_draws=50)
    # All players benched: no appeared row -> no predictions.
    benched = [_row(code=1, minutes=0), _row(code=2, minutes=0)]
    assert simulate_fixture_bonus(benched, model, BPS, config, fixture_seed=1).predictions == []
    # A single appeared player always wins the 3-point bonus.
    single = simulate_fixture_bonus(
        [_row(code=9, minutes=90, bps=10)], model, BPS, config, fixture_seed=1
    )
    assert len(single.predictions) == 1
    assert single.predictions[0].distribution[3] == 1.0


def test_probabilities_are_proper_distributions() -> None:
    model = _model_from_rows(_training_rows(120))
    config = BpsSimConfig(monte_carlo_draws=100)
    fixture = [_row(code=i, minutes=90, bps=10 + i, influence=10.0 * i) for i in range(1, 6)]
    simulation = simulate_fixture_bonus(fixture, model, BPS, config, fixture_seed=5)
    for prediction in simulation.predictions:
        assert sum(prediction.distribution) == pytest.approx(1.0)
        assert all(0.0 <= p <= 1.0 for p in prediction.distribution)


# --------------------------------------------------------------------------------------
# Bonus metrics
# --------------------------------------------------------------------------------------


def test_bonus_metrics_perfect_assignment() -> None:
    # Predictions that place all expected bonus exactly on the true recipients.
    records = [
        BonusRecord("2025-26", 1, 1, "FWD", (0.0, 0.0, 0.0, 1.0), 3.0, 3),
        BonusRecord("2025-26", 1, 2, "MID", (0.0, 0.0, 1.0, 0.0), 2.0, 2),
        BonusRecord("2025-26", 1, 3, "DEF", (0.0, 1.0, 0.0, 0.0), 1.0, 1),
        BonusRecord("2025-26", 1, 4, "GK", (1.0, 0.0, 0.0, 0.0), 0.0, 0),
    ]
    report = score_bonus_predictions(records, label="overall", seed=1)
    assert report.predictions == 4
    assert report.fixtures == 1
    assert report.bonus_points_correctly_assigned == pytest.approx(1.0)
    assert report.bonus_points_correctly_assigned_hard == pytest.approx(1.0)
    assert report.top1_hit_rate == pytest.approx(1.0)
    assert report.top3_overlap_rate == pytest.approx(1.0)
    assert report.exact_podium_rate == pytest.approx(1.0)
    assert report.total_realised_bonus == pytest.approx(6.0)


def test_bonus_metrics_wrong_assignment_scores_low() -> None:
    records = [
        BonusRecord("2025-26", 1, 1, "FWD", (1.0, 0.0, 0.0, 0.0), 0.0, 3),
        BonusRecord("2025-26", 1, 2, "MID", (0.0, 0.0, 0.0, 1.0), 3.0, 0),
        BonusRecord("2025-26", 1, 3, "DEF", (0.0, 0.0, 1.0, 0.0), 2.0, 2),
        BonusRecord("2025-26", 1, 4, "GK", (0.0, 1.0, 0.0, 0.0), 1.0, 1),
    ]
    report = score_bonus_predictions(records, label="overall", seed=1)
    # The 3-point winner was given no expected bonus; assignment accuracy is well below 1.
    assert report.bonus_points_correctly_assigned < 0.6
    assert report.top1_hit_rate == pytest.approx(0.0)


def test_bonus_metrics_empty() -> None:
    report = score_bonus_predictions([], label="overall", seed=1)
    assert report.predictions == 0
    assert report.bonus_points_correctly_assigned == 0.0


# --------------------------------------------------------------------------------------
# Config bps block
# --------------------------------------------------------------------------------------


def test_bps_config_values_and_provenance() -> None:
    assert BPS.goals["FWD"] == 24  # type: ignore[index]
    assert BPS.goals["MID"] == 18  # type: ignore[index]
    assert BPS.goals["DEF"] == 12  # type: ignore[index]
    assert BPS.goals["GK"] == 12  # type: ignore[index]
    assert BPS.assists == 9
    assert BPS.penalties_saved == 7
    assert BPS.clearances_blocks_interceptions.points == 1
    assert BPS.clearances_blocks_interceptions.unit == 3
    from fpl.types import Position

    assert set(BPS.clean_sheets.points) == {Position.GK, Position.DEF}  # type: ignore[union-attr]
    # Verified paths are cited; residual gaps are recorded.
    confirmed = BPS.verification.confirmed_paths()
    assert "goals.FWD" in confirmed
    assert "penalties_saved" in confirmed
    assert BPS.verification.residual_gaps


def test_bps_clean_sheet_rejects_mid_fwd() -> None:
    with pytest.raises(ValidationError):
        BpsRules.model_validate(
            {
                "goals": {"GK": 12, "DEF": 12, "MID": 18, "FWD": 24},
                "penalty_goal": 12,
                "assists": 9,
                "clean_sheets": {"points": {"MID": 1}},
                "penalties_saved": 7,
                "clearances_blocks_interceptions": {"points": 1, "unit": 3},
            }
        )


def test_bps_source_requires_official_host() -> None:
    with pytest.raises(ValidationError):
        BpsSource.model_validate(
            {
                "source_id": "x",
                "title": "t",
                "url": "https://example.com/bps",
                "confirmed": ["assists"],
                "capture_status": "byte_captured",
            }
        )
