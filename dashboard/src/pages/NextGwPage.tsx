// Next GW suggestion: the development-only optimizer plan for the next gameweek -- XI by
// position with captain/vice, ordered bench, squad table with horizon EV (1/3/5 GWs bounded
// by the vintage horizon), ownership/availability overlay, flags, and the transfer path with
// hits. With two architectures present it shows the default-vs-diagnostic diff as set
// overlaps and captain agreement ONLY -- cross-plan EV is never compared, because it measures
// the two models' calibration against each other, not squad quality.

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { loadNextGw } from "@/data/load";
import type { NextGwPlan, PlanPlayer, PlanWeek, SquadContext } from "@/data/types";
import {
  defaultPlan,
  diffPlans,
  horizonXp,
  isDefaultArchitecture,
  planLabel,
} from "@/lib/nextGw";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; plans: NextGwPlan[] };

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const price = (value: number | null) => (value == null ? "–" : `£${(value / 10).toFixed(1)}m`);

const POSITION_ORDER = ["GK", "DEF", "MID", "FWD"] as const;

const AVAILABILITY_LABEL: Record<string, string> = {
  a: "available",
  d: "doubtful",
  i: "injured",
  s: "suspended",
  u: "unavailable",
  n: "not available",
};

function flags(context: SquadContext | undefined): string[] {
  if (!context) return [];
  const labels: string[] = [];
  if (context.cold_start_player) labels.push("cold start");
  if (context.stage_a_league_average_team) labels.push("Stage A league avg");
  if (context.attacking_signal_cold_start) labels.push("attacking cold start");
  if (context.assist_signal_cold_start) labels.push("assist cold start");
  if (context.transferred_no_rescale) labels.push("transferred, no rescale");
  return labels;
}

