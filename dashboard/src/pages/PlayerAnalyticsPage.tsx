// Player deep analytics over one exact schema-v6 cumulative endpoint. This page ranks and draws
// presentation geometry only; probabilities remain backend-published scalars.

import { useEffect, useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import { AnalyticsScatter, type AnalyticsScatterPoint } from "@/components/AnalyticsScatter";
import { FilterPanel } from "@/components/FilterPanel";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import {
  INITIAL_PLAYER_FILTERS,
  matchesPlayerFilters,
  PlayerFiltersBar,
  type PlayerFilters,
} from "@/components/PlayerFiltersBar";
import { VintageSelect } from "@/components/VintageSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
  DashboardManifest,
  NextGwPlan,
  PlayerHorizonsRecord,
  PlayerRecord,
} from "@/data/types";
import {
  compactInsightScope,
  formWindowScope,
  insightFact,
  maxPriceTenthsScope,
  minAverageMinutesScope,
  minPriceTenthsScope,
  playerPastMetricScope,
  playerPositionScope,
  publishedInsightProvenance,
} from "@/lib/insights";
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
      manifest: DashboardManifest | null;
      defaultRunId: string;
    };

const POSITION_COLOURS: Record<string, string> = {
  GK: "#8b5cf6",
  DEF: "#2563eb",
  MID: "#059669",
  FWD: "#ea580c",
};

