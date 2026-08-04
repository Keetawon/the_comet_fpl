"""Thin CLI for artifact-only Stage E squad and transfer optimisation."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from fpl.artifacts.prospective_points import read_artifact
from fpl.optimize.rules import load_squad_rules
from fpl.optimize.squad import ArtifactIndex, SquadMember, optimize_initial_squad
from fpl.optimize.transfers import TransferPlan, plan_transfers


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Select a DEVELOPMENT-ONLY FPL squad from a prospective JSONL artifact."
    )
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--rules", type=Path, default=None)
    parser.add_argument("--risk-lambda", type=float, default=0.0)
    args = parser.parse_args(argv)

    artifact = read_artifact(args.artifact)
    rules = load_squad_rules(args.rules)
    initial = optimize_initial_squad(artifact, rules, risk_lambda=args.risk_lambda)
    index = ArtifactIndex.build(artifact, rules)
    plan = plan_transfers(index, rules, initial, risk_lambda=args.risk_lambda)
    names = {code: row.web_name for code, row in index.first_by_code.items()}
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
