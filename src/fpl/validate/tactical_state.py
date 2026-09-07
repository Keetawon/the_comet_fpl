"""Explicit retrospective-only tactical observations and fixed recent-state estimates.

Nothing here is a production FeatureSource or a PointInTimeView option. Historical capture
time remains visible; event-time causality and same-gameweek isolation remain mandatory.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

import duckdb

from fpl.features.pit import AsOf
from fpl.validate.retrospective_sdp import (
    EVIDENCE_CLASS,
    VERSION_SELECTION_POLICY,
    RetrospectiveBackfillView,
)

StateVector = tuple[float | None, float | None, float | None, float | None, float | None]
StateCounts = tuple[int, int, int, int, int]
SourceKey = tuple[str, int, int]
DIMENSIONS: Final[tuple[str, ...]] = (
    "attack_precision",
    "dangerous_territory",
    "control",
    "directness",
    "defensive_suppression",
)
RECENCY_WEIGHTS: Final[tuple[float, ...]] = (1.0, 0.707, 0.5, 0.354, 0.25)
WHITELIST: Final[tuple[str, ...]] = (
    "ontargetScoringAtt",
    "totalScoringAtt",
    "touchesInOppBox",
    "possessionPercentage",
    "fwdPass",
    "totalPass",
)


@dataclass(frozen=True, slots=True)
class TacticalObservation:
    season: str
    gw: int
    fixture: int
    team_code: int
    opponent_team_code: int
    was_home: bool
    kickoff: datetime
    goals: int
    goals_allowed: int
    values: StateVector
    sdp_match_id: int
    capture_id: str | None
    source_known_at: datetime | None
    payload_sha256: str | None
    provider: Literal["pl_sdp"] = "pl_sdp"
    evidence_class: Literal["retrospective_backfill_development"] = EVIDENCE_CLASS
    version_selection_policy: str = VERSION_SELECTION_POLICY

    def __post_init__(self) -> None:
        AsOf(self.kickoff)
        if self.source_known_at is not None:
            AsOf(self.source_known_at)
        if self.team_code == self.opponent_team_code:
            raise ValueError("a tactical observation needs distinct permanent team codes")
        if len(self.values) != len(DIMENSIONS):
            raise ValueError("exactly five licensed tactical dimensions are required")
        if any(value is not None and not math.isfinite(value) for value in self.values):
            raise ValueError("tactical dimensions must be finite or missing")
        if (
            self.evidence_class != EVIDENCE_CLASS
            or self.provider != "pl_sdp"
            or self.version_selection_policy != VERSION_SELECTION_POLICY
        ):
            raise ValueError("retrospective tactical evidence identity cannot be relabelled")

    @property
    def key(self) -> SourceKey:
        return self.season, self.fixture, self.team_code


@dataclass(frozen=True, slots=True)
class StateEstimate:
    values: StateVector
    recent_raw: StateVector
    counts: StateCounts
    prior: StateVector
    source_keys: tuple[SourceKey, ...]


def _vector(values: Sequence[float | None]) -> StateVector:
    if len(values) != 5:
        raise ValueError("exactly five tactical dimensions are required")
    return values[0], values[1], values[2], values[3], values[4]


def _metric(metrics: Mapping[str, float | None], key: str) -> float | None:
    value = metrics.get(key)
    if value is None:
        return None
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"invalid {key}: {value}")
    if key == "possessionPercentage":
        if value > 100:
            raise ValueError("possessionPercentage exceeds 100")
    elif value != round(value):
        raise ValueError(f"count metric {key} is not integral: {value}")
    return value


def tactical_values(
    own: Mapping[str, float | None], opponent: Mapping[str, float | None]
) -> StateVector:
    """Observed post-match dimensions, not permissible same-match predictor inputs."""
    sot = _metric(own, "ontargetScoringAtt")
    shots = _metric(own, "totalScoringAtt")
    box = _metric(own, "touchesInOppBox")
    possession = _metric(own, "possessionPercentage")
    forward = _metric(own, "fwdPass")
    passes = _metric(own, "totalPass")
    allowed = _metric(opponent, "totalScoringAtt")
    if sot is not None and shots is not None and sot > shots:
        raise ValueError("SOT exceeds total attempts")
    if forward is not None and passes is not None and forward > passes:
        raise ValueError("forward passes exceed total passes")
    return (
        sot / shots if sot is not None and shots is not None and shots > 0 else None,
        math.log1p(box) if box is not None else None,
        possession / 100 if possession is not None else None,
        forward / passes if forward is not None and passes is not None and passes > 0 else None,
        -math.log1p(allowed) if allowed is not None else None,
    )


class RetrospectiveTacticalBackfillView:
    """Separate validation-only six-key licence, composing the frozen identity boundary."""

    __slots__ = ("_as_of", "_con")

    EVIDENCE_CLASS: Final = EVIDENCE_CLASS
    VERSION_POLICY: Final = VERSION_SELECTION_POLICY

    def __init__(self, con: duckdb.DuckDBPyConnection, as_of: AsOf) -> None:
        if not isinstance(as_of, AsOf):
            raise TypeError("as_of must be AsOf")
        self._con = con
        self._as_of = as_of

    @property
    def evidence_class(self) -> Literal["retrospective_backfill_development"]:
        return EVIDENCE_CLASS

    def observations(self) -> tuple[TacticalObservation, ...]:
        anchor = RetrospectiveBackfillView(self._con, self._as_of).observed_real_sot()
        captures = sorted(value for value in anchor["capture_id"].unique() if value is not None)
        selected: dict[tuple[str, str], dict[str, float | None]] = {}
        if captures:
            placeholders = ",".join("?" for _ in captures)
            fields = ",".join("?" for _ in WHITELIST)
            for capture, side, key, value in self._con.execute(
                f"""SELECT payload_id, side, provider_field, value_numeric
                FROM stg_pl_sdp_team_match_metric
                WHERE payload_id IN ({placeholders}) AND provider_field IN ({fields})
                ORDER BY payload_id, side, provider_field""",
                [*captures, *WHITELIST],
            ).fetchall():
                selected.setdefault((capture, side), {})[key] = value
        observations = []
        for row in anchor.iter_rows(named=True):
            side = "home" if row["was_home"] else "away"
            opposite = "away" if row["was_home"] else "home"
            own = selected.get((row["capture_id"], side), {})
            opponent = selected.get((row["capture_id"], opposite), {})
            if own.get("ontargetScoringAtt") != row["shots_on_target"]:
                raise ValueError("exact SOT mapping disagrees with frozen source boundary")
            observations.append(
                TacticalObservation(
                    season=row["season"],
                    gw=row["gw"],
                    fixture=row["fixture"],
                    team_code=row["team_code"],
                    opponent_team_code=row["opponent_team_code"],
                    was_home=row["was_home"],
                    kickoff=row["kickoff_time"],
                    goals=int(row["goals"]),
                    goals_allowed=int(row["goals_allowed"]),
                    values=tactical_values(own, opponent),
                    sdp_match_id=row["sdp_match_id"],
                    capture_id=row["capture_id"],
                    source_known_at=row["source_known_at"],
                    payload_sha256=row["payload_sha256"],
                )
            )
        keyed = {row.key: row for row in observations}
        if len(keyed) != len(observations):
            raise ValueError("duplicate tactical fixture/team key")
        for observation in observations:
            opposite_row = keyed.get(
                (observation.season, observation.fixture, observation.opponent_team_code)
            )
            if (
                opposite_row is None
                or opposite_row.opponent_team_code != observation.team_code
                or opposite_row.was_home == observation.was_home
                or opposite_row.kickoff != observation.kickoff
                or opposite_row.goals != observation.goals_allowed
                or opposite_row.goals_allowed != observation.goals
                or opposite_row.capture_id != observation.capture_id
            ):
                raise ValueError(f"non-reciprocal tactical fixture sides: {observation.key}")
        return tuple(observations)


def load_observations(
    con: duckdb.DuckDBPyConnection, as_of: AsOf
) -> tuple[TacticalObservation, ...]:
    return RetrospectiveTacticalBackfillView(con, as_of).observations()


def current_state(
    history: Sequence[TacticalObservation],
    team_code: int,
    season: str,
    cutoff: datetime,
    excluded_gw: int | None,
) -> StateEstimate:
    """Fixed last-five current-season EWMA shrunk toward measured prior league state.

    Missing raw values consume a chronological slot. The league prior is an explicit state
    estimate, never a filled provider observation. Season reset means zero offseason carryover.
    """
    AsOf(cutoff)
    available = sorted(
        (
            row
            for row in history
            if row.kickoff < cutoff and not (row.season == season and row.gw == excluded_gw)
        ),
        key=lambda row: (row.kickoff, row.season, row.fixture, row.team_code),
    )
    if len({row.key for row in available}) != len(available):
        raise ValueError("duplicate tactical fixture/team key in prior history")
    recent = sorted(
        (row for row in available if row.team_code == team_code and row.season == season),
        key=lambda row: (row.kickoff, row.fixture),
        reverse=True,
    )[:5]
    values: list[float | None] = []
    recent_raw: list[float | None] = []
    priors: list[float | None] = []
    counts = []
    for dimension in range(5):
        measured = [row.values[dimension] for row in available]
        measured_values = [value for value in measured if value is not None]
        prior = math.fsum(measured_values) / len(measured_values) if measured_values else None
        weighted = [
            (row.values[dimension], weight)
            for row, weight in zip(recent, RECENCY_WEIGHTS, strict=False)
            if row.values[dimension] is not None
        ]
        n = len(weighted)
        raw = (
            math.fsum(value * weight for value, weight in weighted if value is not None)
            / math.fsum(weight for _, weight in weighted)
            if weighted
            else None
        )
        alpha = n / (n + 2)
        estimate = (
            alpha * raw + (1 - alpha) * prior if raw is not None and prior is not None else prior
        )
        values.append(estimate)
        recent_raw.append(raw)
        priors.append(prior)
        counts.append(n)
    return StateEstimate(
        values=_vector(values),
        recent_raw=_vector(recent_raw),
        counts=(counts[0], counts[1], counts[2], counts[3], counts[4]),
        prior=_vector(priors),
        source_keys=tuple(row.key for row in available),
    )
