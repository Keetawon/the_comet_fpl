"""Operational architecture policy using the existing Pydantic/YAML configuration conventions."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from fpl.config import _Frozen, _read_yaml, config_dir


class FootballEnvironmentConfig(_Frozen):
    """Owner-directed architecture policy, independent of frozen scientific gates."""

    schema_version: Literal[1] = 1
    football_environment_primary: Literal["sdp_v2", "disabled"]
    football_environment_fallback: Literal["trailing_goals_attack_defence"]
    shadow_incumbent: bool
    gk_saves_candidate_mode: Literal["shadow", "disabled"]
    frozen_parameters: str
    frozen_parameters_sha256: str
    gk_shadow_parameters: str
    gk_shadow_parameters_sha256: str
    lookback_days: int = Field(ge=1, le=30)
    workload_competitions: tuple[int, ...]


def load_football_environment(path: Path | None = None) -> FootballEnvironmentConfig:
    path = path or config_dir() / "football_environment.yaml"
    return FootballEnvironmentConfig.model_validate(_read_yaml(path))
