"""Synthetic-only numerical amendment integration; never loads the research DB."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from fpl.validate import tactical_matchup as loop
from fpl.validate.tactical_math import fit_poisson_offset
from fpl.validate.tactical_numeric_solver import fit_poisson_offset_stable
from tests.test_tactical_matchup import _cache, _pair


def _observations():
    return [
        row
        for gw in range(1, 12)
        for fixture in range(10)
        for row in _pair(gw, gw * 10 + fixture, teams=(fixture * 2 + 1, fixture * 2 + 2))
    ]


def test_legacy_solver_bytes_and_failed_result_unchanged() -> None:
    root = Path(__file__).resolve().parents[1]
    for name, expected in (
        (
            "src/fpl/validate/tactical_math.py",
            "3aa8ab5907b234321d2a3b38ad0fd9b127af85e74593b5f72647422999898ed4",
        ),
        (
            "results/v2_tactical_matchup_development.json",
            "726e513660045f0e34cce9909d7e8e4ac9c0a3999d8a23630866550159bdd8ed",
        ),
    ):
        # Python sources are checkout-EOL dependent; compare canonical Git LF bytes.
        data = (root / name).read_bytes()
        if name.endswith(".py"):
            data = data.replace(b"\r\n", b"\n")
        assert hashlib.sha256(data).hexdigest() == expected


def test_explicit_legacy_injection_and_checkpoint_leave_output_identical() -> None:
    observations = _observations()
    expected = loop.run_tactical_walk_forward(observations, _cache(observations), ("2023-24",))
    batches = []

    def record(batch):
        batches.append((batch["fold"]["gw"], len(batch["rows"])))
        # Even an ill-behaved logger must not alter the fitting state or output.
        batch["fold"]["goal_fits"].clear()
        batch["rows"][0]["predicted_state"] = (99,) * 5

    actual = loop.run_tactical_walk_forward(
        observations,
        _cache(observations),
        ("2023-24",),
        goal_fitter=fit_poisson_offset,
        checkpoint=record,
    )
    assert actual == expected
    assert batches == [(gw, 20) for gw in range(1, 12)]


def test_numeric_fitter_reaches_primary_and_both_diagnostic_arms(monkeypatch) -> None:
    observations = _observations()
    widths = []

    def fit(x, goals, offsets, penalty):
        widths.append(len(x[0]))
        return fit_poisson_offset_stable(x, goals, offsets, penalty)

    # Force a selected penalty only in this plumbing test, not in the formal runner.
    monkeypatch.setattr(loop, "_selection", lambda prior: (1.0, {}))
    run = loop.run_tactical_walk_forward(
        observations, _cache(observations), ("2023-24",), goal_fitter=fit
    )
    assert 13 in widths and widths.count(10) == 4
    final = run["folds"][-1]
    for fit in [*final["goal_fits"].values(), *final["diagnostic_goal_fits"].values()]:
        assert fit["model"]["solver"] == "poisson_offset_stable_difference_v1"
    keyed = {row["key"]: row for row in run["rows"]}
    for row in run["rows"]:
        opponent = keyed[f"{row['season']}:{row['fixture']}:{row['opponent_team_code']}"]
        for arm, pmf in row["distributions"].items():
            assert sum(pmf) == pytest.approx(1.0)
            assert row["clean_sheet_probabilities"][arm] == opponent["distributions"][arm][0]


def test_amended_fitted_path_preserves_target_isolation_and_future_truncation() -> None:
    observations = _observations()

    def run(rows):
        return loop.run_tactical_walk_forward(
            rows, _cache(rows), ("2023-24",), goal_fitter=fit_poisson_offset_stable
        )

    full = run(observations)
    prefix = run([row for row in observations if row.gw <= 10])
    assert full["history_rows"][:200] == prefix["history_rows"]
    assert full["folds"][:10] == prefix["folds"]
    changed = run(
        [
            replace(row, values=(0.99, 9.0, 0.99, 0.99, -5.0), goals=7, goals_allowed=7)
            if row.gw == 11
            else row
            for row in observations
        ]
    )
    assert full["folds"][-1] == changed["folds"][-1]
    for old, new in zip(full["rows"][-20:], changed["rows"][-20:], strict=True):
        assert old["per_penalty_distributions"] == new["per_penalty_distributions"]
        assert old["predicted_state"] == new["predicted_state"]
        assert old["actual_state"] != new["actual_state"]


def test_fit_failure_retains_exact_layer_batch_and_input_context() -> None:
    observations = _observations()
    completed = []

    def fail(x, goals, offsets, penalty):
        raise ValueError("synthetic numerical failure")

    with pytest.raises(ValueError, match="synthetic numerical failure") as caught:
        loop.run_tactical_walk_forward(
            observations,
            _cache(observations),
            ("2023-24",),
            goal_fitter=fail,
            checkpoint=lambda batch: completed.append(batch["fold"]["gw"]),
        )
    note = caught.value.__notes__[0]
    assert "season=2023-24 gw=10 cutoff=" in note
    assert "kind=goal_x penalty=10.0 rows=160 input_sha256=" in note
    assert completed == list(range(1, 10))
