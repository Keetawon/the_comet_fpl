"""Preserve the failed audit's identified transport defect without repairing its run."""

import json
from pathlib import Path

import pytest

from fpl.validate.player_model_gw1_3_audit import _write_json, canonical


def test_invalidated_v1_integer_key_roundtrip_reproducer() -> None:
    source = {"fixture_gameweeks": {1: 1, 2: 1, 10: 1}}
    encoded = canonical(source)
    assert encoded == b'{"fixture_gameweeks":{"1":1,"2":1,"10":1}}\n'
    decoded = json.loads(encoded)
    assert canonical(decoded) == b'{"fixture_gameweeks":{"1":1,"10":1,"2":1}}\n'
    assert canonical(decoded) != encoded


def test_failed_guard_keeps_original_publication_and_refuses_replacement(tmp_path: Path) -> None:
    path = tmp_path / "historical-inputs.json"
    source = {"fixture_gameweeks": {1: 1, 2: 1, 10: 1}}
    with pytest.raises(ValueError, match="canonical artifact replay changed bytes"):
        _write_json(path, source)
    original = path.read_bytes()
    assert original == canonical(source)
    with pytest.raises(FileExistsError):
        _write_json(path, {"replacement": True})
    assert path.read_bytes() == original
