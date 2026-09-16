"""Synthetic runner/preregistration checks; no real archived candidate predictions."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from contextlib import nullcontext
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from fpl.config import repo_root
from fpl.models.defensive_environment_v3 import DcPlayerObservation, DcTeamObservation
from fpl.types import Position
from fpl.validate import dev_dc_predicted_environment as runner
from fpl.validate.development_reference_components import (
    ReferenceMinutesRow,
    ValidatedMinutesControlCache,
    ValidatedMinutesControlFold,
)
from fpl.validate.minutes_baselines import TargetRow

NOW = datetime(2025, 10, 10, tzinfo=UTC)


def _fixture(gw: int, cutoff: datetime):
    observations, teams, cached = [], [], []
    for code, club, opponent, hit in ((100, 10, 20, 20), (101, 20, 10, 0)):
        observations.append(
            DcPlayerObservation("2025-26", gw, gw, cutoff, code, club, Position.DEF, 90, hit)
        )
        teams.append(DcTeamObservation("2025-26", gw, gw, cutoff, club, 100))
        target = TargetRow(
            "2025-26", gw, gw, cutoff, code, Position.DEF, club, opponent, club == 10
        )
        cached.append(ReferenceMinutesRow(target, club, (0.1, 0.2, 0.3, 0.4), False, False, "{}"))
    fold = ValidatedMinutesControlFold(
        "2025-26", gw, cutoff, tuple(cached), "db", "manifest", "fold", "{}"
    )
    return observations, teams, fold


def test_contract_exact_policy_pins_and_no_frozen_variance_constant():
    root = repo_root()
    config = runner.load_contract(root)
    assert config["primary_rows"] == 7859
    assert config["outer_folds"] == 28
    assert config["transferred_rows"] == 307
    assert config["primary_price_proxy_rows"] == 12
    assert config["all_outfield_price_proxy_rows"] == 74
    assert config["shared_minutes_all_proxy_rows"] == 821
    assert config["dispersion_minimum_rows"] == 200
    assert config["dispersion_prior_rows"] == 100
    assert config["formal_runs"] == 1
    assert config["promotion_permitted"] is False
    assert config["hyperparameter_grid"] == "none_fixed_single_setting"
    assert config["minimum_relative_log_lift"] == 0.01
    assert hashlib.sha256((root / runner.CONFIG).read_bytes()).hexdigest() == runner.CONFIG_SHA256
    assert hashlib.sha256((root / runner.AUDIT).read_bytes()).hexdigest() == runner.AUDIT_SHA256
    attrs = subprocess.check_output(
        ["git", "check-attr", "text", "--", runner.CONFIG, runner.AUDIT], cwd=root, text=True
    ).splitlines()
    assert len(attrs) == 2
    assert all(a.endswith(": text: unset") for a in attrs)


def test_any_preregistered_byte_change_fails_closed(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / runner.CONFIG).write_bytes((repo_root() / runner.CONFIG).read_bytes() + b"\n")
    with pytest.raises(ValueError, match="bytes changed"):
        runner.load_contract(tmp_path)


def test_observed_gameweek_coverage_not_numeric_gw_assumption():
    players, _, _ = _fixture(1, NOW - timedelta(days=14))
    prior, _, _ = _fixture(5, NOW - timedelta(days=7))
    _, _, target = _fixture(9, NOW)
    cache = ValidatedMinutesControlCache((target,), "{}")
    config = {"eligible_seasons": ["2025-26"], "minimum_prior_measured_gameweeks": 2}
    assert runner.eligible_folds(cache, [*players, *prior], config) == [target]
    missing = [replace(r, defensive_contribution=None) for r in prior]
    assert runner.eligible_folds(cache, [*players, *missing], config) == []
    late = [replace(r, kickoff=NOW - timedelta(hours=6)) for r in prior]
    assert runner.eligible_folds(cache, [*players, *late], config) == []


def test_primary_cohort_excludes_gk_dnp_and_missing_not_measured_zero():
    players, _, _ = _fixture(1, NOW)
    assert runner.primary(players[0])
    assert runner.primary(replace(players[0], defensive_contribution=0))
    assert not runner.primary(replace(players[0], position=Position.GK))
    assert not runner.primary(replace(players[0], minutes=0))
    assert not runner.primary(replace(players[0], defensive_contribution=None))


def test_exact_current_v1_factory_reproduction_and_current_minutes_untouched():
    prior, _, _ = _fixture(1, NOW - timedelta(days=7))
    _, _, fold = _fixture(2, NOW)
    predictions, report = runner.reproduce_incumbent([fold], prior, {Position.DEF: 10})
    assert predictions["2025-26", 2, 100] == (1 + 5 * 0.5) / 6
    assert predictions["2025-26", 2, 101] == 2.5 / 6
    assert report["maximum_probability_difference"] == 0
    assert report["all_outfield_rows"] == 2
    assert fold.rows[0].minutes == (0.1, 0.2, 0.3, 0.4)


def test_comparator_refuses_actual_current_history_that_would_break_guard():
    prior, _, _ = _fixture(1, NOW - timedelta(minutes=1))
    _, _, fold = _fixture(2, NOW)
    with pytest.raises(ValueError, match="completion/GW"):
        runner.reproduce_incumbent([fold], prior, {Position.DEF: 10})
    same_gw = [replace(r, gw=2, kickoff=NOW - timedelta(days=7)) for r in prior]
    with pytest.raises(ValueError, match="completion/GW"):
        runner.reproduce_incumbent([fold], same_gw, {Position.DEF: 10})


def test_half_credit_auc_ties_and_hand_computable_probability_floor():
    assert runner.auc([0.5, 0.5], [0, 1]) == 0.5
    assert runner.auc([0.9, 0.1], [1, 0]) == 1
    assert runner.auc([0.1, 0.9], [1, 0]) == 0
    assert runner.auc([0.2, 0.4], [0, 0]) is None
    assert runner.binary_scores(0, 1) == (-math.log(1e-12), 1)
    assert runner.binary_scores(0.5, 1) == (-math.log(0.5), 0.25)


@pytest.mark.parametrize(("p", "y"), [(math.nan, 1), (1.1, 1), (-1, 0), (0.1, True), (0.1, 2)])
def test_bad_probability_and_label_fail_before_scoring(p, y):
    with pytest.raises(ValueError, match="invalid binary"):
        runner.binary_scores(p, y)


def _scored_rows():
    return [
        {
            "season": "2025-26",
            "gw": 11 + i,
            "position": "DEF",
            "was_home": bool(i % 2),
            "past_witnessed_transfer": True,
            "price_proxy_dependent": False,
            "cold_start": False,
            "minutes_pmf": [0, 0, 0, 1],
            "primary": True,
            "observed_hit": i % 2,
            "conditional": {"incumbent": 0.4, "poisson": 0.45, "candidate": 0.5},
            "unconditional": {"incumbent": 0.4, "poisson": 0.45, "candidate": 0.5},
            "maximum_source_kickoff": (NOW - timedelta(days=7)).isoformat(),
            "as_of": NOW.isoformat(),
        }
        for i in range(4)
    ]


def test_primary_gate_uses_current_not_more_convenient_poisson_control():
    config = {"primary_rows": 4, "minimum_relative_log_lift": 0.01}
    rows = _scored_rows()
    result = runner.summarise(rows, config)
    assert result["verdict"] == "SUPPORTED"
    assert result["promotion_permitted"] is False
    assert result["proxy_exclusion_changes_primary_population"] is False
    for row in rows:
        row["conditional"]["poisson"] = 0.001
        row["conditional"]["candidate"] = row["conditional"]["incumbent"]
    assert runner.summarise(rows, config)["verdict"] == "INCONCLUSIVE"


def test_conditional_primary_and_full_roster_unconditional_remain_distinct():
    rows = _scored_rows()
    dnp = {**rows[0], "primary": False, "observed_hit": 0}
    result = runner.summarise([*rows, dnp], {"primary_rows": 4, "minimum_relative_log_lift": 0.01})
    assert result["slices"]["overall"]["rows"] == 4
    assert result["all_outfield_unconditional_diagnostic"]["rows"] == 5
    assert result["slices"]["overall"]["paired_loss"]["incumbent"]["clusters"] == 4


def test_dirty_and_existing_output_refusal_before_candidate_claim(tmp_path, monkeypatch):
    def dirty(_):
        raise ValueError("synthetic dirty worktree")

    monkeypatch.setattr(runner, "git_clean_head", dirty)
    with pytest.raises(ValueError, match="dirty"):
        runner.snapshot(tmp_path, tmp_path / "missing")
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="no result overwrite"):
        runner.run(
            root=tmp_path / "repo", db=tmp_path / "missing", minutes_cache=tmp_path, output=existing
        )


@pytest.mark.parametrize("cache_changed", [False, True])
def test_synthetic_end_to_end_claim_then_prequential_means_and_count_pmfs(
    tmp_path, monkeypatch, cache_changed
):
    root = tmp_path / "repo"
    root.mkdir()
    output = tmp_path / "result"
    p1, t1, _ = _fixture(1, NOW - timedelta(days=14))
    p2, t2, f2 = _fixture(2, NOW - timedelta(days=7))
    p3, t3, f3 = _fixture(3, NOW)
    cache = ValidatedMinutesControlCache((f2, f3), "{}")
    config = {
        "eligible_seasons": ["2025-26"],
        "minimum_prior_measured_gameweeks": 1,
        "maximum_environment_fits": 38,
        "outer_folds": 2,
        "primary_rows": 4,
        "minimum_relative_log_lift": 0.01,
    }
    monkeypatch.setattr(runner, "snapshot", lambda *a: {"synthetic": True})
    monkeypatch.setattr(runner, "load_contract", lambda *a: config)
    cache_reads = []

    def read_cache(*args, **kwargs):
        cache_reads.append(True)
        if len(cache_reads) == 2 and cache_changed:
            raise ValueError("synthetic changed external minutes fold")
        return cache

    monkeypatch.setattr(runner, "read_minutes_control_cache", read_cache)
    monkeypatch.setattr(runner, "connect", lambda *a, **k: nullcontext(None))
    monkeypatch.setattr(runner, "load_history", lambda *a: ([*p1, *p2, *p3], [*t1, *t2, *t3]))
    monkeypatch.setattr(runner, "verify_population", lambda *a: {"synthetic_rows": 4})
    sequence = []
    original = runner.reproduce_incumbent

    def reproduce(*args):
        sequence.append("incumbent")
        return original(*args)

    monkeypatch.setattr(runner, "reproduce_incumbent", reproduce)

    def claim(*args):
        assert sequence == ["incumbent"]
        sequence.append("claim")
        path = tmp_path / "claimed.json"
        runner.publish_json(path, {"synthetic": True})
        return path

    monkeypatch.setattr(runner, "reserve_program_claim", claim)
    original_model = runner.PredictedDefensiveEnvironment

    class CheckedEnvironment(original_model):
        def fit(self, *a, **k):
            assert "claim" in sequence
            sequence.append("fit")
            return super().fit(*a, **k)

    monkeypatch.setattr(runner, "PredictedDefensiveEnvironment", CheckedEnvironment)
    if cache_changed:
        with pytest.raises(ValueError, match="changed external minutes fold"):
            runner.run(
                root=root, db=tmp_path / "fake.duckdb", minutes_cache=tmp_path, output=output
            )
        assert len(cache_reads) == 2
        assert not (output / "result.json").exists()
        failure = json.loads((output / "failure.json").read_bytes())
        assert failure["claim_preserved"] is True
        assert failure["retry_permitted"] is False
        return
    result = runner.run(
        root=root, db=tmp_path / "fake.duckdb", minutes_cache=tmp_path, output=output
    )
    assert result["completed"] is True
    assert len(cache_reads) == 2
    assert datetime.fromisoformat(result["finished_at_utc"]) >= datetime.fromisoformat(
        result["started_at_utc"]
    )
    assert sequence == ["incumbent", "claim", "fit", "fit"]
    assert len(result["folds"]) == len(result["upstream_folds"]) == 2
    first = json.loads((output / "2025-26-gw02.json").read_bytes())
    second = json.loads((output / "2025-26-gw03.json").read_bytes())
    assert first["dispersion"]["rows"] == 0
    assert second["dispersion"]["rows"] == 2
    for row in second["rows"]:
        assert row["conditional"]["candidate"] == row["conditional"]["poisson"]
        assert row["candidate_count"] == row["poisson_count"]
        assert len(row["candidate_count"]["conditional_count_pmf"]) == 61
        assert row["same_gw_source_rows"] == 0
        assert row["mean"]["maximum_source_kickoff"] == (NOW - timedelta(days=7)).isoformat()
    frozen = (output / "result.json").read_bytes()
    with pytest.raises(ValueError, match="no result overwrite"):
        runner.run(root=root, db=tmp_path / "fake.duckdb", minutes_cache=tmp_path, output=output)
    assert (output / "result.json").read_bytes() == frozen
