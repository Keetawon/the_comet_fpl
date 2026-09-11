"""New identity and repaired transport around the unchanged frozen V1 audit body."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from fpl.config import repo_root
from fpl.jobs.competitive_participation_pilot import file_sha256
from fpl.validate import player_model_gw1_3_audit as v1
from fpl.validate.audit_json import canonical

CONFIG = "config/player_model_gw1_3_audit_v2.yaml"
CONFIG_SHA256 = "f7a5593b472ac2a8b9fa592fa4b97d7e6fe7a57e86c23b94d64227f489690e09"
AUDIT_ID = "player_model_gw1_3_20260908_v2"
IMPLEMENTATION = (
    *v1.IMPLEMENTATION,
    CONFIG,
    "src/fpl/validate/audit_json.py",
    "src/fpl/jobs/evaluate_player_model_gw1_3_v2.py",
    "docs/player-model-gw1-3-preregistration-v2-2026-09-08.md",
)


def load_effective_contract(repo: Path) -> dict[str, Any]:
    """Inherit every scientific value; change only the run identity and output path."""
    if file_sha256(repo / CONFIG) != CONFIG_SHA256:
        raise ValueError("V2 identity configuration differs from preregistration")
    identity = yaml.safe_load((repo / CONFIG).read_bytes())
    for name in ("base_config", "v1_verification", "v1_scorecard", "serializer"):
        path = identity["serializer_source" if name == "serializer" else name]
        if file_sha256(repo / path) != identity[f"{name}_sha256"]:
            raise ValueError(f"frozen {name} bytes changed")
    verification = json.loads((repo / identity["v1_verification"]).read_bytes())
    for group in (
        "frozen_files_sha256",
        "preregistered_implementation_sha256",
        "result_artifact_sha256",
    ):
        for name, digest in verification[group].items():
            if file_sha256(repo / name) != digest:
                raise ValueError(f"frozen V1 source/model/result changed: {name}")
    for name, receipt in verification["original_receipts"].items():
        if file_sha256(Path(verification["external_receipts_root"]) / name) != receipt["sha256"]:
            raise ValueError(f"original invalid V1 receipt changed: {name}")
    base = yaml.safe_load((repo / identity["base_config"]).read_bytes())
    result = dict(base)
    result["audit_id"] = AUDIT_ID
    result["default_output_dir"] = str(
        Path(base["default_output_dir"]).parent / identity["output_directory_name"]
    )
    if sorted(key for key in result if result[key] != base[key]) != sorted(
        identity["allowed_effective_config_changes"]
    ):
        raise ValueError("only V2 identity/output changes are authorized")
    return result


def run_v2(repo: Path) -> dict[str, Any]:
    """Restore V1 bindings even on failure; never reopen its reserved claim."""
    with patch.multiple(
        v1,
        CONFIG=CONFIG,
        CONFIG_SHA256=CONFIG_SHA256,
        AUDIT_ID=AUDIT_ID,
        IMPLEMENTATION=IMPLEMENTATION,
        canonical=canonical,
        load_contract=load_effective_contract,
    ):
        result = v1.run_audit(repo)
        load_effective_contract(repo)  # Original V1 receipts must also survive the new run.
        return result


def main() -> None:
    run_v2(repo_root())


if __name__ == "__main__":
    main()
