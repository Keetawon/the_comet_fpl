// Next GW suggestion: the platform's development-only optimizer plans for the next gameweek -- XI by
// position with captain/vice, ordered bench, and the SAME player pivot table as the
// Players page (form stats, filters, per-GW fixture chips as the last columns) restricted
// to the squad by default, switchable to the whole roster to compare candidates against
// the selected 15. Plan EV columns sit before the fixture columns. With two
// platform architectures present it shows the default-vs-diagnostic diff as set overlaps and
// captain agreement ONLY -- cross-plan EV is never compared, because it measures the two
// models' calibration against each other, not squad quality. User-constrained plans live
// only in Plan Builder and can never hijack this page through hash ordering or localStorage.

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { FilterPanel } from "@/components/FilterPanel";
import {
  FORM_WINDOW_LABEL,
  INITIAL_PLAYER_FILTERS,
  PlayerFiltersBar,
  matchesPlayerFilters,
  type PlayerFilters,
} from "@/components/PlayerFiltersBar";
import {
  PlayerStatTable,
  type PlayerStatRow,
  type PlayerStatSummaryRow,
} from "@/components/PlayerStatTable";
import { loadFixtureMatrix, loadNextGw, loadPlayers } from "@/data/load";
import type { NextGwPlan, PlanPlayer, PlanWeek, PlayerRecord, SquadContext, TeamRecord } from "@/data/types";
import { buildOpponentStrength } from "@/lib/opponentStrength";
import {
  buildPlanChipOutlook,
  type PlanWeekChipOutlook,
} from "@/lib/chipOutlook";
import {
  defaultPlan,
  diffPlans,
  horizonXp,
  isDefaultArchitecture,
  planDisplayLabel,
  platformComparisonPlans,
  platformPlans,
} from "@/lib/nextGw";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; plans: NextGwPlan[]; players: PlayerRecord[]; teams: TeamRecord[] };

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const price = (value: number | null) => (value == null ? "–" : `£${(value / 10).toFixed(1)}m`);

const POSITION_ORDER = ["GK", "DEF", "MID", "FWD"] as const;

type RawPlanXpMetric = "startingXiXp" | "benchXp" | "squadXp";

const RAW_PLAN_XP_ROWS: ReadonlyArray<{
  id: string;
  label: string;
  metric: RawPlanXpMetric;
}> = [
  { id: "planned-xi-xp", label: "Planned XI xP (11)", metric: "startingXiXp" },
  { id: "planned-bench-xp", label: "Planned bench xP (4)", metric: "benchXp" },
  { id: "planned-squad-xp", label: "Planned squad xP (15)", metric: "squadXp" },
];

function completePlanXpSum(
  byGw: ReadonlyMap<number, PlanWeekChipOutlook>,
  gws: number[],
  metric: RawPlanXpMetric,
): number | null {
  if (gws.length === 0) return null;
  let total = 0;
  for (const gw of gws) {
    const value = byGw.get(gw)?.[metric] ?? null;
    if (value == null || !Number.isFinite(value)) return null;
    total += value;
  }
  return total;
}

