"""Owner-adopted frozen player models; no online coefficient fitting."""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from fpl.models.aggregate_conversion import conversion_feature
from fpl.models.aggregate_conversion_v2 import ShareRow, converted_rates
from fpl.models.attacking_baselines import poisson_pmf
from fpl.models.component_followup import (
    Component,
    Observation,
    Policy,
    Target,
    checked_history,
    duration_dc,
    shrunk_attack,
)
from fpl.models.goal_involvement import EventFit
from fpl.types import Position


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ConversionParameters(_Config):
    smoothing: float = Field(gt=0)
    ridge: float = Field(gt=0)
    bound: float = Field(gt=0)
    beta: float
    name: str
    training_rows: int = Field(gt=0)

    @model_validator(mode="after")
    def _bound(self) -> Self:
        if abs(self.beta) > self.bound:
            raise ValueError("conversion coefficient exceeds fitted bound")
        return self


class PlayerComponentConfig(_Config):
    name: Literal["trained_conversion_duration_player_components_v1"]
    version: Literal[1]
    enabled: bool
    owner_adoption: str
    scientific_status: str
    training_cutoff: datetime
    conversion_result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fitted_parameters_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    components: dict[Component, ConversionParameters]
    policy: Policy

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if set(self.components) != {"goals", "assists"} or self.training_cutoff.tzinfo is None:
            raise ValueError("both frozen components and an aware fitting cutoff required")
        return self


class GoalInvolvementConfig(_Config):
    name: Literal["gameweek_goal_involvement_event_v1"]
    version: Literal[1]
    serving: Literal["component_baseline", "trained_event"]
    training_cutoff: datetime
    selected: str
    fit: EventFit | None
    result_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scientific_status: str

    @model_validator(mode="after")
    def _valid_fit(self) -> Self:
        if self.training_cutoff.tzinfo is None:
            raise ValueError("aware event fitting cutoff required")
        if self.serving == "trained_event" and self.fit is None:
            raise ValueError("trained event serving requires frozen coefficients")
        if self.fit is not None and (
            len(self.fit.intercepts) != 4
            or any(not math.isfinite(v) for v in (*self.fit.intercepts, self.fit.slope_delta))
            or self.fit.ridge <= 0
            or self.fit.rows <= 0
        ):
            raise ValueError("invalid frozen event coefficients")
        return self

    def probabilities(
        self, position: str, baseline: float, *, structural_zero: bool
    ) -> tuple[float, float]:
        shadow = (
            self.fit.predict(position, baseline)
            if self.fit is not None and not structural_zero
            else baseline
        )
        return (shadow if self.serving == "trained_event" else baseline), shadow


def load_component_config(directory: Path) -> tuple[PlayerComponentConfig, str]:
    payload = (directory / "player_components_production.json").read_bytes()
    return PlayerComponentConfig.model_validate_json(payload), hashlib.sha256(payload).hexdigest()


def load_event_config(directory: Path) -> tuple[GoalInvolvementConfig, str]:
    payload = (directory / "goal_involvement_production.json").read_bytes()
    return GoalInvolvementConfig.model_validate_json(payload), hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class PlayerComponents:
    goals: tuple[float, ...]
    assists: tuple[float, ...]
    dc_by_minutes: tuple[float, ...] | None
    fallback_goals: str | None
    fallback_assists: str | None


class FrozenPlayerAdapter:
    def __init__(
        self,
        history: Sequence[Observation],
        *,
        cutoff: datetime,
        season: str,
        gw: int,
        frontier_season: str,
        config: PlayerComponentConfig,
    ) -> None:
        if cutoff <= config.training_cutoff:
            raise ValueError(
                "frozen final conversion fit cannot be used before its training cutoff"
            )
        self.history = checked_history(history, cutoff, season, gw)
        self.config, self.cutoff, self.frontier = config, cutoff, frontier_season
        self.by_code: dict[int, list[Observation]] = defaultdict(list)
        self.by_position: dict[Position, list[Observation]] = defaultdict(list)
        for row in self.history:
            self.by_code[row.code].append(row)
            self.by_position[row.position].append(row)

    def predict_roster(
        self,
        roster: Sequence[Target],
        *,
        goal_budget: float,
        assist_budget: float,
        thresholds: Mapping[Position, int],
    ) -> dict[int, PlayerComponents]:
        components: dict[Component, dict[int, tuple[float, ...]]] = {}
        fallbacks: dict[Component, dict[int, str | None]] = {}
        for component, budget in (("goals", goal_budget), ("assists", assist_budget)):
            kind: Component = "goals" if component == "goals" else "assists"
            base = shrunk_attack(
                self.history,
                roster,
                component=kind,
                frontier_season=self.frontier,
                team_budget=budget,
                policy=self.config.policy,
            )
            shares = []
            for target in roster:
                feature = conversion_feature(
                    self.by_code[target.code], code=target.code, component=kind, cutoff=self.cutoff
                )
                b = base[target.code]
                shares.append(
                    ShareRow(
                        target.code,
                        target.p_play,
                        b.allocated_rate,
                        b.conditional_rate,
                        feature.actual_sum,
                        feature.expected_sum,
                    )
                )
            parameters = self.config.components[kind]
            rates = converted_rates(
                shares, budget=budget, smoothing=parameters.smoothing, beta=parameters.beta
            )
            components[kind] = {
                target.code: tuple(poisson_pmf(rate))
                if rate is not None
                else base[target.code].conditional
                for target, rate in zip(roster, rates, strict=True)
            }
            fallbacks[kind] = {target.code: base[target.code].fallback for target in roster}
        return {
            target.code: PlayerComponents(
                components["goals"][target.code],
                components["assists"][target.code],
                duration_dc(
                    self.by_position[target.position], target, thresholds, self.config.policy
                ).by_minutes,
                fallbacks["goals"][target.code],
                fallbacks["assists"][target.code],
            )
            for target in roster
        }
