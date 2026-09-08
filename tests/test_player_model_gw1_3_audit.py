"""Transaction ordering and immutable evidence guards; no real scoring/data access."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import duckdb
import pytest

from fpl.validate import player_model_gw1_3_audit as audit


def _manifest(tmp_path: Path) -> dict[str, Any]:
    rows = []
    for lane in audit.LANES:
        for gw in (1, 2, 3):
            for model in ("current", "incumbent"):
                row: dict[str, Any] = {"lane": lane, "gw": gw, "model": model}
                for field in ("forecast", "diagnostics"):
                    name = f"{lane}-{gw}-{model}-{field}.json"
                    payload = audit.canonical({"gw": gw, "model": model})
                    (tmp_path / name).write_bytes(payload)
                    row[field + "_file"] = name
                    row[field + "_sha256"] = hashlib.sha256(payload).hexdigest()
                rows.append(row)
    return {"status": "ALL_PREDICTIONS_FROZEN", "artifacts": rows}


def test_complete_prediction_manifest_and_canonical_replay(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    audit.verify_prediction_freeze(tmp_path, manifest)
    encoded = audit.canonical(manifest)
    assert audit.canonical(json.loads(encoded)) == encoded


@pytest.mark.parametrize("defect", ["missing", "duplicate", "changed", "unfinished", "path"])
def test_partial_or_changed_forecast_cannot_unlock_outcomes(tmp_path: Path, defect: str) -> None:
    manifest = _manifest(tmp_path)
    if defect == "missing":
        manifest["artifacts"].pop()
    elif defect == "duplicate":
        manifest["artifacts"].append(manifest["artifacts"][0])
    elif defect == "changed":
        (tmp_path / manifest["artifacts"][0]["forecast_file"]).write_bytes(b"{}")
    elif defect == "unfinished":
        manifest["status"] = "PARTIAL"
    else:
        manifest["artifacts"][0]["forecast_file"] = "../outside.json"
    with pytest.raises(ValueError, match=r"frozen|duplicate|receipt|predictions|bytes"):
        audit.verify_prediction_freeze(tmp_path, manifest)


def test_receipts_are_write_once_and_nonfinite_rejected(tmp_path: Path) -> None:
    path = tmp_path / "receipt.json"
    audit._write_json(path, {"known_at": datetime(2026, 9, 8, tzinfo=UTC)})
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        audit._write_json(path, {"replacement": True})
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match="Out of range float"):
        audit.canonical({"value": float("nan")})


def test_cutoff_requires_exact_preregistered_sources() -> None:
    info = {
        "registry_count": 5,
        "target_fixture_ids": [1],
        "registry_capture_ids": ["raw"],
        "bootstrap_capture_id": "raw",
        "history_capture_ids": [],
    }
    expected = {
        "expected_players": 5,
        "expected_fixtures": 1,
        "registry_capture_id": "raw",
        "history_capture_id": None,
    }
    audit._verify_cutoff(info, expected)
    info["history_capture_ids"] = ["later"]
    with pytest.raises(ValueError, match="history source"):
        audit._verify_cutoff(info, expected)


def _mock_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict[str, Any], list[str]]:
    from fpl.validate import player_model_gw1_3_metrics as metrics
    from fpl.validate import player_model_gw1_3_replay as replay
    from fpl.validate import player_model_gw1_3_sources as sources
    from fpl.validate import sdp_counterfactual as counterfactual

    output = tmp_path / "formal"
    contract: dict[str, Any] = {
        "default_source_database": "frozen.duckdb",
        "default_output_dir": str(output),
        "season": "2026-27",
        "evidence_as_of": "2026-09-08T00:00:00+00:00",
        "outcome_capture_id": "official",
        "cutoffs": [
            {"gw": gw, "as_of": f"2026-08-{20 + gw:02d}T00:00:00+00:00"} for gw in (1, 2, 3)
        ],
    }
    calls: list[str] = []
    monkeypatch.setattr(audit, "load_contract", lambda _: contract)
    monkeypatch.setattr(audit, "verify_freeze", lambda *_: {"model_freeze_sha": "frozen"})
    monkeypatch.setattr(audit, "_verify_cutoff", lambda *_: None)
    monkeypatch.setattr(audit, "reserve_program_claim", lambda *_: tmp_path / "claim")

    class Connection:
        def __enter__(self) -> Connection:
            return self

        def __exit__(self, *_: object) -> None:
            pass

    monkeypatch.setattr(duckdb, "connect", lambda *_, **__: Connection())
    monkeypatch.setattr(sources, "inspect_cutoff", lambda *_, **__: {"fixture_gameweeks": {1: 1}})
    monkeypatch.setattr(counterfactual, "load_counterfactual_inputs", lambda *_, **__: object())

    def forecast(*_: object, **kwargs: Any) -> dict[str, Any]:
        calls.append("forecast")
        return {
            "pair_invariants": {"equal": True},
            **{
                model: {
                    "predictions": [{"gw": kwargs["gw"]}],
                    "artifact_bytes": b"frozen\n",
                    "provenance": {"source_known_at": "actual"},
                }
                for model in ("current", "incumbent")
            },
        }

    def outcomes(*_: object, **__: object) -> list[dict[str, Any]]:
        assert calls == ["forecast"] * 6
        manifest = json.loads((output / "prediction-freeze.json").read_bytes())
        audit.verify_prediction_freeze(output, manifest)
        calls.append("outcomes")
        return []

    monkeypatch.setattr(replay, "replay_gameweek", forecast)
    monkeypatch.setattr(sources, "load_official_outcomes", outcomes)
    monkeypatch.setattr(metrics, "score_predictions", lambda *_: {"scored": True})
    monkeypatch.setattr(metrics, "paired_comparison", lambda *_: {"equal": True})
    return contract, calls


def test_all_lanes_and_whole_gws_freeze_before_outcome_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    contract, calls = _mock_run(monkeypatch, tmp_path)
    result = audit.run_audit(tmp_path)
    assert result["status"] == "COMPLETE"
    assert calls == ["forecast"] * 6 + ["outcomes"]
    assert len(list(Path(contract["default_output_dir"]).glob("*.jsonl"))) == 12
    with pytest.raises(FileExistsError):
        audit.run_audit(tmp_path)
    assert calls == ["forecast"] * 6 + ["outcomes"]


def test_inference_failure_keeps_identity_and_never_exposes_outcomes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from fpl.validate import player_model_gw1_3_replay as replay
    from fpl.validate import player_model_gw1_3_sources as sources

    contract, _ = _mock_run(monkeypatch, tmp_path)
    outcome_reader = Mock(side_effect=AssertionError("must not read outcomes"))
    monkeypatch.setattr(sources, "load_official_outcomes", outcome_reader)
    monkeypatch.setattr(replay, "replay_gameweek", Mock(side_effect=ValueError("model bug")))
    with pytest.raises(ValueError, match="model bug"):
        audit.run_audit(tmp_path)
    outcome_reader.assert_not_called()
    path = Path(contract["default_output_dir"])
    invalid = json.loads((path / "invalid-run.json").read_bytes())
    assert invalid["resume_permitted"] is False
    assert invalid["stage"] == "forecast_strict_gw1"
    with pytest.raises(FileExistsError):
        audit.run_audit(tmp_path)


def test_frozen_source_guard_rejects_changed_model_before_inference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    model = tmp_path / "model.py"
    model.write_bytes(b"changed")
    monkeypatch.setattr(
        audit,
        "_git",
        lambda _, *args: (
            "" if args[0] == "status" else audit.BRANCH if args[0] == "branch" else "commit"
        ),
    )
    monkeypatch.setattr(subprocess, "run", lambda *_, **__: SimpleNamespace(returncode=0))
    with pytest.raises(ValueError, match="frozen science/model"):
        audit.verify_freeze(
            tmp_path,
            {
                "model_freeze_sha": "old",
                "frozen_files_sha256": {"model.py": hashlib.sha256(b"original").hexdigest()},
            },
        )
