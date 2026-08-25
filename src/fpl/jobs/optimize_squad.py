"""Thin CLI for artifact-only Stage E squad and transfer optimisation.

Two outputs, both development-only:

* stdout -- the existing machine-readable plan report, printed on every successful run;
* ``--output PATH`` -- a durable, provenance-bearing :mod:`fpl.artifacts.optimizer_plan` artifact,
  written atomically and immutably (no-clobber). It pins the forecast it consumed (path + content
  hash + schema/version + as_of + horizon + forecast commit), the optimiser's own Git commit and
  clean-worktree state, the squad-rules file (path + contract version + hash), the solver identity
  and its deterministic options, the complete bounded-search policy, the chosen squad and every
  weekly XI/captain/vice/bench and transfer step, and a stable ``run_id`` derived only from the
  behaviour-defining provenance.

The job stays thin: all schema, serialisation, run-id derivation, and atomic-write logic lives in
the artifact module. This entry point discovers provenance, maps the optimiser's domain objects into
the typed records, and fails closed (a dirty worktree, an unresolvable commit, or an already-present
destination all refuse to write) so an artifact can never misrepresent how it was produced.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fpl.artifacts.optimizer_plan import (
    ForecastInputProvenance,
    InitialSquadRecord,
    ManagerPlanContext,
    OptimizerArtifactExistsError,
    OptimizerPlanArtifact,
    OptimizerProvenance,
    OwnedPlayerValueRecord,
    PlayerRef,
    PositionRuleRecord,
    SearchPolicy,
    SolverIdentity,
    SquadMemberRecord,
    SquadRulesProvenance,
    SquadRulesSnapshot,
    TransferPlanRecord,
    TransferWeekRecord,
    build_optimizer_plan_artifact,
    write_optimizer_artifact_atomic,
)
from fpl.artifacts.prospective_points import ProspectivePointsArtifact, read_artifact_bytes
from fpl.config import config_dir, repo_root
from fpl.ingest.manager_team import (
    ManagerTeamCapture,
    manager_capture_sha256,
    read_manager_capture_bytes,
)
from fpl.optimize.rules import POSITIONS, SquadRules, parse_squad_rules
from fpl.optimize.squad import (
    CBC_RANDOM_SEED,
    CBC_SOLVER_OPTIONS,
    ArtifactIndex,
    OptimizationError,
    SquadMember,
    SquadSolution,
    optimize_initial_squad,
    solution_for_existing_squad,
)
from fpl.optimize.transfers import (
    ManagerFinancialState,
    OwnedPlayerFinancials,
    TransferPlan,
    plan_transfers,
)

logger = logging.getLogger("fpl.jobs.optimize_squad")

# The explicit simplifying assumptions behind the plan, recorded verbatim in the artifact so a
# reader never has to infer them. These are the operational caveats the roadmap requires the GW1
# decision pack to surface.
OPTIMIZER_ASSUMPTIONS: tuple[str, ...] = (
    "bench points and autosub probabilities are excluded from the objective; the solver still "
    "emits one bench goalkeeper and a deterministic outfield bench order, and a player the "
    "availability overlay rules out (multiplier 0 in any planned gameweek) ranks behind every "
    "available filler in the bench tie-break, while equally-priced fillers prefer the "
    "most-selected players (deadline ownership; unmeasured ownership carries no preference)",
    "availability is a reported overlay already folded into availability-adjusted expected points; "
    "the deadline chance_of_playing_next_round overlay is valid for GW1 only, and reusing it "
    "across later gameweeks is an explicit scenario assumption, not a measured per-gameweek policy",
    "ownership (selected_by_percent) is reported but does not affect selection",
    "every gameweek uses the deadline-known now_cost as a frozen-price planning assumption; future "
    "price changes are not modelled",
    "FPL selling-value and purchase-price profit rules are not modelled",
    "vice-captain fallback and its expected value are not modelled",
    "the initial fixed-squad ILP is exact; the multi-gameweek transfer path is optimal only within "
    "the configured candidate-pool, transfer-depth, transition, and beam bounds and makes no "
    "global-optimality claim",
)

MANAGER_OPTIMIZER_ASSUMPTIONS: tuple[str, ...] = (
    "the imported squad is a provenance-bearing reconstruction from public manager endpoints and "
    "a committed deadline bootstrap; it is not authenticated my-team state, so the capture time "
    "and its public reconstruction scope remain part of the decision",
    "the capture's reconstructed purchase prices, selling prices, and cash bank govern first-"
    "deadline affordability; a manager squad may legitimately exceed the fresh 100.0 market-"
    "price budget",
    "each forecast gameweek freezes now_cost at the forecast deadline; future price changes are "
    "not modelled, and a player bought inside the scenario can later be sold for that frozen "
    "purchase/current price",
    "the capture's already-incurred transfer hits are sunk and reported separately; only new "
    "recommended transfers beyond the effective remaining free transfers reduce the prospective "
    "plan objective at four points each",
    "bench points and autosub probabilities are excluded from the objective; the solver still "
    "emits one bench goalkeeper and a deterministic outfield bench order",
    "availability is a reported overlay already folded into availability-adjusted expected "
    "points; the overlay is measured for the first forecast gameweek and reused across later "
    "gameweeks only as an explicit scenario assumption",
    "vice-captain fallback and its expected value are not modelled",
    "lineups are exact within each visited squad; the multi-gameweek transfer path is optimal "
    "only within the configured candidate-pool, transfer-depth, transition, and beam bounds and "
    "makes no global-optimality claim",
)


# Owner product rule (2026-08-17): a suggestion may pin at most five must-keep players;
# the optimizer assigns every remaining quota around them.
MAX_LOCKED_PLAYERS = 5
# Owner product rule (2026-08-18): a personal plan may exclude at most fifteen players.
MAX_EXCLUDED_PLAYERS = 15


def _assumptions(
    min_bench_appearance: float,
    locked_label: str | None = None,
    excluded_label: str | None = None,
    *,
    manager_mode: bool = False,
) -> tuple[str, ...]:
    """The recorded assumptions, plus the active policies' semantics."""
    extras: list[str] = []
    if min_bench_appearance > 0.0:
        extras.append(
            f"min_bench_appearance={min_bench_appearance}: every gated player benched in "
            "any planned gameweek must show an appearance lower bound of at least that "
            "fraction (1 - P(0 points) read from the stored distribution and scaled by the "
            "availability overlay, which understates true appearance probability); the bench "
            "goalkeeper is exempt because a backup keeper plays only on an unforecastable "
            "starter injury, and locked players are exempt because the owner's must-keep "
            "instruction outranks the rotation heuristic (owner rule, 2026-08-18)",
        )
    if locked_label:
        if manager_mode:
            extras.append(
                f"locked players: {locked_label} -- members of the imported squad who are never "
                "transferred out anywhere in the scenario"
            )
        else:
            extras.append(
                f"locked players: {locked_label} -- pinned into the squad and never transferred "
                "out; the optimizer assigns every remaining quota around them"
            )
    if excluded_label:
        if manager_mode:
            extras.append(
                f"excluded players: {excluded_label} -- an imported holding is forced out at the "
                "first actionable deadline; a non-owned player is never bought, and no excluded "
                "player can re-enter later"
            )
        else:
            extras.append(
                f"excluded players: {excluded_label} -- removed from the initial-squad population "
                "and from every future transfer candidate set"
            )
    base = MANAGER_OPTIMIZER_ASSUMPTIONS if manager_mode else OPTIMIZER_ASSUMPTIONS
    if not extras:
        return base
    return (*base, *extras)


