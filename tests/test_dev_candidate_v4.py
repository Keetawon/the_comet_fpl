"""Candidate V4 development runner: provenance and the dirty-worktree refusal (V3 defect 4).

These tests exercise the runner's provenance helpers directly. They never start a V4 historical
evaluation: `main()` is not called, and the harness is not run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from fpl.config import config_dir, load_phase1_evaluation
from fpl.validate.dev_candidate_v4 import (
    Provenance,
    ProvenanceError,
    build_provenance,
    config_fingerprint,
    file_sha256,
    format_development_report,
    hash_bytes,
    head_commit_sha,
    load_contract_from_bytes,
    require_clean_worktree,
    verify_provenance,
    worktree_is_clean,
)
from fpl.validate.harness import HarnessResult
from fpl.validate.metrics import ScoreReport


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


def test_worktree_is_clean_for_a_freshly_committed_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    assert worktree_is_clean(repo) is True


def test_require_clean_worktree_passes_when_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    require_clean_worktree(repo)  # must not raise


def test_require_clean_worktree_refuses_a_dirty_tree(tmp_path: Path) -> None:
    """The V3 defect 4 fix: a dirty worktree is a hard stop, never a recorded clean SHA."""
    repo = _init_repo(tmp_path)
    (repo / "uncommitted.txt").write_text("change", encoding="utf-8")
    assert worktree_is_clean(repo) is False
    with pytest.raises(SystemExit, match="dirty"):
        require_clean_worktree(repo)


def test_head_commit_sha_reads_the_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    rev_parse = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
    assert head_commit_sha(repo) == rev_parse


def test_file_sha256_is_stable_and_order_independent(tmp_path: Path) -> None:
    payload = b"x" * 100000 + b"tail"
    (tmp_path / "blob").write_bytes(payload)
    digest = file_sha256(tmp_path / "blob")
    assert digest == file_sha256(tmp_path / "blob")
    assert len(digest) == 64
    # A different file hashes differently.
    (tmp_path / "other").write_bytes(b"y" * 100000)
    assert file_sha256(tmp_path / "other") != digest


def test_config_fingerprint_hashes_the_phase1_contract() -> None:
    assert config_fingerprint() == file_sha256(config_dir() / "phase1_evaluation.yaml")
    assert len(config_fingerprint()) == 64


def test_provenance_lists_every_recorded_field() -> None:
    provenance = Provenance(
        candidate="dynamic_team_goals_v4",
        contract_version="1.5",
        commit_sha="deadbeef" * 5,
        config_fingerprint="c" * 64,
        archive_fingerprint="a" * 64,
        seed=202627,
        captured_at="2026-07-28T00:00:00Z",
    )
    text = "\n".join(provenance.as_lines())
    for needle in (
        "dynamic_team_goals_v4",
        "1.5",
        "deadbeef",
        "c" * 64,
        "a" * 64,
        "202627",
        "2026-07-28T00:00:00Z",
    ):
        assert needle in text


def test_build_provenance_reads_contract_and_repo(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    contract = load_phase1_evaluation()
    (tmp_path / "db.duckdb").write_bytes(b"archive-bytes")
    provenance = build_provenance(tmp_path / "db.duckdb", contract, repo=repo)
    assert provenance.candidate == "dynamic_team_goals_v4"
    assert provenance.contract_version == contract.contract_version
    assert provenance.seed == contract.training.seed
    assert provenance.commit_sha == head_commit_sha(repo)
    assert provenance.archive_fingerprint == file_sha256(tmp_path / "db.duckdb")


# --------------------------------------------------------------------------------------
# Development report: never a promotion verdict
# --------------------------------------------------------------------------------------


def _score(name: str, log: float, *, cold: int = 0) -> ScoreReport:
    return ScoreReport(
        name=name,
        predictions=760,
        eligible_predictions=760,
        exclusions=0,
        cold_starts=cold,
        mean_log_score=log,
        mean_log_score_standard_error=0.01,
        mean_crps=0.64,
        mean_poisson_deviance=1.12,
        interval_80_coverage=0.93,
        pit_interval_80_coverage=0.80,
        mean_absolute_error=0.94,
        mean_predictive_variance=1.20,
        spearman_within_gameweek=0.3,
        pit_values=(),
    )


def _result() -> HarnessResult:
    baseline = _score("trailing_goals_attack_defence", 1.5003)
    candidate = _score("dynamic_team_goals_v4", 1.4600, cold=84)
    return HarnessResult(
        folds_evaluated=181,
        folds_by_season={"2025-26": 38},
        predictions=760,
        eligible_predictions=760,
        leakage_failures=0,
        required_baselines=frozenset({"trailing_goals_attack_defence"}),
        overall={baseline.name: baseline, candidate.name: candidate},
        by_fold={},
        by_season={"2025-26": {baseline.name: baseline, candidate.name: candidate}},
        by_promoted_status={},
        by_home_away={},
        parameters_by_fold={
            "2025-26-GW1": {
                "dynamic_team_goals_v4": {
                    "learning_rate": 0.05,
                    "retention": 0.995,
                    "season_retention": 0.5,
                    "used_inner_holdout": True,
                }
            }
        },
    )


def test_the_development_report_is_labelled_and_never_a_verdict() -> None:
    contract = load_phase1_evaluation()
    provenance = Provenance(
        candidate="dynamic_team_goals_v4",
        contract_version=contract.contract_version,
        commit_sha="deadbeef" * 5,
        config_fingerprint="c" * 64,
        archive_fingerprint="a" * 64,
        seed=contract.training.seed,
        captured_at="2026-07-28T00:00:00Z",
    )
    text = format_development_report(
        _result(), "dynamic_team_goals_v4", contract, provenance=provenance
    )
    assert "DEVELOPMENT ONLY" in text
    assert "NOT A PROMOTION RESULT" in text
    assert "trailing_goals_attack_defence" in text
    # Provenance is embedded so the number is tied to a frozen triple.
    assert "deadbeef" in text
    assert "lift" in text


# --------------------------------------------------------------------------------------
# Provenance revalidation: the (code, config, data) triple is re-checked before print
# --------------------------------------------------------------------------------------


def _provenance_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Provenance]:
    """A clean repo plus sibling (config, db) files and the provenance captured over them.

    The config and db live outside the repo dir so editing them does not dirty the worktree,
    letting each revalidation failure be isolated to the dimension it simulates.
    """
    repo = _init_repo(tmp_path / "repo")
    config_copy = tmp_path / "phase1_evaluation.yaml"
    config_copy.write_bytes((config_dir() / "phase1_evaluation.yaml").read_bytes())
    db = tmp_path / "db.duckdb"
    db.write_bytes(b"archive-bytes")
    contract = load_phase1_evaluation()
    provenance = build_provenance(db, contract, repo=repo, config_path=config_copy)
    return repo, config_copy, db, provenance


def test_verify_provenance_passes_when_unchanged(tmp_path: Path) -> None:
    repo, config_copy, db, provenance = _provenance_fixture(tmp_path)
    verify_provenance(provenance, db_path=db, repo=repo, config_path=config_copy)  # must not raise


def test_verify_provenance_aborts_on_a_dirty_worktree(tmp_path: Path) -> None:
    repo, config_copy, db, provenance = _provenance_fixture(tmp_path)
    (repo / "uncommitted.txt").write_text("change", encoding="utf-8")
    with pytest.raises(ProvenanceError, match="dirty"):
        verify_provenance(provenance, db_path=db, repo=repo, config_path=config_copy)


def test_verify_provenance_aborts_on_a_head_change(tmp_path: Path) -> None:
    repo, config_copy, db, provenance = _provenance_fixture(tmp_path)
    (repo / "new.txt").write_text("second commit", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=repo, check=True)
    with pytest.raises(ProvenanceError, match="HEAD"):
        verify_provenance(provenance, db_path=db, repo=repo, config_path=config_copy)


def test_verify_provenance_aborts_on_a_config_change(tmp_path: Path) -> None:
    repo, config_copy, db, provenance = _provenance_fixture(tmp_path)
    config_copy.write_bytes(b"# altered contract bytes\n")
    with pytest.raises(ProvenanceError, match="config"):
        verify_provenance(provenance, db_path=db, repo=repo, config_path=config_copy)


def test_verify_provenance_aborts_on_a_database_change(tmp_path: Path) -> None:
    repo, config_copy, db, provenance = _provenance_fixture(tmp_path)
    db.write_bytes(b"rebuilt-bytes")
    with pytest.raises(ProvenanceError, match="database"):
        verify_provenance(provenance, db_path=db, repo=repo, config_path=config_copy)


def test_load_contract_from_bytes_fingerprints_the_exact_parsed_bytes(tmp_path: Path) -> None:
    """The config fingerprint is the hash of the exact bytes the contract was parsed from, so
    there is no load-then-hash window in which the file could change between the two."""
    config_copy = tmp_path / "phase1_evaluation.yaml"
    real = (config_dir() / "phase1_evaluation.yaml").read_bytes()
    config_copy.write_bytes(real)
    contract, fingerprint = load_contract_from_bytes(config_copy)
    assert contract.contract_version == "1.5"
    assert fingerprint == file_sha256(config_copy)
    assert fingerprint == hash_bytes(real)
    # Editing the bytes -- even a no-op comment -- changes the fingerprint, so any mid-run
    # edit is detectable even when it leaves the parsed contract identical.
    config_copy.write_bytes(real + b"\n# trailing comment\n")
    _, edited = load_contract_from_bytes(config_copy)
    assert edited != fingerprint
