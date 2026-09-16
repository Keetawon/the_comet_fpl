"""Offline boundary tests; no real archive fit or formal candidate claim."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import polars as pl
import pytest

from fpl.config import repo_root
from fpl.validate import chance_creation as model
from fpl.validate import dev_v2_chance_creation as runner
from fpl.validate.baselines import TrailingGoalsAttackDefence, TrainingWindow
from fpl.validate.metrics import Distribution, poisson_pmf


def _fixture() -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    targets, rows, folds = [], [], []
    start = datetime(2023, 8, 1, tzinfo=UTC)
    for gw in range(1, 4):
        cutoff = start + timedelta(days=7 * gw)
        for team, opponent in ((10, 20), (20, 10)):
            key = f"2023-24:{gw}:{team}"
            row = {
                "key": key,
                "season": "2023-24",
                "gw": gw,
                "fixture": gw,
                "team_code": team,
                "opponent_team_code": opponent,
                "was_home": team == 10,
                "kickoff_time": cutoff.isoformat(),
                "as_of": cutoff.isoformat(),
                "observed_goals": int(team == 10),
                "predicted_state": [0.0] * 5,
                "predicted_opponent_state": [0.0] * 5,
                "maximum_state_source_event": None,
                "maximum_style_training_event": None,
                "incumbent_latent_rate": 1.2,
                "incumbent_pmf": list(poisson_pmf(1.2, max_goals=10)),
                "recent_counts": [gw - 1] * 5,
                "opponent_counts": [gw - 1] * 5,
                "source_capture_id": f"capture-{gw}",
                "source_known_at": "2026-09-04T12:00:00+00:00",
                "payload_sha256": f"sha-{gw}",
                "provider": "pl_sdp",
                "sdp_match_id": 1000 + gw,
                "state_source_keys_sha256": "empty",
                "state_source_rows": 0,
            }
            rows.append(row)
            targets.append(
                {
                    **{
                        k: row[k]
                        for k in (
                            "key",
                            "season",
                            "gw",
                            "fixture",
                            "team_code",
                            "opponent_team_code",
                            "was_home",
                            "kickoff_time",
                            "sdp_match_id",
                            "payload_sha256",
                        )
                    },
                    "goals": row["observed_goals"],
                    "expected_goals": 0.75,
                    "shots": 8,
                    "capture_id": row["source_capture_id"],
                    "source_known_at": row["source_known_at"],
                }
            )
        fits = {
            dimension: {
                "model": None,
                "maximum_training_event": None,
                "maximum_training_prediction_cutoff": None,
            }
            for dimension in runner.DIMENSIONS
        }
        folds.append(
            {
                "season": "2023-24",
                "gw": gw,
                "as_of": cutoff.isoformat(),
                "target_rows": 2,
                "style_fits": fits,
                "maximum_state_source_event": None,
                "maximum_style_training_event": None,
                "event_time_violations": 0,
                "same_gameweek_violations": 0,
                "stacking_in_sample_rows": 0,
                "target_fixture_source_overlap": 0,
            }
        )
    contract = dict(
        runner.load_contract(repo_root()),
        expected_rows=6,
        expected_folds=3,
        maximum_historical_batches=3,
        eligible_seasons=["2023-24"],
    )
    return targets, {"rows": rows, "folds": folds, "provenance": {}}, contract


def _cache(upstream: dict[str, Any]) -> dict[str, Any]:
    return {
        r["key"]: (r["incumbent_latent_rate"], tuple(r["incumbent_pmf"])) for r in upstream["rows"]
    }


def _experiment() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], list[model.ChanceObservation]
]:
    targets, upstream, contract = _fixture()
    observations = runner.make_observations(targets, upstream, _cache(upstream))
    # Six synthetic rows cannot meet the fixed 160-row fitting threshold.
    experiment = model.run_chance_walk_forward(observations, tuple(contract["eligible_seasons"]))
    runner.attach_evidence(experiment, upstream, {"2023-24": frozenset({10})})
    return experiment, upstream, contract, observations


def test_exact_contract_and_module_bindings() -> None:
    contract = runner.load_contract(repo_root())
    assert contract["expected_rows"] == 2280
    assert contract["eligible_seasons"] == ["2023-24", "2024-25", "2025-26"]
    assert contract["minimum_fit_rows"] == model.MINIMUM_FIT_ROWS


def test_unknown_config_parameter_refused(tmp_path: Path) -> None:
    path = tmp_path / runner.CONFIG
    path.parent.mkdir(parents=True)
    path.write_bytes((repo_root() / runner.CONFIG).read_bytes() + b"unlicensed_parameter: true\n")
    with pytest.raises(ValueError, match="preregistration"):
        runner.load_contract(tmp_path)


def test_changed_pure_constant_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(model, "RIDGE", 2.0)
    with pytest.raises(ValueError, match="constant"):
        runner.load_contract(repo_root())


def test_clean_branch_guard(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.scoring, "require_clean_worktree", lambda _: None)
    monkeypatch.setattr(runner.scoring, "_git", lambda *_: "main")
    with pytest.raises(RuntimeError, match="V2 branch"):
        runner._assert_clean(tmp_path)


def test_dirty_guard_not_bypassed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner.scoring, "_git", lambda *_: " M changed.py")
    with pytest.raises(RuntimeError, match="dirty"):
        runner._assert_clean(tmp_path)


def test_missing_database_and_wal_refused(tmp_path: Path) -> None:
    db = tmp_path / "source.duckdb"
    with pytest.raises(ValueError, match="existing"):
        runner._assert_database(db)
    db.write_bytes(b"preserved")
    wal = Path(str(db) + ".wal")
    wal.write_bytes(b"unresolved")
    with pytest.raises(RuntimeError, match="WAL"):
        runner._assert_database(db)
    assert db.read_bytes() == b"preserved"
    assert wal.read_bytes() == b"unresolved"


def test_claim_and_result_are_write_once(tmp_path: Path) -> None:
    runner.reserve_claim(tmp_path, {"head": "synthetic"})
    payload = runner._claim_path(tmp_path).read_bytes()
    with pytest.raises(FileExistsError):
        runner.reserve_claim(tmp_path, {})
    with pytest.raises(FileExistsError, match="consumed"):
        runner._unclaimed(tmp_path)
    assert runner._claim_path(tmp_path).read_bytes() == payload


def test_existing_result_alone_refuses(tmp_path: Path) -> None:
    result = tmp_path / runner.RESULT
    result.parent.mkdir(parents=True)
    result.write_text("prior evidence")
    with pytest.raises(FileExistsError):
        runner._unclaimed(tmp_path)
    assert result.read_text() == "prior evidence"


def test_canonical_coverage_equivalence_does_not_depend_on_key_order() -> None:
    assert runner._canonical({"b": [(1, 2)], "a": 3}) == runner._canonical({"a": 3, "b": [[1, 2]]})
    assert runner._canonical({"x": None}) != runner._canonical({"x": 0})


def test_upstream_projection_cannot_supply_actual_tactics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, upstream, contract = _fixture()
    full_rows = []
    for row in upstream["rows"]:
        full_rows.append(
            {
                **row,
                "distributions": {"incumbent": row["incumbent_pmf"]},
                "actual_state": [999] * 5,
                "raw_corrections": [888] * 5,
                "chosen_penalty": 42,
                "outer_goal_score": -999,
            }
        )
    payload = {
        "completed": True,
        "candidate": "retrospective_tactical_matchup_team_environment_v1_numeric1",
        "provenance": {
            "clean_worktree": True,
            "known_at_rewritten": False,
            "evidence_class": model.EVIDENCE_CLASS,
            "database_sha256": contract["database_sha256"],
            "sdp_version_policy": runner.RetrospectiveBackfillView.VERSION_POLICY,
        },
        "historical_style_predictions": full_rows,
        "historical_fit_provenance": upstream["folds"],
    }
    path = tmp_path / contract["upstream"]
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(runner, "HISTORICAL_ROWS", 6)
    loaded = runner._load_upstream(tmp_path, contract)
    for row in loaded["rows"]:
        assert not {
            "actual_state",
            "raw_corrections",
            "chosen_penalty",
            "outer_goal_score",
        }.intersection(row)
        assert row["predicted_state"] == [0.0] * 5


@pytest.mark.parametrize("field", ["maximum_training_event", "maximum_training_prediction_cutoff"])
def test_upstream_same_target_style_fit_refused(field: str) -> None:
    _, upstream, _ = _fixture()
    runner._verify_upstream_trace(upstream)
    upstream["folds"][0]["style_fits"]["control"][field] = upstream["folds"][0]["as_of"]
    with pytest.raises(ValueError, match=r"future event|in-sample"):
        runner._verify_upstream_trace(upstream)


def test_upstream_same_gw_split_and_dgw_late_cutoff_refused() -> None:
    _, upstream, _ = _fixture()
    upstream["rows"][0]["as_of"] = "2023-08-09T00:00:00+00:00"
    with pytest.raises(ValueError, match="isolation"):
        runner._verify_upstream_trace(upstream)


@pytest.mark.parametrize(
    "field", ["capture_id", "payload_sha256", "sdp_match_id", "source_known_at"]
)
def test_provider_revision_or_known_at_mismatch_refused(field: str) -> None:
    targets, upstream, _ = _fixture()
    targets[0][field] = "2026-09-05T12:00:00+00:00" if field == "source_known_at" else "changed"
    with pytest.raises(ValueError, match=r"revision|known_at"):
        runner.make_observations(targets, upstream, _cache(upstream))


def test_missing_shots_and_xg_stay_missing_and_capture_time_not_rewritten() -> None:
    targets, upstream, _ = _fixture()
    targets[0]["shots"] = targets[0]["expected_goals"] = None
    observations = runner.make_observations(targets, upstream, _cache(upstream))
    assert observations[0].shots is None and observations[0].expected_goals is None
    assert upstream["rows"][0]["source_known_at"].startswith("2026-")
    assert observations[0].as_of.year == 2023


def test_fractional_shots_are_never_rounded() -> None:
    targets, upstream, _ = _fixture()
    targets[0]["shots"] = 1.5
    with pytest.raises(ValueError, match="never rounded"):
        runner.make_observations(targets, upstream, _cache(upstream))


def test_synthetic_fallback_preserves_both_pmf_and_reciprocal_cs() -> None:
    experiment, _, contract, observations = _experiment()
    runner.verify_run(experiment, observations, contract)
    for row in experiment["rows"]:
        assert row["incumbent_fallback"]
        assert row["distributions"]["candidate"] == row["distributions"]["incumbent"]
        assert row["clean_sheet_probabilities"]["candidate"] == poisson_pmf(1.2, max_goals=10)[0]
        assert row["paired_log_loss_difference"] == 0
        assert row["paired_cs_brier_difference"] == 0
    scores = runner.score_experiment(experiment, contract)
    assert scores["relative_log_lift"] == scores["relative_cs_brier_lift"] == 0
    assert scores["verdict"] == "INCONCLUSIVE"
    assert scores["paired_uncertainty"]["log_score"]["gw_clustered_standard_error"] == 0
    assert "season:2023-24" in scores["slices"]


def test_mutated_clean_sheet_or_mass_refused() -> None:
    experiment, upstream, _, _ = _experiment()
    experiment["history_rows"][0]["clean_sheet_probabilities"]["candidate"] = 0.99
    with pytest.raises(ValueError, match="reciprocal PMF"):
        runner.attach_evidence(experiment, upstream, {})


def test_candidate_future_conversion_and_population_refused() -> None:
    experiment, _, contract, observations = _experiment()
    experiment["historical_folds"][0]["conversion_fit"]["maximum_training_event"] = observations[
        0
    ].as_of.isoformat()
    with pytest.raises(ValueError, match="future"):
        runner.verify_run(experiment, observations, contract)
    experiment["rows"].pop()
    with pytest.raises(ValueError, match="population"):
        runner.verify_run(experiment, observations, contract)


def test_diagnostic_trailing_means_are_prior_batch_only() -> None:
    experiment, _, _, _ = _experiment()
    experiment["history_rows"][0]["observed_shots"] = 2
    report = runner.chance_diagnostics(experiment)
    assert experiment["rows"][0]["diagnostic_prior_means"]["shots"] is None
    assert experiment["rows"][2]["diagnostic_prior_means"]["shots"] == 2
    assert report["diagnostic_only"]
    assert report["within_gw_strict_pair_order_reversals"] == 0


def _mock_formal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[str], dict[str, Any]]:
    targets, upstream, contract = _fixture()
    db = tmp_path / "archive.duckdb"
    duckdb.connect(str(db)).close()
    coverage = {
        "eligible_seasons": contract["eligible_seasons"],
        "capture_versions_sha256": "versions",
    }
    audit = tmp_path / contract["coverage_report"]
    audit.parent.mkdir(parents=True)
    database_sha = runner.scoring.file_sha256(db)
    audit.write_text(json.dumps({**coverage, "database_sha256": database_sha}))
    events: list[str] = []
    monkeypatch.setattr(runner, "load_contract", lambda _: contract)
    monkeypatch.setattr(
        runner,
        "_snapshot",
        lambda *_: {
            "head": "synthetic",
            "database_sha256": database_sha,
        },
    )
    monkeypatch.setattr(runner, "build_audit", lambda _: coverage)
    monkeypatch.setattr(runner, "_load_upstream", lambda *_: upstream)
    monkeypatch.setattr(runner, "load_chance_targets", lambda _: targets)
    monkeypatch.setattr(runner, "promoted_team_codes", lambda _: {})

    def reproduce(*_: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        events.append("reproduce")
        predictions = [
            runner.Prediction(
                season=r["season"],
                gw=r["gw"],
                key=r["key"],
                distribution=tuple(r["incumbent_pmf"]),
                observed=r["observed_goals"],
                was_home=r["was_home"],
            )
            for r in upstream["rows"]
        ]
        return _cache(upstream), {
            "synthetic": True,
            "current_metrics": runner.scoring._score_block(
                runner.INCUMBENT, predictions, seed=contract["seed"]
            ),
        }

    monkeypatch.setattr(runner, "reproduce_incumbent", reproduce)
    claim = runner.reserve_claim

    def reserve(*args: Any) -> None:
        events.append("claim")
        claim(*args)

    monkeypatch.setattr(runner, "reserve_claim", reserve)
    return db, events, contract


def test_control_failure_does_not_claim_or_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, events, _ = _mock_formal(tmp_path, monkeypatch)

    def failed(*_: Any) -> Any:
        raise ValueError("incumbent mismatch")

    monkeypatch.setattr(runner, "reproduce_incumbent", failed)
    with pytest.raises(ValueError, match="incumbent mismatch"):
        runner.run(tmp_path, db)
    assert not runner._claim_path(tmp_path).exists()
    assert not (tmp_path / runner.RESULT).exists()
    assert events == []


def test_coverage_mismatch_stops_before_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, events, _ = _mock_formal(tmp_path, monkeypatch)
    monkeypatch.setattr(runner, "build_audit", lambda _: {"changed": True})
    with pytest.raises(ValueError, match="coverage-only"):
        runner.run(tmp_path, db)
    assert events == []


def test_post_claim_numerical_failure_is_retained_and_consumed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, events, _ = _mock_formal(tmp_path, monkeypatch)
    before = runner.scoring.file_sha256(db)

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        events.append("fit")
        raise model.ChanceMeanFitError("synthetic nonconvergence", {"iteration": 40})

    monkeypatch.setattr(model, "run_chance_walk_forward", fail)
    with pytest.raises(model.ChanceMeanFitError):
        runner.run(tmp_path, db)
    assert events == ["reproduce", "claim", "fit"]
    result = json.loads((tmp_path / runner.RESULT).read_bytes())
    assert not result["completed"] and result["candidate_identity_consumed"]
    assert not result["scientific_verdict_available"]
    assert result["failure"]["state"]["iteration"] == 40
    assert runner.scoring.file_sha256(db) == before
    with pytest.raises(FileExistsError):
        runner.run(tmp_path, db)


def test_successful_synthetic_run_readonly_write_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, events, _ = _mock_formal(tmp_path, monkeypatch)
    before = runner.scoring.file_sha256(db)
    original = model.run_chance_walk_forward

    def execute(*args: Any, **kwargs: Any) -> dict[str, Any]:
        events.append("fit")
        return original(*args, **kwargs)

    monkeypatch.setattr(model, "run_chance_walk_forward", execute)
    result = runner.run(tmp_path, db)
    assert events == ["reproduce", "claim", "fit"]
    assert result["completed"] and not result["promotion_permitted"]
    assert len(result["fixture_predictions"]) == 6
    assert len(result["historical_chance_predictions"]) == 6
    assert result["provenance"]["started_at_utc"]
    assert runner.scoring.file_sha256(db) == before
    assert not Path(str(db) + ".wal").exists()
    with pytest.raises(FileExistsError):
        runner.run(tmp_path, db)


def test_provenance_change_after_claim_retains_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db, _, _ = _mock_formal(tmp_path, monkeypatch)
    calls = 0

    def snapshot(*_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "head": "changed" if calls >= 3 else "synthetic",
            "database_sha256": runner.scoring.file_sha256(db),
        }

    monkeypatch.setattr(runner, "_snapshot", snapshot)
    with pytest.raises(RuntimeError, match="provenance changed"):
        runner.run(tmp_path, db)
    result = json.loads((tmp_path / runner.RESULT).read_bytes())
    assert result["artifact_kind"] == "execution_failure"


def test_actual_incumbent_reproduction_checks_every_history_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets, upstream, contract = _fixture()
    frame = pl.DataFrame(
        [
            {
                **r,
                "kickoff_time": runner._timestamp(r["kickoff_time"]),
                "goals_allowed": int(r["team_code"] == 20),
                "expected_goals_conceded_measured": 0.75,
            }
            for r in targets
        ]
    )
    references = {r["key"]: r for r in upstream["rows"]}
    called = []
    for _season, gw, cutoff in runner.observed_folds(frame, minimum_prior_gameweeks=0):
        baseline = TrailingGoalsAttackDefence()
        baseline.fit(
            TrainingWindow(
                runner.scoring._baseline_frame(frame.filter(pl.col("kickoff_time") < cutoff))
            )
        )
        target = frame.filter(pl.col("gw") == gw)
        for row, pmf in zip(target.iter_rows(named=True), baseline.predict(target), strict=True):
            references[row["key"]]["incumbent_pmf"] = pmf
            references[row["key"]]["incumbent_latent_rate"] = baseline.rate_for(row)

    def prospective(_: Any, **kwargs: Any) -> tuple[dict[tuple[int, int], Distribution], float]:
        called.append(kwargs["as_of"])
        return {
            (r["fixture"], r["team_code"]): tuple(references[r["key"]]["incumbent_pmf"])
            for r in frame.filter(pl.col("gw") == kwargs["schedule"]["gw"][0]).iter_rows(named=True)
        }, 1.2

    monkeypatch.setattr(runner, "HISTORICAL_ROWS", 6)
    monkeypatch.setattr(runner, "load_team_frame", lambda *_args, **_kwargs: frame)
    monkeypatch.setattr(runner, "prospective_team_scored", prospective)
    with duckdb.connect(":memory:") as con:
        cache, report = runner.reproduce_incumbent(con, contract, upstream)
        assert len(cache) == 6 and len(called) == 3
        assert report["maximum_absolute_pmf_difference"] == 0
        upstream["rows"][0]["incumbent_pmf"] = poisson_pmf(2.0, max_goals=10)
        with pytest.raises(ValueError, match="PMF reproduction"):
            runner.reproduce_incumbent(con, contract, upstream)


def test_runner_does_not_mutate_frozen_upstream() -> None:
    experiment, upstream, contract, observations = _experiment()
    before = copy.deepcopy(upstream)
    runner.verify_run(experiment, observations, contract)
    runner.chance_diagnostics(experiment)
    runner.score_experiment(experiment, contract)
    assert upstream == before


@pytest.mark.parametrize("goals", [True, 1.5, None])
def test_goal_target_never_coerced(goals: Any) -> None:
    targets, upstream, _ = _fixture()
    targets[0]["goals"] = goals
    with pytest.raises(ValueError, match="trusted goal targets"):
        runner.make_observations(targets, upstream, _cache(upstream))


def test_snapshot_hashes_frozen_results_sources_and_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, contract = _fixture()
    db = tmp_path / "read_only.duckdb"
    db.write_bytes(b"unchanged operational evidence")
    contract["database_sha256"] = runner.scoring.file_sha256(db)
    config = tmp_path / runner.CONFIG
    config.parent.mkdir(parents=True)
    config.write_bytes((repo_root() / runner.CONFIG).read_bytes())
    for key, sha_key in (("upstream", "upstream_sha256"), ("coverage_report", "coverage_sha256")):
        path = tmp_path / contract[key]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}")
        contract[sha_key] = runner.scoring.file_sha256(path)
    source = tmp_path / "src/fpl/validate/chance_creation.py"
    source.parent.mkdir(parents=True)
    source.write_text("# synthetic source\n")
    for name in ("AGENTS.md", "DEV-ROADMAP.md", "README.md"):
        (tmp_path / name).write_text("synthetic instructions")
    frozen = tmp_path / "results/frozen_prior.json"
    frozen.write_text('{"frozen": true}')
    monkeypatch.setattr(runner, "_assert_clean", lambda _: None)
    monkeypatch.setattr(runner.scoring, "_git", lambda *_: "synthetic-head")
    first = runner._snapshot(tmp_path, db, contract)
    assert first["source_sha256"]["results/frozen_prior.json"] == runner.scoring.file_sha256(frozen)
    assert first["source_sha256"][
        "src/fpl/validate/chance_creation.py"
    ] == runner.scoring.file_sha256(source)
    source.write_text("# changed source\n")
    assert runner._snapshot(tmp_path, db, contract) != first
    db.write_bytes(b"changed database")
    with pytest.raises(RuntimeError, match="database differs"):
        runner._snapshot(tmp_path, db, contract)


@pytest.mark.parametrize(
    ("log_lift", "cs_lift", "verdict"),
    [
        (0.02, 0.02, "SUPPORTED"),
        (0.02, 0.005, "INCONCLUSIVE"),
        (0.005, 0.02, "INCONCLUSIVE"),
        (-0.02, 0.02, "REFUTED"),
    ],
)
def test_two_materiality_gates_required_without_promoting(
    log_lift: float, cs_lift: float, verdict: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    experiment, _, contract, _ = _experiment()

    def scores(*_: Any) -> dict[str, Any]:
        return {
            "incumbent": {"mean_log_score": 1.0, "clean_sheet_brier": 0.2, "crps": 0.3},
            "candidate": {
                "mean_log_score": 1 - log_lift,
                "clean_sheet_brier": 0.2 * (1 - cs_lift),
                "crps": 0.29,
                "pit_interval_80_coverage": 0.8,
            },
        }

    monkeypatch.setattr(runner, "_score_rows", scores)
    result = runner.score_experiment(experiment, contract)
    assert result["verdict"] == verdict


def test_target_mutation_after_fit_is_detected() -> None:
    experiment, _, contract, observations = _experiment()
    experiment["history_rows"][0]["observed_archive_xg"] = 9.99
    with pytest.raises(ValueError, match="trusted targets"):
        runner.verify_run(experiment, observations, contract)


def test_preflight_restores_frozen_utc_serialization_and_database_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, events, contract = _mock_formal(tmp_path, monkeypatch)
    before = runner.scoring.file_sha256(db)
    connect = duckdb.connect

    def local_connection(*args: Any, **kwargs: Any) -> duckdb.DuckDBPyConnection:
        con = connect(*args, **kwargs)
        con.execute("SET TimeZone = 'Asia/Bangkok'")
        return con

    monkeypatch.setattr(runner.duckdb, "connect", local_connection)
    frozen = json.loads((tmp_path / contract["coverage_report"]).read_bytes())
    frozen["captured"] = "2026-09-04T16:58:26.444378+00:00"
    (tmp_path / contract["coverage_report"]).write_text(json.dumps(frozen))

    def audit(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
        # Arrow conversion, as in the real capture view, uses the session timezone.
        captured = (
            con.execute("SELECT TIMESTAMPTZ '2026-09-04 16:58:26.444378+00' AS captured")
            .pl()["captured"][0]
            .isoformat()
        )
        assert captured == frozen["captured"]
        return {key: value for key, value in frozen.items() if key != "database_sha256"} | {
            "captured": captured,
        }

    monkeypatch.setattr(runner, "build_audit", audit)
    result = runner.run(tmp_path, db)
    assert events == ["reproduce", "claim"]
    assert result["coverage"] == frozen
    assert result["coverage"]["database_sha256"] == before
    assert runner.scoring.file_sha256(db) == before


def test_frozen_coverage_database_hash_is_not_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, events, contract = _mock_formal(tmp_path, monkeypatch)
    path = tmp_path / contract["coverage_report"]
    frozen = json.loads(path.read_bytes())
    frozen["database_sha256"] = "different-database"
    path.write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match="coverage-only"):
        runner.run(tmp_path, db)
    assert events == []
    assert not runner._claim_path(tmp_path).exists()
