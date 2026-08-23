"""Stable, provenance-bearing artifact for a Stage E squad/transfer optimisation.

The Stage E optimiser turns one frozen prospective-points forecast into a legal 15-player squad,
a rotating weekly XI/captain/vice/bench, and a bounded multi-gameweek transfer plan. Until now that
decision only existed as stdout JSON: nothing pinned *which* forecast it consumed, *which* code
produced it, or *which* solver and search bounds it ran under, and nothing stopped a second run from
silently overwriting the first. This module is the durable boundary that fixes those gaps.

It is the optimiser analogue of :mod:`fpl.artifacts.prospective_points`. The two share a discipline:
the artifact module owns the typed schema, canonical serialisation, and atomic write, and stays free
of any dependency on the domain models it records -- the job maps its domain objects into these
typed records. Everything here is **development-only** -- it transports a decision, it does not
certify that the decision is a validated production recommendation.

Three properties make a recorded plan auditable and safe:

* **Stable run identity.** ``decision_sha256`` binds the complete legal decision and assumptions;
  ``run_id`` binds that digest to the forecast/rules hashes, optimiser commit, complete search
  policy, and complete solver identity. Only relocatable paths and optimizer publication time are
  excluded; an input manager capture's knowledge timestamp remains identity-binding. Both hashes
  are re-derived on read.
* **Immutability.** :func:`write_optimizer_artifact_atomic` refuses to overwrite an existing
  destination and promotes a flushed sibling temporary file with an atomic create-if-absent hard
  link. Concurrent writers therefore have exactly one winner and cannot clobber it.
* **Strictness and determinism.** Serialisation is canonical (sorted keys, ``allow_nan=False``) and
  every float field rejects non-finite values at construction, so a NaN can never reach the file or
  a downstream consumer.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OPTIMIZER_ARTIFACT_SCHEMA = "fpl.optimizer-plan"
OPTIMIZER_ARTIFACT_SCHEMA_VERSION: Literal[2] = 2
_LEGACY_OPTIMIZER_ARTIFACT_SCHEMA_VERSION: Literal[1] = 1
OPTIMIZER_ARTIFACT_STATUS = "development_only_not_a_validated_production_recommendation"

PositionName = Literal["GK", "DEF", "MID", "FWD"]


def _validate_sha256(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    return value


class OptimizerArtifactError(ValueError):
    """The optimizer artifact is malformed, internally inconsistent, or unsafe to consume."""


class OptimizerArtifactExistsError(OptimizerArtifactError):
    """Refused to overwrite an existing immutable optimizer artifact (no-clobber)."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class ForecastInputProvenance(_Frozen):
    """The frozen prospective-points artifact this plan was optimised from."""

    path: str
    sha256: str
    forecast_schema: str
    forecast_schema_version: int
    as_of: datetime
    season: str
    gw_from: int = Field(ge=1)
    gw_to: int = Field(ge=1)
    commit_sha: str
    selectable_player_registry_sha256: str | None = None

    @field_validator("sha256", "selectable_player_registry_sha256")
    @classmethod
    def _valid_sha256(cls, value: str | None) -> str | None:
        return None if value is None else _validate_sha256(value)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.gw_to < self.gw_from:
            raise ValueError("forecast gw_to must be >= gw_from")
        if not self.commit_sha:
            raise ValueError("forecast commit_sha is required")
        if not self.forecast_schema:
            raise ValueError("forecast schema is required")
        if not self.season:
            raise ValueError("forecast season is required")
        if not self.path:
            raise ValueError("forecast path is required")
        return self