function planXpSummaryRows(
  plan: NextGwPlan,
  horizonWeeks: number,
): { rows: PlayerStatSummaryRow[]; highestBenchXpGw: number | null } {
  const outlook = buildPlanChipOutlook(plan);
  const byGw = new Map(outlook.weeks.map((week) => [week.gw, week]));
  const allGws = Array.from(
    { length: Math.max(0, plan.gw_to - plan.gw_from + 1) },
    (_, index) => plan.gw_from + index,
  );
  const selectedGws = allGws.slice(0, horizonWeeks);
  const rows = RAW_PLAN_XP_ROWS.map(({ id, label, metric }) => {
    const values: Record<string, ReactNode> = {
      totalXp: fmt(completePlanXpSum(byGw, allGws, metric)),
      "plan-gw-xp": fmt(completePlanXpSum(byGw, [plan.gw_from], metric)),
      "plan-horizon-xp": fmt(completePlanXpSum(byGw, selectedGws, metric)),
    };
    for (const gw of allGws) {
      const value = completePlanXpSum(byGw, [gw], metric);
      const isHighestBench = metric === "benchXp" && outlook.highestBenchXpGw === gw;
      values[`gw-${gw}`] = isHighestBench ? (
        <span
          className="inline-flex rounded bg-emerald-100 px-1 font-semibold text-emerald-900 dark:bg-emerald-950 dark:text-emerald-100"
          title="Highest complete planned bench xP in the loaded horizon"
        >
          {fmt(value)}
        </span>
      ) : (
        fmt(value)
      );
    }
    return { id, label, values };
  });
  return { rows, highestBenchXpGw: outlook.highestBenchXpGw };
}

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
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
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
  const [squadOnly, setSquadOnly] = useState<"squad" | "all">("squad");
  const [playerFilters, setPlayerFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadNextGw(), loadPlayers(), loadFixtureMatrix()])
      .then(([nextGw, playersData, teamsData]) => {
        if (cancelled) return;
        const officialPlans = platformPlans(nextGw.plans);
        setState({
          status: "ready",
          plans: officialPlans,
          players: playersData.players,
          teams: teamsData.teams,
        });
        setPlanId(defaultPlan(officialPlans)?.optimizer_run_id ?? null);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
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
    if (state.status !== "ready") return null;
    const pair = platformComparisonPlans(state.plans);
    return pair ? diffPlans(pair.defaultPlan, pair.diagnosticPlan) : null;
  }, [state]);

  const runPlayers = useMemo(
    () =>
      state.status === "ready" && plan
        ? state.players.filter((p) => p.run_id === plan.forecast_run_id)
        : [],
    [state, plan],
  );

  const runTeams = useMemo(
    () =>
      state.status === "ready" && plan
        ? state.teams.filter((t) => t.run_id === plan.forecast_run_id)
        : [],
    [state, plan],
  );

  const opponentStrength = useMemo(() => buildOpponentStrength(runTeams), [runTeams]);
  const opponentIndexOf = useMemo(
    () => (teamCode: number) => opponentStrength.get(teamCode)?.index ?? null,
    [opponentStrength],
  );

  const teams = useMemo(() => {
    const seen = new Map<number, string>();
    for (const p of runPlayers) if (!seen.has(p.team_code)) seen.set(p.team_code, p.team_short_name);
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [runPlayers]);

  /** Squad rows first in the plan's own order (XI by position, then bench), then anyone
   * else from the same vintage's roster by xP -- so compare mode still reads in order. */
  const { rows, weekByCode } = useMemo(() => {
    if (!plan) return { rows: [] as PlayerStatRow[], weekByCode: new Map<number, PlanPlayer>() };
    const week = plan.weeks[0];
    const byCode = new Map(week.players.map((p) => [p.code, p]));
    const roleRank = (p: PlanPlayer) =>
      p.role === "starting_xi" ? 0 : p.role === "bench_goalkeeper" ? 1 : 2;
    const squadOrdered = [...week.players].sort(
      (a, b) =>
        POSITION_ORDER.indexOf(a.position as (typeof POSITION_ORDER)[number]) -
          POSITION_ORDER.indexOf(b.position as (typeof POSITION_ORDER)[number]) ||
        roleRank(a) - roleRank(b) ||
        (a.bench_order_index ?? 99) - (b.bench_order_index ?? 99) ||
        a.web_name.localeCompare(b.web_name),
    );
    const buildRow = (player: PlayerRecord): PlayerStatRow => {
      const filtered = [...player.fixtures].sort(
        (a, b) => a.gw - b.gw || (a.kickoff_time ?? "").localeCompare(b.kickoff_time ?? ""),
      );
      const xpValues = filtered
        .map((f) => f.expected_points)
        .filter((v): v is number => v != null);
      return {
        player,
        filtered,
        totalXp: xpValues.length ? xpValues.reduce((a, b) => a + b, 0) : null,
        form: player.form ? player.form.windows[playerFilters.formWindow] : null,
      };
    };
    const squadRows = squadOrdered
      .map((squadPlayer) => runPlayers.find((p) => p.code === squadPlayer.code))
      .filter((p): p is PlayerRecord => p != null)
      .filter((p) => matchesPlayerFilters(p, playerFilters))
      .map(buildRow);
    const otherRows = runPlayers
      .filter((p) => !byCode.has(p.code))
      .filter((p) => matchesPlayerFilters(p, playerFilters))
      .map(buildRow)
      .sort((a, b) => (b.totalXp ?? -1) - (a.totalXp ?? -1));
    return { rows: squadOnly === "squad" ? squadRows : [...squadRows, ...otherRows], weekByCode: byCode };
  }, [plan, runPlayers, playerFilters, squadOnly]);

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Next GW suggestion</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!state.plans.length) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Next GW suggestion</h1>
        <p className="max-w-xl text-sm text-muted-foreground">
          No platform optimizer plans are present in this export. User-specific scenarios stay
          in Plan Builder and never substitute for the platform recommendation.
        </p>
      </div>
    );
  }
  if (!plan) return <p className="p-6 text-muted-foreground">Select a plan.</p>;

  const horizon = plan.gw_to - plan.gw_from + 1;
  const week = plan.weeks[0];
  const options = [1, 3, 5].filter((n) => n <= horizon);
  const weeks = options.includes(horizonWeeks) ? horizonWeeks : options[0];
  const planTotals = planXpSummaryRows(plan, weeks);

  const planColumns: LegacyColumnDef<PlayerStatRow>[] = [
    {
      id: "plan-flags",
      header: "Flags",
      enableSorting: false,
      cell: ({ row }) => {
        const ctx = plan.squad_context[String(row.original.player.code)];
        const labels = flags(ctx);
        return labels.length ? (
          <span className="text-[10px] text-muted-foreground">{labels.join(" · ")}</span>
        ) : (
          <span className="text-muted-foreground">–</span>
        );
      },
    },
    {
      id: "plan-gw-xp",
      header: `Plan xP GW${week.gw}`,
      accessorFn: (row) => weekByCode.get(row.player.code)?.expected_points ?? null,
      cell: ({ row }) => (
        <span className="tabular-nums">
          {fmt(weekByCode.get(row.original.player.code)?.expected_points ?? null)}
        </span>
      ),
    },
    {
      id: "plan-horizon-xp",
      header: `EV ${weeks} GW${weeks > 1 ? "s" : ""}`,
      accessorFn: (row) => horizonXp(plan, row.player.code, weeks),
      cell: ({ row }) => (
        <span className="tabular-nums font-medium">
          {fmt(horizonXp(plan, row.original.player.code, weeks))}
        </span>
      ),
    },
  ];

  const nameSuffix = (player: PlayerRecord) => {
    const squadPlayer = weekByCode.get(player.code);
    if (!squadPlayer) return null;
    return (
      <>
        {squadPlayer.is_captain && <Badge className="px-1 text-[9px]">C</Badge>}
        {squadPlayer.is_vice_captain && (
          <Badge variant="outline" className="px-1 text-[9px]">
            V
          </Badge>
        )}
        {squadPlayer.role !== "starting_xi" && (
          <span className="text-[10px] text-muted-foreground">bench</span>
        )}
        {squadPlayer.transferred_in && (
          <span className="text-[10px] text-emerald-600 dark:text-emerald-400">in</span>
        )}
      </>
    );
  };

  /** Row conditional formatting: captain gold, vice pale gold, bench grey, XI default. */
  const rowClassName = (player: PlayerRecord) => {
    const squadPlayer = weekByCode.get(player.code);
    if (!squadPlayer) return undefined;
    if (squadPlayer.is_captain) {
      return "bg-amber-100/70 dark:bg-amber-950/40 border-l-4 border-l-amber-500";
    }
    if (squadPlayer.is_vice_captain) {
      return "bg-amber-50 dark:bg-amber-950/20 border-l-4 border-l-amber-300 dark:border-l-amber-700";
    }
    if (squadPlayer.role !== "starting_xi") {
      return "bg-zinc-200 dark:bg-zinc-800/80 border-l-4 border-l-transparent";
    }
    return undefined;
  };

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">Platform Next GW suggestion — GW{plan.gw_from}</h1>
          <p className="text-xs text-muted-foreground">
            Formal platform recommendation; your locks, exclusions, and thresholds live in Plan
            Builder.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          {state.plans.length > 1 && (
            <Select value={plan.optimizer_run_id} onValueChange={setPlanId}>
              <SelectTrigger size="sm" className="w-80" aria-label="Platform model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {state.plans.map((p) => (
                  <SelectItem key={p.optimizer_run_id} value={p.optimizer_run_id}>
                    {planDisplayLabel(p)}
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

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          squad cost {price(week.squad_cost)} (deadline prices; later-GW affordability is a
          frozen-price scenario)
        </span>
        <span>hit GW{week.gw}: -{fmt(week.hit_points, 0)} pts</span>
        <span>
          architecture {isDefaultArchitecture(plan.component_modes) ? "default" : "diagnostic"} ·{" "}
          {planDisplayLabel(plan)}
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

      <FilterPanel>
        <div className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
            <ToggleGroup
              type="single"
              value={squadOnly}
              onValueChange={(value) => {
                if (value) setSquadOnly(value as "squad" | "all");
              }}
              variant="outline"
              aria-label="Roster scope"
            >
              <ToggleGroupItem value="squad">Squad only</ToggleGroupItem>
              <ToggleGroupItem value="all">Compare all players</ToggleGroupItem>
            </ToggleGroup>
            <span className="text-xs">
              {rows.length} rows · chips headline fixture xP and colour on opponent strength ·
              row colours: gold = captain, pale gold = vice, grey = bench
            </span>
          </div>
          <PlayerFiltersBar filters={playerFilters} onChange={setPlayerFilters} teams={teams} />
        </div>
      </FilterPanel>

      <PlayerStatTable
        fullscreenLabel="Next GW suggestion players table"
        rows={rows}
        view="overall"
        colorSource="opponent"
        gwFrom={plan.gw_from}
        gwTo={plan.gw_to}
        opponentIndexOf={opponentIndexOf}
        formHeading={FORM_WINDOW_LABEL[playerFilters.formWindow]}
        initialSorting={[]}
        beforeFixtureColumns={planColumns}
        nameSuffix={nameSuffix}
        rowClassName={({ player }) => rowClassName(player)}
        summaryRows={planTotals.rows}
        summaryNote={
          <>
            Full selected post-transfer plan; raw player xP sums, unaffected by table filters,
            sorting, or pagination. Bench xP is the marginal Bench Boost signal.{" "}
            {planTotals.highestBenchXpGw == null
              ? "No complete bench total is available."
              : `Highest complete bench xP in this loaded horizon: GW${planTotals.highestBenchXpGw}.`}
          </>
        }
        emptyMessage={
          squadOnly === "squad"
            ? "No squad players match the current filters."
            : "No players match the current filters."
        }
      />

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
