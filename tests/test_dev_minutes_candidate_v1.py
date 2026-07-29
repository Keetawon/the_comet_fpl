"""Deterministic OFFLINE tests for the Stage B Candidate V1 development runner.

No network, no built archive. ``main()`` is exercised only with monkeypatched offline collaborators
(a fake read-only connection whose ``execute`` raises, and a stubbed harness returning a canned
result); every other check runs against tiny local files or constructed result objects.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import duckdb
import pytest

import fpl.validate.dev_minutes_candidate_v1 as dev
from fpl.config import config_dir, load_phase2_evaluation, repo_root
from fpl.storage.db import connect
from fpl.validate.dev_minutes_candidate_v1 import (
    DevelopmentDiagnostics,
    PreflightSnapshot,
    Provenance,
    ProvenanceError,
    build_reconciliation_record,
    candidate_source_path,
    capture_preflight,
    compute_development_diagnostics,
    file_sha256,
    finalize_provenance,
    format_development_report,
    format_reconciliation_record,
    hash_bytes,
    head_commit_sha,
    load_contract_from_bytes,
    open_database,
    require_clean_worktree,
    verify_snapshot,
    worktree_is_clean,
)
from fpl.validate.minutes_harness import MinutesHarnessResult
from fpl.validate.minutes_metrics import (
    MinutesScoreReport,
    ReliabilityBucket,
    ReliabilityCurve,
)

BASELINES = (
    "position_minutes_frequency",
    "last_observed_player_minutes",
    "trailing_5_player_minutes",
    "trailing_5_team_position_minutes",
)
CANDIDATE = "shrunk_trailing_5_player_minutes_v1"
COMPARATOR = BASELINES[0]  # the lowest-log baseline in the canned results below
CONFIG = load_phase2_evaluation()


# --------------------------------------------------------------------------------------
# Tiny git repo + canned result helpers
# --------------------------------------------------------------------------------------


def _init_repo(path: Path) -> Path:
    """A minimal local git repo with one committed file, so the worktree starts clean."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    (path / "f.txt").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _real_config_bytes() -> bytes:
    return (config_dir() / "phase2_evaluation.yaml").read_bytes()


def _real_source_bytes() -> bytes:
    return (repo_root() / "src" / "fpl" / "models" / "minutes_v1.py").read_bytes()


def _reliability() -> ReliabilityCurve:
    return ReliabilityCurve(
        tuple(ReliabilityBucket(i / 10, (i + 1) / 10, 0, None, None) for i in range(10))
    )


def _score(
    name: str,
    log: float,
    *,
    rps: float = 0.50,
    brier_any: float = 0.20,
    brier_60: float = 0.20,
    pit80: float = 0.80,
    coverage: float = 1.0,
    cold: int = 0,
    predictions: int = 760,
) -> MinutesScoreReport:
    return MinutesScoreReport(
        name=name,
        predictions=predictions,
        eligible_predictions=predictions,
        exclusions=0,
        cold_starts=cold,
        mean_log_score=log,
        mean_log_score_standard_error=0.01,
        mean_ranked_probability_score=rps,
        mean_brier_any_minutes=brier_any,
        mean_brier_60_plus=brier_60,
        pit_interval_80_coverage=pit80,
        pit_values=(),
        reliability_any_minutes=_reliability(),
        reliability_60_plus=_reliability(),
        spearman_p60_within_position_gameweek=0.30,
        prediction_coverage=coverage,
    )


