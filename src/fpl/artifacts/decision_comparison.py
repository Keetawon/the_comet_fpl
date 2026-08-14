"""Immutable side-by-side comparison of the default and diagnostic GW1 decisions.

DEV-ROADMAP P0.3 requires the deadline pack to show, for both the frozen default architecture and
the V1/V1 diagnostic comparator, what each one actually decided and where they disagree. This module
is that report as a durable artifact: it derives everything from two already-frozen prospective
forecasts and their two optimizer plans, and it computes nothing new about football.

It is a **decision aid, not a promotion test**. Two properties keep it honest:

* **It never ranks the architectures.** Each path's expected points are that model's own
  self-estimate on its own scale, so the absolute totals are not comparable; only the selections
  are. The captain question is therefore answered by cross-evaluation -- each model scores *both*
  captains -- rather than by comparing one model's EV against the other's.
* **It fails closed when the two paths are not comparable.** A comparison across different cutoffs,
  horizons, databases, seeds, or live captures would be meaningless, so
  :func:`build_decision_comparison` refuses it. It also refuses a plan paired with a forecast it was
  not optimised from, and re-derives each plan's first-gameweek expected points from the forecast
  rows to prove the plan and the forecast agree.

Like :mod:`fpl.artifacts.optimizer_plan`, the module owns its schema, canonical serialisation,
deterministic identity, and atomic no-clobber write, and reads no database. ``comparison_id`` covers
the content hashes and run identities of both paths and excludes relocatable paths and wall-clock
time, so the same two vintages always compare to the same id.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fpl.artifacts.optimizer_plan import OptimizerPlanArtifact, PositionName
from fpl.artifacts.prospective_points import (
    ForecastArtifactRow,
    ProspectivePointsArtifact,
    artifact_bytes,
)
from fpl.storage.ledger import derive_run_id

DECISION_COMPARISON_SCHEMA = "fpl.decision-comparison"
DECISION_COMPARISON_SCHEMA_VERSION = 1
DECISION_COMPARISON_STATUS = "development_only_decision_aid_not_a_promotion_test"

PathRole = Literal["default", "diagnostic"]

#: The forecast row's degradation flags, reported per path for the whole roster and for the
#: selected squad. Named here so a new flag is a deliberate contract change.
FORECAST_FLAG_FIELDS: tuple[str, ...] = (
    "cold_start_player",
    "stage_a_league_average_team",
    "attacking_signal_cold_start",
    "assist_signal_cold_start",
    "transferred_no_rescale",
)

#: Manifest fields that must be identical for a comparison to mean anything. ``component_modes`` is
#: deliberately absent: it is the one thing that is *supposed* to differ.
SHARED_MANIFEST_FIELDS: tuple[str, ...] = (
    "as_of",
    "season",
    "gw_from",
    "gw_to",
    "row_count",
    "roster_size",
    "fixture_count",
    "monte_carlo_draws",
    "base_seed",
    "commit_sha",
    "database_sha256",
    "schema_version",
)

DECISION_COMPARISON_CAVEATS: tuple[str, ...] = (
    "this is a decision aid, not a promotion test: it does not rank the two architectures and is "
    "not grounds to change the frozen default",
    "expected points are each model's own self-estimate on its own scale; absolute EV is NOT "
    "comparable between the two paths, only the selections are",
    "the next-round availability overlay is valid for the first forecast gameweek only; reusing it "
    "across later gameweeks is an explicit scenario assumption, never a measured policy",
    "every gameweek uses the deadline-known now_cost, so later-gameweek affordability and the "
    "whole transfer scenario are frozen-price scenarios, not price forecasts",
    "bench points and autosub probability are excluded from the optimizer objective, so a low-xP "
    "or unavailable bench slot is an expected consequence of that objective, not a defect",
    "the initial fixed-squad selection is exact; the transfer path is optimal only within the "
    "configured candidate-pool, transfer-depth, transition, and beam bounds",
    "both paths carry every development-only component caveat of their forecasts and neither is a "
    "validated production recommendation",
)


class DecisionComparisonError(ValueError):
    """The two decisions are not comparable, or the comparison is internally inconsistent."""


class DecisionComparisonExistsError(DecisionComparisonError):
    """Refused to overwrite an existing immutable comparison artifact (no-clobber)."""


def _validate_sha256(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
    return value


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


class SharedInputs(_Frozen):
    """The inputs both paths provably share. Stored once because they must be identical."""

    as_of: datetime
    season: str
    gw_from: int = Field(ge=1)
    gw_to: int = Field(ge=1)
    roster_size: int = Field(gt=0)
    row_count: int = Field(gt=0)
    fixture_count: int = Field(ge=0)
    monte_carlo_draws: int = Field(gt=0)
    base_seed: int
    forecast_commit_sha: str
    database_sha256: str
    bootstrap_known_at: datetime
    bootstrap_payload_sha256: str
    contract_versions: dict[str, str]

    @field_validator("database_sha256", "bootstrap_payload_sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.gw_to < self.gw_from:
            raise ValueError("gw_to must be >= gw_from")
        if self.row_count != self.roster_size * (self.gw_to - self.gw_from + 1):
            raise ValueError("row_count does not equal roster_size * gameweeks")
        if self.bootstrap_known_at > self.as_of:
            raise ValueError("bootstrap_known_at must not be after as_of")
        if not self.forecast_commit_sha:
            raise ValueError("forecast_commit_sha is required")
        return self


class PathProvenance(_Frozen):
    """What identifies one compared path: its architecture and its three run identities."""

    role: PathRole
    forecast_path: str
    forecast_sha256: str
    ledger_run_id: str
    optimizer_run_id: str
    optimizer_decision_sha256: str
    optimizer_artifact_sha256: str
    component_modes: dict[str, str]

    @field_validator(
        "forecast_sha256",
        "ledger_run_id",
        "optimizer_run_id",
        "optimizer_decision_sha256",
        "optimizer_artifact_sha256",
    )
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _complete(self) -> Self:
        if not self.component_modes:
            raise ValueError("component_modes are required")
        if not self.forecast_path:
            raise ValueError("forecast_path is required")
        return self


class SquadSlot(_Frozen):
    """One selected player, with the role the plan gave them in the first forecast gameweek."""

    code: int = Field(gt=0)
    web_name: str | None
    position: PositionName
    team_id: int = Field(gt=0)
    team_code: int | None
    now_cost: int = Field(ge=0)
    selected_by_percent: float | None = Field(default=None, ge=0.0, le=100.0, allow_inf_nan=False)
    expected_points: float = Field(allow_inf_nan=False)
    availability_status: str | None
    availability_multiplier: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    role: Literal["starting_xi", "bench_goalkeeper", "bench_outfield"]
    bench_order_index: int | None = Field(default=None, ge=1)
    is_captain: bool
    is_vice_captain: bool
    flags: tuple[str, ...]

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.role == "bench_outfield" and self.bench_order_index is None:
            raise ValueError("an outfield bench slot requires its bench_order_index")
        if self.role != "bench_outfield" and self.bench_order_index is not None:
            raise ValueError("only an outfield bench slot carries a bench_order_index")
        if (self.is_captain or self.is_vice_captain) and self.role != "starting_xi":
            raise ValueError("captain and vice-captain must start")
        if self.is_captain and self.is_vice_captain:
            raise ValueError("one player cannot be both captain and vice-captain")
        for flag in self.flags:
            if flag not in FORECAST_FLAG_FIELDS:
                raise ValueError(f"unknown forecast flag {flag!r}")
        if self.flags != tuple(sorted(self.flags)):
            raise ValueError("flags must be sorted")
        return self


class TransferStep(_Frozen):
    """One gameweek of the bounded transfer scenario, under frozen deadline prices."""

    gw: int = Field(ge=1)
    transfers_in: tuple[int, ...]
    transfers_out: tuple[int, ...]
    hit_points: int = Field(ge=0)
    free_transfers_before: int = Field(ge=0)
    free_transfers_after: int = Field(ge=0)
    squad_cost_tenths: int = Field(ge=0)

    @model_validator(mode="after")
    def _balanced(self) -> Self:
        if len(self.transfers_in) != len(self.transfers_out):
            raise ValueError("transfers in and out must balance")
        for label, codes in (("in", self.transfers_in), ("out", self.transfers_out)):
            if codes != tuple(sorted(codes)) or len(set(codes)) != len(codes):
                raise ValueError(f"transfers {label} must be unique and sorted")
        return self


class PathDecision(_Frozen):
    """One path's complete decision plus the degradation flags behind it."""

    provenance: PathProvenance
    cost_tenths: int = Field(ge=0)
    budget_tenths: int = Field(gt=0)
    captain_multiplier: int = Field(ge=2)
    mean_ownership_percent: float | None = Field(default=None, ge=0.0, allow_inf_nan=False)
    first_gw_expected_points: float = Field(allow_inf_nan=False)
    horizon_expected_points_after_hits: float = Field(allow_inf_nan=False)
    total_hit_points: int = Field(ge=0)
    squad: tuple[SquadSlot, ...]
    transfer_steps: tuple[TransferStep, ...]
    roster_flag_row_counts: dict[str, int]
    squad_flagged_codes: dict[str, tuple[int, ...]]

    @field_validator("squad")
    @classmethod
    def _sorted_squad(cls, value: tuple[SquadSlot, ...]) -> tuple[SquadSlot, ...]:
        codes = [slot.code for slot in value]
        if codes != sorted(codes) or len(set(codes)) != len(codes):
            raise ValueError("squad slots must be unique and ordered by code")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> Self:
        if self.cost_tenths > self.budget_tenths:
            raise ValueError("squad cost exceeds the budget")
        if self.cost_tenths != sum(slot.now_cost for slot in self.squad):
            raise ValueError("squad cost does not equal its member prices")
        if sum(1 for slot in self.squad if slot.is_captain) != 1:
            raise ValueError("exactly one captain is required")
        if sum(1 for slot in self.squad if slot.is_vice_captain) != 1:
            raise ValueError("exactly one vice-captain is required")
        if sum(1 for slot in self.squad if slot.role == "bench_goalkeeper") != 1:
            raise ValueError("exactly one bench goalkeeper is required")
        bench = sorted(
            slot.bench_order_index
            for slot in self.squad
            if slot.role == "bench_outfield" and slot.bench_order_index is not None
        )
        if bench != list(range(1, len(bench) + 1)):
            raise ValueError("outfield bench order must be a dense 1..n sequence")
        for flag in tuple(self.roster_flag_row_counts) + tuple(self.squad_flagged_codes):
            if flag not in FORECAST_FLAG_FIELDS:
                raise ValueError(f"unknown forecast flag {flag!r}")
        squad_codes = {slot.code for slot in self.squad}
        for flag, codes in self.squad_flagged_codes.items():
            if tuple(sorted(codes)) != codes or len(set(codes)) != len(codes):
                raise ValueError(f"{flag} codes must be unique and sorted")
            if not set(codes) <= squad_codes:
                raise ValueError(f"{flag} names a player outside the squad")
        gws = [step.gw for step in self.transfer_steps]
        if gws != sorted(gws) or len(set(gws)) != len(gws):
            raise ValueError("transfer steps must be unique and ordered by gameweek")
        if self.total_hit_points != sum(step.hit_points for step in self.transfer_steps):
            raise ValueError("total hit points do not reconcile to the weekly steps")
        return self

    @property
    def starting_xi(self) -> tuple[int, ...]:
        return tuple(slot.code for slot in self.squad if slot.role == "starting_xi")

    @property
    def captain(self) -> int:
        return next(slot.code for slot in self.squad if slot.is_captain)

    @property
    def vice_captain(self) -> int:
        return next(slot.code for slot in self.squad if slot.is_vice_captain)