class SquadRulesProvenance(_Frozen):
    """The verified squad-rule and bounded-search configuration file this plan obeyed."""

    path: str
    contract_version: str
    sha256: str

    @field_validator("sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if not self.path or not self.contract_version:
            raise ValueError("squad-rules path and contract_version are required")
        return self


class OptimizerProvenance(_Frozen):
    """Who produced the plan and from what. The Git worktree is pinned clean by construction."""

    optimizer_commit_sha: str
    optimizer_worktree_clean: Literal[True] = True
    forecast: ForecastInputProvenance
    squad_rules: SquadRulesProvenance

    @model_validator(mode="after")
    def _requires_commit(self) -> Self:
        if not self.optimizer_commit_sha:
            raise ValueError("optimizer_commit_sha is required")
        return self


class SolverIdentity(_Frozen):
    """The solver, its discoverable identity, and its deterministic options.

    Package and binary versions are required for durable output and enter ``run_id``: solver
    upgrades can alter branch-and-bound and tie behaviour even with unchanged options.
    """

    name: str
    package: str
    package_version: str
    binary_version: str
    options: tuple[str, ...]
    seed: int
    status: str

    @model_validator(mode="after")
    def _complete(self) -> Self:
        values = (self.name, self.package, self.package_version, self.binary_version, self.status)
        if any(not value.strip() for value in values):
            raise ValueError("solver identity fields must be non-empty")
        return self


class SearchPolicy(_Frozen):
    """The complete bounded-search policy that shaped the transfer plan.

    Every field is behaviour-defining. The original fields enter the ``run_id``; additive
    exclusions enter when non-empty, and only the non-default user-custom origin enters, so
    schema-v1 identities written before those fields existed remain stable. The constraint bounds
    and transfer-state parameters come from the squad-rules file; ``risk_lambda`` and
    ``min_bench_appearance`` come from the CLI; ``search_method`` and ``optimality_scope``
    are the planner's own declared scope of exactness.
    """

    candidate_pool_per_position: int = Field(gt=0)
    transfer_depth: int = Field(gt=0)
    transition_limit_per_state: int = Field(gt=0)
    beam_width: int = Field(gt=0)
    free_transfer_per_gameweek: int = Field(ge=0)
    free_transfer_bank_cap: int = Field(ge=0)
    hit_cost_points: int = Field(ge=0)
    maximum_transfers_per_gameweek: int = Field(gt=0)
    risk_lambda: float = Field(ge=0.0, allow_inf_nan=False)
    min_bench_appearance: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    locked_codes: tuple[int, ...] = ()
    excluded_codes: tuple[int, ...] = ()
    # These two fields are additive schema-v2 policy. Their defaults deliberately describe the
    # pre-v2 scratch-squad planner, and are omitted from schema-v1 canonical bytes and identity.
    plan_mode: Literal["scratch", "manager"] = "scratch"
    initial_free_transfers: int = Field(default=0, ge=0)
    # None exists only for schema-v1 artifacts written before origin provenance was added.
    # Every current producer passes an explicit value; retaining None on read lets downstream
    # compatibility logic distinguish a constrained legacy user plan from a platform plan.
    plan_origin: Literal["platform", "user_custom"] | None = None
    search_method: str
    optimality_scope: str

    @field_validator("locked_codes")
    @classmethod
    def _distinct_locks(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) != len(value):
            raise ValueError("locked_codes must be distinct")
        return tuple(sorted(value))

    @field_validator("excluded_codes")
    @classmethod
    def _distinct_exclusions(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(value)) != len(value):
            raise ValueError("excluded_codes must be distinct")
        return tuple(sorted(value))

    @model_validator(mode="after")
    def _descriptions_present(self) -> Self:
        if set(self.locked_codes).intersection(self.excluded_codes):
            raise ValueError("players cannot be both locked and excluded")
        if not self.search_method.strip() or not self.optimality_scope.strip():
            raise ValueError("search_method and optimality_scope are required")
        if self.initial_free_transfers > self.free_transfer_bank_cap:
            raise ValueError("initial_free_transfers exceeds the free-transfer bank cap")
        if self.plan_mode == "scratch" and self.initial_free_transfers != 0:
            raise ValueError("scratch plans cannot start with free transfers")
        return self


class OwnedPlayerValueRecord(_Frozen):
    """Deadline-frozen acquisition and sale values for one imported manager player."""

    code: int = Field(gt=0)
    purchase_price_tenths: int = Field(gt=0)
    selling_price_tenths: int = Field(gt=0)


class ManagerPlanContext(_Frozen):
    """Private, immutable manager-team capture bound to a schema-v2 plan.

    The public FPL API exposes the last-deadline squad and transfer history, not authenticated live
    team state. The source field makes that limitation explicit. existing_hit_points records costs
    already incurred before this solve; they are sunk and therefore never deducted from the plan's
    prospective objective a second time.
    """

    capture_id: str
    capture_sha256: str
    selectable_player_registry_sha256: str
    captured_at: datetime
    manager_id: int = Field(gt=0)
    source: Literal["public_last_deadline_squad"] = "public_last_deadline_squad"
    picks_event: int = Field(ge=1)
    planning_gw: int = Field(ge=1)
    bank_tenths: int = Field(ge=0)
    initial_free_transfers: int = Field(ge=0)
    free_transfers_source: str
    free_transfers_override: int | None = Field(default=None, ge=0)
    existing_hit_points: int = Field(ge=0)
    owned_players: tuple[OwnedPlayerValueRecord, ...]

    @field_validator("capture_sha256", "selectable_player_registry_sha256")
    @classmethod
    def _valid_capture_hash(cls, value: str) -> str:
        return _validate_sha256(value)

    @field_validator("capture_id")
    @classmethod
    def _valid_capture_id(cls, value: str) -> str:
        digest = value.removeprefix("manager-")
        _validate_sha256(digest)
        return value

    @field_validator("owned_players")
    @classmethod
    def _ordered_owned_players(
        cls, value: tuple[OwnedPlayerValueRecord, ...]
    ) -> tuple[OwnedPlayerValueRecord, ...]:
        codes = tuple(player.code for player in value)
        if codes != tuple(sorted(codes)) or len(set(codes)) != len(codes):
            raise ValueError("manager owned-player values must be unique and ordered by code")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("manager capture timestamp must be timezone-aware")
        if self.picks_event > self.planning_gw:
            raise ValueError("manager picks_event cannot be after planning_gw")
        if not self.free_transfers_source.strip():
            raise ValueError("free_transfers_source is required")
        if (
            self.free_transfers_override is not None
            and self.free_transfers_override != self.initial_free_transfers
        ):
            raise ValueError("free-transfer override must equal the recorded initial state")
        return self


class PositionRuleRecord(_Frozen):
    """One position's verified squad and formation limits."""

    position: PositionName
    squad: int = Field(gt=0)
    minimum_starters: int = Field(ge=0)
    maximum_starters: int = Field(ge=0)

    @model_validator(mode="after")
    def _valid(self) -> Self:
        if self.minimum_starters > self.maximum_starters:
            raise ValueError("minimum_starters exceeds maximum_starters")
        if self.maximum_starters > self.squad:
            raise ValueError("maximum_starters exceeds squad count")
        return self


class SquadRulesSnapshot(_Frozen):
    """Self-contained legality rules copied from the content-hashed squad contract."""

    contract_version: str
    season: str
    squad_size: int = Field(gt=0)
    budget_tenths: int = Field(gt=0)
    maximum_per_club: int = Field(gt=0)
    positions: tuple[PositionRuleRecord, ...]
    lineup_starters: int = Field(gt=0)
    captain_multiplier: int = Field(ge=2)
    vice_captain_enabled: Literal[True] = True
    goalkeeper_bench_slots: int = Field(ge=0)
    outfield_bench_slots: int = Field(ge=0)

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if not self.contract_version:
            raise ValueError("squad-rule contract_version is required")
        if not self.season:
            raise ValueError("squad-rule season is required")
        order = tuple(rule.position for rule in self.positions)
        if order != ("GK", "DEF", "MID", "FWD"):
            raise ValueError("position rules must be ordered GK, DEF, MID, FWD")
        if sum(rule.squad for rule in self.positions) != self.squad_size:
            raise ValueError("position squad counts do not sum to squad_size")
        bench = self.goalkeeper_bench_slots + self.outfield_bench_slots
        if self.lineup_starters + bench != self.squad_size:
            raise ValueError("starters plus bench slots do not sum to squad_size")
        return self


class SquadMemberRecord(_Frozen):
    """One selected 15-player squad member with its deadline-known price and ownership."""

    code: int = Field(gt=0)
    web_name: str | None
    position: PositionName
    team_id: int = Field(gt=0)
    team_code: int | None
    now_cost: int = Field(ge=0)
    selected_by_percent: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)


