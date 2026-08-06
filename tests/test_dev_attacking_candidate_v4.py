"""Offline tests for the Candidate V4 development runner (``dev_attacking_candidate_v4``).

No network, no archive run. These exercise the provenance-ready pieces that do not require the
database: the V4 factory builds a model with the pinned constants, the contract round-trips at v1.4,
and the file/byte fingerprint helpers are deterministic. The full runner is NOT invoked (it is the
single explicitly authorized clean historical development run, never a test).
"""

from __future__ import annotations

from pathlib import Path

from fpl.config import config_dir, load_phase2_evaluation, load_phase3_evaluation
from fpl.validate.dev_attacking_candidate_v4 import (
    candidate_factory,
    file_sha256,
    hash_bytes,
    load_contract_from_bytes,
)
from fpl.validate.minutes_baselines import MinuteBins

NAME = "exposure_weighted_xg_team_share_attacking_goals_v4"


def test_v4_factory_builds_model_with_pinned_constants() -> None:
    config = load_phase3_evaluation()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    factory = candidate_factory(config, bins)
    model = factory([])
    assert model.name == NAME
    params = model.parameters()
    assert params["alpha"] == 5.0
    assert params["prior_minutes"] == 90.0
    assert params["signal"] == "expected_goals_only_no_fallback"


def test_v4_contract_round_trips_at_1_4() -> None:
    config_path = config_dir() / "phase3_evaluation.yaml"
    contract, fingerprint = load_contract_from_bytes(config_path)
    assert contract.contract_version == "1.4"
    assert contract.stage_c_candidate_v4.name == NAME
    assert len(fingerprint) == 64  # sha256 hex


def test_v4_fingerprint_helpers_are_deterministic(tmp_path: Path) -> None:
    payload = b"candidate v4 provenance fixture\n"
    path = tmp_path / "candidate.py"
    path.write_bytes(payload)
    assert file_sha256(path) == file_sha256(path)
    assert hash_bytes(payload) == hash_bytes(payload)
    assert file_sha256(path) == hash_bytes(payload)
