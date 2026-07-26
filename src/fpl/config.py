"""Configuration loading and validation.

R2: scoring rules are configuration, not code. Every scoring constant lives in
`config/scoring_<ruleset>.yaml` and reaches the calculator only through `ScoringRules`.
`extra="forbid"` throughout, so a typo or an upstream rule change surfaces as a
validation error rather than a silently ignored key.
"""

from __future__ import annotations

import functools
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from fpl.types import Position, RulesetId, Season


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --------------------------------------------------------------------------------------
# Scoring rules
# --------------------------------------------------------------------------------------


class AppearanceRules(_Frozen):
    short_play_points: int
    long_play_points: int
    long_play_minutes: int


class CleanSheetRules(_Frozen):
    minimum_minutes: int
    points: dict[Position, int]


class UnitRule(_Frozen):
    """A "N points per K events, for these positions only" rule.

    Covers goals conceded (-1 per 2, GK and DEF) and saves (+1 per 3, GK only).
    """

    points_per_unit: int
    unit: int
    positions: frozenset[Position]

    @field_validator("unit")
    @classmethod
    def _unit_positive(cls, value: int) -> int:
        if value < 1:
            raise ValueError("unit must be >= 1")
        return value


class DefensiveContributionRules(_Frozen):
    """Threshold counts, not points.

    A position absent from `thresholds` can never earn DC. GK is deliberately absent
    (gotcha 7: goalkeeper defensive_contribution is always 0, measured max 0).
    """

    points: int
    thresholds: dict[Position, int]

    @field_validator("thresholds")
    @classmethod
    def _gk_never_earns_dc(cls, value: dict[Position, int]) -> dict[Position, int]:
        if Position.GK in value:
            raise ValueError(
                "goalkeepers never earn defensive contribution (gotcha 7); "
                "omit GK from thresholds rather than setting it to 0"
            )
        return value


class BonusRules(_Frozen):
    """Bonus is a rank within the match, never a per-player regression target.

    Phase 0 passes the recorded value through. `bps_rank` is the Stage D mode.
    """

    mode: Literal["passthrough", "bps_rank"]
    ranked_points: tuple[int, int, int]


class VerificationBlock(_Frozen):
    """Provenance for a ruleset. Two independent notions of trust.

    `payload_confirmed` -- the value matches the live `game_config.scoring`.
    `replay_exercised`  -- the rule actually fired against recorded data.

    They are not the same and a value can have one without the other.
    `goals_scored.GK` is precisely that case: a payload confirms the number FPL
    publishes, but no goalkeeper scored in the validation data, so no replay can
    exercise it.
    """

    payload_captured_at: datetime | None = None
    payload_sha256: str | None = None
    payload_confirmed: list[str] = Field(default_factory=list)
    replay_exercised: list[str] = Field(default_factory=list)
    unverified: dict[str, str] = Field(default_factory=dict)

    def is_confirmed(self, dotted_path: str) -> bool:
        return dotted_path in self.payload_confirmed and dotted_path not in self.unverified


class ScoringRules(_Frozen):
    """One season's scoring function, as data."""

    ruleset_id: RulesetId
    season: Season
    appearance: AppearanceRules
    goals_scored: dict[Position, int]
    assists: int
    clean_sheets: CleanSheetRules
    goals_conceded: UnitRule
    saves: UnitRule
    penalties_saved: int
    penalties_missed: int
    own_goals: int
    yellow_cards: int
    red_cards: int
    defensive_contribution: DefensiveContributionRules
    bonus: BonusRules
    verification: VerificationBlock = Field(default_factory=VerificationBlock)

    @field_validator("goals_scored")
    @classmethod
    def _all_positions_priced(cls, value: dict[Position, int]) -> dict[Position, int]:
        missing = set(Position) - set(value)
        if missing:
            raise ValueError(f"goals_scored missing positions: {sorted(missing)}")
        return value


# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------