const VIEW_DESCRIPTION: Record<PlayerAnalyticsView, string> = {
  value: "Asset-style efficient frontier: cheaper and higher-xP players form the Pareto-nondominated set.",
  upside_downside:
    "Risk/reward efficient frontier: lower published blank probability and higher published haul probability are preferred.",
  differential: "Differential efficient frontier: lower deadline ownership and higher cumulative xP form the Pareto-nondominated set.",
  past_future:
    "Latest-at-export observed form is shown beside future cumulative xP for context only; it is not aligned to the selected forecast vintage and no frontier is claimed.",
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

function playerFormAnchor(player: PlayerRecord): string | null {
  return player.form ? `${player.form.season} GW${player.form.as_at_gw}` : null;
}

function formAnchorSummary(players: readonly PlayerRecord[]): string {
  const anchors = [
    ...new Set(
      players
        .map(playerFormAnchor)
        .filter((anchor): anchor is string => anchor != null),
    ),
  ].sort();
  const unavailableCount =
    players.length - players.filter((player) => player.form != null).length;
  if (!anchors.length) {
    return "Latest-at-export observed form is unavailable for this filtered population.";
  }
  const measured = anchors.length === 1
    ? anchors[0]
    : `${anchors.length} different anchors; see the exact table`;
  const unavailable = unavailableCount
    ? ` ${unavailableCount} filtered player${unavailableCount === 1 ? " has" : "s have"} no form anchor.`
    : "";
  return `Observed form uses the latest static-export anchor (${measured}), not the selected forecast vintage.${unavailable}`;
}

export function PlayerAnalyticsPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [gwTo, setGwTo] = useState<number | null>(null);
  const [view, setView] = useState<PlayerAnalyticsView>("value");
  const [haulThreshold, setHaulThreshold] = useState<HaulThreshold>(10);
  const [pastMetric, setPastMetric] = useState<PastMetric>("points");
  const [filters, setFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);
  const [chartXMin, setChartXMin] = useState("");
  const [chartXMax, setChartXMax] = useState("");
  const [chartPointScope, setChartPointScope] = useState<"all" | "frontier">("all");

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
          manifest: playerData.manifest,
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
  const formAnchorByCode = useMemo(
    () => new Map(filteredPlayers.map((player) => [player.code, playerFormAnchor(player)])),
    [filteredPlayers],
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

  const effectiveChartXMin = useMemo(() => {
    if (chartXMin.trim() === "") return null;
    const value = Number(chartXMin);
    if (!Number.isFinite(value)) return null;
    return view === "upside_downside" ? value / 100 : value;
  }, [chartXMin, view]);

  const effectiveChartXMax = useMemo(() => {
    if (chartXMax.trim() === "") return null;
    const value = Number(chartXMax);
    if (!Number.isFinite(value)) return null;
    return view === "upside_downside" ? value / 100 : value;
  }, [chartXMax, view]);
  const invalidChartXRange =
    effectiveChartXMin != null &&
    effectiveChartXMax != null &&
    effectiveChartXMin > effectiveChartXMax;
  const invalidProbabilityBound =
    view === "upside_downside" &&
    [effectiveChartXMin, effectiveChartXMax].some(
      (value) => value != null && (value < 0 || value > 1),
    );
  const invalidChartXBounds = invalidChartXRange || invalidProbabilityBound;

  const xFocusedScatterPoints = useMemo(
    () =>
      invalidChartXBounds
        ? scatterPoints
        : scatterPoints.filter(
            (point) =>
              (effectiveChartXMin == null || point.x >= effectiveChartXMin) &&
              (effectiveChartXMax == null || point.x <= effectiveChartXMax),
          ),
    [scatterPoints, effectiveChartXMin, effectiveChartXMax, invalidChartXBounds],
  );

  const visibleScatterPoints = useMemo(
    () =>
      xFocusedScatterPoints.filter(
        (point) =>
          (view === "past_future" || chartPointScope === "all" || point.isFrontier === true),
      ),
    [xFocusedScatterPoints, view, chartPointScope],
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
  const horizontalInputAxisLabel = `${analytics?.xAxis.label ?? "X"}${
    view === "upside_downside" ? " (percent)" : ""
  }`;
  const formAnchorNote = formAnchorSummary(filteredPlayers);
  const insightFacts = analytics?.facts.map((fact) =>
    insightFact(
      fact.id,
      fact.id.startsWith("frontier")
        ? "frontier"
        : fact.id.startsWith("highest")
          ? "rank"
          : fact.id.startsWith("coverage") || fact.id === "scope"
            ? "coverage"
            : "comparison",
      fact.statement,
      fact.sources,
    ),
  ) ?? [];
  const insightCaveats = [
    "Price and ownership are deadline-vintage overlays.",
    "Cumulative probabilities are raw published values from the run's fixed start.",
    view === "past_future"
      ? "Observed form is the latest snapshot at static export and may post-date the selected forecast vintage. It is reporting context only, not a vintage-aligned input or causal comparison."
      : "Pareto-frontier membership is an exploration aid and does not establish optimality.",
  ];

  const changeRun = (nextRunId: string) => {
    setRunId(nextRunId);
    const nextRun = state.runs.find((run) => run.run_id === nextRunId);
    setGwTo(nextRun?.gw_to ?? null);
    setChartXMin("");
    setChartXMax("");
    setChartPointScope("all");
  };

  const resetFilters = () => {
    setFilters(INITIAL_PLAYER_FILTERS);
    setChartXMin("");
    setChartXMax("");
    setChartPointScope("all");
  };

  const changeFilters = (nextFilters: PlayerFilters) => {
    if (nextFilters.formWindow !== filters.formWindow) {
      setChartXMin("");
      setChartXMax("");
    }
    setFilters(nextFilters);
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
                if (value) {
                  setView(value as PlayerAnalyticsView);
                  setChartXMin("");
                  setChartXMax("");
                  setChartPointScope("all");
                }
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

            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <span>Cumulative horizon</span>
              <Select
                value={String(effectiveGwTo)}
                onValueChange={(value) => {
                  setGwTo(Number(value));
                  setChartXMin("");
                  setChartXMax("");
                }}
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
                <Select
                  value={pastMetric}
                  onValueChange={(value) => {
                    setPastMetric(value as PastMetric);
                    setChartXMin("");
                    setChartXMax("");
                  }}
                >
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

            <div className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
              <span>
                Horizontal range ({analytics?.xAxis.label ?? "X"}
                {view === "upside_downside" ? ", %" : ""})
              </span>
              <Input
                type="number"
                inputMode="decimal"
                min={view === "upside_downside" ? 0 : undefined}
                max={view === "upside_downside" ? 100 : undefined}
                step={view === "upside_downside" ? 0.1 : "any"}
                placeholder="min"
                aria-label={`Minimum horizontal chart value · ${horizontalInputAxisLabel}`}
                aria-invalid={invalidChartXBounds}
                className="h-8 w-20"
                value={chartXMin}
                onChange={(event) => setChartXMin(event.target.value)}
              />
              <span>to</span>
              <Input
                type="number"
                inputMode="decimal"
                min={view === "upside_downside" ? 0 : undefined}
                max={view === "upside_downside" ? 100 : undefined}
                step={view === "upside_downside" ? 0.1 : "any"}
                placeholder="max"
                aria-label={`Maximum horizontal chart value · ${horizontalInputAxisLabel}`}
                aria-invalid={invalidChartXBounds}
                className="h-8 w-20"
                value={chartXMax}
                onChange={(event) => setChartXMax(event.target.value)}
              />
              {invalidChartXBounds && (
                <span role="alert" className="text-xs text-destructive">
                  {invalidProbabilityBound
                    ? "Probability bounds must be between 0% and 100%. Horizontal bounds are ignored."
                    : "Min must not exceed max. Horizontal bounds are ignored."}
                </span>
              )}
            </div>

            {view !== "past_future" && (
              <ToggleGroup
                type="single"
                value={chartPointScope}
                onValueChange={(value) => {
                  if (value) setChartPointScope(value as "all" | "frontier");
                }}
                variant="outline"
                aria-label="Chart point scope"
              >
                <ToggleGroupItem value="all">All players</ToggleGroupItem>
                <ToggleGroupItem value="frontier">Efficient frontier only</ToggleGroupItem>
              </ToggleGroup>
            )}
          </div>

          <PlayerFiltersBar filters={filters} onChange={changeFilters} teams={teams} />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">
              The horizon always starts at the vintage's fixed GW{selectedRun.gw_from}.
              {view === "past_future" ? ` ${formAnchorNote}` : ""}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={resetFilters}
              aria-label="Clear player analytics filters"
            >
              <RotateCcw className="size-3.5" aria-hidden />
              Clear filters
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Horizontal min/max and efficient-frontier focus only tighten the visible plot domain.
            Enter values in the active X-axis units shown above. The exact-values table, frontier
            membership, filters, and insight summary still use every eligible published point.
          </p>
        </div>
      </FilterPanel>

      {analytics && (
        <>
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(22rem,0.7fr)]">
            <AnalyticsScatter
              title={PLAYER_ANALYTICS_VIEW_LABEL[view]}
              description={VIEW_DESCRIPTION[view]}
              points={visibleScatterPoints}
              xAxis={{
                label: analytics.xAxis.label,
                direction: analytics.xAxis.direction,
                format: (value) => axisTick(view, "x", value),
                bounds:
                  view === "upside_downside"
                    ? { min: 0, max: 1 }
                    : view === "differential"
                      ? { min: 0, max: 100 }
                      : view === "value"
                        ? { min: 0 }
                        : pastMetric === "points"
                          ? undefined
                          : { min: 0 },
              }}
              yAxis={{
                label: analytics.yAxis.label,
                direction: analytics.yAxis.direction,
                format: (value) => axisTick(view, "y", value),
                bounds: view === "upside_downside" ? { min: 0, max: 1 } : { min: 0 },
              }}
              vintageLabel={vintageLabel}
              horizonLabel={horizonLabel}
              emptyMessage={
                analytics.eligibleCount === 0
                  ? "No players match the current filters."
                  : scatterPoints.length > 0 && visibleScatterPoints.length === 0
                    ? "No plotted player reaches the current chart focus."
                  : "Every filtered player is missing at least one selected axis value."
              }
            />
            <InsightSummaryPanel
              items={insightFacts}
              caveats={insightCaveats}
              remote={{
                page: "player_analytics",
                provenance: publishedInsightProvenance(state.manifest, {
                  ...selectedRun,
                  as_of: selectedRun.as_of ?? exactRunPlayers[0]?.as_of,
                }),
                scope: compactInsightScope({
                  gw_from: selectedRun.gw_from,
                  gw_to: effectiveGwTo,
                  position: playerPositionScope(filters.position),
                  team_code: filters.teamCode === "all" ? undefined : Number(filters.teamCode),
                  view,
                  form_window: formWindowScope(filters.formWindow),
                  threshold: view === "upside_downside" ? haulThreshold : undefined,
                  min_price_tenths: minPriceTenthsScope(filters.minPrice),
                  max_price_tenths: maxPriceTenthsScope(filters.maxPrice),
                  min_avg_minutes_l5: minAverageMinutesScope(filters.minMinutes),
                  availability: filters.availability,
                  past_metric: playerPastMetricScope(view, pastMetric),
                }),
                localScopeKey: JSON.stringify({
                  runId: selectedRun.run_id,
                  gwTo: effectiveGwTo,
                  view,
                  haulThreshold,
                  pastMetric,
                  filters,
                }),
              }}
            />

          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
            <p>
              {analytics.plotted.length} plotted · {analytics.omittedCount} not plotted of{" "}
              {analytics.eligibleCount} filtered players. {visibleScatterPoints.length} currently
              shown in the chart; null axis values are omitted, never zero.
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
              {view !== "past_future" && <span>outlined = efficient frontier (Pareto)</span>}
            </div>
          </div>

          <section className="rounded-lg border bg-card p-3" aria-labelledby="player-values-title">
            <h2 id="player-values-title" className="mb-2 text-sm font-semibold">
              Exact eligible values
            </h2>
            <Table
              aria-label={`Player analytics exact eligible values · ${PLAYER_ANALYTICS_VIEW_LABEL[view]}`}
            >
              <TableHeader>
                <TableRow>
                  <TableHead>Player</TableHead>
                  <TableHead>Team</TableHead>
                  <TableHead>Position</TableHead>
                  <TableHead>{analytics.xAxis.label}</TableHead>
                  <TableHead>{analytics.yAxis.label}</TableHead>
                  {view === "past_future" && <TableHead>Observed form anchor</TableHead>}
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
                    {view === "past_future" && (
                      <TableCell>{formAnchorByCode.get(row.code) ?? "unavailable"}</TableCell>
                    )}
                    <TableCell>
                      {view === "past_future" ? "Context only" : row.isFrontier ? "Yes" : "No"}
                    </TableCell>
                  </TableRow>
                ))}
                {!analytics.plotted.length && (
                  <TableRow>
                    <TableCell
                      colSpan={view === "past_future" ? 7 : 6}
                      className="text-center text-muted-foreground"
                    >
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
