// Player deep analytics over one exact schema-v5 cumulative endpoint. This page ranks and draws
// presentation geometry only; probabilities remain backend-published scalars.

import { useEffect, useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import { AnalyticsScatter, type AnalyticsScatterPoint } from "@/components/AnalyticsScatter";
import { FilterPanel } from "@/components/FilterPanel";
import {
  INITIAL_PLAYER_FILTERS,
  matchesPlayerFilters,
  PlayerFiltersBar,
  type PlayerFilters,
} from "@/components/PlayerFiltersBar";
import { VintageSelect } from "@/components/VintageSelect";
import { Button } from "@/components/ui/button";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { loadNextGw, loadPlayerHorizons, loadPlayers } from "@/data/load";
import type {
  NextGwPlan,
  PlayerHorizonsRecord,
  PlayerRecord,
} from "@/data/types";
import {
  buildPlayerAnalytics,
  formatPlayerAnalyticsValue,
  PAST_METRIC_LABEL,
  PLAYER_ANALYTICS_VIEW_LABEL,
  type HaulThreshold,
  type PastMetric,
  type PlayerAnalyticsView,
} from "@/lib/playerAnalytics";
import { indexPlayerHorizons } from "@/lib/playerHorizons";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";

interface AnalyticsRun {
  run_id: string;
  season: string;
  gw_from: number;
  gw_to: number;
  as_of?: string;
}
type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      players: PlayerRecord[];
      horizons: PlayerHorizonsRecord[];
      plans: NextGwPlan[];
      runs: AnalyticsRun[];
      defaultRunId: string;
    };

const POSITION_COLOURS: Record<string, string> = {
  GK: "#8b5cf6",
  DEF: "#2563eb",
  MID: "#059669",
  FWD: "#ea580c",
};

const VIEW_DESCRIPTION: Record<PlayerAnalyticsView, string> = {
  value: "Cheaper and higher-xP players form the nondominated exploration frontier.",
  upside_downside:
    "Lower published blank probability and higher published haul probability are preferred.",
  differential: "Lower deadline ownership and higher cumulative xP form the exploration frontier.",
  past_future:
    "Observed past form is shown beside future cumulative xP for context only; no frontier is claimed.",
};

function deriveRuns(
  players: readonly PlayerRecord[],
  horizons: readonly PlayerHorizonsRecord[],
): AnalyticsRun[] {
  const byRun = new Map<string, AnalyticsRun>();
  for (const record of horizons) {
    const endpoints = record.horizons.map((horizon) => horizon.gw_to);
    if (!endpoints.length) continue;
    const existing = byRun.get(record.run_id);
    const player = players.find(
      (candidate) =>
        candidate.run_id === record.run_id &&
        candidate.season === record.season &&
        candidate.code === record.code,
    );
    const gwFrom = Math.min(...endpoints);
    const gwTo = Math.max(...endpoints);
    byRun.set(record.run_id, {
      run_id: record.run_id,
      season: record.season,
      gw_from: existing ? Math.min(existing.gw_from, gwFrom) : gwFrom,
      gw_to: existing ? Math.max(existing.gw_to, gwTo) : gwTo,
      as_of: existing?.as_of ?? player?.as_of,
    });
  }
  return [...byRun.values()].sort((left, right) => left.run_id.localeCompare(right.run_id));
}

function axisTick(view: PlayerAnalyticsView, axis: "x" | "y", value: number): string {
  if (view === "upside_downside") return `${Math.round(value * 100)}%`;
  if (axis === "x" && view === "value") return `£${value.toFixed(1)}`;
  if (axis === "x" && view === "differential") return `${value.toFixed(0)}%`;
  return value.toFixed(2);
}

function firstFormAnchor(players: readonly PlayerRecord[]): string | null {
  const form = players.find((player) => player.form != null)?.form;
  return form ? `${form.season} GW${form.as_at_gw}` : null;
}

