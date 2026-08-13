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

* **Stable run identity.** ``run_id`` is a SHA-256 over only the *behaviour-defining* provenance --
  the forecast's content hash, the squad rules' content hash and contract version, the optimiser's
  commit, the risk parameter, the search bounds, and the solver name/options/seed. It deliberately
  excludes wall-clock creation time, the output path, and environment-discovered solver *versions*,
  so two runs from identical inputs produce an identical id while any behaviour-defining change
  produces a different one. The id is re-derived and checked on read, so a tampered artifact is
  rejected.
* **Immutability.** :func:`write_optimizer_artifact_atomic` refuses to overwrite an existing
  destination (no-clobber) and writes through a unique sibling temporary file plus an atomic rename,
  so a crashed write leaves neither a partial file nor a clobbered previous vintage.
* **Strictness and determinism.** Serialisation is canonical (sorted keys, ``allow_nan=False``) and
  every float field rejects non-finite values at construction, so a NaN can never reach the file or
  a downstream consumer.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

OPTIMIZER_ARTIFACT_SCHEMA = "fpl.optimizer-plan"
OPTIMIZER_ARTIFACT_SCHEMA_VERSION = 1
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
    gw_from: int = Field(ge=1)
    gw_to: int = Field(ge=1)
    commit_sha: str

    @field_validator("sha256")
    @classmethod
    def _valid_sha256(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.gw_to < self.gw_from:
            raise ValueError("forecast gw_to must be >= gw_from")
        if not self.commit_sha:
            raise ValueError("forecast commit_sha is required")
        if not self.forecast_schema:
            raise ValueError("forecast schema is required")
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

    ``package_version`` and ``binary_version`` are environment-discovered and best-effort (either
    may be ``None`` if discovery fails); they are recorded for audit but are deliberately NOT part
    of the ``run_id`` identity, exactly as the prediction ledger's ``run_id`` excludes library
    versions. ``name``, ``options``, and ``seed`` ARE behaviour-defining and enter the id.
    ``status`` is the solver outcome, recorded but not part of the id.
    """

    name: str
    package: str
    package_version: str | None
    binary_version: str | None
    options: tuple[str, ...]
    seed: int
    status: str


class SearchPolicy(_Frozen):
    """The complete bounded-search policy that shaped the transfer plan.

    Every field is behaviour-defining and enters the ``run_id``. The constraint bounds and the
    transfer-state parameters come from the squad-rules file; ``risk_lambda`` comes from the CLI;
    ``search_method`` and ``optimality_scope`` are the planner's own declared scope of exactness.
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
    search_method: str
    optimality_scope: str


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


class OptimizerPlanArtifact(_Frozen):
    """The complete, provenance-bearing optimizer decision at one deadline."""

    artifact_schema: Literal["fpl.optimizer-plan"] = Field(
        default="fpl.optimizer-plan", alias="schema"
    )
    schema_version: Literal[1] = 1
    status: Literal["development_only_not_a_validated_production_recommendation"] = (
        "development_only_not_a_validated_production_recommendation"
    )
    run_id: str
    provenance: OptimizerProvenance
    search_policy: SearchPolicy
    solver: SolverIdentity
    initial_squad: InitialSquadRecord
    plan: TransferPlanRecord
    assumptions: tuple[str, ...]

    @field_validator("run_id")
    @classmethod
    def _valid_run_id(cls, value: str) -> str:
        return _validate_sha256(value)

    @model_validator(mode="after")
    def _run_id_matches_provenance(self) -> Self:
        expected = derive_optimizer_run_id(self.provenance, self.search_policy, self.solver)
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
) -> str:
    """A deterministic, stable id for an optimizer run.

    Built from only the behaviour-defining provenance: the forecast content hash (which fully
    identifies the forecast inputs), the squad-rules content hash and contract version, the
    optimiser commit, the risk parameter, every search bound, and the solver name/options/seed. It
    reads no file path, no wall-clock time, and no environment-discovered solver *version*, so
    byte-identical behaviour-defining inputs yield the same id and any behaviour-defining change
    yields a different one.
    """
    identity = {
        "schema_version": OPTIMIZER_ARTIFACT_SCHEMA_VERSION,
        "forecast_sha256": provenance.forecast.sha256,
        "forecast_schema": provenance.forecast.forecast_schema,
        "forecast_schema_version": provenance.forecast.forecast_schema_version,
        "forecast_as_of": provenance.forecast.as_of.isoformat(),
        "forecast_commit_sha": provenance.forecast.commit_sha,
        "rules_sha256": provenance.squad_rules.sha256,
        "rules_contract_version": provenance.squad_rules.contract_version,
        "optimizer_commit_sha": provenance.optimizer_commit_sha,
        "risk_lambda": search_policy.risk_lambda,
        "candidate_pool_per_position": search_policy.candidate_pool_per_position,
        "transfer_depth": search_policy.transfer_depth,
        "transition_limit_per_state": search_policy.transition_limit_per_state,
        "beam_width": search_policy.beam_width,
        "free_transfer_per_gameweek": search_policy.free_transfer_per_gameweek,
        "free_transfer_bank_cap": search_policy.free_transfer_bank_cap,
        "hit_cost_points": search_policy.hit_cost_points,
        "maximum_transfers_per_gameweek": search_policy.maximum_transfers_per_gameweek,
        "solver_name": solver.name,
        "solver_options": list(solver.options),
        "solver_seed": solver.seed,
    }
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_optimizer_plan_artifact(
    *,
    provenance: OptimizerProvenance,
    search_policy: SearchPolicy,
    solver: SolverIdentity,
    initial_squad: InitialSquadRecord,
    plan: TransferPlanRecord,
    assumptions: tuple[str, ...],
) -> OptimizerPlanArtifact:
    """Assemble a validated artifact, deriving and embedding its ``run_id``."""
    run_id = derive_optimizer_run_id(provenance, search_policy, solver)
    return OptimizerPlanArtifact(
        run_id=run_id,
        provenance=provenance,
        search_policy=search_policy,
        solver=solver,
        initial_squad=initial_squad,
        plan=plan,
        assumptions=assumptions,
    )


def optimizer_artifact_bytes(artifact: OptimizerPlanArtifact) -> bytes:
    """Canonical UTF-8 JSON, suitable for bit-for-bit reproducibility checks.

    Keys are sorted and non-finite floats are rejected, so two artifacts with identical decision
    content and provenance serialise to identical bytes regardless of field construction order.
    """
    payload = artifact.model_dump(mode="json", by_alias=True)
    text = json.dumps(payload, sort_keys=True, indent=2, allow_nan=False)
    return (text + "\n").encode("utf-8")


def write_optimizer_artifact_atomic(path: Path, artifact: OptimizerPlanArtifact) -> str:
    """Atomically write ``path`` without clobbering, returning the SHA-256 of the bytes written.

    Immutable no-clobber: if ``path`` already exists the write is refused
    (:class:`OptimizerArtifactExistsError`). Otherwise the bytes are written to a unique sibling
    temporary file that is flushed and fsynced, then promoted with one atomic rename. A failure at
    any point removes the temporary file and leaves the destination untouched.
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
        if path.exists():  # re-check just before promotion narrows the no-clobber race window
            raise OptimizerArtifactExistsError(
                f"refusing to overwrite an existing immutable optimizer artifact at {path}"
            )
        os.replace(temporary, path)
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
