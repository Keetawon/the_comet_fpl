"""Deterministic OFFLINE tests for the Stage C Candidate V1 development runner.

No network, no built archive. ``main()`` is exercised only with monkeypatched offline
collaborators (a fake read-only connection whose ``execute`` raises, and a stubbed harness
returning a canned result); every other check runs against tiny local files or constructed
result objects. The canned metrics reuse Candidate V1's real historical numbers, but no number
here is a promotion verdict -- the runner records ``combined_promotion_verdict: null``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import duckdb
import pytest

import fpl.validate.dev_attacking_candidate_v1 as dev
from fpl.config import config_dir, load_phase3_evaluation, repo_root
from fpl.storage.db import connect
from fpl.validate.attacking_harness import AttackingHarnessResult
from fpl.validate.attacking_metrics import AttackingScoreReport, ReliabilityBucket, ReliabilityCurve
from fpl.validate.dev_attacking_candidate_v1 import (
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
    head_commit_sha,
    load_contract_from_bytes,
    open_database,
    require_clean_worktree,
    verify_snapshot,
    worktree_is_clean,
)

BASELINES = ("positional_goal_rate_poisson", "trailing_player_goal_rate_poisson")
CANDIDATE = "xg_informed_trailing_player_goals_v1"
COMPARATOR = BASELINES[1]  # the lowest-log baseline in the canned results below
CONFIG = load_phase3_evaluation()


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
    return (config_dir() / "phase3_evaluation.yaml").read_bytes()


def _real_source_bytes() -> bytes:
    return (repo_root() / "src" / "fpl" / "models" / "attacking_v1.py").read_bytes()


def _reliability() -> ReliabilityCurve:
    return ReliabilityCurve(
        tuple(ReliabilityBucket(i / 10, (i + 1) / 10, 0, None, None) for i in range(10))
    )


def _score(
    log: float,
    *,
    rps: float = 0.035129,
    brier: float = 0.031384,
    pit80_err: float = 0.003223,
    pit80_cov: float = 0.80,
    predictions: int = 760,
    exclusions: int = 0,
    cold: int = 0,
) -> AttackingScoreReport:
    return AttackingScoreReport(
        predictions=predictions,
        exclusions=exclusions,
        cold_starts=cold,
        uncertainty=0.01,
        mean_log_score=log,
        mean_ranked_probability_score=rps,
        mean_brier_at_least_one_goal=brier,
        pit_interval_80_coverage=pit80_cov,
        pit_interval_80_error=pit80_err,
        reliability_at_least_one_goal=_reliability(),
    )


def _canned_result(
    *,
    candidate_log: float = 0.137813,
    baseline_log: float = 0.143547,
    folds: int = 181,
    leakage: int = 0,
    seasons: tuple[str, ...] = ("2025-26",),
    season_candidate_log: float | None = None,
    candidate_rps: float = 0.034600,
    candidate_brier: float = 0.030862,
) -> AttackingHarnessResult:
    """A minimal but valid harness result with the two baselines plus the candidate.

    ``COMPARATOR`` is the lowest-log baseline so the comparator is deterministic; the candidate
    is never a required baseline, so it can never be selected as the comparator even when its log
    is lowest. Defaults reuse V1's real historical numbers (development-only, never a verdict).
    """
    positional = _score(0.154512, rps=0.036650, brier=0.032843)
    trailing = _score(baseline_log, rps=0.035129, brier=0.031384)  # comparator (lowest log)
    overall = {
        BASELINES[0]: positional,
        BASELINES[1]: trailing,
        CANDIDATE: _score(candidate_log, rps=candidate_rps, brier=candidate_brier),
    }
    season_cand_log = candidate_log if season_candidate_log is None else season_candidate_log
    by_season: dict[str, dict[str, AttackingScoreReport]] = {}
    for season in seasons:
        season_reports = dict(overall)
        season_reports[CANDIDATE] = _score(
            season_cand_log, rps=candidate_rps, brier=candidate_brier
        )
        by_season[season] = season_reports
    by_fold = {f"{season}-GW01": dict(reports) for season, reports in by_season.items()}
    return AttackingHarnessResult(
        overall=overall,
        by_season=by_season,
        by_position={"FWD": dict(overall)},
        by_home_away={"home": dict(overall)},
        by_fold=by_fold,
        folds_by_season=dict.fromkeys(seasons, folds),
        baseline_names=BASELINES,
        total_predictions=760,
        leakage_failures=leakage,
        best_baseline_name=COMPARATOR,
        candidate_names=(CANDIDATE,),
    )


def _explicit_result(overall_reports: dict[str, AttackingScoreReport]) -> AttackingHarnessResult:
    """A harness result built from explicit per-model scores (per-baseline metrics controlled)."""
    season = "2025-26"
    return AttackingHarnessResult(
        overall=overall_reports,
        by_fold={f"{season}-GW01": dict(overall_reports)},
        by_season={season: dict(overall_reports)},
        by_position={"FWD": dict(overall_reports)},
        by_home_away={"home": dict(overall_reports)},
        folds_by_season={season: 181},
        baseline_names=BASELINES,
        total_predictions=760,
        leakage_failures=0,
        best_baseline_name=COMPARATOR,
        candidate_names=(CANDIDATE,),
    )


def _provenance() -> Provenance:
    return Provenance(
        candidate=CANDIDATE,
        contract_version=CONFIG.contract_version,
        commit_sha="deadbeef" * 5,
        config_fingerprint="c" * 64,
        candidate_source_fingerprint="s" * 64,
        archive_fingerprint="a" * 64,
        seed=202627,
        started_at="2026-07-31T10:00:00Z",
        ended_at="2026-07-31T10:05:00Z",
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
    config_copy = tmp_path / "phase3_evaluation.yaml"
    real = _real_config_bytes()
    config_copy.write_bytes(real)
    contract, fingerprint = load_contract_from_bytes(config_copy)
    assert contract.contract_version == CONFIG.contract_version
    assert fingerprint == file_sha256(config_copy)
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
    config_copy = tmp_path / "phase3_evaluation.yaml"
    config_copy.write_bytes(_real_config_bytes())
    source_copy = tmp_path / "attacking_v1.py"
    source_copy.write_bytes(_real_source_bytes())
    db = tmp_path / "db.duckdb"
    db.write_bytes(b"archive-bytes")
    contract, _ = load_contract_from_bytes(config_copy)
    snapshot = capture_preflight(
        db,
        contract,
        repo=repo,
        config_path=config_copy,
        config_fp=file_sha256(config_copy),
        candidate_source_path=source_copy,
        candidate_source_fp=file_sha256(source_copy),
    )
    return repo, config_copy, source_copy, db, snapshot


def test_capture_preflight_records_every_field_before_evaluation(tmp_path: Path) -> None:
    repo, config_copy, source_copy, db, snapshot = _provenance_fixture(tmp_path)
    assert not hasattr(snapshot, "ended_at")  # preflight has no ended_at
    assert snapshot.candidate == CANDIDATE
    assert snapshot.commit_sha == head_commit_sha(repo)
    assert snapshot.config_fingerprint == file_sha256(config_copy)
    assert snapshot.candidate_source_fingerprint == file_sha256(source_copy)
    assert snapshot.archive_fingerprint == file_sha256(db)
    assert snapshot.seed == 202627
    assert snapshot.started_at.endswith("Z")
    assert snapshot.contract_version == CONFIG.contract_version


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
    provenance = finalize_provenance(snapshot, ended_at="2026-07-31T10:05:00Z")
    assert provenance.started_at == snapshot.started_at
    assert provenance.ended_at == "2026-07-31T10:05:00Z"
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
    assert "started at (UTC)      : 2026-07-31T10:00:00Z" in text
    assert "ended at (UTC)        : 2026-07-31T10:05:00Z" in text
    assert "candidate source fp   : " + "s" * 64 in text


# --------------------------------------------------------------------------------------
# Structured development diagnostics (eight labelled checks, never a verdict)
# --------------------------------------------------------------------------------------


def test_diagnostics_have_eight_labelled_checks() -> None:
    diagnostics: DevelopmentDiagnostics = compute_development_diagnostics(
        _canned_result(), CANDIDATE, CONFIG
    )
    assert diagnostics.comparable is True
    assert diagnostics.comparator == COMPARATOR
    assert [check.name for check in diagnostics.checks] == [
        "aggregate_mean_log_score_lift_at_least_minimum",
        "no_aggregate_ranked_probability_score_regression",
        "no_aggregate_brier_at_least_one_goal_regression",
        "pit_interval_80_absolute_error_at_most_maximum",
        "prediction_coverage_at_least_minimum",
        "folds_evaluated_at_least_minimum",
        "zero_leakage_failures",
        "no_per_season_mean_log_score_regression",
    ]
    # Every check is labelled a development diagnostic, never a verdict.
    assert all(check.label == "DEVELOPMENT DIAGNOSTIC ONLY" for check in diagnostics.checks)


def test_diagnostics_pass_when_candidate_beats_baseline_on_every_condition() -> None:
    result = _canned_result()  # candidate 0.137813, ~3.99% lift over the 0.143547 comparator
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    assert diagnostics.passed_count() == 8
    lines = "\n".join(diagnostics.as_lines())
    assert lines.count("PASS") == 8
    assert "NOT combined into a promotion verdict" in lines


def test_diagnostics_fail_when_lift_below_one_percent() -> None:
    result = _canned_result(candidate_log=0.143547)  # zero lift, below the 1% gate
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    lift_check = next(
        check for check in diagnostics.checks if check.name.startswith("aggregate_mean_log_score")
    )
    assert lift_check.passed is False
    # The non-regression / calibration / count checks still pass on this canned result.
    assert diagnostics.passed_count() == 7


def test_diagnostics_fail_on_a_per_season_regression() -> None:
    result = _canned_result(season_candidate_log=0.20)  # one season regresses
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    season_check = next(
        check
        for check in diagnostics.checks
        if check.name == "no_per_season_mean_log_score_regression"
    )
    assert season_check.passed is False
    assert "1 of 1 seasons regress" in season_check.detail


def test_diagnostics_fail_on_folds_and_leakage() -> None:
    result = _canned_result(folds=180, leakage=1)
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    by_name = {check.name: check for check in diagnostics.checks}
    assert by_name["folds_evaluated_at_least_minimum"].passed is False
    assert by_name["zero_leakage_failures"].passed is False


def test_diagnostics_comparator_is_the_best_required_baseline_not_the_candidate() -> None:
    # Candidate has the lowest log score of all, but it is not a required baseline.
    result = _canned_result(candidate_log=0.10)
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    assert diagnostics.comparator == COMPARATOR
    assert CANDIDATE not in result.baseline_names


def test_diagnostics_not_comparable_when_candidate_absent() -> None:
    full = _canned_result()
    overall = {name: report for name, report in full.overall.items() if name != CANDIDATE}
    result = AttackingHarnessResult(
        overall=overall,
        by_season={},
        by_position={},
        by_home_away={},
        by_fold={},
        folds_by_season=full.folds_by_season,
        baseline_names=BASELINES,
        total_predictions=full.total_predictions,
        leakage_failures=full.leakage_failures,
        best_baseline_name=full.best_baseline_name,
        candidate_names=(),
    )
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    assert diagnostics.comparable is False


def test_rps_guardrail_uses_best_per_metric_baseline_not_the_log_comparator() -> None:
    """The RPS guardrail is the BEST-RPS baseline, not the log comparator. ``positional`` has the
    best (lowest) RPS but a higher log; ``trailing`` is the log comparator. A candidate that beats
    the comparator's RPS but regresses against the best RPS therefore FAILS, while still clearing
    the primary log lift."""
    overall = {
        BASELINES[0]: _score(0.154512, rps=0.034000, brier=0.032843),  # best RPS
        BASELINES[1]: _score(0.143547, rps=0.036000, brier=0.031384),  # log comparator
        CANDIDATE: _score(0.140000, rps=0.035000, brier=0.030862),  # worse than positional RPS
    }
    result = _explicit_result(overall)
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    by_name = {check.name: check for check in diagnostics.checks}
    rps_check = by_name["no_aggregate_ranked_probability_score_regression"]
    assert rps_check.passed is False
    assert BASELINES[0] in rps_check.detail  # positional supplied the best-RPS bar
    assert "regression" in rps_check.detail
    assert by_name["aggregate_mean_log_score_lift_at_least_minimum"].passed is True


# --------------------------------------------------------------------------------------
# Report + reconciliation record (development-only, null combined verdict)
# --------------------------------------------------------------------------------------


def test_report_is_labelled_and_never_a_verdict() -> None:
    result = _canned_result()
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


def test_reconciliation_record_preserves_every_slice_and_null_verdict() -> None:
    result = _canned_result()
    diagnostics = compute_development_diagnostics(result, CANDIDATE, CONFIG)
    record = build_reconciliation_record(
        result, CONFIG, provenance=_provenance(), diagnostics=diagnostics
    )
    harness = record["harness"]
    assert isinstance(harness, dict)
    for dimension in ("overall", "by_fold", "by_season", "by_position", "by_home_away"):
        assert harness[dimension]
    candidate = harness["overall"][CANDIDATE]
    assert isinstance(candidate, dict)
    reliability = candidate["reliability_at_least_one_goal"]
    assert isinstance(reliability, dict)
    assert len(reliability["buckets"]) == 10

    parsed = json.loads(format_reconciliation_record(record))
    assert parsed["schema"] == "stage_c_candidate_v1_development/v1"
    assert parsed["status"] == "development_only_not_a_promotion_result"
    assert parsed["development_diagnostics"]["combined_promotion_verdict"] is None
    assert parsed["historical_proxy_caveats"]["real_deadline_knowledge_time_validity"] == "unproven"


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
    (source_dir / "attacking_v1.py").write_bytes(_real_source_bytes())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "candidate source"], cwd=repo, check=True)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "phase3_evaluation.yaml").write_bytes(_real_config_bytes())
    db = tmp_path / "db.duckdb"
    db.write_bytes(b"archive-bytes")
    assert candidate_source_path(repo) == source_dir / "attacking_v1.py"
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
    ) -> AttackingHarnessResult:
        captured["candidate_factory"] = candidate_factory
        captured["ran"] = True
        return _canned_result()

    real_verify = dev.verify_snapshot

    def verify_wrapper(snapshot: object, **kwargs: object) -> None:
        events.append("verify")
        real_verify(snapshot, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(dev, "connect", fake_connect)
    monkeypatch.setattr(dev, "run_attacking_harness", fake_run)
    monkeypatch.setattr(dev, "verify_snapshot", verify_wrapper)

    rc = dev.main(["--db", str(db)])

    assert rc == 0
    assert captured.get("ran") is True
    out, _err = capsys.readouterr()
    # Both the standard score report and the development report are printed.
    assert "Stage C Attacking Goals" in out  # standard report header
    assert "DEVELOPMENT ONLY" in out
    assert "DEVELOPMENT DIAGNOSTIC ONLY" in out
    assert "BEGIN_STAGE_C_CANDIDATE_V1_RECONCILIATION_JSON" in out
    assert '"schema": "stage_c_candidate_v1_development/v1"' in out
    assert CANDIDATE in out
    # The database is opened read-only.
    assert ("connect", True) in events
    # The connection is closed BEFORE postflight verification runs.
    assert events.index("close") < events.index("verify")
    # A candidate factory was supplied to the harness (the default CLI supplies none).
    assert callable(captured["candidate_factory"])


def test_main_failure_suppresses_all_output_and_writes_no_save_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, cfg_dir, db = _sandbox(tmp_path)
    _patch_offline(monkeypatch, repo, cfg_dir)
    save_path = tmp_path / "out" / "result.json"
    events: list[object] = []

    def fake_connect(path: object, *, read_only: bool = False) -> _FakeCon:
        events.append(("connect", read_only))
        return _FakeCon(events)

    def fake_run(
        con: object, *, config: object, seasons: object, candidate_factory: object
    ) -> AttackingHarnessResult:
        # Simulate the database changing during execution: the postflight recheck must catch it.
        db.write_bytes(b"rebuilt-during-run")
        return _canned_result()

    real_verify = dev.verify_snapshot

    def verify_wrapper(snapshot: object, **kwargs: object) -> None:
        events.append("verify")
        real_verify(snapshot, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(dev, "connect", fake_connect)
    monkeypatch.setattr(dev, "run_attacking_harness", fake_run)
    monkeypatch.setattr(dev, "verify_snapshot", verify_wrapper)

    rc = dev.main(["--db", str(db), "--save-json", str(save_path)])

    assert rc == 1
    out, err = capsys.readouterr()
    # Neither the standard score output nor the development result is printed after failure.
    assert out == ""
    assert "INVALID" in err
    assert "UNPUBLISHABLE" in err
    # No reconciliation save file is written on provenance failure.
    assert not save_path.exists()
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
    ) -> AttackingHarnessResult:
        stub_called.append(True)
        return _canned_result()

    monkeypatch.setattr(dev, "connect", fake_connect)
    monkeypatch.setattr(dev, "run_attacking_harness", stub_run)

    rc = dev.main(["--db", str(db)])

    assert rc == 0
    assert stub_called == [True]  # the stub ran, not the real archive harness
    assert ("connect", True) in events
    # FakeCon.execute raises on any query -> reaching rc == 0 proves no archive access occurred.