def _canned_result(
    *,
    candidate_log: float,
    baseline_log: float = 1.04916,
    folds: int = 181,
    leakage: int = 0,
    seasons: tuple[str, ...] = ("2025-26",),
    season_candidate_log: float | None = None,
    candidate_rps: float = 0.49,
    candidate_coverage: float = 1.0,
) -> MinutesHarnessResult:
    """A minimal but valid harness result with the four baselines plus the candidate.

    ``COMPARATOR`` is the lowest-log baseline so ``best_baseline()`` is deterministic; the candidate
    is never a required baseline, so it can never be selected as the comparator even when its log is
    lowest.
    """
    overall = {
        COMPARATOR: _score(COMPARATOR, baseline_log, rps=0.50),
        BASELINES[1]: _score(BASELINES[1], baseline_log + 0.5),
        BASELINES[2]: _score(BASELINES[2], baseline_log + 0.4),
        BASELINES[3]: _score(BASELINES[3], baseline_log + 0.6),
        CANDIDATE: _score(CANDIDATE, candidate_log, rps=candidate_rps, coverage=candidate_coverage),
    }
    season_cand_log = candidate_log if season_candidate_log is None else season_candidate_log
    season_candidate = _score(
        CANDIDATE, season_cand_log, rps=candidate_rps, coverage=candidate_coverage
    )
    by_season = {}
    for season in seasons:
        season_reports = dict(overall)
        season_reports[CANDIDATE] = season_candidate
        by_season[season] = season_reports
    by_fold = {f"{season}-GW1": dict(reports) for season, reports in by_season.items()}
    parameters_by_fold = {
        f"{season}-GW1": {
            CANDIDATE: {
                "name": CANDIDATE,
                "selected_alpha": 5.0,
                "history_window": 5,
                "inner_holdout_observed_gameweeks": 0,
                "inner_training_observed_gameweeks": 0,
                "used_inner_holdout": False,
                "inner_objective": "pooled_mean_log_score",
            }
        }
        for season in seasons
    }
    return MinutesHarnessResult(
        folds_evaluated=folds,
        folds_by_season=dict.fromkeys(seasons, 1),
        predictions=760,
        eligible_predictions=760,
        leakage_failures=leakage,
        required_baselines=frozenset(BASELINES),
        overall=overall,
        by_fold=by_fold,
        by_season=by_season,
        by_position={"MID": dict(overall)},
        by_home_away={"home": dict(overall)},
        by_transfer_status={"same_team_code_as_last_observed_fixture": dict(overall)},
        by_player_history_cohort={"prior_positive_minutes": dict(overall)},
        parameters_by_fold=parameters_by_fold,
    )


def _provenance() -> Provenance:
    return Provenance(
        candidate=CANDIDATE,
        contract_version="1.1",
        commit_sha="deadbeef" * 5,
        config_fingerprint="c" * 64,
        candidate_source_fingerprint="s" * 64,
        archive_fingerprint="a" * 64,
        seed=202627,
        started_at="2026-07-29T10:00:00Z",
        ended_at="2026-07-29T10:05:00Z",
    )


# --------------------------------------------------------------------------------------
# Git / fingerprint helpers
# --------------------------------------------------------------------------------------


def test_worktree_is_clean_for_a_freshly_committed_repo(tmp_path: Path) -> None:
    assert worktree_is_clean(_init_repo(tmp_path)) is True


def test_require_clean_worktree_refuses_a_dirty_tree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    (repo / "uncommitted.txt").write_text("change", encoding="utf-8")
    with pytest.raises(SystemExit, match="dirty"):
        require_clean_worktree(repo)


def test_head_commit_sha_reads_the_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    rev_parse = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert head_commit_sha(repo) == rev_parse


def test_file_sha256_is_stable(tmp_path: Path) -> None:
    (tmp_path / "blob").write_bytes(b"x" * 100000 + b"tail")
    digest = file_sha256(tmp_path / "blob")
    assert digest == file_sha256(tmp_path / "blob")
    assert len(digest) == 64


def test_load_contract_from_bytes_fingerprints_the_exact_parsed_bytes(tmp_path: Path) -> None:
    config_copy = tmp_path / "phase2_evaluation.yaml"
    real = _real_config_bytes()
    config_copy.write_bytes(real)
    contract, fingerprint = load_contract_from_bytes(config_copy)
    assert contract.contract_version == "1.1"
    assert fingerprint == file_sha256(config_copy)
    assert fingerprint == hash_bytes(real)
    # Editing the bytes -- even a no-op comment -- changes the fingerprint.
    config_copy.write_bytes(real + b"\n# trailing comment\n")
    _, edited = load_contract_from_bytes(config_copy)
    assert edited != fingerprint


def test_open_database_opens_read_only_and_rejects_writes(tmp_path: Path) -> None:
    db = tmp_path / "ro.duckdb"
    con = connect(str(db))  # create writable
    con.execute("CREATE TABLE t (x INTEGER)")
    con.close()
    read_only = open_database(db)
    try:
        with pytest.raises(duckdb.Error):
            read_only.execute("INSERT INTO t VALUES (1)")
    finally:
        read_only.close()


