"""Synthetic-only contract, provenance and reciprocal-goal scoring checks."""

from __future__ import annotations

import ast
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest
import yaml

from fpl.config import repo_root
from fpl.features.pit import AsOf, FeatureSource, PointInTimeView
from fpl.validate import dev_v2_tactical_matchup as runner
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow
from fpl.validate.metrics import poisson_pmf
from fpl.validate.tactical_state import RetrospectiveTacticalBackfillView

START = datetime(2023, 8, 12, 12, tzinfo=UTC)


def _contract():
    return runner.load_contract(repo_root() / runner.CONFIG)


def _rows():
    rows = []
    for season, gw in (("2023-24", 1), ("2025-26", 7)):
        for team, opponent, home, goals, allowed in ((3, 1, True, 2, 0), (1, 3, False, 0, 2)):
            old = (0.2, 0.3, 0.5) if home else (0.7, 0.2, 0.1)
            new = (0.25, 0.35, 0.4) if home else (0.6, 0.25, 0.15)
            rows.append(
                {
                    "key": f"{season}:10:{team}",
                    "season": season,
                    "gw": gw,
                    "fixture": 10,
                    "team_code": team,
                    "opponent_team_code": opponent,
                    "was_home": home,
                    "observed_goals": goals,
                    "goals_allowed": allowed,
                    "as_of": START.replace(year=int(season[:4])).isoformat(),
                    "distributions": {
                        arm: (*(old if arm == "incumbent" else new), *([0.0] * 8))
                        for arm in runner.MODEL_LABELS
                    },
                    "state_cold_start": home,
                    "high_confidence": not home,
                    "style_error_risk": "unknown" if home else "low",
                    "actual_state": (0.5,) * 5,
                    "predicted_state": (0.4,) * 5,
                    "persistence_prediction": (0.2,) * 5,
                    "prior_style_target_sd": (2.0,) * 5,
                    "style_venue_contribution": (0.03,) * 5,
                    "style_opponent_contribution": (0.05,) * 5,
                }
            )
    runner.attach_reciprocal_and_slices(rows, {"2023-24": frozenset({3})})
    return rows


def _run(rows=None):
    return {
        "rows": _rows() if rows is None else rows,
        "folds": [{"chosen_penalty": None}, {"chosen_penalty": 10.0}],
        "history_rows": [],
        "historical_folds": [],
    }


def _tiny_contract():
    # Pure synthetic scorer only: the formal loader still enforces 1,520 rows / 76 folds.
    return _contract().model_copy(update={"expected_rows": 4, "expected_folds": 2})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("candidate", "renamed_after_scoring"),
        ("incumbent", "retrospective_goals_xg_weekly_inner_selection_v1"),
        ("evidence_class", "strict_prospective"),
        ("eligible_seasons", ["2023-24", "2024-25", "2025-26"]),
        ("expected_rows", 2280),
        ("formal_runs", 2),
        ("require_clean_worktree", False),
        ("promotion_permitted", True),
        ("allow_dirty", True),
        ("recent_weights", [1, 1, 1, 1, 1]),
        ("shrinkage_matches", 1),
        ("goal_penalties", [0.1, 1, 10, None]),
        ("style_ridge_penalty", 0.5),
        ("minimum_log_lift", 0.009),
        ("minimum_cs_brier_lift", 0.009),
        ("maximum_goals", 15),
        ("rate_floor", 0.001),
        ("season_carryover", "future_season_average"),
        ("provider_fields", ["expectedGoals"]),
        ("interactions", ["all_pairwise"]),
    ],
)
def test_loader_rejects_changes_to_frozen_procedure(tmp_path, field, value):
    data = _contract().model_dump()
    data[field] = value
    path = tmp_path / "changed.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match=field):
        runner.load_contract(path)