class PlayerRef(_Frozen):
    """A compact player reference used inside weekly lineup/transfer lists."""

    code: int = Field(gt=0)
    web_name: str | None


class TransferWeekRecord(_Frozen):
    """One gameweek of the plan: the transfers taken, the free-transfer state, and the exact XI."""

    gw: int = Field(ge=1)
    transfers_in: tuple[PlayerRef, ...]
    transfers_out: tuple[PlayerRef, ...]
    free_transfers_before: int = Field(ge=0)
    free_transfers_after: int = Field(ge=0)
    hit_points: int = Field(ge=0)
    bank_before_tenths: int | None = Field(default=None, ge=0)
    bank_after_tenths: int | None = Field(default=None, ge=0)
    squad_cost_tenths: int = Field(ge=0)
    squad_after_transfers: tuple[SquadMemberRecord, ...]
    starting_xi: tuple[PlayerRef, ...]
    captain: PlayerRef
    vice_captain: PlayerRef
    bench_goalkeeper: PlayerRef
    bench_order: tuple[PlayerRef, ...]
    expected_points: float = Field(ge=0.0, allow_inf_nan=False)
    objective_value: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _balanced(self) -> Self:
        if len(self.transfers_in) != len(self.transfers_out):
            raise ValueError("transfers_in and transfers_out must have equal length")
        for label, refs in (
            ("transfers_in", self.transfers_in),
            ("transfers_out", self.transfers_out),
            ("starting_xi", self.starting_xi),
        ):
            codes = tuple(ref.code for ref in refs)
            if len(set(codes)) != len(codes):
                raise ValueError(f"{label} contains duplicate codes")
            if codes != tuple(sorted(codes)):
                raise ValueError(f"{label} must be ordered by code")
        if {ref.code for ref in self.transfers_in} & {ref.code for ref in self.transfers_out}:
            raise ValueError("a player cannot be transferred in and out in the same gameweek")
        squad_codes = tuple(member.code for member in self.squad_after_transfers)
        if squad_codes != tuple(sorted(squad_codes)) or len(set(squad_codes)) != len(squad_codes):
            raise ValueError("weekly squad members must be unique and ordered by code")
        bench_codes = (self.bench_goalkeeper.code, *(ref.code for ref in self.bench_order))
        if len(set(bench_codes)) != len(bench_codes):
            raise ValueError("bench contains duplicate codes")
        return self


