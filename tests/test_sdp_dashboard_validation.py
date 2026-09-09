"""Effective dashboard health accepts confirmed zeros, without changing source health."""

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

import pytest

from fpl.publish.sdp_stats import _owner_corrected_dashboard_valid
from fpl.storage.sdp_runtime import SdpHealthError, checked_metrics


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "future",
        "revision",
        "missing_xg",
        "explicit_null",
        "positive_xgot",
        "identity",
        "unconfirmed",
        "assumption_only",
        "missing_side",
    ],
)
def test_effective_core_validation_is_bounded_and_leaves_source_unchanged(
    defect: str | None,
) -> None:
    cutoff = datetime(2026, 9, 9, 9, tzinfo=UTC)
    complete = {
        "expectedGoals": 0.4,
        "totalScoringAtt": 6,
        "ontargetScoringAtt": 1,
        "attemptsIbox": 2,
        "touchesInOppBox": 5,
        "possessionPercentage": 40,
        "totalPass": 300,
        "accuratePass": 250,
    }
    sides = {"home": dict(complete), "away": dict(complete)}
    del sides["away"]["ontargetScoringAtt"]
    correction = {
        "relation": "direct",
        "provider_field": "ontargetScoringAtt",
        "evidence_class": "owner_confirmed_display_correction",
        "raw_payload_sha256": "a" * 64,
        "subject_team_code": 7,
        "provider_match_id": 123,
        "owner_confirmation_recorded_at": cutoff.isoformat(),
        "value": 0,
    }
    rows: dict[str, Any] = {
        "home": {"team_code": 36, "provider_match_id": 123, "display_corrections": {}},
        "away": {
            "team_code": 7,
            "provider_match_id": 123,
            "display_corrections": {"shots_on_target": correction},
        },
    }
    if defect == "future":
        correction["owner_confirmation_recorded_at"] = "2026-09-10T00:00:00Z"
    if defect == "revision":
        correction["raw_payload_sha256"] = "b" * 64
    if defect == "missing_xg":
        del sides["away"]["expectedGoals"]
    if defect == "explicit_null":
        sides["away"]["ontargetScoringAtt"] = None  # type: ignore[assignment]
    if defect == "positive_xgot":
        sides["away"]["expectedGoalsOnTarget"] = 1
    if defect == "identity":
        correction["subject_team_code"] = 8
    if defect == "unconfirmed":
        correction["evidence_class"] = "provider_guess"
    if defect == "assumption_only":
        rows["away"]["display_assumptions"] = rows["away"]["display_corrections"]
        rows["away"]["display_corrections"] = {}
    if defect == "missing_side":
        del sides["home"]
    original = deepcopy((sides, rows))
    for _ in range(2):
        assert _owner_corrected_dashboard_valid(
            sides, rows, raw_sha256="a" * 64, cutoff=cutoff
        ) is (defect is None)
    assert (sides, rows) == original
    if defect is None:
        # The same raw payload still truthfully lacks a provider field.
        with pytest.raises(SdpHealthError, match="required field absent: ontargetScoringAtt"):
            checked_metrics(sides["away"])
