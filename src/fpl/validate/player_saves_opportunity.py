"""Development-only frozen OOS shot volume -> pooled SOT share -> saves.

No fit of Phase A, keeper-specific ability, target exposure or goal/SOT identity.
Original provider fields and NULLs survive; all rate fitting is prior-event only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from fpl.models.attacking_baselines import poisson_pmf

NAME = "retrospective_oos_shot_opportunity_gk_saves_v1"
EVIDENCE_CLASS = "retrospective_backfill_development"
MINIMUM_MEASURED_SIDES = 160


@dataclass(frozen=True)
class ShotObservation:
    season: str
    gw: int
    fixture: int
    team_code: int
    kickoff: datetime
    shots: int | None
    sot: int | None
    capture_id: str
    payload_sha256: str
    known_at: datetime


@dataclass(frozen=True)
class PooledShotPrecision:
    as_of: datetime
    excluded_gw: tuple[str, int]
    measured_sides: int
    shots: int
    sot: int
    fraction: float | None
    maximum_training_event: datetime | None
    source_keys: tuple[tuple[str, int, int, str], ...]


def fit_precision(
    history: Sequence[ShotObservation], *, as_of: datetime, excluded_gw: tuple[str, int]
) -> PooledShotPrecision:
    """One league-pooled ratio; no grid, future normalization or selected-player fit."""
    if as_of.utcoffset() is None:
        raise ValueError("aware cutoff required")
    prior = sorted(
        (
            r
            for r in history
            if r.kickoff + timedelta(hours=6) < as_of and (r.season, r.gw) != excluded_gw
        ),
        key=lambda r: (r.kickoff, r.season, r.fixture, r.team_code),
    )
    seen = set()
    measured = []
    for row in prior:
        key = row.season, row.fixture, row.team_code
        if key in seen:
            raise ValueError("duplicate team revision is not another match")
        seen.add(key)
        if row.shots is None or row.sot is None:
            continue
        if type(row.shots) is not int or type(row.sot) is not int or not 0 <= row.sot <= row.shots:
            raise ValueError("invalid measured shot/SOT counts")
        if not row.capture_id or len(row.payload_sha256) != 64 or row.known_at.utcoffset() is None:
            raise ValueError("original source evidence required")
        measured.append(row)
    shots, sot = (
        sum(r.shots for r in measured if r.shots is not None),
        sum(r.sot for r in measured if r.sot is not None),
    )
    return PooledShotPrecision(
        as_of,
        excluded_gw,
        len(measured),
        shots,
        sot,
        sot / shots if len(measured) >= MINIMUM_MEASURED_SIDES and shots > 0 else None,
        max((r.kickoff for r in measured), default=None),
        tuple((r.season, r.fixture, r.team_code, r.capture_id) for r in measured),
    )


@dataclass(frozen=True)
class OosShotForecast:
    season: str
    gw: int
    fixture: int
    attacking_team_code: int
    defending_team_code: int
    as_of: datetime
    kickoff: datetime
    predicted_shots: float | None
    maximum_upstream_training_event: datetime | None
    artifact_sha256: str


@dataclass(frozen=True)
class OpportunitySavesPrediction:
    probabilities: tuple[float, ...]
    rate: float | None
    expected_sot_faced: float | None
    fallback: bool


def predict_saves(
    forecast: OosShotForecast,
    precision: PooledShotPrecision,
    *,
    save_fraction: float,
    incumbent: tuple[float, ...],
) -> OpportunitySavesPrediction:
    if (
        (forecast.season, forecast.gw) != precision.excluded_gw
        or forecast.as_of != precision.as_of
        or forecast.kickoff < forecast.as_of
        or forecast.attacking_team_code == forecast.defending_team_code
    ):
        raise ValueError("opponent/cutoff/whole-GW identity differs")
    if forecast.as_of.utcoffset() is None or len(forecast.artifact_sha256) != 64:
        raise ValueError("explicit original OOS forecast evidence required")
    for stamp in (forecast.maximum_upstream_training_event, precision.maximum_training_event):
        if stamp is not None and stamp + timedelta(hours=6) >= forecast.as_of:
            raise ValueError("upstream target/future event leakage")
    if not math.isfinite(save_fraction) or not 0 <= save_fraction <= 1:
        raise ValueError("invalid fixed-incumbent save fraction")
    if len(incumbent) != 11 or not math.isclose(sum(incumbent), 1, rel_tol=0, abs_tol=1e-12):
        raise ValueError("unchanged incumbent 0..10 PMF required")
    if any(not math.isfinite(p) or p < 0 for p in incumbent):
        raise ValueError("invalid incumbent PMF")
    if precision.fraction is not None and (
        not math.isfinite(precision.fraction) or not 0 <= precision.fraction <= 1
    ):
        raise ValueError("invalid pooled shot precision")
    shots = forecast.predicted_shots
    if shots is None or precision.fraction is None:
        return OpportunitySavesPrediction(incumbent, None, None, True)
    if not math.isfinite(shots) or shots < 0:
        raise ValueError("invalid predicted shot volume")
    sot = shots * precision.fraction
    rate = sot * save_fraction
    return OpportunitySavesPrediction(poisson_pmf(rate), rate, sot, False)
