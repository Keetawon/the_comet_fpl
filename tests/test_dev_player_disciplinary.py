"""Independent synthetic guards; never load archive data or consume a formal run."""

from __future__ import annotations

import hashlib
import math
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fpl.config import repo_root
from fpl.models.disciplinary_development import (
    NONE,
    DisciplinaryObservation,
    ExposurePooledDisciplinary,
)
from fpl.types import Position
from fpl.validate import dev_player_disciplinary as runner
from fpl.validate import development_program_provenance as claims
from fpl.validate.development_reference_components import (
    ReferenceMinutesRow,
    ValidatedMinutesControlCache,
    ValidatedMinutesControlFold,
)
from fpl.validate.minutes_baselines import TargetRow

NOW = datetime(2025, 9, 12, tzinfo=UTC)


def _history() -> list[DisciplinaryObservation]:
    return [
        DisciplinaryObservation(
            "2025-26",
            2,
            i + 1,
            100 + i,
            position,
            NOW - timedelta(days=8),
            minutes,
            yellow,
            red,
        )
        for i, (position, minutes, yellow, red) in enumerate(
            [
                (Position.DEF, 23, 1, 0),
                (Position.GK, 90, 0, 0),
                (Position.MID, 61, 0, 1),
                (Position.FWD, 89, 0, 0),
                (Position.DEF, 90, 0, 0),
                (Position.MID, 0, 1, 0),
            ]
        )
    ]


@pytest.mark.parametrize("empty", [False, True])
def test_independent_position_control_matches_every_conditional_mass_exactly(empty: bool) -> None:
    history = [] if empty else _history()
    model = ExposurePooledDisciplinary().fit(history, as_of=NOW, excluded_target_gw=("2025-26", 4))
    independently_counted = runner.independent_position_control(history, NOW, ("2025-26", 4))
    for position in Position:
        actual = model.predict(-1, position, position_only=True)
        assert actual == independently_counted[position]
        assert actual.marginal((0.3, 0.2, 0.1, 0.4)) == (
            independently_counted[position].marginal((0.3, 0.2, 0.1, 0.4))
        )


def test_independent_control_rejects_future_same_gw_dgw_and_six_hour_boundary() -> None:
    history = _history()
    added = [
        replace(history[0], fixture=100 + i, kickoff=kickoff, gw=gw)
        for i, (kickoff, gw) in enumerate(
            [
                (NOW - timedelta(days=2), 4),  # earlier target-DGW leg
                (NOW + timedelta(days=7), 4),
                (NOW + timedelta(days=1), 1),  # postponed prior-GW fixture
                (NOW - timedelta(hours=6), 1),
                (NOW - timedelta(minutes=10), 1),
            ]
        )
    ]
    assert runner.independent_position_control(history + added, NOW, ("2025-26", 4)) == (
        runner.independent_position_control(history, NOW, ("2025-26", 4))
    )
    eligible = replace(added[-1], kickoff=NOW - timedelta(hours=6, microseconds=1))
    assert runner.independent_position_control([*history, eligible], NOW, ("2025-26", 4)) != (
        runner.independent_position_control(history, NOW, ("2025-26", 4))
    )


def test_probability_floor_applies_only_to_scoring_not_retained_zero_mass() -> None:
    assert runner.losses(NONE, 2) == {
        "joint_log": -math.log(1e-12),
        "yellow_log": 0.0,
        "yellow_brier": 0.0,
        "red_log": -math.log(1e-12),
        "red_brier": 1.0,
    }
    assert NONE == (1.0, 0.0, 0.0)


@pytest.mark.parametrize("pmf", [(0.8, 0.1, 0.1), (0.4, 0.5, 0.1)])
@pytest.mark.parametrize("state", [0, 1, 2])
def test_scoring_is_hand_computable(pmf: tuple[float, ...], state: int) -> None:
    score = runner.losses(pmf, state)
    assert score["joint_log"] == -math.log(pmf[state])
    assert score["yellow_brier"] == (pmf[1] - (state == 1)) ** 2
    assert score["red_brier"] == (pmf[2] - (state == 2)) ** 2


@pytest.mark.parametrize("pmf", [(0.2, 0.2, 0.2), (1, -0.1, 0.1), (1, 0), (math.nan, 0, 1)])
def test_invalid_scored_mass_fails(pmf: tuple[float, ...]) -> None:
    with pytest.raises(ValueError, match="invalid"):
        runner.losses(pmf, 1)


def test_average_precision_ties_have_no_incidental_row_order_resolution() -> None:
    assert runner.average_precision([0.9, 0.9, 0.1], [1, 0, 1]) == pytest.approx(7 / 12)
    assert runner.average_precision([0.1, 0.9, 0.9], [1, 0, 1]) == pytest.approx(7 / 12)
    assert runner.average_precision([0.5, 0.5, 0.5], [1, 0, 0]) == pytest.approx(1 / 3)
    assert runner.average_precision([0.1, 0.9], [0, 0]) is None


