"""Thin CLI for artifact-only Stage E squad and transfer optimisation.

Two outputs, both development-only:

* stdout -- the existing machine-readable plan report, printed on every run;
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
from pathlib import Path
from typing import Any

from fpl.artifacts.optimizer_plan import (
    ForecastInputProvenance,
    InitialSquadRecord,
    OptimizerArtifactExistsError,
    OptimizerPlanArtifact,
    OptimizerProvenance,
    PlayerRef,
    SearchPolicy,
    SolverIdentity,
    SquadMemberRecord,
    SquadRulesProvenance,
    TransferPlanRecord,
    TransferWeekRecord,
    build_optimizer_plan_artifact,
    write_optimizer_artifact_atomic,
)
from fpl.artifacts.prospective_points import ProspectivePointsArtifact, read_artifact
from fpl.config import config_dir, repo_root
from fpl.optimize.rules import SquadRules, load_squad_rules
from fpl.optimize.squad import (
    CBC_RANDOM_SEED,
    CBC_SOLVER_OPTIONS,
    ArtifactIndex,
    SquadMember,
    SquadSolution,
    optimize_initial_squad,
)
from fpl.optimize.transfers import TransferPlan, plan_transfers

logger = logging.getLogger("fpl.jobs.optimize_squad")

# The explicit simplifying assumptions behind the plan, recorded verbatim in the artifact so a
# reader never has to infer them. These are the operational caveats the roadmap requires the GW1
# decision pack to surface.
OPTIMIZER_ASSUMPTIONS: tuple[str, ...] = (
    "bench points and autosub probabilities are excluded from the objective; the solver still "
    "emits one bench goalkeeper and a deterministic outfield bench order",
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


def _pulp_package_version() -> str | None:
    try:
        return importlib.metadata.version("pulp")
    except importlib.metadata.PackageNotFoundError:
        return None


def _cbc_binary_version() -> str | None:
    """Best-effort CBC version string. Recorded for audit only; never part of the ``run_id``."""
    try:
        import pulp

        path = getattr(pulp.PULP_CBC_CMD(msg=False), "path", None)
        if not path:
            return None
        result = subprocess.run(
            [str(path), "--version"], capture_output=True, text=True, timeout=10, check=False
        )
        text = f"{result.stdout}\n{result.stderr}"
        for line in text.splitlines():
            if "Version" in line:
                return line.split(":", 1)[-1].strip() if ":" in line else line.strip()
        return None
    except (OSError, subprocess.SubprocessError):
        return None


def _solve(
    artifact: ProspectivePointsArtifact, rules: SquadRules, risk_lambda: float
) -> tuple[SquadSolution, ArtifactIndex, TransferPlan, dict[int, str | None]]:
    """Run the exact fixed-squad ILP and the bounded transfer plan once for a given input."""
    initial = optimize_initial_squad(artifact, rules, risk_lambda=risk_lambda)
    index = ArtifactIndex.build(artifact, rules)
    plan = plan_transfers(index, rules, initial, risk_lambda=risk_lambda)
    names = {code: row.web_name for code, row in index.first_by_code.items()}
    return initial, index, plan, names


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
        gw_from=manifest.gw_from,
        gw_to=manifest.gw_to,
        commit_sha=manifest.commit_sha,
    )


def _search_policy(rules: SquadRules, plan: TransferPlan, risk_lambda: float) -> SearchPolicy:
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


def _plan_record_model(plan: TransferPlan, names: dict[int, str | None]) -> TransferPlanRecord:
    def ref(code: int) -> PlayerRef:
        return PlayerRef(code=code, web_name=names.get(code))

    def refs(codes: tuple[int, ...]) -> tuple[PlayerRef, ...]:
        return tuple(ref(code) for code in codes)

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
    provenance: OptimizerProvenance,
    rules: SquadRules,
    risk_lambda: float,
    solver_package_version: str | None,
    solver_binary_version: str | None,
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
    return build_optimizer_plan_artifact(
        provenance=provenance,
        search_policy=_search_policy(rules, plan, risk_lambda),
        solver=solver,
        initial_squad=_initial_squad_record(initial),
        plan=_plan_record_model(plan, names),
        assumptions=OPTIMIZER_ASSUMPTIONS,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select a DEVELOPMENT-ONLY FPL squad from a prospective JSONL artifact."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--rules", type=Path, default=None)
    parser.add_argument("--risk-lambda", type=float, default=0.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="atomically write the immutable, provenance-bearing optimizer artifact to this path",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    artifact = read_artifact(args.artifact)
    rules_path = args.rules if args.rules is not None else config_dir() / "squad_2026_27.yaml"
    rules = load_squad_rules(args.rules)
    initial, _index, plan, names = _solve(artifact, rules, args.risk_lambda)
    report = {
        "status": "development_only_not_a_validated_production_recommendation",
        "artifact": {
            "path": str(args.artifact),
            "sha256": hashlib.sha256(args.artifact.read_bytes()).hexdigest(),
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
        "initial_squad": {
            "cost_tenths": initial.squad_cost_tenths,
            "solver_status": initial.solver_status,
            "members": [_member_record(member) for member in initial.members],
        },
        "plan": _plan_record(plan, names),
        "assumptions": [
            initial.bench_policy,
            "availability-adjusted expected points are used in lineup and transfer utility",
            "vice-captain fallback and autosub event probabilities are not modelled",
            "ownership is reported but does not affect the objective",
        ],
    }
    print(json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False))

    if args.output is not None:
        return _write_artifact(args, artifact, rules, rules_path, initial, plan, names)
    return 0


def _write_artifact(
    args: argparse.Namespace,
    artifact: ProspectivePointsArtifact,
    rules: SquadRules,
    rules_path: Path,
    initial: SquadSolution,
    plan: TransferPlan,
    names: dict[int, str | None],
) -> int:
    """Gather provenance and write the immutable optimizer artifact, failing closed on any gap."""
    repo = repo_root()
    if not _git_worktree_clean(repo):
        logger.error("refusing optimizer artifact output from a dirty Git worktree")
        return 1
    commit = _git_head(repo)
    if commit is None:
        logger.error("cannot resolve the optimizer Git HEAD; refusing artifact output")
        return 1

    provenance = OptimizerProvenance(
        optimizer_commit_sha=commit,
        forecast=build_forecast_provenance(
            artifact, str(args.artifact), _file_sha256(args.artifact)
        ),
        squad_rules=SquadRulesProvenance(
            path=str(rules_path),
            contract_version=rules.contract_version,
            sha256=_file_sha256(rules_path),
        ),
    )
    plan_artifact = assemble_optimizer_artifact(
        initial=initial,
        plan=plan,
        names=names,
        provenance=provenance,
        rules=rules,
        risk_lambda=args.risk_lambda,
        solver_package_version=_pulp_package_version(),
        solver_binary_version=_cbc_binary_version(),
    )
    try:
        digest = write_optimizer_artifact_atomic(args.output, plan_artifact)
    except OptimizerArtifactExistsError as exc:
        logger.error(str(exc))
        return 1
    logger.info(
        "wrote optimizer plan run_id=%s to %s (sha256=%s)",
        plan_artifact.run_id,
        args.output,
        digest,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
