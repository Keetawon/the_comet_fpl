"""Synthetic cache-boundary checks; no retained candidate refit or provider requests."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from fpl.validate.player_role_cache import decode_role_batch, load_role_cache
from fpl.validate.player_role_history import RoleHistoryRow, RoleTarget, forecast_role_batch


def payload() -> dict[str, Any]:
    start = datetime(2025, 8, 1, tzinfo=UTC)
    capture = datetime(2026, 9, 7, tzinfo=UTC)
    source = RoleHistoryRow(
        "2025-26",
        8,
        10,
        1,
        99,
        3,
        start,
        True,
        True,
        "Defender",
        999,
        "p999",
        "exact-opta",
        "capture-1",
        "a" * 64,
        capture,
        capture,
    )
    target = RoleTarget(
        "2025-26", 2, 20, 99, 3, start + timedelta(days=7), start + timedelta(days=7), "cache-exact"
    )
    batch = forecast_role_batch([source], [target])
    value = json.loads(json.dumps(asdict(batch), default=lambda v: v.isoformat()))
    row = value["predictions"][0]
    row["key"] = "2025-26:20:99"
    row["cache_reference"] = {"price_proxy_not_role_predictor": True}
    row["arm_probabilities"] = {
        "candidate": row["probabilities"],
        "pooled_prior": row["pooled_prior_baseline"],
        "smoothed_last_role": row["smoothed_last_role_baseline"],
        "recent_state_persistence": row["recent_state_persistence_baseline"],
    }
    return value


def test_decoder_keeps_original_dtos_late_times_and_candidate_identity() -> None:
    value = payload()
    original = copy.deepcopy(value)
    batch = decode_role_batch(value)
    row = batch.predictions[0]
    assert isinstance(row.target.as_of, datetime)
    assert isinstance(row.probabilities, tuple)
    assert isinstance(row.recent_sources, tuple)
    assert isinstance(row.recent_sources[0], RoleHistoryRow)
    assert row.recent_sources[0].known_at > row.target.as_of
    assert row.conditionality == "role_given_hypothetical_start_not_start_probability"
    assert row.witnessed_current_club_spell
    assert row.latest_observed_role == "DEF"
    assert value == original


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "bad_mass",
        "nan",
        "bool",
        "naive",
        "same_gw",
        "future",
        "wrong_club",
        "certificate",
        "proxy",
        "replace_arm",
    ],
)
def test_decoder_rejects_tampered_predictors(change: str) -> None:
    value = payload()
    row = value["predictions"][0]
    if change == "missing":
        del row["conditionality"]
    elif change == "extra":
        row["actual_role"] = "DEF"
    elif change == "bad_mass":
        row["probabilities"] = [0.2] * 4
    elif change == "nan":
        row["probabilities"] = [float("nan"), 1, 0, 0]
    elif change == "bool":
        row["probabilities"] = [False, True, False, False]
    elif change == "naive":
        row["target"]["as_of"] = "2025-08-08T00:00:00"
    elif change == "same_gw":
        row["recent_sources"][0]["gw"] = 2
    elif change == "future":
        row["maximum_prior_event"] = value["as_of"]
    elif change == "wrong_club":
        row["recent_sources"][0]["team_code"] = 4
    elif change == "certificate":
        value["source_versions"] = []
    elif change == "proxy":
        row["cache_reference"]["price_proxy_not_role_predictor"] = False
    else:
        row["arm_probabilities"]["candidate"] = [0.25] * 4
    with pytest.raises(ValueError, match=r"role|Role|timestamp|candidate|probabilit"):
        decode_role_batch(value)


def test_loader_does_not_accept_arbitrary_result_identity(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen"):
        load_role_cache(path, root=tmp_path)


def test_decoder_complete_gw_minimum_cutoff_not_individual_fixture_time() -> None:
    value = payload()
    value["predictions"][0]["target"]["kickoff"] = "2025-08-09T00:00:00+00:00"
    with pytest.raises(ValueError, match="complete"):
        decode_role_batch(value)