class CaptainCrossEvaluation(_Frozen):
    """One model scoring BOTH captains, so the gap is never taken across two different scales."""

    evaluating_role: PathRole
    own_captain_code: int = Field(gt=0)
    own_captain_expected_points: float = Field(allow_inf_nan=False)
    other_captain_code: int = Field(gt=0)
    other_captain_expected_points: float = Field(allow_inf_nan=False)
    captain_multiplier: int = Field(ge=2)
    gap: float = Field(allow_inf_nan=False)
    gap_after_captain_multiplier: float = Field(allow_inf_nan=False)

    @model_validator(mode="after")
    def _reconciles(self) -> Self:
        expected = self.own_captain_expected_points - self.other_captain_expected_points
        if not math.isclose(self.gap, expected, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("captain gap does not equal the difference of the two valuations")
        scaled = self.gap * self.captain_multiplier
        if not math.isclose(self.gap_after_captain_multiplier, scaled, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("scaled captain gap does not equal gap * captain_multiplier")
        return self


class SquadDifference(_Frozen):
    """Where the two paths agree and where they part."""

    common_codes: tuple[int, ...]
    default_only_codes: tuple[int, ...]
    diagnostic_only_codes: tuple[int, ...]
    squad_overlap: int = Field(ge=0)
    first_gw_xi_overlap: int = Field(ge=0)
    first_gw_xi_common_codes: tuple[int, ...]
    captain_agreement: bool
    vice_captain_agreement: bool

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        for label, codes in (
            ("common", self.common_codes),
            ("default-only", self.default_only_codes),
            ("diagnostic-only", self.diagnostic_only_codes),
            ("xi-common", self.first_gw_xi_common_codes),
        ):
            if codes != tuple(sorted(codes)) or len(set(codes)) != len(codes):
                raise ValueError(f"{label} codes must be unique and sorted")
        if self.squad_overlap != len(self.common_codes):
            raise ValueError("squad_overlap does not equal the common code count")
        if self.first_gw_xi_overlap != len(self.first_gw_xi_common_codes):
            raise ValueError("first_gw_xi_overlap does not equal the common XI code count")
        if set(self.common_codes) & set(self.default_only_codes):
            raise ValueError("a common player cannot also be default-only")
        if set(self.common_codes) & set(self.diagnostic_only_codes):
            raise ValueError("a common player cannot also be diagnostic-only")
        if set(self.default_only_codes) & set(self.diagnostic_only_codes):
            raise ValueError("a player cannot be unique to both paths")
        if not set(self.first_gw_xi_common_codes) <= set(self.common_codes):
            raise ValueError("a shared starter must be a shared squad member")
        return self


class DecisionComparisonArtifact(_Frozen):
    """The complete default-versus-diagnostic decision comparison at one deadline."""

    artifact_schema: Literal["fpl.decision-comparison"] = Field(
        default="fpl.decision-comparison", alias="schema"
    )
    schema_version: Literal[1] = 1
    status: Literal["development_only_decision_aid_not_a_promotion_test"] = (
        "development_only_decision_aid_not_a_promotion_test"
    )
    comparison_id: str
    shared_inputs: SharedInputs
    default: PathDecision
    diagnostic: PathDecision
    difference: SquadDifference
    captain_cross_evaluation: tuple[CaptainCrossEvaluation, ...]
    caveats: tuple[str, ...]

    @field_validator("comparison_id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _internally_consistent(self) -> Self:
        if self.default.provenance.role != "default":
            raise ValueError("the default path must carry role 'default'")
        if self.diagnostic.provenance.role != "diagnostic":
            raise ValueError("the diagnostic path must carry role 'diagnostic'")
        if self.default.provenance.component_modes == self.diagnostic.provenance.component_modes:
            raise ValueError(
                "the two paths declare the same component architecture; there is nothing to compare"
            )
        if not self.caveats or any(not caveat.strip() for caveat in self.caveats):
            raise ValueError("caveats must be present and non-empty")

        default_codes = {slot.code for slot in self.default.squad}
        diagnostic_codes = {slot.code for slot in self.diagnostic.squad}
        difference = self.difference
        if set(difference.common_codes) != default_codes & diagnostic_codes:
            raise ValueError("common codes do not match the two squads")
        if set(difference.default_only_codes) != default_codes - diagnostic_codes:
            raise ValueError("default-only codes do not match the two squads")
        if set(difference.diagnostic_only_codes) != diagnostic_codes - default_codes:
            raise ValueError("diagnostic-only codes do not match the two squads")
        if set(difference.first_gw_xi_common_codes) != set(self.default.starting_xi) & set(
            self.diagnostic.starting_xi
        ):
            raise ValueError("shared starters do not match the two lineups")
        if difference.captain_agreement != (self.default.captain == self.diagnostic.captain):
            raise ValueError("captain_agreement disagrees with the recorded captains")
        if difference.vice_captain_agreement != (
            self.default.vice_captain == self.diagnostic.vice_captain
        ):
            raise ValueError("vice_captain_agreement disagrees with the recorded vice-captains")

        roles = tuple(entry.evaluating_role for entry in self.captain_cross_evaluation)
        if roles != ("default", "diagnostic"):
            raise ValueError("captain cross-evaluation must hold one default then one diagnostic")
        for entry in self.captain_cross_evaluation:
            path = self.default if entry.evaluating_role == "default" else self.diagnostic
            other = self.diagnostic if entry.evaluating_role == "default" else self.default
            if entry.own_captain_code != path.captain:
                raise ValueError("cross-evaluation own captain disagrees with the plan")
            if entry.other_captain_code != other.captain:
                raise ValueError("cross-evaluation other captain disagrees with the other plan")
            if entry.captain_multiplier != path.captain_multiplier:
                raise ValueError("cross-evaluation captain multiplier disagrees with the rules")

        expected = derive_comparison_id(self.shared_inputs, self.default, self.diagnostic)
        if self.comparison_id != expected:
            raise ValueError(
                "comparison_id does not match the compared content; the artifact is inconsistent "
                "or was tampered with"
            )
        return self


def derive_comparison_id(
    shared_inputs: SharedInputs, default: PathDecision, diagnostic: PathDecision
) -> str:
    """A deterministic id for one comparison of two specific frozen vintages.

    It covers the shared knowledge-time identity and both paths' content hashes and run identities,
    and reads no relocatable path or wall-clock time.
    """

    def path_identity(path: PathDecision) -> dict[str, object]:
        return {
            "role": path.provenance.role,
            "forecast_sha256": path.provenance.forecast_sha256,
            "ledger_run_id": path.provenance.ledger_run_id,
            "optimizer_run_id": path.provenance.optimizer_run_id,
            "optimizer_decision_sha256": path.provenance.optimizer_decision_sha256,
            "optimizer_artifact_sha256": path.provenance.optimizer_artifact_sha256,
            "component_modes": dict(path.provenance.component_modes),
        }

    identity = {
        "schema_version": DECISION_COMPARISON_SCHEMA_VERSION,
        "as_of": shared_inputs.as_of.isoformat(),
        "season": shared_inputs.season,
        "gw_from": shared_inputs.gw_from,
        "gw_to": shared_inputs.gw_to,
        "forecast_commit_sha": shared_inputs.forecast_commit_sha,
        "database_sha256": shared_inputs.database_sha256,
        "base_seed": shared_inputs.base_seed,
        "default": path_identity(default),
        "diagnostic": path_identity(diagnostic),
    }
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _first_gw_rows(artifact: ProspectivePointsArtifact) -> dict[int, ForecastArtifactRow]:
    gw = artifact.manifest.gw_from
    return {row.code: row for row in artifact.rows if row.gw == gw}


def _require_shared_manifests(
    default: ProspectivePointsArtifact, diagnostic: ProspectivePointsArtifact
) -> None:
    for field in SHARED_MANIFEST_FIELDS:
        left = getattr(default.manifest, field)
        right = getattr(diagnostic.manifest, field)
        if left != right:
            raise DecisionComparisonError(
                f"the two forecasts are not comparable: {field} differs ({left!r} vs {right!r})"
            )
    if default.manifest.live_inputs != diagnostic.manifest.live_inputs:
        raise DecisionComparisonError("the two forecasts used different live captures")
    if default.manifest.contracts != diagnostic.manifest.contracts:
        raise DecisionComparisonError("the two forecasts used different frozen contracts")
    if default.manifest.component_modes == diagnostic.manifest.component_modes:
        raise DecisionComparisonError(
            "the two forecasts declare the same component architecture; there is nothing to compare"
        )


def _require_plan_matches_forecast(
    plan: OptimizerPlanArtifact,
    artifact: ProspectivePointsArtifact,
    forecast_sha256: str,
    role: str,
) -> None:
    if plan.provenance.forecast.sha256 != forecast_sha256:
        raise DecisionComparisonError(
            f"the {role} optimizer plan was not produced from the {role} forecast "
            f"(plan names {plan.provenance.forecast.sha256[:12]}, forecast hashes to "
            f"{forecast_sha256[:12]})"
        )
    manifest = artifact.manifest
    forecast = plan.provenance.forecast
    if (forecast.season, forecast.gw_from, forecast.gw_to, forecast.as_of) != (
        manifest.season,
        manifest.gw_from,
        manifest.gw_to,
        manifest.as_of,
    ):
        raise DecisionComparisonError(f"the {role} plan and forecast disagree on season/horizon")


def _first_week_expected_points(
    plan: OptimizerPlanArtifact, rows: Mapping[int, ForecastArtifactRow]
) -> float:
    week = plan.plan.weeks[0]
    total = 0.0
    for ref in week.starting_xi:
        row = rows.get(ref.code)
        if row is None:
            raise DecisionComparisonError(
                f"starter {ref.code} has no forecast row in the first gameweek"
            )
        total += row.availability_adjusted_expected_points
    captain = rows[week.captain.code]
    total += (plan.rules.captain_multiplier - 1) * captain.availability_adjusted_expected_points
    return total


def _flags_for(row: ForecastArtifactRow) -> tuple[str, ...]:
    """Set flags in sorted order, so a slot's flag list is stable however they are declared."""
    return tuple(sorted(flag for flag in FORECAST_FLAG_FIELDS if getattr(row, flag)))


def _build_path(
    role: PathRole,
    artifact: ProspectivePointsArtifact,
    plan: OptimizerPlanArtifact,
    forecast_path: str,
    forecast_sha256: str,
    plan_sha256: str,
) -> PathDecision:
    _require_plan_matches_forecast(plan, artifact, forecast_sha256, role)
    rows = _first_gw_rows(artifact)
    week = plan.plan.weeks[0]

    derived = _first_week_expected_points(plan, rows)
    if not math.isclose(derived, week.expected_points, rel_tol=0.0, abs_tol=1e-6):
        raise DecisionComparisonError(
            f"the {role} plan's first-gameweek expected points ({week.expected_points:.6f}) do not "
            f"reconcile to its forecast rows ({derived:.6f})"
        )

    starters = {ref.code for ref in week.starting_xi}
    bench_positions = {ref.code: index + 1 for index, ref in enumerate(week.bench_order)}
    slots: list[SquadSlot] = []
    for member in plan.initial_squad.members:
        row = rows.get(member.code)
        if row is None:
            raise DecisionComparisonError(
                f"{role} squad member {member.code} has no first-gameweek forecast row"
            )
        if member.code in starters:
            slot_role: Literal["starting_xi", "bench_goalkeeper", "bench_outfield"] = "starting_xi"
        elif member.code == week.bench_goalkeeper.code:
            slot_role = "bench_goalkeeper"
        else:
            slot_role = "bench_outfield"
        slots.append(
            SquadSlot(
                code=member.code,
                web_name=member.web_name,
                position=member.position,
                team_id=member.team_id,
                team_code=member.team_code,
                now_cost=member.now_cost,
                selected_by_percent=member.selected_by_percent,
                expected_points=row.availability_adjusted_expected_points,
                availability_status=row.availability_status,
                availability_multiplier=row.availability_multiplier,
                role=slot_role,
                bench_order_index=(
                    bench_positions.get(member.code) if slot_role == "bench_outfield" else None
                ),
                is_captain=member.code == week.captain.code,
                is_vice_captain=member.code == week.vice_captain.code,
                flags=_flags_for(row),
            )
        )
    slots.sort(key=lambda slot: slot.code)

    ownerships = [
        slot.selected_by_percent for slot in slots if slot.selected_by_percent is not None
    ]
    squad_codes = {slot.code for slot in slots}
    roster_counts = {
        flag: sum(1 for row in artifact.rows if getattr(row, flag)) for flag in FORECAST_FLAG_FIELDS
    }
    squad_flagged = {
        flag: tuple(
            sorted(
                {
                    row.code
                    for row in artifact.rows
                    if row.code in squad_codes and getattr(row, flag)
                }
            )
        )
        for flag in FORECAST_FLAG_FIELDS
    }

    return PathDecision(
        provenance=PathProvenance(
            role=role,
            forecast_path=forecast_path,
            forecast_sha256=forecast_sha256,
            ledger_run_id=derive_run_id(artifact.manifest, forecast_sha256),
            optimizer_run_id=plan.run_id,
            optimizer_decision_sha256=plan.decision_sha256,
            optimizer_artifact_sha256=plan_sha256,
            component_modes=dict(artifact.manifest.component_modes),
        ),
        cost_tenths=plan.initial_squad.cost_tenths,
        budget_tenths=plan.rules.budget_tenths,
        captain_multiplier=plan.rules.captain_multiplier,
        mean_ownership_percent=(sum(ownerships) / len(ownerships) if ownerships else None),
        first_gw_expected_points=week.expected_points,
        horizon_expected_points_after_hits=plan.plan.expected_points_after_hits,
        total_hit_points=plan.plan.hit_points,
        squad=tuple(slots),
        transfer_steps=tuple(
            TransferStep(
                gw=step.gw,
                transfers_in=tuple(sorted(ref.code for ref in step.transfers_in)),
                transfers_out=tuple(sorted(ref.code for ref in step.transfers_out)),
                hit_points=step.hit_points,
                free_transfers_before=step.free_transfers_before,
                free_transfers_after=step.free_transfers_after,
                squad_cost_tenths=step.squad_cost_tenths,
            )
            for step in plan.plan.weeks
        ),
        roster_flag_row_counts=roster_counts,
        squad_flagged_codes=squad_flagged,
    )


def _cross_evaluate(
    role: PathRole,
    path: PathDecision,
    other: PathDecision,
    rows: Mapping[int, ForecastArtifactRow],
) -> CaptainCrossEvaluation:
    own_code, other_code = path.captain, other.captain
    own_row, other_row = rows.get(own_code), rows.get(other_code)
    if own_row is None or other_row is None:
        raise DecisionComparisonError(
            f"the {role} forecast cannot value both captains ({own_code}, {other_code})"
        )
    own = own_row.availability_adjusted_expected_points
    rival = other_row.availability_adjusted_expected_points
    gap = own - rival
    return CaptainCrossEvaluation(
        evaluating_role=role,
        own_captain_code=own_code,
        own_captain_expected_points=own,
        other_captain_code=other_code,
        other_captain_expected_points=rival,
        captain_multiplier=path.captain_multiplier,
        gap=gap,
        gap_after_captain_multiplier=gap * path.captain_multiplier,
    )


def build_decision_comparison(
    *,
    default_forecast: ProspectivePointsArtifact,
    default_plan: OptimizerPlanArtifact,
    default_forecast_path: str,
    default_plan_sha256: str,
    diagnostic_forecast: ProspectivePointsArtifact,
    diagnostic_plan: OptimizerPlanArtifact,
    diagnostic_forecast_path: str,
    diagnostic_plan_sha256: str,
) -> DecisionComparisonArtifact:
    """Derive the comparison, refusing anything that would make it meaningless.

    Fails closed when the two forecasts do not share a cutoff, horizon, database, seed, live
    capture, or contract set; when a plan is paired with a forecast it was not optimised from; or
    when a plan's first-gameweek expected points do not reconcile to its own forecast rows.
    """
    _require_shared_manifests(default_forecast, diagnostic_forecast)

    default_sha = hashlib.sha256(artifact_bytes(default_forecast)).hexdigest()
    diagnostic_sha = hashlib.sha256(artifact_bytes(diagnostic_forecast)).hexdigest()

    default_path = _build_path(
        "default",
        default_forecast,
        default_plan,
        default_forecast_path,
        default_sha,
        default_plan_sha256,
    )
    diagnostic_path = _build_path(
        "diagnostic",
        diagnostic_forecast,
        diagnostic_plan,
        diagnostic_forecast_path,
        diagnostic_sha,
        diagnostic_plan_sha256,
    )

    manifest = default_forecast.manifest
    shared = SharedInputs(
        as_of=manifest.as_of,
        season=manifest.season,
        gw_from=manifest.gw_from,
        gw_to=manifest.gw_to,
        roster_size=manifest.roster_size,
        row_count=manifest.row_count,
        fixture_count=manifest.fixture_count,
        monte_carlo_draws=manifest.monte_carlo_draws,
        base_seed=manifest.base_seed,
        forecast_commit_sha=manifest.commit_sha,
        database_sha256=manifest.database_sha256,
        bootstrap_known_at=manifest.live_inputs.bootstrap_known_at,
        bootstrap_payload_sha256=manifest.live_inputs.bootstrap_payload_sha256,
        contract_versions={
            name: identity.version for name, identity in sorted(manifest.contracts.items())
        },
    )

    default_codes = {slot.code for slot in default_path.squad}
    diagnostic_codes = {slot.code for slot in diagnostic_path.squad}
    common_xi = set(default_path.starting_xi) & set(diagnostic_path.starting_xi)
    difference = SquadDifference(
        common_codes=tuple(sorted(default_codes & diagnostic_codes)),
        default_only_codes=tuple(sorted(default_codes - diagnostic_codes)),
        diagnostic_only_codes=tuple(sorted(diagnostic_codes - default_codes)),
        squad_overlap=len(default_codes & diagnostic_codes),
        first_gw_xi_overlap=len(common_xi),
        first_gw_xi_common_codes=tuple(sorted(common_xi)),
        captain_agreement=default_path.captain == diagnostic_path.captain,
        vice_captain_agreement=default_path.vice_captain == diagnostic_path.vice_captain,
    )

    cross = (
        _cross_evaluate("default", default_path, diagnostic_path, _first_gw_rows(default_forecast)),
        _cross_evaluate(
            "diagnostic", diagnostic_path, default_path, _first_gw_rows(diagnostic_forecast)
        ),
    )

    return DecisionComparisonArtifact(
        comparison_id=derive_comparison_id(shared, default_path, diagnostic_path),
        shared_inputs=shared,
        default=default_path,
        diagnostic=diagnostic_path,
        difference=difference,
        captain_cross_evaluation=cross,
        caveats=DECISION_COMPARISON_CAVEATS,
    )


def decision_comparison_bytes(artifact: DecisionComparisonArtifact) -> bytes:
    """Canonical UTF-8 JSON: sorted keys, no non-finite floats, stable across constructions."""
    payload = artifact.model_dump(mode="json", by_alias=True)
    text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False)
    return (text + "\n").encode("utf-8")


def write_decision_comparison_atomic(
    path: Path,
    artifact: DecisionComparisonArtifact,
    *,
    pre_publish: Callable[[], None] | None = None,
) -> str:
    """Atomically write ``path`` without clobbering, returning the SHA-256 of the bytes written.

    Same discipline as the optimizer artifact: a flushed and fsynced sibling temporary file is
    promoted with one atomic create-if-absent hard link, so racing writers have exactly one winner
    and an existing destination is never overwritten.
    """
    payload = decision_comparison_bytes(artifact)
    if path.exists():
        raise DecisionComparisonExistsError(
            f"refusing to overwrite an existing immutable decision comparison at {path}"
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
            raise DecisionComparisonExistsError(
                f"refusing to overwrite an existing immutable decision comparison at {path}"
            ) from exc
        temporary.unlink()
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return hashlib.sha256(payload).hexdigest()


def read_decision_comparison(path: Path) -> DecisionComparisonArtifact:
    """Parse and fully validate a comparison, re-checking its ``comparison_id`` integrity."""
    text = path.read_text(encoding="utf-8")
    try:
        return DecisionComparisonArtifact.model_validate_json(text)
    except ValueError as exc:
        raise DecisionComparisonError(f"invalid decision comparison: {exc}") from exc


def _money(tenths: int) -> str:
    return f"{tenths / 10:.1f}"


def _slot_line(slot: SquadSlot) -> str:
    if slot.role == "starting_xi":
        role = "XI"
    elif slot.role == "bench_goalkeeper":
        role = "BENCH-GK"
    else:
        role = f"BENCH-{slot.bench_order_index}"
    marks = "".join(("C" if slot.is_captain else "", "V" if slot.is_vice_captain else ""))
    own = "-" if slot.selected_by_percent is None else f"{slot.selected_by_percent:.1f}"
    flags = ",".join(flag.replace("_", "-") for flag in slot.flags)
    status = slot.availability_status or "?"
    multiplier = (
        "" if slot.availability_multiplier == 1.0 else f" x{slot.availability_multiplier:g}"
    )
    return (
        f"  {slot.code:>7}  {slot.position:<3} t{slot.team_id:<3} {_money(slot.now_cost):>5} "
        f"{own:>5}% {slot.expected_points:>6.2f}  {role:<9}{marks:<2} {status}{multiplier}"
        f"{('  ' + flags) if flags else ''}"
    )


def _render_path(path: PathDecision, label: str) -> list[str]:
    modes = ", ".join(
        f"{name}={value}"
        for name, value in sorted(path.provenance.component_modes.items())
        if not name.startswith("component.")
    )
    lines = [
        f"### {label} ({modes})",
        "",
        f"- cost {_money(path.cost_tenths)}m of {_money(path.budget_tenths)}m"
        f"  |  GW EV {path.first_gw_expected_points:.2f}"
        f"  |  horizon EV {path.horizon_expected_points_after_hits:.2f}"
        f"  |  hits {path.total_hit_points}",
        "- mean ownership "
        + ("n/a" if path.mean_ownership_percent is None else f"{path.mean_ownership_percent:.2f}%"),
        f"- ledger run `{path.provenance.ledger_run_id}`",
        f"- optimizer run `{path.provenance.optimizer_run_id}`",
        f"- decision `{path.provenance.optimizer_decision_sha256}`",
        f"- forecast `{path.provenance.forecast_sha256}`",
        "",
        "```",
        f"  {'code':>7}  {'pos':<3} {'team':<4} {'£':>5} {'own':>5}   {'xP':>4}  "
        f"{'role':<9}   status  flags",
    ]
    lines.extend(_slot_line(slot) for slot in path.squad)
    lines.append("```")
    lines.append("")
    lines.append("Transfer scenario (frozen deadline prices, not a price forecast):")
    lines.append("")
    for step in path.transfer_steps:
        moves = (
            "hold"
            if not step.transfers_in
            else f"in {list(step.transfers_in)} out {list(step.transfers_out)}"
        )
        lines.append(
            f"- GW{step.gw}: {moves}; free transfers {step.free_transfers_before} -> "
            f"{step.free_transfers_after}; hit {step.hit_points}; "
            f"squad {_money(step.squad_cost_tenths)}m"
        )
    flagged = {flag: codes for flag, codes in path.squad_flagged_codes.items() if codes}
    lines.append("")
    if flagged:
        lines.append("Degradation flags on selected players (any gameweek in the horizon):")
        lines.append("")
        for flag, codes in sorted(flagged.items()):
            lines.append(
                f"- `{flag}`: {list(codes)} "
                f"({path.roster_flag_row_counts[flag]} flagged rows across the roster)"
            )
    else:
        lines.append("No degradation flags on any selected player.")
    lines.append("")
    return lines


def render_decision_comparison(artifact: DecisionComparisonArtifact) -> str:
    """Render the comparison as a self-contained Markdown decision aid."""
    shared = artifact.shared_inputs
    difference = artifact.difference
    lines = [
        "# GW1 decision comparison: default vs diagnostic",
        "",
        f"Status: **{artifact.status}**",
        "",
        f"- comparison `{artifact.comparison_id}`",
        f"- season {shared.season}, GW{shared.gw_from}-{shared.gw_to}, "
        f"as_of `{shared.as_of.isoformat()}`",
        f"- forecast commit `{shared.forecast_commit_sha}`",
        f"- database `{shared.database_sha256}`",
        f"- bootstrap known_at `{shared.bootstrap_known_at.isoformat()}` "
        f"(<= as_of), payload `{shared.bootstrap_payload_sha256}`",
        f"- roster {shared.roster_size}, rows {shared.row_count}, "
        f"fixtures {shared.fixture_count}, draws {shared.monte_carlo_draws}, "
        f"seed {shared.base_seed}",
        "- frozen contracts: "
        + ", ".join(
            f"{name} v{version}" for name, version in sorted(shared.contract_versions.items())
        ),
        "",
        "Both paths were generated from the identical cutoff, horizon, database, seed, live",
        "capture, and contract set. Only the component architecture differs.",
        "",
    ]
    lines.extend(_render_path(artifact.default, "Default"))
    lines.extend(_render_path(artifact.diagnostic, "Diagnostic"))

    lines.extend(
        [
            "### Where they differ",
            "",
            f"- squad overlap **{difference.squad_overlap}/{len(artifact.default.squad)}**; "
            f"first-gameweek XI overlap **{difference.first_gw_xi_overlap}/"
            f"{len(artifact.default.starting_xi)}**",
            f"- common: {list(difference.common_codes)}",
            f"- default only: {list(difference.default_only_codes)}",
            f"- diagnostic only: {list(difference.diagnostic_only_codes)}",
            f"- captain: default {artifact.default.captain}, "
            f"diagnostic {artifact.diagnostic.captain} -- "
            f"**{'AGREE' if difference.captain_agreement else 'DISAGREE'}**",
            f"- vice-captain: default {artifact.default.vice_captain}, "
            f"diagnostic {artifact.diagnostic.vice_captain} -- "
            f"**{'AGREE' if difference.vice_captain_agreement else 'DISAGREE'}**",
            "",
            "### Captain cross-evaluation",
            "",
            "Each model scores **both** captains, so no gap is ever taken across two different",
            "scales. A positive gap means that model prefers its own captain.",
            "",
        ]
    )
    for entry in artifact.captain_cross_evaluation:
        lines.append(
            f"- under the **{entry.evaluating_role}** model: own {entry.own_captain_code} = "
            f"{entry.own_captain_expected_points:.2f} xP, other {entry.other_captain_code} = "
            f"{entry.other_captain_expected_points:.2f} xP, gap {entry.gap:+.2f} "
            f"({entry.gap_after_captain_multiplier:+.2f} after the "
            f"x{entry.captain_multiplier} armband)"
        )
    lines.extend(["", "### Caveats", ""])
    lines.extend(f"- {caveat}" for caveat in artifact.caveats)
    lines.append("")
    return "\n".join(lines)


__all__ = [
    "DECISION_COMPARISON_CAVEATS",
    "DECISION_COMPARISON_SCHEMA",
    "DECISION_COMPARISON_SCHEMA_VERSION",
    "DECISION_COMPARISON_STATUS",
    "FORECAST_FLAG_FIELDS",
    "CaptainCrossEvaluation",
    "DecisionComparisonArtifact",
    "DecisionComparisonError",
    "DecisionComparisonExistsError",
    "PathDecision",
    "PathProvenance",
    "SharedInputs",
    "SquadDifference",
    "SquadSlot",
    "TransferStep",
    "build_decision_comparison",
    "decision_comparison_bytes",
    "derive_comparison_id",
    "read_decision_comparison",
    "render_decision_comparison",
    "write_decision_comparison_atomic",
]