# --------------------------------------------------------------------------------------
# Provenance lifecycle: preflight snapshot -> verify -> finalize
# --------------------------------------------------------------------------------------


def _provenance_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, Path, PreflightSnapshot]:
    """A clean repo plus sibling (config, candidate-source, db) files and the captured snapshot.

    The config, candidate source, and db live OUTSIDE the repo dir so editing any one of them does
    not dirty the worktree, letting each revalidation failure be isolated to its own dimension.
    """
    repo = _init_repo(tmp_path / "repo")
    config_copy = tmp_path / "phase2_evaluation.yaml"
    config_copy.write_bytes(_real_config_bytes())
    source_copy = tmp_path / "minutes_v1.py"
    source_copy.write_bytes(_real_source_bytes())
    db = tmp_path / "db.duckdb"
    db.write_bytes(b"archive-bytes")
    contract, _ = load_contract_from_bytes(config_copy)
    snapshot = capture_preflight(
        db,
        contract,
        repo=repo,
        config_path=config_copy,
        candidate_source_path=source_copy,
    )
    return repo, config_copy, source_copy, db, snapshot


def test_capture_preflight_records_every_field_before_evaluation(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    # No ended_at is required to build the preflight snapshot.
    assert not hasattr(snapshot, "ended_at")
    assert snapshot.candidate == CANDIDATE
    assert snapshot.contract_version == "1.1"
    assert snapshot.commit_sha == head_commit_sha(repo)
    assert snapshot.config_fingerprint == file_sha256(config_copy)
    assert snapshot.candidate_source_fingerprint == file_sha256(source_copy)
    assert snapshot.archive_fingerprint == file_sha256(db)
    assert snapshot.seed == 202627
    assert snapshot.started_at.endswith("Z")


def test_verify_snapshot_passes_when_unchanged(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    verify_snapshot(
        snapshot, db_path=db, repo=repo, config_path=config_copy, candidate_source_path=source_copy
    )  # must not raise


def test_verify_snapshot_aborts_on_a_dirty_worktree(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    (repo / "uncommitted.txt").write_text("change", encoding="utf-8")
    with pytest.raises(ProvenanceError, match="dirty"):
        verify_snapshot(
            snapshot,
            db_path=db,
            repo=repo,
            config_path=config_copy,
            candidate_source_path=source_copy,
        )


def test_verify_snapshot_aborts_on_a_head_change(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    (repo / "new.txt").write_text("second commit", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=repo, check=True)
    with pytest.raises(ProvenanceError, match="HEAD"):
        verify_snapshot(
            snapshot,
            db_path=db,
            repo=repo,
            config_path=config_copy,
            candidate_source_path=source_copy,
        )


def test_verify_snapshot_aborts_on_a_config_change(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    config_copy.write_bytes(b"# altered contract bytes\n")
    with pytest.raises(ProvenanceError, match="config"):
        verify_snapshot(
            snapshot,
            db_path=db,
            repo=repo,
            config_path=config_copy,
            candidate_source_path=source_copy,
        )


def test_verify_snapshot_aborts_on_a_candidate_source_change(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    source_copy.write_bytes(_real_source_bytes() + b"\n# mid-run edit\n")
    with pytest.raises(ProvenanceError, match="Candidate V1 source"):
        verify_snapshot(
            snapshot,
            db_path=db,
            repo=repo,
            config_path=config_copy,
            candidate_source_path=source_copy,
        )


def test_verify_snapshot_aborts_on_a_database_change(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    db.write_bytes(b"rebuilt-bytes")
    with pytest.raises(ProvenanceError, match="database"):
        verify_snapshot(
            snapshot,
            db_path=db,
            repo=repo,
            config_path=config_copy,
            candidate_source_path=source_copy,
        )


def test_finalize_provenance_carries_both_utc_timestamps(tmp_path: Path) -> None:
    _repo, _config, _source, _db, snapshot = _provenance_fixture(tmp_path)
    provenance = finalize_provenance(snapshot, ended_at="2026-07-29T10:05:00Z")
    assert provenance.started_at == snapshot.started_at
    assert provenance.ended_at == "2026-07-29T10:05:00Z"
    # The finalized record carries the same fingerprints captured before the run.
    assert provenance.config_fingerprint == snapshot.config_fingerprint
    assert provenance.candidate_source_fingerprint == snapshot.candidate_source_fingerprint
    assert provenance.archive_fingerprint == snapshot.archive_fingerprint
    text = "\n".join(provenance.as_lines())
    for needle in (
        "started at (UTC)",
        "ended at (UTC)",
        "candidate source fp",
        "archive fingerprint",
    ):
        assert needle in text


def test_provenance_lines_record_utc_start_and_end() -> None:
    text = "\n".join(_provenance().as_lines())
    assert "started at (UTC)      : 2026-07-29T10:00:00Z" in text
    assert "ended at (UTC)        : 2026-07-29T10:05:00Z" in text
    assert "candidate source fp   : " + "s" * 64 in text


# --------------------------------------------------------------------------------------
# Structured development diagnostics
# --------------------------------------------------------------------------------------


def test_diagnostics_have_nine_labelled_checks() -> None:
    diagnostics: DevelopmentDiagnostics = compute_development_diagnostics(
        _canned_result(candidate_log=1.028), CANDIDATE, CONFIG
    )
    assert diagnostics.comparable is True
    assert diagnostics.comparator == COMPARATOR
    assert [check.name for check in diagnostics.checks] == [
        "aggregate_mean_log_score_lift_at_least_minimum",
        "no_aggregate_ranked_probability_score_regression",
        "no_aggregate_brier_any_minutes_regression",
        "no_aggregate_brier_60_plus_regression",
        "pit_interval_80_absolute_error_at_most_maximum",
        "prediction_coverage_at_least_minimum",
        "folds_evaluated_at_least_minimum",
        "zero_leakage_failures",
        "no_per_season_mean_log_score_regression",
    ]
    # Every check is labelled a development diagnostic, never a verdict.
    assert all(check.label == "DEVELOPMENT DIAGNOSTIC ONLY" for check in diagnostics.checks)


def test_diagnostics_pass_when_candidate_beats_baseline_on_every_condition() -> None:
    result = _canned_result(candidate_log=1.028)  # ~2% lift over the 1.04916 comparator
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    assert diagnostics.passed_count() == 9
    lines = "\n".join(diagnostics.as_lines())
    assert lines.count("PASS") == 9
    assert "NOT combined into a promotion verdict" in lines


def test_diagnostics_fail_when_lift_below_one_percent() -> None:
    result = _canned_result(candidate_log=1.04916)  # zero lift, below the 1% gate
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    lift_check = next(
        check for check in diagnostics.checks if check.name.startswith("aggregate_mean_log_score")
    )
    assert lift_check.passed is False
    # The non-regression / calibration / count checks still pass on this canned result.
    assert diagnostics.passed_count() == 8


def test_diagnostics_fail_on_a_per_season_regression() -> None:
    result = _canned_result(candidate_log=1.028, season_candidate_log=1.10)  # one season regresses
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    season_check = next(
        check
        for check in diagnostics.checks
        if check.name == "no_per_season_mean_log_score_regression"
    )
    assert season_check.passed is False
    assert "1 of 1 seasons regress" in season_check.detail


def test_diagnostics_fail_on_coverage_folds_and_leakage() -> None:
    result = _canned_result(candidate_log=1.028, candidate_coverage=0.99, folds=180, leakage=1)
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    by_name = {check.name: check for check in diagnostics.checks}
    assert by_name["prediction_coverage_at_least_minimum"].passed is False
    assert by_name["folds_evaluated_at_least_minimum"].passed is False
    assert by_name["zero_leakage_failures"].passed is False


def test_diagnostics_comparator_is_the_best_required_baseline_not_the_candidate() -> None:
    # Candidate has the lowest log score of all, but it is not a required baseline.
    result = _canned_result(candidate_log=0.90)
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    assert diagnostics.comparator == COMPARATOR
    assert CANDIDATE not in result.required_baselines


def test_diagnostics_not_comparable_when_candidate_absent() -> None:
    full = _canned_result(candidate_log=1.028)
    overall = {name: report for name, report in full.overall.items() if name != CANDIDATE}
    result = MinutesHarnessResult(
        folds_evaluated=full.folds_evaluated,
        folds_by_season=full.folds_by_season,
        predictions=full.predictions,
        eligible_predictions=full.eligible_predictions,
        leakage_failures=full.leakage_failures,
        required_baselines=full.required_baselines,
        overall=overall,
        by_fold={},
        by_season={},
        by_position={},
        by_home_away={},
        by_transfer_status={},
        by_player_history_cohort={},
        parameters_by_fold={},
    )
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    assert diagnostics.comparable is False


# --------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------


def test_report_is_labelled_and_never_a_verdict() -> None:
    result = _canned_result(candidate_log=1.028)
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    text = format_development_report(
        result, CANDIDATE, CONFIG, provenance=_provenance(), diagnostics=diagnostics
    )
    assert "DEVELOPMENT ONLY" in text
    assert "NOT A PROMOTION RESULT" in text
    assert "DEVELOPMENT DIAGNOSTIC ONLY" in text
    assert COMPARATOR in text
    assert "Do not promote" in text
    # Provenance is embedded so the number is tied to a frozen quadruple.
    assert "deadbeef" in text
    assert "s" * 64 in text  # candidate-source fingerprint
    # No uppercase standalone "PROMOTE" verdict token anywhere.
    assert "PROMOTE" not in text


def test_reconciliation_record_preserves_every_slice_calibration_and_parameter() -> None:
    result = _canned_result(candidate_log=1.028)
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    record = build_reconciliation_record(
        result, CONFIG, provenance=_provenance(), diagnostics=diagnostics
    )
    harness = record["harness"]
    assert isinstance(harness, dict)
    for dimension in (
        "overall",
        "by_fold",
        "by_season",
        "by_position",
        "by_home_away",
        "by_transfer_status",
        "by_player_history_cohort",
    ):
        assert harness[dimension]
    overall = harness["overall"]
    assert isinstance(overall, dict)
    candidate = overall[CANDIDATE]
    assert isinstance(candidate, dict)
    assert candidate["pit_values_count"] == 0
    reliability = candidate["reliability_any_minutes"]
    assert isinstance(reliability, dict)
    assert len(reliability["buckets"]) == 10
    parameters = harness["candidate_parameters_by_fold"]
    assert isinstance(parameters, dict)
    assert parameters["2025-26-GW1"][CANDIDATE]["selected_alpha"] == 5.0

    parsed = json.loads(format_reconciliation_record(record))
    assert parsed["schema"] == "stage_b_candidate_v1_development/v1"
    assert parsed["development_diagnostics"]["combined_promotion_verdict"] is None
    assert parsed["historical_proxy_caveats"]["real_deadline_knowledge_time_validity"] == (
        "unproven"
    )


# --------------------------------------------------------------------------------------
# main() orchestration with monkeypatched offline collaborators
# --------------------------------------------------------------------------------------


class _FakeCon:
    """A stand-in connection that records close and forbids any archive query."""

    def __init__(self, events: list[object]) -> None:
        self._events = events

    def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("no archive access: the connection must not be queried")

    def close(self) -> None:
        self._events.append("close")


def _sandbox(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A clean tmp repo (with a committed candidate source) plus sibling config and db files."""
    repo = _init_repo(tmp_path / "repo")
    source_dir = repo / "src" / "fpl" / "models"
    source_dir.mkdir(parents=True)
    (source_dir / "minutes_v1.py").write_bytes(_real_source_bytes())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "candidate source"], cwd=repo, check=True)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "phase2_evaluation.yaml").write_bytes(_real_config_bytes())
    db = tmp_path / "db.duckdb"
    db.write_bytes(b"archive-bytes")
    assert candidate_source_path(repo) == source_dir / "minutes_v1.py"
    return repo, cfg_dir, db


def _patch_offline(monkeypatch: pytest.MonkeyPatch, repo: Path, cfg_dir: Path) -> None:
    monkeypatch.setattr(dev, "repo_root", lambda: repo)
    monkeypatch.setattr(dev, "config_dir", lambda: cfg_dir)


def test_main_success_path_uses_read_only_and_prints_both_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, cfg_dir, db = _sandbox(tmp_path)
    _patch_offline(monkeypatch, repo, cfg_dir)
    events: list[object] = []
    captured: dict[str, object] = {}

    def fake_connect(path: object, *, read_only: bool = False) -> _FakeCon:
        events.append(("connect", read_only))
        return _FakeCon(events)

    def fake_run(
        con: object, *, config: object, seasons: object, candidate_factory: object
    ) -> None:
        captured["candidate_factory"] = candidate_factory
        captured["ran"] = True
        return _canned_result(candidate_log=1.028)

    real_verify = dev.verify_snapshot

    def verify_wrapper(snapshot: object, **kwargs: object) -> None:
        events.append("verify")
        real_verify(snapshot, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(dev, "connect", fake_connect)
    monkeypatch.setattr(dev, "run_minutes_harness", fake_run)
    monkeypatch.setattr(dev, "verify_snapshot", verify_wrapper)

    rc = dev.main(["--db", str(db)])

    assert rc == 0
    assert captured.get("ran") is True
    out, _err = capsys.readouterr()
    # Both the standard score report and the development report are printed.
    assert "contract" in out  # format_minutes_report header
    assert "DEVELOPMENT ONLY" in out
    assert "DEVELOPMENT DIAGNOSTIC ONLY" in out
    assert "BEGIN_STAGE_B_CANDIDATE_V1_RECONCILIATION_JSON" in out
    assert '"schema": "stage_b_candidate_v1_development/v1"' in out
    assert CANDIDATE in out
    # The database is opened read-only.
    assert ("connect", True) in events
    # The connection is closed BEFORE postflight verification runs.
    assert events.index("close") < events.index("verify")
    # A candidate factory was supplied to the harness (the default CLI supplies none).
    assert callable(captured["candidate_factory"])


def test_main_failure_suppresses_all_output_and_returns_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, cfg_dir, db = _sandbox(tmp_path)
    _patch_offline(monkeypatch, repo, cfg_dir)
    events: list[object] = []

    def fake_connect(path: object, *, read_only: bool = False) -> _FakeCon:
        events.append(("connect", read_only))
        return _FakeCon(events)

    def fake_run(
        con: object, *, config: object, seasons: object, candidate_factory: object
    ) -> None:
        # Simulate the database changing during execution: the postflight recheck must catch it.
        db.write_bytes(b"rebuilt-during-run")
        return _canned_result(candidate_log=1.028)

    real_verify = dev.verify_snapshot

    def verify_wrapper(snapshot: object, **kwargs: object) -> None:
        events.append("verify")
        real_verify(snapshot, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(dev, "connect", fake_connect)
    monkeypatch.setattr(dev, "run_minutes_harness", fake_run)
    monkeypatch.setattr(dev, "verify_snapshot", verify_wrapper)

    rc = dev.main(["--db", str(db)])

    assert rc == 1
    out, err = capsys.readouterr()
    # Neither the standard score output nor the development result is printed after failure.
    assert out == ""
    assert "INVALID" in err
    assert "UNPUBLISHABLE" in err
    # Read-only open, and close happened before the (failing) verification.
    assert ("connect", True) in events
    assert events.index("close") < events.index("verify")


def test_main_performs_no_archive_or_network_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, cfg_dir, db = _sandbox(tmp_path)
    _patch_offline(monkeypatch, repo, cfg_dir)
    events: list[object] = []
    stub_called: list[bool] = []

    def fake_connect(path: object, *, read_only: bool = False) -> _FakeCon:
        events.append(("connect", read_only))
        return _FakeCon(events)  # execute() raises if anything tries to query the archive

    def stub_run(
        con: object, *, config: object, seasons: object, candidate_factory: object
    ) -> None:
        stub_called.append(True)
        return _canned_result(candidate_log=1.028)

    monkeypatch.setattr(dev, "connect", fake_connect)
    monkeypatch.setattr(dev, "run_minutes_harness", stub_run)

    rc = dev.main(["--db", str(db)])

    assert rc == 0
    assert stub_called == [True]  # the stub ran, not the real archive harness
    assert ("connect", True) in events
    # FakeCon.execute raises on any query -> reaching rc == 0 proves no archive access occurred.