def _scored_rows() -> list[dict]:
    # 822 entirely synthetic rows: 821 direct-proxy and one non-proxy row.
    return [
        {
            "season": ("2023-24", "2024-25", "2025-26")[i // 274],
            "gw": 1 if i % 2 else 8,
            "position": "DEF",
            "was_home": bool(i % 2),
            "price_proxy_dependent": i < 821,
            "cold_start": i < 821,
            "minutes_observed": 0 if i == 0 else 90,
            "observed_bin": 0 if i == 0 else 3,
            "outcome": i % 2,
            "incumbent_zero": NONE,
            "position_control": (0.65, 0.35, 0),
            "candidate": (0.5, 0.5, 0),
            "maximum_source_kickoff": (NOW - timedelta(days=7)).isoformat(),
            "as_of": NOW.isoformat(),
        }
        for i in range(822)
    ]


def test_synthetic_gate_uses_both_controls_and_retains_proxy_exclusion_as_diagnostic() -> None:
    config = runner.load_contract(repo_root())
    config["expected_rows"] = 822
    rows = _scored_rows()
    result = runner.summarise(rows, config)
    assert result["verdict"] == "SUPPORTED"
    assert all(result["gates"].values())
    assert result["promotion_permitted"] is False
    assert result["slices"]["direct_price_proxy"]["rows"] == 821
    assert result["slices"]["non_proxy"]["rows"] == 1
    assert result["slices"]["overall"]["rows"] == 822
    assert result["proxy_exclusion_changes_primary_population"] is False
    for tag in ("GW1-6", "GW7+", "cold_start", "established", "actual_zero_minutes", "appeared"):
        assert tag in result["slices"]
    unchanged = [{**r, "candidate": r["position_control"]} for r in rows]
    assert runner.summarise(unchanged, config)["verdict"] == "INCONCLUSIVE"
    rows[0]["maximum_source_kickoff"] = (NOW - timedelta(hours=6)).isoformat()
    assert runner.summarise(rows, config)["gates"]["zero_leakage"] is False


def test_paired_uncertainty_groups_season_qualified_gws_not_individual_rows() -> None:
    report = runner.score_rows(_scored_rows())
    paired = report["paired_joint_loss"]["position_control"]
    assert paired["clusters"] == 6
    assert paired["negative_favours"] == runner.NAME
    assert paired["serial_dependence_adjusted"] is False
    assert paired["gw_clustered_standard_error"] > 0


def test_real_contract_pins_are_exact_bytes_and_git_preserves_them() -> None:
    root = repo_root()
    body = (root / runner.CONFIG).read_bytes()
    assert hashlib.sha256(body).hexdigest() == runner.CONFIG_SHA256
    config = runner.load_contract(root)
    assert config["source_completion_margin_hours"] == 6
    assert config["expected_rows"] == 86755
    assert config["expected_folds"] == 114
    assert config["expected_direct_price_proxy_rows"] == 821
    assert config["promotion_permitted"] is False
    assert config["formal_runs"] == 1
    attrs = subprocess.check_output(
        ["git", "check-attr", "text", "--", runner.CONFIG, runner.AUDIT], cwd=root, text=True
    ).splitlines()
    assert len(attrs) == 2 and all(line.endswith(": text: unset") for line in attrs)


def test_config_byte_mutation_fails_before_parsing(tmp_path: Path) -> None:
    path = tmp_path / runner.CONFIG
    path.parent.mkdir()
    path.write_bytes((repo_root() / runner.CONFIG).read_bytes() + b"\n")
    with pytest.raises(ValueError, match="bytes changed"):
        runner.load_contract(tmp_path)


def test_dirty_worktree_is_refused_before_database_or_cache_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dirty(_: Path) -> str:
        raise ValueError("synthetic dirty worktree")

    monkeypatch.setattr(runner, "git_clean_head", dirty)
    with pytest.raises(ValueError, match="dirty worktree"):
        runner.snapshot(tmp_path, tmp_path / "absent.duckdb")


def test_existing_output_refused_before_snapshot_or_claim(tmp_path: Path) -> None:
    existing = tmp_path / "external"
    existing.mkdir()
    with pytest.raises(ValueError, match="no overwrite"):
        runner.run(
            root=tmp_path / "repo", db=tmp_path / "missing", minutes_cache=tmp_path, output=existing
        )


def test_population_rejects_missing_or_changed_identity_before_scoring() -> None:
    observed = _history()[0]
    target = TargetRow(
        observed.season, 4, observed.fixture, NOW, observed.code, Position.DEF, 1, 2, True
    )
    cached = ReferenceMinutesRow(target, 3, (0, 0, 0, 1), False, False, "{}")
    fold = ValidatedMinutesControlFold(
        target.season, 4, NOW, (cached,), "db", "manifest", "fold", "{}"
    )
    cache = ValidatedMinutesControlCache((fold,), "{}")
    with pytest.raises(ValueError, match="identity/coverage"):
        runner.validate_population(cache, [observed])
    with pytest.raises(ValueError, match="population differs"):
        runner.validate_population(cache, [])
    current = replace(observed, gw=4, kickoff=NOW)
    with pytest.raises(ValueError, match="counts differ"):
        runner.validate_population(cache, [current])


def test_claim_is_exclusive_across_two_linked_worktrees(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    common = tmp_path / "shared-git"
    common.mkdir()
    roots = [tmp_path / "worktree-one", tmp_path / "worktree-two"]
    for root in roots:
        root.mkdir()
    monkeypatch.setattr(claims.subprocess, "check_output", lambda *a, **k: str(common))
    path = runner.reserve_claim(roots[0], {"synthetic": True})
    before = path.read_bytes()
    assert path.parent == common / "development-evaluation-claims"
    with pytest.raises(FileExistsError):
        runner.reserve_claim(roots[1], {"synthetic": "second output cannot bypass claim"})
    assert path.read_bytes() == before


def test_legacy_claim_is_not_overridden_by_new_shared_location(tmp_path: Path) -> None:
    path = tmp_path / "data" / "evaluation-claims" / f"{runner.NAME}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"frozen original claim")
    with pytest.raises(FileExistsError, match="remain frozen"):
        runner.reserve_claim(tmp_path, {"synthetic": True})
    assert path.read_bytes() == b"frozen original claim"


def test_claim_candidate_cannot_escape_shared_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="safe filename"):
        claims.reserve_program_claim(tmp_path, "../different", {})
