"""Typed 2026/27 squad-rule and bounded-search configuration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fpl.config import config_dir

PositionName = Literal["GK", "DEF", "MID", "FWD"]
POSITIONS: tuple[PositionName, ...] = ("GK", "DEF", "MID", "FWD")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PositionRule(_Frozen):
    squad: int = Field(gt=0)
    minimum_starters: int = Field(ge=0)
    maximum_starters: int = Field(ge=0)

    @model_validator(mode="after")
    def _valid_starters(self) -> Self:
        if self.minimum_starters > self.maximum_starters:
            raise ValueError("minimum_starters exceeds maximum_starters")
        if self.maximum_starters > self.squad:
            raise ValueError("maximum_starters exceeds squad position count")
        return self


class SquadSection(_Frozen):
    size: int = Field(gt=0)
    budget_tenths: int = Field(gt=0)
    maximum_per_club: int = Field(gt=0)
    positions: dict[PositionName, PositionRule]

    @model_validator(mode="after")
    def _valid_position_counts(self) -> Self:
        if set(self.positions) != set(POSITIONS):
            raise ValueError("positions must contain exactly GK, DEF, MID, and FWD")
        if sum(rule.squad for rule in self.positions.values()) != self.size:
            raise ValueError("position squad counts do not sum to squad size")
        return self


class LineupSection(_Frozen):
    starters: int = Field(gt=0)
    captain_multiplier: int = Field(ge=2)
    vice_captain_enabled: Literal[True]
    outfield_bench_slots: int = Field(ge=0)
    goalkeeper_bench_slots: int = Field(ge=0)


class TransferSection(_Frozen):
    initial_squad_unlimited_free: Literal[True]
    free_per_gameweek_after_first_deadline: int = Field(ge=0)
    free_transfer_bank_cap: int = Field(ge=0)
    hit_cost_points: int = Field(ge=0)
    maximum_transfers_per_gameweek: int = Field(gt=0)


class SearchSection(_Frozen):
    candidate_pool_per_position: int = Field(gt=0)
    maximum_planned_transfers_per_gameweek: int = Field(gt=0)
    transition_limit_per_state: int = Field(gt=0)
    beam_width: int = Field(gt=0)


class RulesProvenance(_Frozen):
    bootstrap_snapshot: str
    bootstrap_captured_at: datetime
    bootstrap_payload_sha256: str
    payload_confirmed: tuple[str, ...]
    authoritative_sources: tuple[str, ...]


class SquadRules(_Frozen):
    contract_version: Literal["1.0"]
    season: str
    squad: SquadSection
    lineup: LineupSection
    transfers: TransferSection
    search: SearchSection
    provenance: RulesProvenance

    @model_validator(mode="after")
    def _cross_checks(self) -> Self:
        minimum = sum(rule.minimum_starters for rule in self.squad.positions.values())
        maximum = sum(rule.maximum_starters for rule in self.squad.positions.values())
        if not minimum <= self.lineup.starters <= maximum:
            raise ValueError("starter count is incompatible with position formation bounds")
        bench = self.lineup.outfield_bench_slots + self.lineup.goalkeeper_bench_slots
        if self.lineup.starters + bench != self.squad.size:
            raise ValueError("starters plus bench slots must equal squad size")
        if (
            self.search.maximum_planned_transfers_per_gameweek
            > self.transfers.maximum_transfers_per_gameweek
        ):
            raise ValueError("bounded search exceeds the official transfer cap")
        sha = self.provenance.bootstrap_payload_sha256
        if len(sha) != 64 or any(char not in "0123456789abcdef" for char in sha):
            raise ValueError("bootstrap_payload_sha256 is not lowercase SHA-256")
        return self


def parse_squad_rules(payload: bytes) -> SquadRules:
    """Parse the verified squad rules from exact UTF-8 bytes."""
    try:
        loaded = yaml.safe_load(payload.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValueError("squad rules are not valid UTF-8") from exc
    return SquadRules.model_validate(loaded)


def load_squad_rules(path: Path | None = None) -> SquadRules:
    """Load the verified live squad rules and bounded planning policy."""
    resolved = path or config_dir() / "squad_2026_27.yaml"
    return parse_squad_rules(resolved.read_bytes())
