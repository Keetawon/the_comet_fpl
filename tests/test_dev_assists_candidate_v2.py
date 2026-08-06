"""Offline tests for the assists Candidate V2 development runner (``dev_assists_candidate_v2``).

No network, no archive run. Exercises the provenance-ready pieces that do not require the database:
the V2 factory builds a model with the pinned constants, the assists contract round-trips at v1.2,
and the fingerprint helpers are deterministic. The full runner is NOT invoked.
"""

from __future__ import annotations

from pathlib import Path

from fpl.config import config_dir, load_phase2_evaluation, load_phase3_stage_c_assists_evaluation
from fpl.validate.dev_assists_candidate_v2 import (
    candidate_factory,
    file_sha256,
    hash_bytes,
    load_contract_from_bytes,
)
from fpl.validate.minutes_baselines import MinuteBins

NAME = "exposure_weighted_xa_team_share_assists_v2"


def test_v2_factory_builds_model_with_pinned_constants() -> None:
    config = load_phase3_stage_c_assists_evaluation()
    bins = MinuteBins.from_config(load_phase2_evaluation())
    factory = candidate_factory(config, bins)
    model = factory([])
    assert model.name == NAME
    params = model.parameters()
    assert params["alpha"] == 5.0
    assert params["prior_minutes"] == 90.0
    assert params["signal"] == "expected_assists_only_no_fallback"


def test_v2_contract_round_trips_at_1_2() -> None:
    config_path = config_dir() / "phase3_stage_c_assists_evaluation.yaml"
    contract, fingerprint = load_contract_from_bytes(config_path)
    assert contract.contract_version == "1.2"
    assert contract.stage_c_assists_candidate_v2 is not None
    assert contract.stage_c_assists_candidate_v2.name == NAME
    assert len(fingerprint) == 64


def test_v2_fingerprint_helpers_are_deterministic(tmp_path: Path) -> None:
    payload = b"candidate v2 provenance fixture\n"
    path = tmp_path / "candidate.py"
    path.write_bytes(payload)
    assert file_sha256(path) == file_sha256(path)
    assert hash_bytes(payload) == hash_bytes(payload)
    assert file_sha256(path) == hash_bytes(payload)
