"""Identity/transport binding only; the formal V2 evaluation is never called here."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from fpl.config import repo_root
from fpl.jobs import evaluate_player_model_gw1_3_v2 as v2
from fpl.validate import player_model_gw1_3_audit as v1
from fpl.validate.audit_json import canonical


def test_effective_contract_changes_only_identity_and_output() -> None:
    root = repo_root()
    base = yaml.safe_load((root / "config/player_model_gw1_3_audit.yaml").read_bytes())
    effective = v2.load_effective_contract(root)
    assert {k for k in base if base[k] != effective[k]} == {"audit_id", "default_output_dir"}
    assert effective["audit_id"] == "player_model_gw1_3_20260908_v2"
    assert Path(effective["default_output_dir"]).name == "formal-v2"
    assert effective["model_freeze_sha"] == "17cfa2267ce4d7c89f96842220f40471b81152d2"
    assert effective["inference"] == base["inference"]
    assert effective["scoring"] == base["scoring"]
    assert effective["cutoffs"] == base["cutoffs"]
    assert effective["verdict_policy"] == base["verdict_policy"]


@pytest.mark.parametrize("failed", [False, True])
def test_scoped_transport_identity_restores_without_changing_audit_body(
    monkeypatch: pytest.MonkeyPatch, failed: bool
) -> None:
    original = {
        name: getattr(v1, name)
        for name in (
            "canonical",
            "CONFIG",
            "CONFIG_SHA256",
            "AUDIT_ID",
            "IMPLEMENTATION",
            "load_contract",
        )
    }
    calls = []

    def unchanged_body(repo: Path) -> dict[str, Any]:
        calls.append(repo)
        assert v1.canonical is canonical
        assert v1.AUDIT_ID == v2.AUDIT_ID
        assert v1.CONFIG == v2.CONFIG
        assert v1.CONFIG_SHA256 == v2.CONFIG_SHA256
        assert all(path in v1.IMPLEMENTATION for path in original["IMPLEMENTATION"])
        assert "src/fpl/validate/audit_json.py" in v1.IMPLEMENTATION
        value = {1: {10: 3, 2: 4}}
        assert v1.canonical(value) == v1.canonical(json.loads(v1.canonical(value)))
        if failed:
            raise RuntimeError("synthetic failure")
        return {"status": "synthetic success"}

    monkeypatch.setattr(v1, "run_audit", unchanged_body)
    if failed:
        with pytest.raises(RuntimeError, match="synthetic failure"):
            v2.run_v2(repo_root())
    else:
        assert v2.run_v2(repo_root()) == {"status": "synthetic success"}
    assert len(calls) == 1
    assert {name: getattr(v1, name) for name in original} == original