def test_formal_dirty_worktree_refused_before_database_or_any_fit(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.scoring, "_git", lambda *args: " M AGENTS.md")

    def forbidden(*args, **kwargs):
        pytest.fail("a dirty formal worktree reached data access or fitting")

    monkeypatch.setattr(runner, "connect", forbidden)
    monkeypatch.setattr(runner, "reproduce_incumbent", forbidden)
    with pytest.raises(runner.scoring.RetrospectiveEvaluationError, match="dirty worktree"):
        runner.run_formal(tmp_path, tmp_path / "absent.duckdb")
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("existing", ["claim", "result"])
def test_formal_prior_claim_or_result_refuses_before_fitting(monkeypatch, tmp_path, existing):
    monkeypatch.setattr(runner.scoring, "require_clean_worktree", lambda root: None)
    path = (
        tmp_path / "data" / "evaluation-claims" / f"{runner.CANDIDATE}.json"
        if existing == "claim"
        else tmp_path / runner.RESULT
    )
    path.parent.mkdir(parents=True)
    path.write_text("retained original", encoding="utf-8")
    with pytest.raises(FileExistsError, match="no second run"):
        runner.run_formal(tmp_path, tmp_path / "absent.duckdb")
    assert path.read_text() == "retained original"


def test_formal_database_wal_refused_before_fitting(monkeypatch, tmp_path):
    monkeypatch.setattr(runner.scoring, "require_clean_worktree", lambda root: None)
    db = tmp_path / "research.duckdb"
    db.write_bytes(b"synthetic-not-a-database")
    db.with_suffix(".duckdb.wal").write_bytes(b"unresolved writer")
    with pytest.raises(RuntimeError, match="without a WAL"):
        runner.run_formal(tmp_path, db)


def test_durable_claim_is_exclusive_and_retains_original_provenance(tmp_path):
    provenance = {"git_head": "first", "config_sha256": "config", "database_sha256": "db"}
    path = runner.reserve_claim(tmp_path, provenance)
    original = path.read_bytes()
    assert json.loads(original)["candidate"] == runner.CANDIDATE
    with pytest.raises(FileExistsError):
        runner.reserve_claim(tmp_path, {**provenance, "git_head": "second"})
    assert path.read_bytes() == original


def test_result_publication_is_atomic_and_never_clobbers(tmp_path):
    path = tmp_path / "result.json"
    runner._publish_result(path, {"verdict": "INCONCLUSIVE", "rows": [1, 2]})
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        runner._publish_result(path, {"verdict": "SUPPORTED"})
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_clean_sheet_is_opponent_zero_mass_not_own_zero_mass():
    home, away = _rows()[:2]
    assert home["clean_sheet_probabilities"]["incumbent"] == 0.7
    assert away["clean_sheet_probabilities"]["incumbent"] == 0.2
    assert home["clean_sheet_brier_losses"]["incumbent"] == pytest.approx(0.09)
    assert away["clean_sheet_brier_losses"]["incumbent"] == pytest.approx(0.04)
    assert home["clean_sheet_brier_losses"]["candidate"] == pytest.approx(0.16)
    assert away["clean_sheet_brier_losses"]["candidate"] == pytest.approx(0.0625)


def test_home_away_and_promoted_slices_use_defending_club_context():
    result = runner.score_experiment(_run(), _tiny_contract())
    slices = result["by_slice"]
    assert slices["home"]["incumbent"]["clean_sheet_brier"] == pytest.approx(0.09)
    assert slices["away"]["incumbent"]["clean_sheet_brier"] == pytest.approx(0.04)
    assert slices["promoted"]["incumbent"]["clean_sheet_brier"] == pytest.approx(0.09)
    assert result["overall"]["incumbent"]["clean_sheet_brier"] == pytest.approx(0.065)
    assert {"GW1-6", "GW7+", "confidence_high", "confidence_low", "cold_start"} <= slices.keys()
    assert result["fixture_predictions"] == _rows()
    assert result["development_only"] is True
    assert result["promotion_permitted"] is False