function XiBlock({ week }: { week: PlanWeek }) {
  const xi = week.players.filter((p) => p.role === "starting_xi");
  const formation = POSITION_ORDER.map(
    (position) => xi.filter((p) => p.position === position).length,
  );
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Formation {formation.slice(1).join("-")} · captain{" "}
        <span className="font-medium text-foreground">
          {xi.find((p) => p.code === week.captain_code)?.web_name ?? week.captain_code}
        </span>{" "}
        · vice{" "}
        <span className="font-medium text-foreground">
          {xi.find((p) => p.code === week.vice_captain_code)?.web_name ?? week.vice_captain_code}
        </span>
      </p>
      <div className="grid gap-3 sm:grid-cols-4">
        {POSITION_ORDER.map((position) => (
          <div key={position} className="rounded-md border p-2">
            <p className="mb-1 text-[10px] font-medium text-muted-foreground">{position}</p>
            <ul className="space-y-1 text-sm">
              {xi
                .filter((p) => p.position === position)
                .map((p) => (
                  <li key={p.code} className="flex items-baseline justify-between gap-1">
                    <span className="truncate">
                      {p.web_name}
                      {p.is_captain && <Badge className="ml-1 size-fit px-1 text-[9px]">C</Badge>}
                      {p.is_vice_captain && (
                        <Badge variant="outline" className="ml-1 size-fit px-1 text-[9px]">
                          V
                        </Badge>
                      )}
                    </span>
                    <span className="tabular-nums text-xs text-muted-foreground">
                      {fmt(p.expected_points)}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

function BenchBlock({ week }: { week: PlanWeek }) {
  const bench = week.players
    .filter((p) => p.role !== "starting_xi")
    .sort((a, b) => {
      if (a.role === "bench_goalkeeper") return -1;
      if (b.role === "bench_goalkeeper") return 1;
      return (a.bench_order_index ?? 99) - (b.bench_order_index ?? 99);
    });
  return (
    <div className="rounded-md border p-2">
      <p className="mb-1 text-[10px] font-medium text-muted-foreground">
        Bench (autosub order; the goalkeeper covers first)
      </p>
      <ol className="space-y-1 text-sm">
        {bench.map((p) => (
          <li key={p.code} className="flex items-baseline justify-between gap-1">
            <span className="truncate">
              {p.web_name}
              <span className="ml-1 text-xs text-muted-foreground">{p.position}</span>
              {p.role === "bench_goalkeeper" && (
                <Badge variant="outline" className="ml-1 size-fit px-1 text-[9px]">
                  GK
                </Badge>
              )}
            </span>
            <span className="tabular-nums text-xs text-muted-foreground">{fmt(p.expected_points)}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function NextGwPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [planId, setPlanId] = useState<string | null>(null);
  const [horizonWeeks, setHorizonWeeks] = useState<number>(1);

  useEffect(() => {
    let cancelled = false;
    loadNextGw()
      .then(({ plans }) => {
        if (cancelled) return;
        setState({ status: "ready", plans });
        setPlanId(defaultPlan(plans)?.optimizer_run_id ?? null);
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
        ? (state.plans.find((p) => p.optimizer_run_id === planId) ?? null)
        : null,
    [state, planId],
  );

  const diff = useMemo(() => {
    if (state.status !== "ready" || state.plans.length < 2) return null;
    const a = defaultPlan(state.plans);
    const b = state.plans.find((p) => p !== a) ?? null;
    return a && b ? diffPlans(a, b) : null;
  }, [state]);

  if (state.status === "loading") return <p className="p-6 text-muted-foreground">Loading read models…</p>;
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Next GW suggestion</h1>
        <p className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!state.plans.length) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Next GW suggestion</h1>
        <p className="max-w-xl text-sm text-muted-foreground">
          No optimizer plans in this export. Rebuild it passing the optimizer decision
          artifacts via --optimizer-plan (see dashboard/README.md).
        </p>
      </div>
    );
  }
  if (!plan) return <p className="p-6 text-muted-foreground">Select a plan.</p>;

  const horizon = plan.gw_to - plan.gw_from + 1;
  const week = plan.weeks[0];
  const options = [1, 3, 5].filter((n) => n <= horizon);
  const weeks = options.includes(horizonWeeks) ? horizonWeeks : options[0];
  const context = (code: number) => plan.squad_context[String(code)];

  const squadRows: PlanPlayer[] = [...week.players].sort((a, b) => {
    const rank = (p: PlanPlayer) =>
      p.role === "starting_xi" ? 0 : p.role === "bench_goalkeeper" ? 1 : 2;
    return (
      POSITION_ORDER.indexOf((a.position ?? "FWD") as (typeof POSITION_ORDER)[number]) -
        POSITION_ORDER.indexOf((b.position ?? "FWD") as (typeof POSITION_ORDER)[number]) ||
      rank(a) - rank(b) ||
      a.web_name.localeCompare(b.web_name)
    );
  });

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-lg font-semibold">Next GW suggestion — GW{plan.gw_from}</h1>
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          {state.plans.length > 1 && (
            <Select value={plan.optimizer_run_id} onValueChange={setPlanId}>
              <SelectTrigger size="sm" className="w-72" aria-label="Plan">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {state.plans.map((p) => (
                  <SelectItem key={p.optimizer_run_id} value={p.optimizer_run_id}>
                    {planLabel(p.component_modes)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <div className="flex items-center gap-2">
            <span>EV horizon</span>
            <ToggleGroup
              type="single"
              value={String(weeks)}
              onValueChange={(value) => {
                if (value) setHorizonWeeks(Number(value));
              }}
              variant="outline"
              aria-label="EV horizon"
            >
              {options.map((n) => (
                <ToggleGroupItem key={n} value={String(n)}>
                  {n} GW{n > 1 ? "s" : ""}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          squad cost {price(week.squad_cost)} (deadline prices; later-GW affordability is a
          frozen-price scenario)
        </span>
        <span>hit GW{week.gw}: -{fmt(week.hit_points, 0)} pts</span>
        <span>
          architecture{" "}
          {isDefaultArchitecture(plan.component_modes) ? "default" : "diagnostic"} ·{" "}
          {planLabel(plan.component_modes)}
        </span>
      </div>

      <XiBlock week={week} />

      <div className="grid gap-3 md:grid-cols-2">
        <BenchBlock week={week} />
        <div className="rounded-md border p-2">
          <p className="mb-1 text-[10px] font-medium text-muted-foreground">
            Transfer path over the horizon (frozen prices; no price-change model)
          </p>
          <ul className="space-y-1 text-sm">
            {plan.weeks.map((w) => {
              const incoming = w.players.filter((p) => p.transferred_in);
              const outgoing = w.players.filter((p) => p.transferred_out);
              return (
                <li key={w.gw} className="tabular-nums">
                  <span className="font-medium">GW{w.gw}</span> · hit -{w.hit_points}
                  {incoming.length || outgoing.length ? (
                    <span className="text-muted-foreground">
                      {" "}
                      in: {incoming.map((p) => p.web_name).join(", ") || "–"} · out:{" "}
                      {outgoing.map((p) => p.web_name).join(", ") || "–"}
                    </span>
                  ) : (
                    <span className="text-muted-foreground"> no transfers</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      </div>

      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Player</TableHead>
              <TableHead>Pos</TableHead>
              <TableHead>Team</TableHead>
              <TableHead>Price</TableHead>
              <TableHead>TS%</TableHead>
              <TableHead>Availability (overlay)</TableHead>
              <TableHead>Flags</TableHead>
              <TableHead>xP GW{week.gw}</TableHead>
              <TableHead>xP {weeks} GW{weeks > 1 ? "s" : ""}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {squadRows.map((p) => {
              const ctx = context(p.code);
              const status = ctx?.availability_status ?? null;
              return (
                <TableRow key={p.code}>
                  <TableCell>
                    <span className="font-medium">{p.web_name}</span>
                    {p.is_captain && <Badge className="ml-1 px-1 text-[9px]">C</Badge>}
                    {p.is_vice_captain && (
                      <Badge variant="outline" className="ml-1 px-1 text-[9px]">
                        V
                      </Badge>
                    )}
                    {p.role !== "starting_xi" && (
                      <span className="ml-1 text-xs text-muted-foreground">bench</span>
                    )}
                    {p.transferred_in && (
                      <span className="ml-1 text-xs text-emerald-600 dark:text-emerald-400">
                        transferred in
                      </span>
                    )}
                  </TableCell>
                  <TableCell>{p.position}</TableCell>
                  <TableCell>{p.team_short_name}</TableCell>
                  <TableCell className="tabular-nums">{price(p.now_cost)}</TableCell>
                  <TableCell className="tabular-nums">
                    {ctx?.selected_by_percent == null ? "–" : ctx.selected_by_percent.toFixed(1)}
                  </TableCell>
                  <TableCell>
                    {status == null ? (
                      "–"
                    ) : (
                      <span className={status === "a" ? "" : "text-amber-600 dark:text-amber-400"}>
                        {AVAILABILITY_LABEL[status] ?? status}
                        {ctx?.chance_of_playing != null && ` ${Math.round(ctx.chance_of_playing)}%`}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs">
                    {flags(ctx).join(" · ") || <span className="text-muted-foreground">–</span>}
                  </TableCell>
                  <TableCell className="tabular-nums">{fmt(p.expected_points)}</TableCell>
                  <TableCell className="tabular-nums">{fmt(horizonXp(plan, p.code, weeks))}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>

      {diff && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">
            Default vs diagnostic (GW{diff.gw}) — set overlap only, EV is never compared across
            architectures
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            squad overlap {diff.squadOverlap}/{diff.squadSize} · XI overlap {diff.xiOverlap} ·
            captain {diff.captainAgrees ? "agrees" : "differs"} · vice{" "}
            {diff.viceAgrees ? "agrees" : "differs"}
          </p>
          <p className="mt-1 text-xs">
            <span className="text-muted-foreground">{diff.labelA} unique:</span>{" "}
            {diff.uniqueToA.map((code) => playerNameSafe(code, state.plans)).join(", ") || "–"}
          </p>
          <p className="text-xs">
            <span className="text-muted-foreground">{diff.labelB} unique:</span>{" "}
            {diff.uniqueToB.map((code) => playerNameSafe(code, state.plans)).join(", ") || "–"}
          </p>
        </div>
      )}

      <Separator className="my-1" />
      <p className="text-xs text-muted-foreground">
        Development-only optimizer output (bounded transfer search, no global-optimality
        claim). Optimizer run {plan.optimizer_run_id.slice(0, 12)}… · decision{" "}
        {plan.decision_sha256.slice(0, 12)}… · forecast run {plan.forecast_run_id.slice(0, 12)}… ·
        as of {plan.as_of?.replace("T", " ").slice(0, 16)} UTC. Availability is a reported
        overlay valid for GW{plan.gw_from} only; its later-GW reuse is a scenario assumption.
      </p>
    </div>
  );
}

function playerNameSafe(code: number, plans: NextGwPlan[]): string {
  for (const candidate of plans) {
    for (const week of candidate.weeks) {
      const player = week.players.find((p) => p.code === code);
      if (player) return player.web_name;
    }
  }
  return `code ${code}`;
}