class InitialSquadRecord(_Frozen):
    """The exact initial 15-player squad and its cost."""

    cost_tenths: int = Field(ge=0)
    solver_status: str
    members: tuple[SquadMemberRecord, ...]

    @field_validator("members")
    @classmethod
    def _sorted_unique(cls, value: tuple[SquadMemberRecord, ...]) -> tuple[SquadMemberRecord, ...]:
        codes = [member.code for member in value]
        if codes != sorted(codes) or len(set(codes)) != len(codes):
            raise ValueError("squad members must be unique and ordered by code")
        return value


class TransferPlanRecord(_Frozen):
    """The horizon plan: per-week decisions plus the aggregate expected-point accounting."""

    expected_points_before_hits: float = Field(allow_inf_nan=False)
    hit_points: int = Field(ge=0)
    expected_points_after_hits: float = Field(allow_inf_nan=False)
    objective_value_after_hits: float = Field(allow_inf_nan=False)
    candidate_pool_size: int = Field(ge=0)
    weeks: tuple[TransferWeekRecord, ...]

    @field_validator("weeks")
    @classmethod
    def _ordered_weeks(
        cls, value: tuple[TransferWeekRecord, ...]
    ) -> tuple[TransferWeekRecord, ...]:
        if not value:
            raise ValueError("a plan must contain at least one gameweek")
        gws = [week.gw for week in value]
        if gws != sorted(gws) or len(set(gws)) != len(gws):
            raise ValueError("plan weeks must be unique and ordered by gameweek")
        return value


def _member_map(
    members: tuple[SquadMemberRecord, ...],
    *,
    cost_tenths: int,
    rules: SquadRulesSnapshot,
    context: str,
    enforce_budget: bool = True,
) -> dict[int, SquadMemberRecord]:
    if len(members) != rules.squad_size:
        raise ValueError(f"{context} must contain exactly {rules.squad_size} players")
    by_code = {member.code: member for member in members}
    if len(by_code) != len(members):
        raise ValueError(f"{context} contains duplicate players")
    actual_cost = sum(member.now_cost for member in members)
    if cost_tenths != actual_cost:
        raise ValueError(f"{context} cost does not equal its member prices")
    if enforce_budget and actual_cost > rules.budget_tenths:
        raise ValueError(f"{context} exceeds the configured budget")
    expected_positions = {rule.position: rule.squad for rule in rules.positions}
    actual_positions = Counter(member.position for member in members)
    if actual_positions != expected_positions:
        raise ValueError(f"{context} has an illegal position composition")
    club_counts = Counter(member.team_id for member in members)
    if any(count > rules.maximum_per_club for count in club_counts.values()):
        raise ValueError(f"{context} exceeds the configured club cap")
    return by_code


def _check_refs(
    refs: tuple[PlayerRef, ...],
    members: dict[int, SquadMemberRecord],
    *,
    context: str,
) -> tuple[int, ...]:
    codes = tuple(ref.code for ref in refs)
    for ref in refs:
        member = members.get(ref.code)
        if member is None:
            raise ValueError(f"{context} references a player outside the applicable squad")
        if ref.web_name != member.web_name:
            raise ValueError(f"{context} player name disagrees with squad metadata")
    return codes


def _validate_week_lineup(
    week: TransferWeekRecord,
    members: dict[int, SquadMemberRecord],
    rules: SquadRulesSnapshot,
) -> None:
    starters = _check_refs(week.starting_xi, members, context=f"GW{week.gw} starting XI")
    if len(starters) != rules.lineup_starters:
        raise ValueError(f"GW{week.gw} has the wrong number of starters")
    starter_set = set(starters)
    position_rules = {rule.position: rule for rule in rules.positions}
    starter_positions = Counter(members[code].position for code in starters)
    for position, rule in position_rules.items():
        count = starter_positions[position]
        if not rule.minimum_starters <= count <= rule.maximum_starters:
            raise ValueError(f"GW{week.gw} has an illegal {position} starter count")
    captain = _check_refs((week.captain,), members, context=f"GW{week.gw} captain")[0]
    vice = _check_refs((week.vice_captain,), members, context=f"GW{week.gw} vice-captain")[0]
    if captain == vice or captain not in starter_set or vice not in starter_set:
        raise ValueError("captain and vice-captain must be distinct starters")
    bench_gk = _check_refs(
        (week.bench_goalkeeper,), members, context=f"GW{week.gw} bench goalkeeper"
    )[0]
    bench_order = _check_refs(week.bench_order, members, context=f"GW{week.gw} bench")
    if len(bench_order) != rules.outfield_bench_slots:
        raise ValueError(f"GW{week.gw} has the wrong outfield bench size")
    if rules.goalkeeper_bench_slots != 1 or members[bench_gk].position != "GK":
        raise ValueError(f"GW{week.gw} bench goalkeeper is invalid")
    if any(members[code].position == "GK" for code in bench_order):
        raise ValueError(f"GW{week.gw} outfield bench contains a goalkeeper")
    bench_set = {bench_gk, *bench_order}
    if starter_set & bench_set or starter_set | bench_set != set(members):
        raise ValueError(f"GW{week.gw} lineup and bench do not partition the squad")