@pytest.mark.parametrize(
    ("field", "value"),
    [("was_home", True), ("goals_allowed", 9), ("as_of", "later"), ("gw", 35)],
)
def test_reciprocal_side_contradictions_fail_closed(field, value):
    rows = _rows()
    rows[1][field] = value
    with pytest.raises(ValueError, match="contradiction"):
        runner.attach_reciprocal_and_slices(rows, {})


@pytest.mark.parametrize(
    "fault", ["duplicate", "missing", "mass", "negative", "nonfinite", "support"]
)
def test_fixture_identity_and_goal_pmf_guards(fault):
    rows = _rows()
    if fault == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif fault == "missing":
        rows.pop(1)
    else:
        pmf = list(rows[0]["distributions"]["candidate"])
        if fault == "mass":
            pmf[0] += 0.1
        elif fault == "negative":
            pmf[-1] = -0.1
        elif fault == "nonfinite":
            pmf[-1] = float("nan")
        else:
            pmf.append(0.0)
        rows[0]["distributions"]["candidate"] = tuple(pmf)
    with pytest.raises(ValueError, match=r"duplicate|reciprocal|distribution|mass|negative|finite"):
        runner.attach_reciprocal_and_slices(rows, {})


def test_style_standardized_mse_uses_retained_prior_only_scale():
    report = runner._styles(_rows())
    for dimension in runner.DIMENSIONS:
        block = report[dimension]
        assert block["forecaster"]["mse"] == pytest.approx(0.01)
        assert block["forecaster"]["standardized_mse"] == pytest.approx(0.0025)
        assert block["forecaster"]["standardized_rows"] == 4
        assert block["persistence"]["mse"] == pytest.approx(0.09)


@pytest.mark.parametrize(
    ("log_lift", "cs_lift", "style_lift", "verdict"),
    [
        (0.02, 0.02, 0.1, "SUPPORTED"),
        (0.01, 0.01, 0.1, "SUPPORTED"),
        (0.02, 0.009, 0.1, "INCONCLUSIVE"),
        (0.009, 0.02, 0.1, "INCONCLUSIVE"),
        (0.009, 0.009, 0.1, "INCONCLUSIVE"),
        (-0.02, 0.02, 0.1, "REFUTED"),
        (0.02, -0.02, 0.1, "REFUTED"),
        (0.02, 0.02, 0.0, "REFUTED"),
    ],
)
def test_both_materiality_gates_and_style_hypothesis_are_required(
    monkeypatch, log_lift, cs_lift, style_lift, verdict
):
    def scores(rows, *, seed):
        return {
            arm: {
                "mean_log_score": 1 - (log_lift if arm == "candidate" else 0),
                "clean_sheet_brier": 1 - (cs_lift if arm == "candidate" else 0),
                "crps": 0.49 if arm == "candidate" else 0.5,
                "pit_interval_80_absolute_error": 0.01,
            }
            for arm in runner.MODEL_LABELS
        }

    monkeypatch.setattr(runner, "_score_rows", scores)
    monkeypatch.setattr(
        runner, "_styles", lambda rows: {"attack_precision": {"relative_mse_lift": style_lift}}
    )
    result = runner.score_experiment(_run(), _tiny_contract())
    assert result["verdict"] == verdict
    assert result["gate_checks"]["goal_log_materiality"] == (log_lift >= 0.01)
    assert result["gate_checks"]["cs_brier_materiality"] == (cs_lift >= 0.01)


def test_clustered_uncertainty_groups_reciprocal_sides_within_gw():
    result = runner._clustered([0.0, 0.0, 2.0, 2.0], _rows())
    assert result["clusters"] == 2
    assert result["paired_mean"] == 1
    assert result["gw_clustered_standard_error"] == 1
    assert result["normal_95_interval"] == pytest.approx([-0.96, 2.96])


