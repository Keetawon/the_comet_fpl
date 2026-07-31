"""Deterministic OFFLINE tests for the Stage B Candidate V3 development runner.

The V3 runner reuses the V1 runner's provenance machinery, the shared best-per-metric gate, and the
harness -- all already tested via test_dev_minutes_candidate_v1.py. These tests pin only the V3
wiring: the candidate name, the V3 model-source path it fingerprints, and the V3 reconciliation
schema, all exercised through ``main()`` with monkeypatched offline collaborators and no archive.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import fpl.validate.dev_minutes_candidate_v1 as dev1
import fpl.validate.dev_minutes_candidate_v3 as dev3
from fpl.config import config_dir, repo_root
from fpl.validate.dev_minutes_candidate_v3 import candidate_source_path
from fpl.validate.minutes_harness import MinutesHarnessResult
from fpl.validate.minutes_metrics import (
    MinutesScoreReport,
    ReliabilityBucket,
    ReliabilityCurve,
)

CANDIDATE = "concentration_adaptive_shrinkage_player_minutes_v3"
BASELINES = (
    "position_minutes_frequency",
    "last_observed_player_minutes",
    "trailing_5_player_minutes",
    "trailing_5_team_position_minutes",
)
COMPARATOR = BASELINES[0]


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    (path / "f.txt").write_text("hi", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)
    return path


def _reliability() -> ReliabilityCurve:
    return ReliabilityCurve(
        tuple(ReliabilityBucket(i / 10, (i + 1) / 10, 0, None, None) for i in range(10))
    )


def _score(name: str, log: float, **overrides: float) -> MinutesScoreReport:
    fields = {
        "name": name,
        "predictions": 760,
        "eligible_predictions": 760,
        "exclusions": 0,
        "cold_starts": 0,
        "mean_log_score": log,
        "mean_log_score_standard_error": 0.01,
        "mean_ranked_probability_score": 0.40,
        "mean_brier_any_minutes": 0.18,
        "mean_brier_60_plus": 0.18,
        "pit_interval_80_coverage": 0.80,
        "pit_values": (),
        "reliability_any_minutes": _reliability(),
        "reliability_60_plus": _reliability(),
        "spearman_p60_within_position_gameweek": 0.72,
        "prediction_coverage": 1.0,
    }
    fields.update(overrides)
    return MinutesScoreReport(**fields)  # type: ignore[arg-type]


def _canned_result() -> MinutesHarnessResult:
    overall = {
        COMPARATOR: _score(COMPARATOR, 1.04916),
        BASELINES[1]: _score(BASELINES[1], 1.55, spearman_p60_within_position_gameweek=0.71),
        BASELINES[2]: _score(BASELINES[2], 1.45, spearman_p60_within_position_gameweek=0.70),
        BASELINES[3]: _score(BASELINES[3], 1.65),
        CANDIDATE: _score(CANDIDATE, 1.028, spearman_p60_within_position_gameweek=0.72),
    }
    return MinutesHarnessResult(
        folds_evaluated=181,
        folds_by_season={"2025-26": 1},
        predictions=760,
        eligible_predictions=760,
        leakage_failures=0,
        required_baselines=frozenset(BASELINES),
        overall=overall,
        by_fold={"2025-26-GW1": dict(overall)},
        by_season={"2025-26": dict(overall)},
        by_position={"MID": dict(overall)},
        by_home_away={"home": dict(overall)},
        by_transfer_status={"same_team_code_as_last_observed_fixture": dict(overall)},
        by_player_history_cohort={"prior_positive_minutes": dict(overall)},
        parameters_by_fold={},
    )


class _FakeCon:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def execute(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("no archive access: the connection must not be queried")

    def close(self) -> None:
        self._events.append("close")


def _sandbox(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A clean tmp repo with a committed V3 candidate source, plus sibling config and db files."""
    repo = _init_repo(tmp_path / "repo")
    source_dir = repo / "src" / "fpl" / "models"
    source_dir.mkdir(parents=True)
    (source_dir / "minutes_v3.py").write_bytes(
        (repo_root() / "src" / "fpl" / "models" / "minutes_v3.py").read_bytes()
    )
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "v3 source"], cwd=repo, check=True)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "phase2_evaluation.yaml").write_bytes(
        (config_dir() / "phase2_evaluation.yaml").read_bytes()
    )
    db = tmp_path / "db.duckdb"
    db.write_bytes(b"archive-bytes")
    assert candidate_source_path(repo) == source_dir / "minutes_v3.py"
    return repo, cfg_dir, db


def test_candidate_source_path_targets_minutes_v3() -> None:
    assert (
        candidate_source_path(repo_root())
        == repo_root() / "src" / "fpl" / "models" / "minutes_v3.py"
    )


def test_main_success_path_prints_v3_schema_and_uses_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo, cfg_dir, db = _sandbox(tmp_path)
    monkeypatch.setattr(dev3, "repo_root", lambda: repo)
    monkeypatch.setattr(dev3, "config_dir", lambda: cfg_dir)
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
        return _canned_result()

    real_verify = dev3.verify_snapshot

    def verify_wrapper(snapshot: object, **kwargs: object) -> None:
        events.append("verify")
        real_verify(snapshot, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(dev1, "connect", fake_connect)
    monkeypatch.setattr(dev3, "run_minutes_harness", fake_run)
    monkeypatch.setattr(dev3, "verify_snapshot", verify_wrapper)

    rc = dev3.main(["--db", str(db)])

    assert rc == 0
    out, _err = capsys.readouterr()
    # The V3 reconciliation schema and candidate name are emitted, not V1's/V2's.
    assert "BEGIN_STAGE_B_CANDIDATE_V3_RECONCILIATION_JSON" in out
    assert '"schema": "stage_b_candidate_v3_development/v1"' in out
    assert CANDIDATE in out
    assert "DEVELOPMENT ONLY" in out
    assert "DEVELOPMENT DIAGNOSTIC ONLY" in out
    # The starter-ranking gate (shared) is reported and the V3 candidate (0.72) clears it.
    assert "no_aggregate_spearman_p60_regression" in out
    # Read-only open, and the connection closed before postflight verification.
    assert ("connect", True) in events
    assert events.index("close") < events.index("verify")
    # A V3 candidate factory was supplied to the harness.
    assert callable(captured["candidate_factory"])
    # No V1/V2 schema leaks into the V3 output.
    assert "stage_b_candidate_v1_development" not in out
    assert "stage_b_candidate_v2_development" not in out


def test_main_performs_no_archive_or_network_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, cfg_dir, db = _sandbox(tmp_path)
    monkeypatch.setattr(dev3, "repo_root", lambda: repo)
    monkeypatch.setattr(dev3, "config_dir", lambda: cfg_dir)
    events: list[object] = []

    def fake_connect(path: object, *, read_only: bool = False) -> _FakeCon:
        events.append(("connect", read_only))
        return _FakeCon(events)  # execute() raises on any query

    monkeypatch.setattr(dev1, "connect", fake_connect)
    monkeypatch.setattr(dev3, "run_minutes_harness", lambda *a, **k: _canned_result())

    rc = dev3.main(["--db", str(db)])
    assert rc == 0
    assert ("connect", True) in events  # reaching rc == 0 proves no archive access occurred