class OptimizerPlanArtifact(_Frozen):
    """The complete, provenance-bearing optimizer decision at one deadline."""

    artifact_schema: Literal["fpl.optimizer-plan"] = Field(
        default="fpl.optimizer-plan", alias="schema"
    )
    schema_version: Literal[1, 2] = 1
    status: Literal["development_only_not_a_validated_production_recommendation"] = (
        "development_only_not_a_validated_production_recommendation"
    )
    run_id: str
    decision_sha256: str
    provenance: OptimizerProvenance
    search_policy: SearchPolicy
    solver: SolverIdentity
    rules: SquadRulesSnapshot
    initial_squad: InitialSquadRecord
    plan: TransferPlanRecord
    assumptions: tuple[str, ...]
    manager_context: ManagerPlanContext | None = None

    @field_validator("run_id", "decision_sha256")
    @classmethod
    def _valid_run_id(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _internally_consistent(self) -> Self:
        manager_mode = self.schema_version == 2
        if manager_mode:
            if self.manager_context is None:
                raise ValueError("schema-v2 manager plans require manager_context")
            if self.search_policy.plan_mode != "manager":
                raise ValueError("schema-v2 manager plans require plan_mode=manager")
            if (
                self.search_policy.initial_free_transfers
                != self.manager_context.initial_free_transfers
            ):
                raise ValueError("manager initial free transfers disagree with search policy")
        elif self.manager_context is not None:
            raise ValueError("schema-v1 artifacts cannot carry manager_context")
        elif (
            self.search_policy.plan_mode != "scratch"
            or self.search_policy.initial_free_transfers != 0
        ):
            raise ValueError("schema-v1 artifacts require the scratch planning policy")

        if self.provenance.forecast.season != self.rules.season:
            raise ValueError("forecast and squad-rule seasons disagree")
        if self.provenance.squad_rules.contract_version != self.rules.contract_version:
            raise ValueError("squad-rule provenance and embedded contract versions disagree")
        if self.solver.status != self.initial_squad.solver_status:
            raise ValueError("solver status disagrees with the initial-squad status")
        if not self.assumptions or any(not assumption.strip() for assumption in self.assumptions):
            raise ValueError("optimizer assumptions must be present and non-empty")

        previous = _member_map(
            self.initial_squad.members,
            cost_tenths=self.initial_squad.cost_tenths,
            rules=self.rules,
            context="initial squad",
            enforce_budget=not manager_mode,
        )
        if not set(self.search_policy.locked_codes).issubset(previous):
            raise ValueError("initial squad omits a locked player")
        if not manager_mode and set(self.search_policy.excluded_codes).intersection(previous):
            raise ValueError("initial squad contains an excluded player")
        if manager_mode:
            assert self.manager_context is not None
            forecast_registry_sha = self.provenance.forecast.selectable_player_registry_sha256
            if forecast_registry_sha is None:
                raise ValueError(
                    "manager plans require a forecast selectable-player registry binding"
                )
            if (
                forecast_registry_sha
                != self.manager_context.selectable_player_registry_sha256
            ):
                raise ValueError(
                    "manager capture and forecast selectable-player registries disagree"
                )
            if self.manager_context.planning_gw != self.provenance.forecast.gw_from:
                raise ValueError("manager planning_gw must equal the first forecast gameweek")
            if (
                self.manager_context.initial_free_transfers
                > self.search_policy.free_transfer_bank_cap
            ):
                raise ValueError("manager initial free transfers exceed the configured bank cap")
            hit_cost = self.search_policy.hit_cost_points
            invalid_existing_hits = (
                self.manager_context.existing_hit_points != 0
                if hit_cost == 0
                else self.manager_context.existing_hit_points % hit_cost != 0
            )
            if invalid_existing_hits:
                raise ValueError(
                    "manager existing hit points disagree with the configured hit cost"
                )
            owned = {record.code: record for record in self.manager_context.owned_players}
            if set(owned) != set(previous):
                raise ValueError("manager owned-player values must exactly cover the initial squad")
            for code, record in owned.items():
                now_cost = previous[code].now_cost
                expected_selling = (
                    now_cost
                    if now_cost <= record.purchase_price_tenths
                    else record.purchase_price_tenths
                    + (now_cost - record.purchase_price_tenths) // 2
                )
                if record.selling_price_tenths != expected_selling:
                    raise ValueError(
                        "manager selling price is inconsistent with purchase and current price"
                    )
        expected_gws = tuple(
            range(self.provenance.forecast.gw_from, self.provenance.forecast.gw_to + 1)
        )
        actual_gws = tuple(week.gw for week in self.plan.weeks)
        if actual_gws != expected_gws:
            raise ValueError("plan weeks do not exactly cover the forecast horizon")
        if self.plan.candidate_pool_size < self.rules.squad_size:
            raise ValueError("candidate pool cannot be smaller than the squad")

        previous_free_after = 0
        previous_bank: int | None = None
        sale_values: dict[int, int] = {}
        if manager_mode:
            assert self.manager_context is not None
            previous_bank = self.manager_context.bank_tenths
            sale_values = {
                record.code: record.selling_price_tenths
                for record in self.manager_context.owned_players
            }
        for offset, week in enumerate(self.plan.weeks):
            current = _member_map(
                week.squad_after_transfers,
                cost_tenths=week.squad_cost_tenths,
                rules=self.rules,
                context=f"GW{week.gw} squad",
                enforce_budget=not manager_mode,
            )
            incoming = _check_refs(week.transfers_in, current, context=f"GW{week.gw} transfers in")
            outgoing = _check_refs(
                week.transfers_out, previous, context=f"GW{week.gw} transfers out"
            )
            if not set(self.search_policy.locked_codes).issubset(current):
                raise ValueError(f"GW{week.gw} squad omits a locked player")
            if set(self.search_policy.excluded_codes).intersection(current):
                raise ValueError(f"GW{week.gw} squad contains an excluded player")
            if any(code in previous for code in incoming):
                raise ValueError(f"GW{week.gw} transfers in an existing squad member")
            if any(code not in previous for code in outgoing):
                raise ValueError(f"GW{week.gw} transfers out a non-squad player")
            expected_codes = (set(previous) - set(outgoing)) | set(incoming)
            if expected_codes != set(current):
                raise ValueError(f"GW{week.gw} transfer delta does not produce its recorded squad")
            transfer_count = len(incoming)
            if transfer_count > self.search_policy.transfer_depth:
                raise ValueError(f"GW{week.gw} exceeds the bounded transfer depth")
            if transfer_count > self.search_policy.maximum_transfers_per_gameweek:
                raise ValueError(f"GW{week.gw} exceeds the official transfer maximum")

            if offset == 0 and not manager_mode:
                if transfer_count or week.free_transfers_before or week.free_transfers_after:
                    raise ValueError("the initial gameweek must not contain transfers")
                expected_hit = 0
            else:
                expected_before = (
                    self.search_policy.initial_free_transfers
                    if offset == 0
                    else min(
                        self.search_policy.free_transfer_bank_cap,
                        previous_free_after + self.search_policy.free_transfer_per_gameweek,
                    )
                )
                if week.free_transfers_before != expected_before:
                    raise ValueError(f"GW{week.gw} free-transfer state is inconsistent")
                expected_after = max(0, expected_before - transfer_count)
                if week.free_transfers_after != expected_after:
                    raise ValueError(f"GW{week.gw} banked free transfers are inconsistent")
                expected_hit = (
                    max(0, transfer_count - expected_before) * self.search_policy.hit_cost_points
                )
            if week.hit_points != expected_hit:
                raise ValueError(f"GW{week.gw} hit cost is inconsistent")

            if manager_mode:
                if week.bank_before_tenths is None or week.bank_after_tenths is None:
                    raise ValueError(f"GW{week.gw} manager plan requires bank accounting")
                if week.bank_before_tenths != previous_bank:
                    raise ValueError(f"GW{week.gw} bank-before state is inconsistent")
                proceeds = sum(sale_values[code] for code in outgoing)
                purchases = sum(current[code].now_cost for code in incoming)
                expected_bank_after = week.bank_before_tenths + proceeds - purchases
                if expected_bank_after < 0:
                    raise ValueError(f"GW{week.gw} transfer spend exceeds available cash")
                if week.bank_after_tenths != expected_bank_after:
                    raise ValueError(f"GW{week.gw} bank-after state is inconsistent")
                for code in outgoing:
                    del sale_values[code]
                for code in incoming:
                    # Future prices are frozen: an acquired player's later sale basis is now_cost.
                    sale_values[code] = current[code].now_cost
                previous_bank = week.bank_after_tenths
            elif week.bank_before_tenths is not None or week.bank_after_tenths is not None:
                raise ValueError("schema-v1 artifacts cannot carry weekly bank accounting")
            _validate_week_lineup(week, current, self.rules)
            previous = current
            previous_free_after = week.free_transfers_after

        expected_before_hits = sum(week.expected_points for week in self.plan.weeks)
        expected_hits = sum(week.hit_points for week in self.plan.weeks)
        expected_after_hits = expected_before_hits - expected_hits
        expected_objective = sum(week.objective_value for week in self.plan.weeks) - expected_hits
        reconciliations = (
            (self.plan.expected_points_before_hits, expected_before_hits),
            (self.plan.expected_points_after_hits, expected_after_hits),
            (self.plan.objective_value_after_hits, expected_objective),
        )
        if self.plan.hit_points != expected_hits or any(
            not math.isclose(recorded, expected, rel_tol=0.0, abs_tol=1e-8)
            for recorded, expected in reconciliations
        ):
            raise ValueError("aggregate plan points do not reconcile to the weekly records")

        decision_sha256 = derive_optimizer_decision_sha256(
            self.rules,
            self.initial_squad,
            self.plan,
            self.assumptions,
            manager_context=self.manager_context,
        )
        if self.decision_sha256 != decision_sha256:
            raise ValueError("decision_sha256 does not match the recorded decision")
        expected = derive_optimizer_run_id(
            self.provenance,
            self.search_policy,
            self.solver,
            self.decision_sha256,
            manager_context=self.manager_context,
        )
        if self.run_id != expected:
            raise ValueError(
                "run_id does not match the behaviour-defining provenance; the artifact is "
                "inconsistent or was tampered with"
            )
        return self


def derive_optimizer_run_id(
    provenance: OptimizerProvenance,
    search_policy: SearchPolicy,
    solver: SolverIdentity,
    decision_sha256: str,
    *,
    manager_context: ManagerPlanContext | None = None,
) -> str:
    """A deterministic, stable id for an optimizer run.

    The identity covers the content-hashed inputs, optimiser commit, complete search policy,
    complete solver identity, and the separately validated decision digest. It reads no relocatable
    file path or optimizer publication time.
    """
    identity: dict[str, object] = {
        "schema_version": (
            OPTIMIZER_ARTIFACT_SCHEMA_VERSION
            if manager_context is not None
            else _LEGACY_OPTIMIZER_ARTIFACT_SCHEMA_VERSION
        ),
        "forecast_sha256": provenance.forecast.sha256,
        "forecast_schema": provenance.forecast.forecast_schema,
        "forecast_schema_version": provenance.forecast.forecast_schema_version,
        "forecast_as_of": provenance.forecast.as_of.isoformat(),
        "forecast_season": provenance.forecast.season,
        "forecast_gw_from": provenance.forecast.gw_from,
        "forecast_gw_to": provenance.forecast.gw_to,
        "forecast_commit_sha": provenance.forecast.commit_sha,
        "rules_sha256": provenance.squad_rules.sha256,
        "rules_contract_version": provenance.squad_rules.contract_version,
        "optimizer_commit_sha": provenance.optimizer_commit_sha,
        "decision_sha256": _validate_sha256(decision_sha256),
        "risk_lambda": search_policy.risk_lambda,
        "min_bench_appearance": search_policy.min_bench_appearance,
        "locked_codes": list(search_policy.locked_codes),
        "candidate_pool_per_position": search_policy.candidate_pool_per_position,
        "transfer_depth": search_policy.transfer_depth,
        "transition_limit_per_state": search_policy.transition_limit_per_state,
        "beam_width": search_policy.beam_width,
        "free_transfer_per_gameweek": search_policy.free_transfer_per_gameweek,
        "free_transfer_bank_cap": search_policy.free_transfer_bank_cap,
        "hit_cost_points": search_policy.hit_cost_points,
        "maximum_transfers_per_gameweek": search_policy.maximum_transfers_per_gameweek,
        "search_method": search_policy.search_method,
        "optimality_scope": search_policy.optimality_scope,
        "solver_name": solver.name,
        "solver_package": solver.package,
        "solver_package_version": solver.package_version,
        "solver_binary_version": solver.binary_version,
        "solver_options": list(solver.options),
        "solver_seed": solver.seed,
        "solver_status": solver.status,
    }
    # Preserve legacy run ids: new policy fields enter identity only when non-default.
    if search_policy.excluded_codes:
        identity["excluded_codes"] = list(search_policy.excluded_codes)
    if search_policy.plan_origin == "user_custom":
        identity["plan_origin"] = search_policy.plan_origin
    if manager_context is not None:
        identity["forecast_selectable_player_registry_sha256"] = (
            provenance.forecast.selectable_player_registry_sha256
        )
        identity["plan_mode"] = search_policy.plan_mode
        identity["initial_free_transfers"] = search_policy.initial_free_transfers
        identity["manager_context"] = manager_context.model_dump(mode="json")
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def derive_optimizer_decision_sha256(
    rules: SquadRulesSnapshot,
    initial_squad: InitialSquadRecord,
    plan: TransferPlanRecord,
    assumptions: tuple[str, ...],
    *,
    manager_context: ManagerPlanContext | None = None,
) -> str:
    """Hash the complete self-contained decision and its legality/assumption context."""
    plan_payload = plan.model_dump(mode="json")
    if manager_context is None:
        # Preserve schema-v1 decision hashes exactly: additive v2 None fields did not exist.
        for week in plan_payload["weeks"]:
            week.pop("bank_before_tenths", None)
            week.pop("bank_after_tenths", None)
    decision = {
        "rules": rules.model_dump(mode="json"),
        "initial_squad": initial_squad.model_dump(mode="json"),
        "plan": plan_payload,
        "assumptions": list(assumptions),
    }
    if manager_context is not None:
        decision["manager"] = {
            "plan_mode": "manager",
            "initial_free_transfers": manager_context.initial_free_transfers,
            "context": manager_context.model_dump(mode="json"),
        }
    blob = json.dumps(decision, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_optimizer_plan_artifact(
    *,
    provenance: OptimizerProvenance,
    search_policy: SearchPolicy,
    solver: SolverIdentity,
    rules: SquadRulesSnapshot,
    initial_squad: InitialSquadRecord,
    plan: TransferPlanRecord,
    assumptions: tuple[str, ...],
    manager_context: ManagerPlanContext | None = None,
) -> OptimizerPlanArtifact:
    """Assemble a validated artifact, deriving and embedding its ``run_id``."""
    decision_sha256 = derive_optimizer_decision_sha256(
        rules,
        initial_squad,
        plan,
        assumptions,
        manager_context=manager_context,
    )
    run_id = derive_optimizer_run_id(
        provenance,
        search_policy,
        solver,
        decision_sha256,
        manager_context=manager_context,
    )
    schema_version: Literal[1, 2] = (
        OPTIMIZER_ARTIFACT_SCHEMA_VERSION
        if manager_context is not None
        else _LEGACY_OPTIMIZER_ARTIFACT_SCHEMA_VERSION
    )
    return OptimizerPlanArtifact(
        schema_version=schema_version,
        run_id=run_id,
        decision_sha256=decision_sha256,
        provenance=provenance,
        search_policy=search_policy,
        solver=solver,
        rules=rules,
        initial_squad=initial_squad,
        plan=plan,
        assumptions=assumptions,
        manager_context=manager_context,
    )


def optimizer_artifact_bytes(artifact: OptimizerPlanArtifact) -> bytes:
    """Canonical UTF-8 JSON, suitable for bit-for-bit reproducibility checks.

    Keys are sorted and non-finite floats are rejected, so two artifacts with identical decision
    content and provenance serialise to identical bytes regardless of field construction order.
    """
    payload = artifact.model_dump(mode="json", by_alias=True)
    if artifact.schema_version == _LEGACY_OPTIMIZER_ARTIFACT_SCHEMA_VERSION:
        # The v2 fields are accepted with scratch defaults when old JSON is parsed, but canonical
        # v1 output remains byte-for-byte identical to the pre-v2 serializer.
        payload.pop("manager_context", None)
        payload["provenance"]["forecast"].pop(
            "selectable_player_registry_sha256", None
        )
        payload["search_policy"].pop("plan_mode", None)
        payload["search_policy"].pop("initial_free_transfers", None)
        for week in payload["plan"]["weeks"]:
            week.pop("bank_before_tenths", None)
            week.pop("bank_after_tenths", None)
    text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False)
    return (text + "\n").encode("utf-8")


def write_optimizer_artifact_atomic(
    path: Path,
    artifact: OptimizerPlanArtifact,
    *,
    pre_publish: Callable[[], None] | None = None,
) -> str:
    """Atomically write ``path`` without clobbering, returning the SHA-256 of the bytes written.

    Immutable no-clobber: if ``path`` already exists the write is refused
    (:class:`OptimizerArtifactExistsError`). Otherwise the bytes are written to a unique sibling
    temporary file that is flushed and fsynced, then promoted with one atomic create-if-absent hard
    link. Unlike an existence check followed by replacement, the filesystem operation itself
    chooses exactly one winner when writers race. A failure removes the temporary file and leaves
    an existing destination untouched.
    """
    payload = optimizer_artifact_bytes(artifact)
    if path.exists():
        raise OptimizerArtifactExistsError(
            f"refusing to overwrite an existing immutable optimizer artifact at {path}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if pre_publish is not None:
            pre_publish()
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise OptimizerArtifactExistsError(
                f"refusing to overwrite an existing immutable optimizer artifact at {path}"
            ) from exc
        temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def read_optimizer_artifact(path: Path) -> OptimizerPlanArtifact:
    """Parse and fully validate an optimizer artifact, re-checking its ``run_id`` integrity."""
    text = path.read_text(encoding="utf-8")
    try:
        return OptimizerPlanArtifact.model_validate_json(text)
    except ValueError as exc:
        raise OptimizerArtifactError(f"invalid optimizer artifact: {exc}") from exc