@dataclass(frozen=True, slots=True)
class _InputSnapshot:
    """Exact bytes and Git identity used by one durable optimizer run."""

    commit_sha: str
    forecast_path: Path
    forecast_bytes: bytes
    forecast_sha256: str
    artifact: ProspectivePointsArtifact
    rules_path: Path
    rules_bytes: bytes
    rules_sha256: str
    rules: SquadRules
    manager_capture_path: Path | None = None
    manager_capture_bytes: bytes | None = None
    manager_capture_sha256: str | None = None
    manager_capture: ManagerTeamCapture | None = None


def _member_record(member: SquadMember) -> dict[str, Any]:
    return {
        "code": member.code,
        "web_name": member.web_name,
        "position": member.position,
        "team_id": member.team_id,
        "team_code": member.team_code,
        "now_cost": member.now_cost,
        "selected_by_percent": member.selected_by_percent,
    }


def _plan_record(plan: TransferPlan, names: dict[int, str | None]) -> dict[str, Any]:
    def player(code: int) -> dict[str, Any]:
        return {"code": code, "web_name": names[code]}

    return {
        "search_method": plan.search_method,
        "optimality_scope": plan.optimality_scope,
        "risk_lambda": plan.risk_lambda,
        "expected_points_before_hits": plan.expected_points_before_hits,
        "hit_points": plan.hit_points,
        "expected_points_after_hits": plan.expected_points_after_hits,
        "objective_value_after_hits": plan.objective_value_after_hits,
        "candidate_pool_size": len(plan.candidate_pool),
        "weeks": [
            {
                "gw": week.gw,
                "transfers_in": [player(code) for code in week.transfers_in],
                "transfers_out": [player(code) for code in week.transfers_out],
                "free_transfers_before": week.free_transfers_before,
                "free_transfers_after": week.free_transfers_after,
                "hit_points": week.hit_points,
                "starting_xi": [player(code) for code in week.lineup.starting_xi],
                "captain": player(week.lineup.captain),
                "vice_captain": player(week.lineup.vice_captain),
                "bench_goalkeeper": player(week.lineup.bench_goalkeeper),
                "bench_order": [player(code) for code in week.lineup.bench_order],
                "expected_points": week.lineup.expected_points,
                "objective_value": week.lineup.objective_value,
            }
            for week in plan.weeks
        ],
    }