class ArchiveSource(_Frozen):
    base_url: str
    seasons: list[Season]
    files: dict[str, str]

    def url(self, season: Season, file_key: str) -> str:
        return f"{self.base_url}/{season}/{self.files[file_key]}"


class LiveApiSource(_Frozen):
    base_url: str
    endpoints: dict[str, str]
    min_request_interval_seconds: float
    timeout_seconds: float
    max_retries: int
    retry_backoff_base_seconds: float


class CurrentSeason(_Frozen):
    season: Season
    ruleset_id: RulesetId
    gw1_deadline: datetime


class Paths(_Frozen):
    database: str
    archive_cache: str
    snapshots: str


class SourcesConfig(_Frozen):
    archive: ArchiveSource
    live_api: LiveApiSource
    current_season: CurrentSeason
    paths: Paths


# --------------------------------------------------------------------------------------
# Data quality
# --------------------------------------------------------------------------------------


class NullifyExpectation(_Frozen):
    null_through_gw: int
    not_null_from_gw: int


class NullifyRule(_Frozen):
    """A declared repair of present-but-not-measured values.

    Only ever widens NULL coverage; it never writes a value.
    """

    id: str
    season: Season
    columns: list[str]
    reason: str
    gw_max: int | None = None
    gw_min: int | None = None
    expect: NullifyExpectation | None = None


class RangeRule(_Frozen):
    min: float
    max: float


class ConsistencyRule(_Frozen):
    id: str
    description: str
    predicate: str


class ExpectedAnomaly(_Frozen):
    id: str
    description: str
    season: Season | None = None


class DataQualityConfig(_Frozen):
    nullify: list[NullifyRule] = Field(default_factory=list)
    ranges: dict[str, RangeRule] = Field(default_factory=dict)
    consistency: list[ConsistencyRule] = Field(default_factory=list)
    expected_anomalies: list[ExpectedAnomaly] = Field(default_factory=list)

    def nullify_for(self, season: Season) -> list[NullifyRule]:
        return [rule for rule in self.nullify if rule.season == season]


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------


def repo_root() -> Path:
    """Locate the repository root by walking up to the directory holding `config/`."""
    for candidate in (Path(__file__).resolve(), *Path(__file__).resolve().parents):
        if (candidate / "config" / "sources.yaml").is_file():
            return candidate
    raise FileNotFoundError("could not locate repository root (no config/sources.yaml found)")


def config_dir() -> Path:
    return repo_root() / "config"


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} did not parse to a mapping")
    return loaded


@functools.cache
def load_sources(path: Path | None = None) -> SourcesConfig:
    return SourcesConfig.model_validate(_read_yaml(path or config_dir() / "sources.yaml"))


@functools.cache
def load_scoring_rules(ruleset_id: RulesetId, path: Path | None = None) -> ScoringRules:
    """Load one ruleset. `ruleset_id` uses underscores, e.g. "2026_27"."""
    resolved = path or config_dir() / f"scoring_{ruleset_id}.yaml"
    if not resolved.is_file():
        raise FileNotFoundError(f"no scoring config for ruleset {ruleset_id!r} at {resolved}")
    rules = ScoringRules.model_validate(_read_yaml(resolved))
    if rules.ruleset_id != ruleset_id:
        raise ValueError(
            f"{resolved} declares ruleset_id {rules.ruleset_id!r}, expected {ruleset_id!r}"
        )
    return rules


def available_rulesets() -> list[RulesetId]:
    """Every ruleset with a config file, sorted. Drives the target table's columns."""
    prefix, suffix = "scoring_", ".yaml"
    return sorted(
        path.name[len(prefix) : -len(suffix)] for path in config_dir().glob(f"{prefix}*{suffix}")
    )


@functools.cache
def load_data_quality(path: Path | None = None) -> DataQualityConfig:
    return DataQualityConfig.model_validate(_read_yaml(path or config_dir() / "data_quality.yaml"))