export function PlayerAnalyticsPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [gwTo, setGwTo] = useState<number | null>(null);
  const [view, setView] = useState<PlayerAnalyticsView>("value");
  const [haulThreshold, setHaulThreshold] = useState<HaulThreshold>(10);
  const [pastMetric, setPastMetric] = useState<PastMetric>("points");
  const [filters, setFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadPlayers(), loadPlayerHorizons(), loadNextGw()])
      .then(([playerData, horizonData, nextGw]) => {
        if (cancelled) return;
        const runs = playerData.manifest?.runs ?? deriveRuns(playerData.players, horizonData.players);
        const fallback = playerData.manifest?.runs.at(-1)?.run_id ?? runs[0]?.run_id ?? null;
        const defaultRun = defaultVintageRunId(runs, nextGw.plans, fallback);
        const selected = runs.find((run) => run.run_id === defaultRun) ?? runs[0];
        setState({
          status: "ready",
          players: playerData.players,
          horizons: horizonData.players,
          plans: nextGw.plans,
          runs,
          defaultRunId: defaultRun ?? "",
        });
        setRunId(defaultRun);
        setGwTo(selected?.gw_to ?? null);
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

  const selectedRun = useMemo(() => {
    if (state.status !== "ready") return null;
    const selected = runId ?? state.defaultRunId;
    return state.runs.find((run) => run.run_id === selected) ?? null;
  }, [state, runId]);

  const horizonEndpoints = useMemo(() => {
    if (state.status !== "ready" || selectedRun == null) return [];
    return [
      ...new Set(
        state.horizons
          .filter(
            (record) =>
              record.run_id === selectedRun.run_id && record.season === selectedRun.season,
          )
          .flatMap((record) => record.horizons.map((horizon) => horizon.gw_to)),
      ),
    ].sort((left, right) => left - right);
  }, [state, selectedRun]);

  const effectiveGwTo =
    gwTo != null && horizonEndpoints.includes(gwTo)
      ? gwTo
      : horizonEndpoints.at(-1) ?? selectedRun?.gw_to ?? null;

  const exactRunPlayers = useMemo(() => {
    if (state.status !== "ready" || selectedRun == null) return [];
    return state.players.filter(
      (player) =>
        player.run_id === selectedRun.run_id && player.season === selectedRun.season,
    );
  }, [state, selectedRun]);

  const teams = useMemo(() => {
    const seen = new Map<number, string>();
    for (const player of exactRunPlayers) {
      if (!seen.has(player.team_code)) seen.set(player.team_code, player.team_short_name);
    }
    return [...seen.entries()].sort((left, right) => left[1].localeCompare(right[1]));
  }, [exactRunPlayers]);

  const filteredPlayers = useMemo(
    () => exactRunPlayers.filter((player) => matchesPlayerFilters(player, filters)),
    [exactRunPlayers, filters],
  );

  const horizonIndex = useMemo(
    () => indexPlayerHorizons(state.status === "ready" ? state.horizons : []),
    [state],
  );

  const analytics = useMemo(() => {
    if (selectedRun == null || effectiveGwTo == null) return null;
    return buildPlayerAnalytics(filteredPlayers, horizonIndex, {
      runId: selectedRun.run_id,
      season: selectedRun.season,
      gwFrom: selectedRun.gw_from,
      gwTo: effectiveGwTo,
      view,
      haulThreshold,
      formWindow: filters.formWindow,
      pastMetric,
    });
  }, [
    selectedRun,
    effectiveGwTo,
    filteredPlayers,
    horizonIndex,
    view,
    haulThreshold,
    filters.formWindow,
    pastMetric,
  ]);

  const scatterPoints: AnalyticsScatterPoint[] = useMemo(
    () =>
      analytics?.plotted.map((row) => ({
        id: row.code,
        label: row.webName,
        x: row.x,
        y: row.y,
        xDisplay: formatPlayerAnalyticsValue(analytics.config, "x", row.x),
        yDisplay: formatPlayerAnalyticsValue(analytics.config, "y", row.y),
        isFrontier: row.isFrontier,
        color: POSITION_COLOURS[row.position] ?? "#64748b",
        groupLabel: `${row.position} · ${row.teamShortName}`,
      })) ?? [],
    [analytics],
  );

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Player analytics</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!state.runs.length || selectedRun == null || effectiveGwTo == null) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Player analytics</h1>
        <p className="text-sm text-muted-foreground">
          No recorded forecast vintages with cumulative player endpoints are available.
        </p>
      </div>
    );
  }

  const horizonLabel = `GW${selectedRun.gw_from}-${effectiveGwTo} (fixed start)`;
  const vintageLabel = `${selectedRun.run_id} · ${selectedRun.season}`;
  const formAnchor = firstFormAnchor(exactRunPlayers);

  const changeRun = (nextRunId: string) => {
    setRunId(nextRunId);
    const nextRun = state.runs.find((run) => run.run_id === nextRunId);
    setGwTo(nextRun?.gw_to ?? null);
  };

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Player analytics</h1>
          <p className="text-xs text-muted-foreground">
            {selectedRun.season} · fixed start GW{selectedRun.gw_from} · as of{" "}
            {(selectedRun.as_of ?? exactRunPlayers[0]?.as_of ?? "unknown").replace("T", " ").slice(0, 16)} UTC
          </p>
        </div>
        <VintageSelect
          options={vintageOptions(state.runs, state.plans)}
          value={selectedRun.run_id}
          onChange={changeRun}
        />
      </header>

      <FilterPanel>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <ToggleGroup
              type="single"
              value={view}
              onValueChange={(value) => {
                if (value) setView(value as PlayerAnalyticsView);
              }}
              variant="outline"
              aria-label="Analytics view"
            >
              {(Object.keys(PLAYER_ANALYTICS_VIEW_LABEL) as PlayerAnalyticsView[]).map(
                (value) => (
                  <ToggleGroupItem key={value} value={value}>
                    {PLAYER_ANALYTICS_VIEW_LABEL[value]}
                  </ToggleGroupItem>
                ),
              )}
            </ToggleGroup>

            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Cumulative horizon</span>
              <Select
                value={String(effectiveGwTo)}
                onValueChange={(value) => setGwTo(Number(value))}
              >
                <SelectTrigger size="sm" className="w-28" aria-label="Cumulative horizon endpoint">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {horizonEndpoints.map((endpoint) => (
                    <SelectItem key={endpoint} value={String(endpoint)}>
                      GW{selectedRun.gw_from}-{endpoint}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            {view === "upside_downside" && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Haul threshold</span>
                <Select
                  value={String(haulThreshold)}
                  onValueChange={(value) => setHaulThreshold(Number(value) as HaulThreshold)}
                >
                  <SelectTrigger size="sm" className="w-24" aria-label="Haul threshold">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {[6, 10, 15].map((threshold) => (
                      <SelectItem key={threshold} value={String(threshold)}>
                        ≥ {threshold}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            {view === "past_future" && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Past metric</span>
                <Select value={pastMetric} onValueChange={(value) => setPastMetric(value as PastMetric)}>
                  <SelectTrigger size="sm" className="w-64" aria-label="Past form metric">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {(Object.keys(PAST_METRIC_LABEL) as PastMetric[]).map((metric) => (
                      <SelectItem key={metric} value={metric}>
                        {PAST_METRIC_LABEL[metric]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>

          <PlayerFiltersBar filters={filters} onChange={setFilters} teams={teams} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              The horizon always starts at the vintage's fixed GW{selectedRun.gw_from}.{" "}
              {formAnchor
                ? `Past form is observed through ${formAnchor}.`
                : "Past form is unmeasured for this filtered vintage."}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setFilters(INITIAL_PLAYER_FILTERS)}
              aria-label="Clear player analytics filters"
            >
              <RotateCcw className="size-3.5" aria-hidden />
              Clear filters
            </Button>
          </div>
        </div>
      </FilterPanel>

      {analytics && (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(22rem,0.7fr)]">
            <AnalyticsScatter
              title={PLAYER_ANALYTICS_VIEW_LABEL[view]}
              description={VIEW_DESCRIPTION[view]}
              points={scatterPoints}
              xAxis={{
                label: analytics.xAxis.label,
                direction: analytics.xAxis.direction,
                format: (value) => axisTick(view, "x", value),
              }}
              yAxis={{
                label: analytics.yAxis.label,
                direction: analytics.yAxis.direction,
                format: (value) => axisTick(view, "y", value),
              }}
              vintageLabel={vintageLabel}
              horizonLabel={horizonLabel}
              emptyMessage={
                analytics.eligibleCount === 0
                  ? "No players match the current filters."
                  : "Every filtered player is missing at least one selected axis value."
              }
            />

            <section className="rounded-lg border bg-card p-4" aria-labelledby="player-insight-title">
              <h2 id="player-insight-title" className="text-sm font-semibold">
                Deterministic insight
              </h2>
              <p className="mt-1 text-xs text-muted-foreground">
                Evidence-bound facts from the visible scope; no remote AI call.
              </p>
              <ul className="mt-3 space-y-2 text-sm">
                {analytics.facts.map((fact) => (
                  <li key={fact.id}>{fact.statement}</li>
                ))}
              </ul>
              <div className="mt-4 border-t pt-3 text-xs text-muted-foreground">
                {analytics.caveats.map((caveat) => (
                  <p key={caveat} className="mt-1">{caveat}</p>
                ))}
              </div>
            </section>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <p>
              {analytics.plotted.length} plotted · {analytics.omittedCount} not plotted of{" "}
              {analytics.eligibleCount} filtered players. Null axis values are omitted, never zero.
            </p>
            <div className="flex flex-wrap items-center gap-3" aria-label="Player position colour legend">
              {Object.entries(POSITION_COLOURS).map(([position, colour]) => (
                <span key={position} className="inline-flex items-center gap-1">
                  <span
                    className="size-2.5 rounded-full"
                    style={{ backgroundColor: colour }}
                    aria-hidden
                  />
                  {position}
                </span>
              ))}
              {view !== "past_future" && <span>outlined = Pareto frontier</span>}
            </div>
          </div>

          <section className="rounded-lg border bg-card p-3" aria-labelledby="player-values-title">
            <h2 id="player-values-title" className="mb-2 text-sm font-semibold">
              Exact plotted values
            </h2>
            <Table aria-label={`Player analytics exact values · ${PLAYER_ANALYTICS_VIEW_LABEL[view]}`}>
              <TableHeader>
                <TableRow>
                  <TableHead>Player</TableHead>
                  <TableHead>Team</TableHead>
                  <TableHead>Position</TableHead>
                  <TableHead>{analytics.xAxis.label}</TableHead>
                  <TableHead>{analytics.yAxis.label}</TableHead>
                  <TableHead>Frontier</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {analytics.plotted.map((row) => (
                  <TableRow key={row.code}>
                    <TableCell className="font-medium">{row.webName}</TableCell>
                    <TableCell>{row.teamShortName}</TableCell>
                    <TableCell>{row.position}</TableCell>
                    <TableCell className="tabular-nums">
                      {formatPlayerAnalyticsValue(analytics.config, "x", row.x)}
                    </TableCell>
                    <TableCell className="tabular-nums">
                      {formatPlayerAnalyticsValue(analytics.config, "y", row.y)}
                    </TableCell>
                    <TableCell>
                      {view === "past_future" ? "Context only" : row.isFrontier ? "Yes" : "No"}
                    </TableCell>
                  </TableRow>
                ))}
                {!analytics.plotted.length && (
                  <TableRow>
                    <TableCell colSpan={6} className="text-center text-muted-foreground">
                      {analytics.eligibleCount === 0
                        ? "No players match the current filters."
                        : "No players have both selected axis values."}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </section>

          <p className="text-xs text-muted-foreground">
            Price and ownership are deadline-vintage overlays. Probability values are inclusive,
            backend-published, and raw: the reported availability multiplier is not applied. The
            frontier compares these two axes only and is not an optimizer, squad, or transfer plan.
          </p>
        </>
      )}
    </div>
  );
}