def test_incorrect_population_refused_before_score(monkeypatch):
    monkeypatch.setattr(runner, "_score_rows", lambda *args, **kwargs: pytest.fail("scored"))
    with pytest.raises(ValueError, match="population"):
        runner.score_experiment(_run(), _contract())


def _trace():
    before = (START - timedelta(days=1)).isoformat()
    block = {"maximum_training_event": before, "maximum_training_prediction_cutoff": before}
    return {
        "history_rows": [
            {
                "as_of": START.isoformat(),
                "kickoff_time": (START + timedelta(days=2)).isoformat(),
                "maximum_state_source_event": before,
            }
        ],
        "historical_folds": [
            {
                "as_of": START.isoformat(),
                "event_time_violations": 0,
                "same_gameweek_violations": 0,
                "stacking_in_sample_rows": 0,
                "style_fits": {"attack_precision": deepcopy(block)},
                "goal_fits": {"10.0": deepcopy(block)},
                "diagnostic_goal_fits": {"recent": deepcopy(block)},
            }
        ],
    }


def test_independent_trace_accepts_prior_only_fits_and_delayed_target():
    assert runner.verify_temporal_trace(_trace()) == {
        "boundary_checks": 11,
        "fit_blocks": 3,
        "violations": 0,
    }


@pytest.mark.parametrize("fault", ["late_prediction", "target_state", "same_gw", "stacking"])
def test_independent_trace_rejects_target_and_batch_leakage(fault):
    trace = _trace()
    if fault == "late_prediction":
        trace["history_rows"][0]["as_of"] = (START + timedelta(days=3)).isoformat()
    elif fault == "target_state":
        trace["history_rows"][0]["maximum_state_source_event"] = START.isoformat()
    else:
        key = "same_gameweek_violations" if fault == "same_gw" else "stacking_in_sample_rows"
        trace["historical_folds"][0][key] = 1
    with pytest.raises(ValueError, match=r"after target|future event|temporal guard"):
        runner.verify_temporal_trace(trace)


@pytest.mark.parametrize("family", ["style_fits", "goal_fits", "diagnostic_goal_fits"])
@pytest.mark.parametrize("key", ["maximum_training_event", "maximum_training_prediction_cutoff"])
def test_independent_trace_rejects_future_or_in_sample_fit(family, key):
    trace = _trace()
    fit = next(iter(trace["historical_folds"][0][family].values()))
    fit[key] = START.isoformat()
    with pytest.raises(ValueError, match="future/in-sample"):
        runner.verify_temporal_trace(trace)


def _incumbent_fixture(monkeypatch):
    rows = []
    for gw in (1, 2):
        for team, opponent, home, goals, allowed in ((3, 1, True, 2, 0), (1, 3, False, 0, 2)):
            rows.append(
                {
                    "season": "2023-24",
                    "gw": gw,
                    "fixture": gw,
                    "team_code": team,
                    "opponent_team_code": opponent,
                    "was_home": home,
                    "goals": goals,
                    "goals_allowed": allowed,
                    "expected_goals": 1.0,
                    "expected_goals_conceded_measured": 1.0,
                    "kickoff_time": START + timedelta(days=7 * (gw - 1)),
                }
            )
    frame = pl.DataFrame(rows)
    expected = []
    adapters = {}
    for gw in (1, 2):
        cutoff = START + timedelta(days=7 * (gw - 1))
        model = TrailingGoalsAttackDefence()
        model.fit(TrainingWindow(runner.scoring._baseline_frame(frame.filter(pl.col("gw") < gw))))
        target = frame.filter(pl.col("gw") == gw)
        adapters[gw] = {}
        for row, pmf in zip(target.iter_rows(named=True), model.predict(target), strict=True):
            adapters[gw][row["fixture"], row["team_code"]] = pmf
            expected.append(
                {
                    **row,
                    "key": runner.identity(row),
                    "observed_goals": row["goals"],
                    "as_of": cutoff.isoformat(),
                    "distributions": {runner.INCUMBENT: pmf},
                }
            )
    monkeypatch.setattr(runner, "load_team_frame", lambda *args, **kwargs: frame)
    monkeypatch.setattr(
        runner,
        "prospective_team_scored",
        lambda con, **kwargs: (adapters[kwargs["schedule"]["gw"][0]], None),
    )
    contract = _tiny_contract().model_copy(update={"eligible_seasons": ("2023-24",)})
    return contract, {"fixture_predictions": expected}, adapters


