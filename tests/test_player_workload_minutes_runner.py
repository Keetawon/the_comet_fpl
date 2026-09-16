"""Synthetic Phase D runner checks; external draft during the shared clean-run freeze."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pytest

from fpl.config import load_phase2_evaluation
from fpl.types import Position
from fpl.validate import dev_player_workload_minutes as runner
from fpl.validate.development_reference_components import (
    ReferenceMinutesRow,
    ValidatedMinutesControlCache,
    ValidatedMinutesControlFold,
)
from fpl.validate.minutes_baselines import (
    HistoryRow,
    MinuteBins,
    TargetRow,
    TeamCodeMap,
    build_minutes_baselines,
)
from fpl.validate.player_workload_inputs import WorkloadProgramInputs
from fpl.validate.player_workload_minutes import (
    WorkloadMinutesInput,
    control_from_cache,
    workload_role_features,
)


def tiny_inputs() -> tuple[WorkloadProgramInputs, list[HistoryRow]]:
    time = datetime(2025, 8, 1, tzinfo=UTC)
    target = TargetRow("2025-26", 1, 10, time, 99, Position.DEF, 3, 7, True)
    row = ReferenceMinutesRow(target, 33, (0.4, 0.2, 0.2, 0.2), False, False, "{}")
    fold = ValidatedMinutesControlFold(
        "2025-26", 1, time, (row,), "a" * 64, "b" * 64, "c" * 64, '{"maximum_prior_kickoff":null}'
    )
    item = WorkloadMinutesInput(control_from_cache(fold, row), None, None, None, frozenset())
    reference = ValidatedMinutesControlCache((fold,), "{}")
    inputs = WorkloadProgramInputs(
        reference,
        {("2025-26", 1): (item,)},
        {("2025-26", 10, 99): workload_role_features(item)},
        {},
        {},
    )
    observed = HistoryRow(**asdict(target), minutes=0)
    return inputs, [observed]


def test_exact_current_pmf_population_preserves_dnp(monkeypatch: pytest.MonkeyPatch) -> None:
    inputs, targets = tiny_inputs()
    monkeypatch.setattr(runner, "EXPECTED_COUNTS", {"2025-26": 1, "rows": 1, "price_proxy_rows": 0})
    result = runner.verify_population(inputs, targets)
    assert result["maximum_pmf_difference"] == 0
    assert result["counts"]["rows"] == 1
    assert targets[0].minutes == 0


@pytest.mark.parametrize(
    "mode", ["missing", "extra", "duplicate", "changed_identity", "changed_pmf"]
)
def test_population_refuses_any_scored_row_or_control_change(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    inputs, targets = tiny_inputs()
    monkeypatch.setattr(runner, "EXPECTED_COUNTS", {"2025-26": 1, "rows": 1, "price_proxy_rows": 0})
    if mode == "missing":
        targets = []
    elif mode == "extra":
        targets.append(replace(targets[0], code=100))
    elif mode == "duplicate":
        targets *= 2
    elif mode == "changed_identity":
        targets[0] = replace(targets[0], position=Position.FWD)
    else:
        item = inputs.batches["2025-26", 1][0]
        inputs.batches["2025-26", 1] = (
            replace(item, control=replace(item.control, probabilities=(0.25,) * 4)),
        )
    with pytest.raises(ValueError, match=r"population|outcome|duplicate|projection|reproduction"):
        runner.verify_population(inputs, targets)


def test_baseline_prediction_memoization_exactly_matches_original() -> None:
    inputs, _ = tiny_inputs()
    fold = inputs.reference.folds[0]
    target = fold.rows[0].target
    history = [
        HistoryRow(
            **{
                **asdict(target),
                "gw": 1,
                "fixture": i,
                "kickoff_time": fold.as_of - timedelta(days=8 - i),
            },
            minutes=0 if i % 2 else 90,
        )
        for i in range(1, 7)
    ]
    teams = TeamCodeMap.from_pairs([("2025-26", 3, 33), ("2025-26", 7, 77)])
    bins = MinuteBins.from_config(load_phase2_evaluation())
    # Nominal history GW must differ from the target whole-GW batch.
    history = [replace(h, gw=99) for h in history]
    actual = runner.baseline_predictions(history, fold, bins=bins, teams=teams)
    independent = {
        m.name: (m.predict(target),)
        for m in build_minutes_baselines(history, as_of=fold.as_of, team_codes=teams, bins=bins)
    }
    assert actual == independent


def test_baselines_reject_target_gw_even_with_prior_kickoff() -> None:
    inputs, target = tiny_inputs()
    fold = inputs.reference.folds[0]
    history = [replace(target[0], fixture=9, kickoff_time=fold.as_of - timedelta(days=1))]
    teams = TeamCodeMap.from_pairs([("2025-26", 3, 33), ("2025-26", 7, 77)])
    with pytest.raises(ValueError, match="target GW"):
        runner.baseline_predictions(
            history, fold, bins=MinuteBins.from_config(load_phase2_evaluation()), teams=teams
        )


def report_rows() -> list[dict[str, Any]]:
    result = []
    for season in ("2023-24", "2024-25", "2025-26"):
        for gw in (1, 8):
            for code in range(8):
                outcome = code % 4
                distribution = [0.1] * 4
                distribution[outcome] = 0.7
                result.append(
                    {
                        "season": season,
                        "gw": gw,
                        "fixture": gw,
                        "code": code,
                        "position": "DEF",
                        "venue": "home" if code % 2 else "away",
                        "cold_start": False,
                        "price_proxy": False,
                        "early_later": "GW1-6" if gw == 1 else "GW7+",
                        "transfer_status": "same",
                        "player_history_cohort": "prior_positive",
                        "feature_active": season == "2025-26",
                        "observed_bin": outcome,
                        "pmfs": dict.fromkeys(runner.ARMS, distribution),
                    }
                )
    return result


def test_identical_pmf_zero_lift_cannot_pass181fold_gate() -> None:
    result = runner.summarize(report_rows(), load_phase2_evaluation(), fold_count=114)
    assert result["relative_mean_log_lift_vs_current"] == 0
    assert result["verdict"] == "INCONCLUSIVE"
    assert result["full_stage_b_gate_eligible"] is False
    assert result["synthesis_eligible"] is False
    failures = [
        c["name"] for c in result["stage_b_frozen_gate_diagnostics"]["checks"] if not c["passed"]
    ]
    assert "folds_evaluated_at_least_minimum" in failures
    assert result["paired_vs_current"]["paired_mean"] == 0
    assert result["paired_vs_current"]["gw_clustered_standard_error"] == 0
    json.dumps(result, allow_nan=False)


def test_material_numeric_gain_still_cannot_promote_ineligible_scope() -> None:
    rows = report_rows()
    for row in rows:
        pmf = [0.05] * 4
        pmf[row["observed_bin"]] = 0.85
        row["pmfs"]["candidate"] = pmf
    result = runner.summarize(rows, load_phase2_evaluation(), fold_count=114)
    assert result["relative_mean_log_lift_vs_current"] > 0.01
    assert result["current_control_gate"]["log_lift_at_least_1pct"]
    assert result["verdict"] == "INCONCLUSIVE"
    assert not result["synthesis_eligible"]


def test_existing_output_refused_before_any_source_or_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "already"
    output.mkdir()
    monkeypatch.setattr(runner, "snapshot", lambda *_: pytest.fail("must reject first"))
    with pytest.raises(ValueError, match="write-once"):
        runner.run(
            root=tmp_path,
            database=tmp_path,
            archive_database=tmp_path,
            minutes_directory=tmp_path,
            role_result=tmp_path,
            stage_report=tmp_path,
            coverage_report=tmp_path,
            output=output,
        )


def test_dirty_worktree_refused_before_loading_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dirty(_):
        raise ValueError("dirty worktree")

    monkeypatch.setattr(runner, "git_clean_head", dirty)
    monkeypatch.setattr(
        runner, "build_workload_inputs", lambda **_: pytest.fail("must reject first")
    )
    with pytest.raises(ValueError, match="dirty"):
        runner.snapshot(tmp_path, {})


def test_wrong_branch_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "git_clean_head", lambda _: "a" * 40)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_a, **_kw: "main")
    with pytest.raises(ValueError, match="exact V2"):
        runner.snapshot(tmp_path, {})


def test_unregistered_candidate_cannot_load_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "CONFIG_SHA256", "UNREGISTERED")
    with pytest.raises(ValueError, match="absent or changed"):
        runner.load_contract(tmp_path)


def test_actual_frozen_config_loads_exactly_with_numeric_yaml_types() -> None:
    contract = runner.load_contract(runner.repo_root())
    assert contract["policy"] == runner.FIXED_POLICY
    assert type(contract["policy"]["gradient_tolerance"]) is float


@pytest.mark.parametrize("key", ["minutes_manifest_sha256", "role_result_sha256"])
def test_every_external_fold_is_rechecked_not_only_manifests(tmp_path: Path, key: str) -> None:
    paths = {}
    for source in ("minutes_manifest_sha256", "role_result_sha256"):
        directory = tmp_path / source
        directory.mkdir()
        fold = directory / "2025-26-gw01.json"
        fold.write_text("{}", encoding="utf-8")
        manifest = directory / "manifest.json"
        manifest.write_text(
            json.dumps({"folds": [{"file": fold.name, "sha256": runner.file_sha256(fold)}]}),
            encoding="utf-8",
        )
        (directory / "source_versions.json").write_text("{}", encoding="utf-8")
        paths[source] = manifest
    before = runner.cache_fingerprints(paths)
    assert len(before) == 3
    (paths[key].parent / "2025-26-gw01.json").write_text('{"changed":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="fold hash changed"):
        runner.cache_fingerprints(paths)


def test_role_source_ledger_drift_is_bound_to_external_snapshot(tmp_path: Path) -> None:
    paths = {}
    for source in ("minutes_manifest_sha256", "role_result_sha256"):
        directory = tmp_path / source
        directory.mkdir()
        manifest = directory / "manifest.json"
        manifest.write_text('{"folds":[]}', encoding="utf-8")
        (directory / "source_versions.json").write_text("{}", encoding="utf-8")
        paths[source] = manifest
    before = runner.cache_fingerprints(paths)
    (paths["role_result_sha256"].parent / "source_versions.json").write_text(
        '{"changed":true}', encoding="utf-8"
    )
    assert runner.cache_fingerprints(paths) != before


@pytest.mark.parametrize("mode", ["hash", "wal"])
def test_snapshot_rejects_database_hash_or_wal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    database = tmp_path / "source.duckdb"
    database.write_bytes(b"source")
    digest = runner.file_sha256(database)
    monkeypatch.setattr(runner, "git_clean_head", lambda _: "a" * 40)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_a, **_kw: runner.BRANCH)
    monkeypatch.setattr(
        runner,
        "load_contract",
        lambda _: {"pins": {"database_sha256": digest if mode == "wal" else "0" * 64}},
    )
    if mode == "wal":
        Path(str(database) + ".wal").write_bytes(b"pending")
    with pytest.raises(ValueError, match=r"input differs|WAL"):
        runner.snapshot(tmp_path, {"database_sha256": database})


def run_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    inputs, _targets = tiny_inputs()
    database = tmp_path / "source.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute(
            "CREATE TABLE mart_fact_player_fixture(season VARCHAR,gw INTEGER,fixture INTEGER,"
            "kickoff_time TIMESTAMPTZ,code INTEGER,position VARCHAR,team_id INTEGER,"
            "opponent_team_id INTEGER,was_home BOOLEAN,minutes INTEGER)"
        )
        con.execute(
            "INSERT INTO mart_fact_player_fixture VALUES "
            "('2025-26',1,10,'2025-08-01T00:00:00Z',99,'DEF',3,7,true,0)"
        )
        con.execute("CREATE TABLE mart_dim_team(season VARCHAR,team_id INTEGER,team_code INTEGER)")
        con.execute("INSERT INTO mart_dim_team VALUES ('2025-26',3,33),('2025-26',7,77)")
    coverage = tmp_path / "coverage.json"
    coverage.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "EXPECTED_COUNTS", {"2025-26": 1, "rows": 1, "price_proxy_rows": 0})
    monkeypatch.setattr(runner, "build_workload_inputs", lambda **_: inputs)
    monkeypatch.setattr(runner, "snapshot", lambda *_: {"synthetic": True})
    monkeypatch.setattr(runner, "player_fixture_history", lambda *_a, **_kw: [])
    monkeypatch.setattr(
        runner,
        "baseline_predictions",
        lambda *_a, **_kw: dict.fromkeys(runner.STAGE_B_BASELINE_ORDER, ((0.25,) * 4,)),
    )
    monkeypatch.setattr(runner, "summarize", lambda *_a, **_kw: {"verdict": "INCONCLUSIVE"})
    claims = []

    def claim(_root, name, provenance):
        path = tmp_path / "shared-claim.json"
        runner.publish_json(path, {"candidate": name, "provenance": provenance})
        claims.append(path)
        return path

    monkeypatch.setattr(runner, "reserve_program_claim", claim)
    args = {
        "root": tmp_path / "root",
        "database": database,
        "archive_database": database,
        "minutes_directory": tmp_path,
        "role_result": tmp_path / "role.json",
        "stage_report": tmp_path / "stage.json",
        "coverage_report": coverage,
        "output": tmp_path / "newoutput",
    }
    return args, claims


def test_failure_consumes_shared_claim_and_retains_immutable_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, claims = run_fixture(tmp_path, monkeypatch)

    def numerical_failure(*_a, **_kw):
        assert len(claims) == 1
        raise ValueError("synthetic fixed-solver failure")

    monkeypatch.setattr(runner, "fit_minutes_correction", numerical_failure)
    with pytest.raises(ValueError, match="synthetic fixed-solver"):
        runner.run(**args)
    failure = json.loads((args["output"] / "failure.json").read_bytes())
    assert failure["claim_preserved"] is True
    assert failure["retry_permitted"] is False
    assert claims[0].exists()
    assert not (args["output"] / "result.json").exists()
    with pytest.raises(ValueError, match="write-once"):
        runner.run(**args)
    assert len(claims) == 1


def test_clean_postflight_drift_cannot_publish_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, claims = run_fixture(tmp_path, monkeypatch)
    calls = []

    def snapshot(*_):
        calls.append(1)
        return {"synthetic": len(calls) < 3}

    monkeypatch.setattr(runner, "snapshot", snapshot)
    with pytest.raises(ValueError, match="changed during run"):
        runner.run(**args)
    assert len(claims) == 1
    assert not (args["output"] / "result.json").exists()
    assert (args["output"] / "failure.json").exists()


def test_failed_comparator_does_not_reserve_or_fit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    args, claims = run_fixture(tmp_path, monkeypatch)

    def failure(*_):
        raise ValueError("comparator fails")

    monkeypatch.setattr(runner, "verify_population", failure)
    monkeypatch.setattr(
        runner, "fit_minutes_correction", lambda *_a, **_kw: pytest.fail("no fit licensed")
    )
    with pytest.raises(ValueError, match="comparator fails"):
        runner.run(**args)
    assert claims == []
    assert not args["output"].exists()