def _git_head(repo: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _git_worktree_clean(repo: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        return not result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _bytes_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _verify_input_snapshot(snapshot: _InputSnapshot) -> None:
    """Fail if Git or either content-hashed input drifted after preflight."""
    repo = repo_root()
    if not _git_worktree_clean(repo):
        raise RuntimeError("optimizer worktree became dirty during the run")
    if _git_head(repo) != snapshot.commit_sha:
        raise RuntimeError("optimizer Git HEAD changed during the run")
    try:
        forecast_bytes = snapshot.forecast_path.read_bytes()
        rules_bytes = snapshot.rules_path.read_bytes()
        manager_bytes = (
            snapshot.manager_capture_path.read_bytes()
            if snapshot.manager_capture_path is not None
            else None
        )
    except OSError as exc:
        raise RuntimeError("a content-hashed optimizer input became unreadable") from exc
    if forecast_bytes != snapshot.forecast_bytes:
        raise RuntimeError("forecast artifact changed during the optimizer run")
    if rules_bytes != snapshot.rules_bytes:
        raise RuntimeError("squad-rules file changed during the optimizer run")
    if manager_bytes != snapshot.manager_capture_bytes:
        raise RuntimeError("manager-team capture changed during the optimizer run")


def _capture_input_snapshot(
    forecast_path: Path,
    rules_path: Path,
    manager_capture_path: Path | None = None,
) -> _InputSnapshot:
    """Read, hash, and parse each input once under a clean, stable Git identity."""
    repo = repo_root()
    if not _git_worktree_clean(repo):
        raise RuntimeError("refusing optimizer artifact output from a dirty Git worktree")
    commit = _git_head(repo)
    if commit is None:
        raise RuntimeError("cannot resolve the optimizer Git HEAD")
    forecast_bytes = forecast_path.read_bytes()
    rules_bytes = rules_path.read_bytes()
    manager_bytes = manager_capture_path.read_bytes() if manager_capture_path is not None else None
    manager_capture = (
        read_manager_capture_bytes(manager_bytes) if manager_bytes is not None else None
    )
    snapshot = _InputSnapshot(
        commit_sha=commit,
        forecast_path=forecast_path,
        forecast_bytes=forecast_bytes,
        forecast_sha256=_bytes_sha256(forecast_bytes),
        artifact=read_artifact_bytes(forecast_bytes),
        rules_path=rules_path,
        rules_bytes=rules_bytes,
        rules_sha256=_bytes_sha256(rules_bytes),
        rules=parse_squad_rules(rules_bytes),
        manager_capture_path=manager_capture_path,
        manager_capture_bytes=manager_bytes,
        manager_capture_sha256=(
            _bytes_sha256(manager_bytes) if manager_bytes is not None else None
        ),
        manager_capture=manager_capture,
    )
    _verify_input_snapshot(snapshot)
    return snapshot


def _pulp_package_version() -> str | None:
    """Return the imported PuLP package version without accepting an ambiguous identity."""
    try:
        metadata_version = importlib.metadata.version("pulp").strip()
    except importlib.metadata.PackageNotFoundError:
        metadata_version = ""
    try:
        import pulp
    except ImportError:
        return None
    module_version = str(getattr(pulp, "__version__", "")).strip()
    if metadata_version and module_version and metadata_version != module_version:
        return None
    return metadata_version or module_version or None


def _cbc_binary_version() -> str | None:
    """Return the CBC binary version required by durable-output provenance and ``run_id``."""
    try:
        import pulp

        path = getattr(pulp.PULP_CBC_CMD(msg=False), "path", None)
        if not path:
            return None
        # CBC accepts both spellings across distributions. A second probe also makes discovery
        # robust to a transient first-process launch failure on Windows (for example first-use
        # endpoint scanning) without ever inventing or defaulting a version.
        for version_flag in ("--version", "-version"):
            try:
                result = subprocess.run(
                    [str(path), version_flag],
                    capture_output=True,
                    text=True,
                    stdin=subprocess.DEVNULL,
                    timeout=10,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            text = f"{result.stdout}\n{result.stderr}"
            for line in text.splitlines():
                label, separator, value = line.partition(":")
                if separator and label.strip().casefold() == "version" and value.strip():
                    return value.strip()
        return None
    except ImportError:
        return None


def _solver_versions() -> tuple[str, str] | None:
    """Discover the complete runtime identity, or fail closed with no partial identity."""
    package_version = _pulp_package_version()
    binary_version = _cbc_binary_version()
    if not package_version or not binary_version:
        return None
    return package_version, binary_version


def _solve(
    artifact: ProspectivePointsArtifact,
    rules: SquadRules,
    risk_lambda: float,
    min_bench_appearance: float = 0.0,
    locked_codes: tuple[int, ...] = (),
    excluded_codes: tuple[int, ...] = (),
    *,
    manager_capture: ManagerTeamCapture | None = None,
    free_transfers_override: int | None = None,
) -> tuple[SquadSolution, ArtifactIndex, TransferPlan, dict[int, str | None]]:
    """Run the exact fixed-squad ILP and the bounded transfer plan once for a given input."""
    if manager_capture is not None:
        _validate_manager_registry_binding(artifact, manager_capture)
        _validate_manager_owned_exclusions(
            manager_capture,
            excluded_codes=excluded_codes,
            rules=rules,
        )
    index = ArtifactIndex.build(artifact, rules)
    if manager_capture is None:
        if free_transfers_override is not None:
            raise ValueError("free_transfers_override requires a manager capture")
        initial = optimize_initial_squad(
            artifact,
            rules,
            risk_lambda=risk_lambda,
            min_bench_appearance=min_bench_appearance,
            locked_codes=locked_codes,
            excluded_codes=excluded_codes,
        )
        plan = plan_transfers(
            index,
            rules,
            initial,
            risk_lambda=risk_lambda,
            min_bench_appearance=min_bench_appearance,
            locked_codes=locked_codes,
            excluded_codes=excluded_codes,
        )
    else:
        if manager_capture.season != artifact.manifest.season:
            raise ValueError(
                f"manager capture season {manager_capture.season} does not match forecast "
                f"season {artifact.manifest.season}"
            )
        if manager_capture.planning_event != artifact.manifest.gw_from:
            raise ValueError(
                f"manager capture plans GW{manager_capture.planning_event}, but forecast starts "
                f"at GW{artifact.manifest.gw_from}"
            )
        effective_free = (
            manager_capture.free_transfers_available
            if free_transfers_override is None
            else free_transfers_override
        )
        if not 0 <= effective_free <= rules.transfers.free_transfer_bank_cap:
            raise ValueError(
                "effective free transfers must be within the configured free-transfer bank cap"
            )
        imported_codes = tuple(player.code for player in manager_capture.squad)
        missing_locks = sorted(set(locked_codes) - set(imported_codes))
        if missing_locks:
            raise OptimizationError(
                f"manager locks must be players in the imported squad: {missing_locks}"
            )
        initial = solution_for_existing_squad(
            artifact,
            rules,
            imported_codes,
            risk_lambda=risk_lambda,
            min_bench_appearance=min_bench_appearance,
            locked_codes=locked_codes,
            excluded_codes=excluded_codes,
        )
        financial_state = ManagerFinancialState(
            bank_tenths=manager_capture.bank_tenths,
            free_transfers_available=effective_free,
            owned_players=tuple(
                OwnedPlayerFinancials(
                    code=player.code,
                    purchase_price_tenths=player.purchase_price,
                    selling_price_tenths=player.selling_price,
                )
                for player in manager_capture.squad
            ),
        )
        plan = plan_transfers(
            index,
            rules,
            initial,
            risk_lambda=risk_lambda,
            min_bench_appearance=min_bench_appearance,
            locked_codes=locked_codes,
            excluded_codes=excluded_codes,
            manager_financial_state=financial_state,
        )
    names = {code: row.web_name for code, row in index.first_by_code.items()}
    return initial, index, plan, names


def _validate_manager_registry_binding(
    artifact: ProspectivePointsArtifact,
    capture: ManagerTeamCapture,
) -> None:
    forecast_sha = artifact.manifest.live_inputs.selectable_player_registry_sha256
    if forecast_sha is None:
        raise OptimizationError(
            "manager optimization requires a forecast with a selectable-player registry "
            "binding; regenerate the prospective forecast"
        )
    if forecast_sha != capture.provenance.selectable_player_registry_sha256:
        raise OptimizationError(
            "manager capture and forecast selectable-player registries disagree; recapture the "
            "manager team and regenerate the forecast from the same player registry"
        )


def _validate_manager_owned_exclusions(
    capture: ManagerTeamCapture,
    *,
    excluded_codes: tuple[int, ...],
    rules: SquadRules,
) -> None:
    owned = {player.code for player in capture.squad}
    forced_out = tuple(sorted(owned.intersection(excluded_codes)))
    maximum = rules.search.maximum_planned_transfers_per_gameweek
    if len(forced_out) > maximum:
        raise OptimizationError(
            f"manager exclusions force {len(forced_out)} first-week transfers "
            f"({list(forced_out)}), but the bounded first-week transfer depth is {maximum}"
        )


def _manager_plan_context(
    capture: ManagerTeamCapture,
    *,
    free_transfers_override: int | None,
) -> ManagerPlanContext:
    effective_free = (
        capture.free_transfers_available
        if free_transfers_override is None
        else free_transfers_override
    )
    return ManagerPlanContext(
        capture_id=capture.capture_id,
        capture_sha256=manager_capture_sha256(capture),
        selectable_player_registry_sha256=(capture.provenance.selectable_player_registry_sha256),
        captured_at=capture.captured_at,
        manager_id=capture.manager_id,
        picks_event=capture.picks_event,
        planning_gw=capture.planning_event,
        bank_tenths=capture.bank_tenths,
        initial_free_transfers=effective_free,
        free_transfers_source=capture.free_transfers_source,
        free_transfers_override=free_transfers_override,
        existing_hit_points=capture.existing_hit_points,
        owned_players=tuple(
            OwnedPlayerValueRecord(
                code=player.code,
                purchase_price_tenths=player.purchase_price,
                selling_price_tenths=player.selling_price,
            )
            for player in capture.squad
        ),
    )


def build_forecast_provenance(
    artifact: ProspectivePointsArtifact, forecast_path: str, forecast_sha256: str
) -> ForecastInputProvenance:
    manifest = artifact.manifest
    return ForecastInputProvenance(
        path=forecast_path,
        sha256=forecast_sha256,
        forecast_schema=manifest.artifact_schema,
        forecast_schema_version=manifest.schema_version,
        as_of=manifest.as_of,
        season=manifest.season,
        gw_from=manifest.gw_from,
        gw_to=manifest.gw_to,
        commit_sha=manifest.commit_sha,
        selectable_player_registry_sha256=(manifest.live_inputs.selectable_player_registry_sha256),
    )


def _rules_snapshot(rules: SquadRules) -> SquadRulesSnapshot:
    return SquadRulesSnapshot(
        contract_version=rules.contract_version,
        season=rules.season,
        squad_size=rules.squad.size,
        budget_tenths=rules.squad.budget_tenths,
        maximum_per_club=rules.squad.maximum_per_club,
        positions=tuple(
            PositionRuleRecord(
                position=position,
                squad=rules.squad.positions[position].squad,
                minimum_starters=rules.squad.positions[position].minimum_starters,
                maximum_starters=rules.squad.positions[position].maximum_starters,
            )
            for position in POSITIONS
        ),
        lineup_starters=rules.lineup.starters,
        captain_multiplier=rules.lineup.captain_multiplier,
        vice_captain_enabled=rules.lineup.vice_captain_enabled,
        goalkeeper_bench_slots=rules.lineup.goalkeeper_bench_slots,
        outfield_bench_slots=rules.lineup.outfield_bench_slots,
    )


def _search_policy(
    rules: SquadRules,
    plan: TransferPlan,
    risk_lambda: float,
    min_bench_appearance: float = 0.0,
    locked_codes: tuple[int, ...] = (),
    excluded_codes: tuple[int, ...] = (),
    plan_origin: Literal["platform", "user_custom"] = "platform",
    manager_context: ManagerPlanContext | None = None,
) -> SearchPolicy:
    return SearchPolicy(
        candidate_pool_per_position=rules.search.candidate_pool_per_position,
        transfer_depth=rules.search.maximum_planned_transfers_per_gameweek,
        transition_limit_per_state=rules.search.transition_limit_per_state,
        beam_width=rules.search.beam_width,
        free_transfer_per_gameweek=rules.transfers.free_per_gameweek_after_first_deadline,
        free_transfer_bank_cap=rules.transfers.free_transfer_bank_cap,
        hit_cost_points=rules.transfers.hit_cost_points,
        maximum_transfers_per_gameweek=rules.transfers.maximum_transfers_per_gameweek,
        risk_lambda=risk_lambda,
        min_bench_appearance=min_bench_appearance,
        locked_codes=tuple(sorted(set(locked_codes))),
        excluded_codes=tuple(sorted(set(excluded_codes))),
        plan_mode="manager" if manager_context is not None else "scratch",
        initial_free_transfers=(
            manager_context.initial_free_transfers if manager_context is not None else 0
        ),
        plan_origin=plan_origin,
        search_method=plan.search_method,
        optimality_scope=plan.optimality_scope,
    )


def _initial_squad_record(initial: SquadSolution) -> InitialSquadRecord:
    return InitialSquadRecord(
        cost_tenths=initial.squad_cost_tenths,
        solver_status=initial.solver_status,
        members=tuple(
            SquadMemberRecord(
                code=member.code,
                web_name=member.web_name,
                position=member.position,
                team_id=member.team_id,
                team_code=member.team_code,
                now_cost=member.now_cost,
                selected_by_percent=member.selected_by_percent,
            )
            for member in sorted(initial.members, key=lambda member: member.code)
        ),
    )


def _plan_record_model(
    plan: TransferPlan,
    names: dict[int, str | None],
    index: ArtifactIndex,
) -> TransferPlanRecord:
    def ref(code: int) -> PlayerRef:
        return PlayerRef(code=code, web_name=names.get(code))

    def refs(codes: tuple[int, ...]) -> tuple[PlayerRef, ...]:
        return tuple(ref(code) for code in codes)

    def member(code: int) -> SquadMemberRecord:
        row = index.first_by_code[code]
        if row.now_cost is None:
            raise ValueError(f"planned squad member {code} has no deadline-known price")
        return SquadMemberRecord(
            code=code,
            web_name=row.web_name,
            position=row.position,
            team_id=row.team_id,
            team_code=row.team_code,
            now_cost=row.now_cost,
            selected_by_percent=row.selected_by_percent,
        )

    return TransferPlanRecord(
        expected_points_before_hits=plan.expected_points_before_hits,
        hit_points=plan.hit_points,
        expected_points_after_hits=plan.expected_points_after_hits,
        objective_value_after_hits=plan.objective_value_after_hits,
        candidate_pool_size=len(plan.candidate_pool),
        weeks=tuple(
            TransferWeekRecord(
                gw=week.gw,
                transfers_in=refs(week.transfers_in),
                transfers_out=refs(week.transfers_out),
                free_transfers_before=week.free_transfers_before,
                free_transfers_after=week.free_transfers_after,
                hit_points=week.hit_points,
                bank_before_tenths=week.bank_before_tenths,
                bank_after_tenths=week.bank_after_tenths,
                squad_cost_tenths=sum(member(code).now_cost for code in week.squad),
                squad_after_transfers=tuple(member(code) for code in week.squad),
                starting_xi=refs(week.lineup.starting_xi),
                captain=ref(week.lineup.captain),
                vice_captain=ref(week.lineup.vice_captain),
                bench_goalkeeper=ref(week.lineup.bench_goalkeeper),
                bench_order=refs(week.lineup.bench_order),
                expected_points=week.lineup.expected_points,
                objective_value=week.lineup.objective_value,
            )
            for week in plan.weeks
        ),
    )


def assemble_optimizer_artifact(
    *,
    initial: SquadSolution,
    plan: TransferPlan,
    names: dict[int, str | None],
    index: ArtifactIndex,
    provenance: OptimizerProvenance,
    rules: SquadRules,
    risk_lambda: float,
    solver_package_version: str,
    solver_binary_version: str,
    min_bench_appearance: float = 0.0,
    locked_codes: tuple[int, ...] = (),
    excluded_codes: tuple[int, ...] = (),
    plan_origin: Literal["platform", "user_custom"] = "platform",
    manager_context: ManagerPlanContext | None = None,
) -> OptimizerPlanArtifact:
    """Map a solved squad/plan plus injected provenance into a validated optimizer artifact.

    This does no solving of its own and touches neither Git nor the filesystem, so it is a pure
    deterministic function of its inputs -- two calls with equal inputs return equal artifacts and
    an identical ``run_id``.
    """
    solver = SolverIdentity(
        name="PULP_CBC_CMD",
        package="pulp",
        package_version=solver_package_version,
        binary_version=solver_binary_version,
        options=CBC_SOLVER_OPTIONS,
        seed=CBC_RANDOM_SEED,
        status=initial.solver_status,
    )
    locked_label = ", ".join(
        f"{names.get(code) or code} ({code})" for code in sorted(set(locked_codes))
    )
    excluded_label = ", ".join(
        f"{names.get(code) or code} ({code})" for code in sorted(set(excluded_codes))
    )
    return build_optimizer_plan_artifact(
        provenance=provenance,
        search_policy=_search_policy(
            rules,
            plan,
            risk_lambda,
            min_bench_appearance,
            locked_codes,
            excluded_codes,
            plan_origin,
            manager_context,
        ),
        solver=solver,
        rules=_rules_snapshot(rules),
        initial_squad=_initial_squad_record(initial),
        plan=_plan_record_model(plan, names, index),
        assumptions=_assumptions(
            min_bench_appearance,
            locked_label or None,
            excluded_label or None,
            manager_mode=manager_context is not None,
        ),
        manager_context=manager_context,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select a DEVELOPMENT-ONLY FPL squad from a prospective JSONL artifact."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--rules", type=Path, default=None)
    parser.add_argument("--risk-lambda", type=float, default=0.0)
    parser.add_argument(
        "--min-bench-appearance",
        type=float,
        default=0.0,
        help=(
            "require every outfield player benched in any planned gameweek to show an appearance "
            "lower bound (1 - P(0 points), scaled by the availability overlay) of at least this "
            "fraction, so bench slots are live rotation options; 0.0 disables the gate (default); "
            "the bench goalkeeper is always exempt"
        ),
    )
    parser.add_argument(
        "--lock",
        type=int,
        action="append",
        default=[],
        metavar="CODE",
        help=(
            "pin this player (stable code) into the squad; the optimizer assigns every "
            "remaining quota around the must-keep players and never transfers them out; "
            f"repeatable, at most {MAX_LOCKED_PLAYERS} locks"
        ),
    )
    parser.add_argument(
        "--exclude",
        type=int,
        action="append",
        default=[],
        metavar="CODE",
        help=(
            "exclude this player (stable code) from the initial squad and every future "
            f"transfer candidate set; repeatable, at most {MAX_EXCLUDED_PLAYERS} exclusions"
        ),
    )
    parser.add_argument(
        "--plan-origin",
        choices=("platform", "user_custom"),
        default="platform",
        help="record whether this is a platform suggestion or an interactive user plan",
    )
    parser.add_argument(
        "--manager-capture",
        type=Path,
        default=None,
        help=(
            "start from this immutable public manager-team capture instead of selecting a fresh "
            "15; enables first-forecast-GW transfers and selling-value/cash accounting"
        ),
    )
    parser.add_argument(
        "--free-transfers-override",
        type=int,
        default=None,
        metavar="N",
        help=(
            "override the manager capture's reconstructed remaining free transfers (0-5); the "
            "override is retained in artifact provenance"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="atomically write the immutable, provenance-bearing optimizer artifact to this path",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    rules_path = args.rules if args.rules is not None else config_dir() / "squad_2026_27.yaml"
    if args.free_transfers_override is not None and args.manager_capture is None:
        logger.error("--free-transfers-override requires --manager-capture")
        return 1
    if args.manager_capture is not None and args.plan_origin != "user_custom":
        logger.error("manager-capture runs must use --plan-origin user_custom")
        return 1
    snapshot: _InputSnapshot | None = None
    solver_package_version: str | None = None
    solver_binary_version: str | None = None
    if args.output is not None:
        if args.output.exists():
            logger.error(
                "refusing to overwrite an existing immutable optimizer artifact at %s",
                args.output,
            )
            return 1
        try:
            snapshot = _capture_input_snapshot(args.artifact, rules_path, args.manager_capture)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("%s", exc)
            return 1
        artifact = snapshot.artifact
        rules = snapshot.rules
        forecast_sha256 = snapshot.forecast_sha256
        manager_capture = snapshot.manager_capture
        solver_versions = _solver_versions()
        if solver_versions is None:
            logger.error(
                "cannot resolve complete PuLP/CBC solver versions in %s; refusing artifact "
                "output (install the locked environment and launch with "
                ".venv\\Scripts\\python.exe)",
                sys.executable,
            )
            return 1
        solver_package_version, solver_binary_version = solver_versions
    else:
        forecast_bytes = args.artifact.read_bytes()
        artifact = read_artifact_bytes(forecast_bytes)
        rules = parse_squad_rules(rules_path.read_bytes())
        forecast_sha256 = _bytes_sha256(forecast_bytes)
        manager_capture = (
            read_manager_capture_bytes(args.manager_capture.read_bytes())
            if args.manager_capture is not None
            else None
        )

    locked_codes = tuple(sorted(set(args.lock)))
    excluded_codes = tuple(sorted(set(args.exclude)))
    if len(locked_codes) > MAX_LOCKED_PLAYERS:
        logger.error(
            "at most %d players may be locked (got %d)", MAX_LOCKED_PLAYERS, len(locked_codes)
        )
        return 1
    if len(excluded_codes) > MAX_EXCLUDED_PLAYERS:
        logger.error(
            "at most %d players may be excluded (got %d)",
            MAX_EXCLUDED_PLAYERS,
            len(excluded_codes),
        )
        return 1
    overlap = sorted(set(locked_codes).intersection(excluded_codes))
    if overlap:
        logger.error("players cannot be both locked and excluded: %s", overlap)
        return 1
    selectable_codes = {row.code for row in artifact.rows if row.now_cost is not None}
    unknown_locks = [code for code in locked_codes if code not in selectable_codes]
    if unknown_locks:
        logger.error("locked codes are not selectable players in the artifact: %s", unknown_locks)
        return 1
    unknown_exclusions = [code for code in excluded_codes if code not in selectable_codes]
    if unknown_exclusions:
        logger.error(
            "excluded codes are not selectable players in the artifact: %s", unknown_exclusions
        )
        return 1

    try:
        initial, index, plan, names = _solve(
            artifact,
            rules,
            args.risk_lambda,
            args.min_bench_appearance,
            locked_codes,
            excluded_codes,
            manager_capture=manager_capture,
            free_transfers_override=args.free_transfers_override,
        )
    except (OptimizationError, RuntimeError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    locked_label = ", ".join(f"{names.get(code) or code} ({code})" for code in locked_codes)
    excluded_label = ", ".join(f"{names.get(code) or code} ({code})" for code in excluded_codes)
    report = {
        "status": "development_only_not_a_validated_production_recommendation",
        "artifact": {
            "path": str(args.artifact),
            "sha256": forecast_sha256,
            "schema": artifact.manifest.artifact_schema,
            "schema_version": artifact.manifest.schema_version,
            "as_of": artifact.manifest.as_of.isoformat(),
            "season": artifact.manifest.season,
            "gw_from": artifact.manifest.gw_from,
            "gw_to": artifact.manifest.gw_to,
            "forecast_commit_sha": artifact.manifest.commit_sha,
        },
        "rules": {
            "contract_version": rules.contract_version,
            "source_snapshot": rules.provenance.bootstrap_snapshot,
            "source_payload_sha256": rules.provenance.bootstrap_payload_sha256,
        },
        "locked_codes": list(locked_codes),
        "excluded_codes": list(excluded_codes),
        "plan_origin": args.plan_origin,
        "manager": (
            {
                "capture_id": manager_capture.capture_id,
                "capture_sha256": manager_capture_sha256(manager_capture),
                "manager_id": manager_capture.manager_id,
                "picks_event": manager_capture.picks_event,
                "planning_gw": manager_capture.planning_event,
                "bank_tenths": manager_capture.bank_tenths,
                "free_transfers_available": (
                    manager_capture.free_transfers_available
                    if args.free_transfers_override is None
                    else args.free_transfers_override
                ),
                "free_transfers_source": manager_capture.free_transfers_source,
                "free_transfers_override": args.free_transfers_override,
                "existing_hit_points": manager_capture.existing_hit_points,
            }
            if manager_capture is not None
            else None
        ),
        "initial_squad": {
            "cost_tenths": initial.squad_cost_tenths,
            "solver_status": initial.solver_status,
            "members": [_member_record(member) for member in initial.members],
        },
        "plan": _plan_record(plan, names),
        "assumptions": list(
            _assumptions(
                args.min_bench_appearance,
                locked_label or None,
                excluded_label or None,
                manager_mode=manager_capture is not None,
            )
        ),
    }

    if args.output is not None:
        if snapshot is None or solver_package_version is None or solver_binary_version is None:
            raise RuntimeError("durable optimizer output lost its preflight state")
        result = _write_artifact(
            output=args.output,
            snapshot=snapshot,
            initial=initial,
            index=index,
            plan=plan,
            names=names,
            risk_lambda=args.risk_lambda,
            min_bench_appearance=args.min_bench_appearance,
            locked_codes=locked_codes,
            excluded_codes=excluded_codes,
            plan_origin=args.plan_origin,
            manager_capture=manager_capture,
            free_transfers_override=args.free_transfers_override,
            solver_package_version=solver_package_version,
            solver_binary_version=solver_binary_version,
        )
        if result != 0:
            return result
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


def _write_artifact(
    *,
    output: Path,
    snapshot: _InputSnapshot,
    initial: SquadSolution,
    index: ArtifactIndex,
    plan: TransferPlan,
    names: dict[int, str | None],
    risk_lambda: float,
    min_bench_appearance: float = 0.0,
    locked_codes: tuple[int, ...] = (),
    excluded_codes: tuple[int, ...] = (),
    plan_origin: Literal["platform", "user_custom"] = "platform",
    manager_capture: ManagerTeamCapture | None = None,
    free_transfers_override: int | None = None,
    solver_package_version: str,
    solver_binary_version: str,
) -> int:
    """Gather provenance and write the immutable optimizer artifact, failing closed on any gap."""
    try:
        provenance = OptimizerProvenance(
            optimizer_commit_sha=snapshot.commit_sha,
            forecast=build_forecast_provenance(
                snapshot.artifact,
                str(snapshot.forecast_path),
                snapshot.forecast_sha256,
            ),
            squad_rules=SquadRulesProvenance(
                path=str(snapshot.rules_path),
                contract_version=snapshot.rules.contract_version,
                sha256=snapshot.rules_sha256,
            ),
        )
        plan_artifact = assemble_optimizer_artifact(
            initial=initial,
            plan=plan,
            names=names,
            index=index,
            provenance=provenance,
            rules=snapshot.rules,
            risk_lambda=risk_lambda,
            min_bench_appearance=min_bench_appearance,
            locked_codes=locked_codes,
            excluded_codes=excluded_codes,
            plan_origin=plan_origin,
            manager_context=(
                _manager_plan_context(
                    manager_capture,
                    free_transfers_override=free_transfers_override,
                )
                if manager_capture is not None
                else None
            ),
            solver_package_version=solver_package_version,
            solver_binary_version=solver_binary_version,
        )
        _verify_input_snapshot(snapshot)
        digest = write_optimizer_artifact_atomic(
            output,
            plan_artifact,
            pre_publish=lambda: _verify_input_snapshot(snapshot),
        )
        try:
            _verify_input_snapshot(snapshot)
        except RuntimeError:
            if output.exists() and _file_sha256(output) == digest:
                output.unlink()
            raise
    except (OSError, OptimizerArtifactExistsError, RuntimeError, ValueError) as exc:
        logger.error(str(exc))
        return 1
    logger.info(
        "wrote optimizer plan run_id=%s to %s (sha256=%s)",
        plan_artifact.run_id,
        output,
        digest,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