def test_exact_incumbent_reproduces_synthetic_reference_and_adapter(monkeypatch):
    contract, reference, _ = _incumbent_fixture(monkeypatch)
    cache, report = runner.reproduce_incumbent(None, contract, reference)
    assert report["rows"] == 4
    assert report["folds"] == 2
    assert report["maximum_absolute_pmf_difference"] == 0.0
    assert report["current_metrics"] == report["reference_metrics"]
    assert set(cache) == {row["key"] for row in reference["fixture_predictions"]}
    for rate, pmf in cache.values():
        assert pmf == poisson_pmf(rate)
    assert report["actual_prospective_adapter_checked"] is True


@pytest.mark.parametrize("fault", ["pmf", "adapter", "identity", "outcome", "cutoff"])
def test_incumbent_reproduction_fails_on_any_changed_reference(monkeypatch, fault):
    contract, reference, adapters = _incumbent_fixture(monkeypatch)
    row = reference["fixture_predictions"][0]
    if fault == "pmf":
        row["distributions"][runner.INCUMBENT] = poisson_pmf(3.0)
    elif fault == "adapter":
        adapters[1][1, 3] = poisson_pmf(3.0)
    elif fault == "identity":
        row["key"] = "2023-24:99:3"
    elif fault == "outcome":
        row["observed_goals"] = 4
    else:
        row["as_of"] = (START + timedelta(minutes=1)).isoformat()
    with pytest.raises(ValueError, match=r"reproduction|population|target/cutoff"):
        runner.reproduce_incumbent(None, contract, reference)


def test_retrospective_tactical_capability_cannot_supply_production_pit():
    retrospective = RetrospectiveTacticalBackfillView(object(), AsOf(START))
    assert not isinstance(retrospective, (FeatureSource, PointInTimeView))
    assert retrospective.evidence_class == "retrospective_backfill_development"
    with pytest.raises(AttributeError):
        PointInTimeView(retrospective, AsOf(START)).observed_team_football()


def test_production_import_graph_has_no_tactical_development_source():
    modules = {"tactical_state", "tactical_math", "tactical_matchup", "dev_v2_tactical_matchup"}
    root = repo_root() / "src" / "fpl"
    violations = []
    for package in ("features", "jobs", "models", "optimize", "publish", "insights"):
        for path in (root / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [node.module or "", *(alias.name for alias in node.names)]
                else:
                    continue
                if any(set(name.split(".")) & modules for name in imports):
                    violations.append(str(path.relative_to(root)))
    assert violations == []


def test_previous_results_remain_byte_identical():
    for name, digest in {
        "v2_real_sot_development.json": (
            "32a3332dd92e30b160a632d6ad68ee268cbfd3367a27340e365583c2e9ca7e7d"
        ),
        "v2_corroborated_zero_sot_development.json": (
            "e8d1a5c0fcce42946d3bf8e798f52e208ac79168c2453e4c0840c1be65c009c5"
        ),
        "v2_weekly_inner_selection_development.json": (
            "79f3a0815271a95cd0e39874aaa20fa89d3b1df0875a5e780c0317a961424d35"
        ),
        "v2_weekly_sot_development.json": (
            "c94cf71a52e926970656733e746d8a0b661c050152647e5de78bde9b0cd8227f"
        ),
    }.items():
        assert hashlib.sha256((repo_root() / "results" / name).read_bytes()).hexdigest() == digest
