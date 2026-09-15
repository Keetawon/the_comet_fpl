"""Serializer-only regression checks; no player inference or outcome loading."""

import hashlib
import itertools
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

import pytest

from fpl.config import repo_root
from fpl.validate import player_model_gw1_3_audit as v1
from fpl.validate.audit_json import canonical


@pytest.mark.parametrize(
    "value",
    [
        {1: 1, 2: 1, 10: 1},
        {3: [{10: {2: None, 1: True}}, {1: (2, 3)}]},
        {
            "null": None,
            "bool": False,
            "int": -3,
            "float": -0.0,
            "unicode": "\u00e9\u0e01",
            "time": datetime(2026, 9, 8, tzinfo=UTC),
            "tuple": (1, None, {10: 0.25}),
            "mapping": MappingProxyType({2: "b", 1: "a"}),
        },
    ],
)
def test_json_roundtrip_is_byte_identical(value: object) -> None:
    encoded = canonical(value)
    assert canonical(json.loads(encoded)) == encoded
    assert encoded.endswith(b"\n") and not encoded.endswith(b"\n\n")


def test_normalized_keys_sort_lexically_before_first_encoding() -> None:
    assert canonical({1: 1, 2: 1, 10: 1}) == b'{"1":1,"10":1,"2":1}\n'
    assert canonical({"2": 1, "1": 1, "10": 1}) == canonical({1: 1, 2: 1, 10: 1})


@pytest.mark.parametrize("value", [{1: "a", "1": "b"}, {"nested": [{10: 1, "10": 2}]}])
def test_key_collisions_fail_closed(value: object) -> None:
    with pytest.raises(ValueError, match="ambiguous audit JSON mapping key"):
        canonical(value)


@pytest.mark.parametrize("key", [True, None, 1.25, (1, 2)])
def test_unsupported_key_types_fail_closed(key: object) -> None:
    with pytest.raises(TypeError, match="keys must be strings or integers"):
        canonical({key: "value"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_values_remain_rejected(value: float) -> None:
    with pytest.raises(ValueError, match="Out of range float"):
        canonical({1: [value]})


def test_insertion_order_and_separate_processes_are_deterministic() -> None:
    items = [(1, {20: True, 3: None}), (2, [0.25]), (10, "\u00e9")]
    expected = canonical(dict(items))
    for permutation in itertools.permutations(items):
        assert canonical(dict(permutation)) == expected
    script = (
        "import sys; from fpl.validate.audit_json import canonical; "
        "sys.stdout.buffer.write(canonical({10:'\\u00e9',2:[0.25],1:{3:None,20:True}}))"
    )
    for _ in range(2):
        assert subprocess.check_output([sys.executable, "-c", script]) == expected


def test_existing_write_once_publisher_keeps_byte_verification(tmp_path: Path) -> None:
    path = tmp_path / "metadata.json"
    with patch.object(v1, "canonical", canonical):
        digest = v1._write_json(path, {2: 1, 10: 1, 1: 1})
        first = path.read_bytes()
        assert hashlib.sha256(first).hexdigest() == digest
        assert canonical(json.loads(first)) == first
        with pytest.raises(FileExistsError):
            v1._write_json(path, {1: "changed"})
        assert path.read_bytes() == first
        collision = tmp_path / "collision.json"
        with pytest.raises(ValueError, match="ambiguous"):
            v1._write_json(collision, {1: "a", "1": "b"})
        assert not collision.exists()


def test_original_v1_records_and_frozen_model_configs_remain_unchanged() -> None:
    root = repo_root()
    path = root / "results/player_model_gw1_3_verification_2026-09-08.json"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "c163a1895e9e57258a514d7a043999560c1c78281ff397bcdc989a9ca6a5d564"
    )
    verification = json.loads(path.read_bytes())
    for group in (
        "frozen_files_sha256",
        "preregistered_implementation_sha256",
        "result_artifact_sha256",
    ):
        for name, digest in verification[group].items():
            assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, name
    assert hashlib.sha256(
        (root / "docs/player-model-gw1-3-scorecard-2026-09-08.md").read_bytes()
    ).hexdigest() == ("17807d5c53e79056dfd436366a5da2aa96738a2e12049b0497c7189c8115cdee")


def test_retained_historical_metadata_and_original_receipts() -> None:
    verification = json.loads(
        (repo_root() / "results/player_model_gw1_3_verification_2026-09-08.json").read_bytes()
    )
    directory = Path(verification["external_receipts_root"])
    if not directory.exists():
        pytest.skip("requires retained owner-machine invalid V1 receipts")
    for name, receipt in verification["original_receipts"].items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == receipt["sha256"]
    original_bytes = (directory / "historical-inputs.json").read_bytes()
    decoded = json.loads(original_bytes)
    source_native = {
        int(gw): {
            **info,
            "fixture_gameweeks": {
                int(fixture): event for fixture, event in info["fixture_gameweeks"].items()
            },
        }
        for gw, info in decoded.items()
    }
    corrected = canonical(source_native)
    assert corrected == canonical(decoded) == canonical(json.loads(corrected))
    assert corrected != original_bytes  # Preserve the old defective ordering as evidence.
    assert (directory / "historical-inputs.json").read_bytes() == original_bytes
