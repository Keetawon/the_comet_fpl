// Optimizer audit: the provenance behind each optimizer decision -- Git heads, forecast and
// squad-rule inputs, solver identity/status/seed, the bounded-search policy, the verified
// squad-rule constraints, and the explicit assumptions. The squad/XI/transfer detail lives on
// the Next GW page; here we summarise the transfer path with its hits.

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { loadNextGw, loadOptimizerAudit } from "@/data/load";
import type { AuditPlan, NextGwPlan } from "@/data/types";
import { defaultPlan, planLabel } from "@/lib/nextGw";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; audit: AuditPlan[]; nextGw: NextGwPlan[] };

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border p-3">
      <p className="mb-2 text-xs font-medium text-muted-foreground">{title}</p>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b py-1 text-sm last:border-b-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-right tabular-nums break-all">{value}</span>
    </div>
  );
}

export function OptimizerAuditPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [planId, setPlanId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadOptimizerAudit(), loadNextGw()])
      .then(([audit, nextGw]) => {
        if (cancelled) return;
        setState({ status: "ready", audit: audit.plans, nextGw: nextGw.plans });
        setPlanId(defaultPlan(audit.plans)?.optimizer_run_id ?? null);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const plan = useMemo(
    () =>
      state.status === "ready"
        ? (state.audit.find((p) => p.optimizer_run_id === planId) ?? null)
        : null,
    [state, planId],
  );
  const nextGwPlan = useMemo(
    () =>
      state.status === "ready"
        ? (state.nextGw.find((p) => p.optimizer_run_id === planId) ?? null)
        : null,
    [state, planId],
  );

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Optimizer audit</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!state.audit.length) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Optimizer audit</h1>
        <p className="max-w-xl text-sm text-muted-foreground">
          No optimizer plans in this export. Rebuild it passing the optimizer decision
          artifacts via --optimizer-plan (see dashboard/README.md).
        </p>
      </div>
    );
  }
  if (!plan) return <p className="p-6 text-muted-foreground">Select a plan.</p>;

  const rules = plan.rules_snapshot;
  const policy = plan.search_policy;

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Optimizer audit</h1>
        <div className="flex items-center gap-3">
          {state.audit.length > 1 && (
            <Select value={plan.optimizer_run_id} onValueChange={setPlanId}>
              <SelectTrigger size="sm" className="w-72" aria-label="Plan">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {state.audit.map((p) => (
                  <SelectItem key={p.optimizer_run_id} value={p.optimizer_run_id}>
                    {planLabel(p.component_modes)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <Badge variant="outline" className="border-amber-500 text-amber-700 dark:text-amber-400">
            development-only — not a validated production recommendation
          </Badge>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Provenance">
          <Row label="optimizer run" value={plan.optimizer_run_id} />
          <Row label="decision sha256" value={plan.decision_sha256} />
          <Row label="forecast run" value={plan.forecast_run_id} />
          <Row
            label="as of"
            value={plan.as_of ? `${plan.as_of.replace("T", " ").slice(0, 16)} UTC` : "–"}
          />
          <Row label="horizon" value={`${plan.season} GW${plan.gw_from}-${plan.gw_to}`} />
          <Row label="architecture" value={planLabel(plan.component_modes)} />
          <Row label="optimizer commit" value={plan.provenance.optimizer_commit_sha} />
          <Row
            label="worktree clean"
            value={plan.provenance.optimizer_worktree_clean ? "yes (refused dirty)" : "no"}
          />
          <Row label="forecast artifact sha256" value={plan.provenance.forecast_artifact_sha256} />
          <Row label="forecast commit" value={plan.provenance.forecast_commit_sha} />
          <Row
            label="squad rules"
            value={`${plan.provenance.squad_rules_path} (v${plan.provenance.squad_rules_contract_version})`}
          />
          <Row label="squad rules sha256" value={plan.provenance.squad_rules_sha256} />
        </Card>

        <div className="space-y-3">
          <Card title="Solver">
            <Row
              label="solver"
              value={`${plan.solver.name} (${plan.solver.package} ${plan.solver.package_version}, binary ${plan.solver.binary_version})`}
            />
            <Row label="status" value={plan.solver.status} />
            <Row label="seed" value={plan.solver.seed} />
            <Row
              label="options"
              value={plan.solver.options.length ? plan.solver.options.join(", ") : "defaults"}
            />
          </Card>
          <Card title="Search policy (declared optimality scope)">
            <Row label="method" value={policy.search_method} />
            <Row label="optimality scope" value={policy.optimality_scope} />
            <Row label="candidate pool / position" value={policy.candidate_pool_per_position} />
            <Row label="transfer depth" value={policy.transfer_depth} />
            <Row label="transitions / state" value={policy.transition_limit_per_state} />
            <Row label="beam width" value={policy.beam_width} />
            <Row
              label="free transfers"
              value={`${policy.free_transfer_per_gameweek}/GW, bank cap ${policy.free_transfer_bank_cap}`}
            />
            <Row
              label="hit cost / max per GW"
              value={`${policy.hit_cost_points} pts, max ${policy.maximum_transfers_per_gameweek}`}
            />
            <Row label="risk lambda" value={policy.risk_lambda} />
          </Card>
        </div>
      </div>

      <Card title="Constraints (verified squad-rule snapshot)">
        <div className="grid gap-x-8 md:grid-cols-2">
          <div>
            <Row label="squad size" value={rules.squad_size} />
            <Row label="budget" value={`£${(rules.budget_tenths / 10).toFixed(1)}m`} />
            <Row label="maximum per club" value={rules.maximum_per_club} />
            <Row label="lineup starters" value={rules.lineup_starters} />
            <Row label="captain multiplier" value={rules.captain_multiplier} />
            <Row
              label="bench slots"
              value={`${rules.goalkeeper_bench_slots} GK + ${rules.outfield_bench_slots} outfield`}
            />
          </div>
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Position</TableHead>
                  <TableHead>In squad</TableHead>
                  <TableHead>Min starters</TableHead>
                  <TableHead>Max starters</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rules.positions.map((p) => (
                  <TableRow key={p.position}>
                    <TableCell>{p.position}</TableCell>
                    <TableCell className="tabular-nums">{p.squad}</TableCell>
                    <TableCell className="tabular-nums">{p.minimum_starters}</TableCell>
                    <TableCell className="tabular-nums">{p.maximum_starters}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      </Card>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Assumptions">
          <ul className="list-disc space-y-1 pl-4 text-sm">
            {plan.assumptions.map((assumption) => (
              <li key={assumption}>{assumption}</li>
            ))}
          </ul>
        </Card>
        <Card title="Transfer path and hits (squad/XI detail on the Next GW page)">
          {nextGwPlan ? (
            <ul className="space-y-1 text-sm">
              {nextGwPlan.weeks.map((week) => {
                const incoming = week.players.filter((p) => p.transferred_in);
                const outgoing = week.players.filter((p) => p.transferred_out);
                return (
                  <li key={week.gw} className="tabular-nums">
                    <span className="font-medium">GW{week.gw}</span> · hit -{week.hit_points} ·
                    squad cost £{(week.squad_cost / 10).toFixed(1)}m
                    <span className="text-muted-foreground">
                      {" "}
                      {incoming.length || outgoing.length
                        ? `in: ${incoming.map((p) => p.web_name).join(", ") || "–"} · out: ${
                            outgoing.map((p) => p.web_name).join(", ") || "–"
                          }`
                        : "no transfers"}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">
              no matching next-GW plan record for this optimizer run
            </p>
          )}
        </Card>
      </div>

      <p className="text-xs text-muted-foreground">
        Every price is the deadline-known now_cost (frozen-price scenario; no price-change or
        selling-value model). The initial fixed-squad ILP is exact; the multi-gameweek path is
        optimal only within the declared bounds and makes no global-optimality claim.
      </p>
    </div>
  );
}
