import { useEffect, useMemo, useState } from "react";
import { AnalyticsScatter, type AnalyticsScatterPoint } from "@/components/AnalyticsScatter";
import { FilterPanel } from "@/components/FilterPanel";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import { VintageSelect } from "@/components/VintageSelect";
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
import { loadFixtureMatrix, loadNextGw } from "@/data/load";
import type { DashboardManifest, NextGwPlan, TeamRecord, WindowLabel } from "@/data/types";
import { WINDOW_LABELS } from "@/data/types";
import {
  TEAM_ANALYTICS_CAVEATS,
  buildTeamAnalyticsPlot,
  buildTeamAnalyticsRows,
  buildTeamInsightFacts,
  type TeamAnalyticsVenue,
  type TeamAnalyticsView,
  type TeamPastMetric,
} from "@/lib/teamAnalytics";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";
import {
  compactInsightScope,
  formWindowScope,
  insightFact,
  publishedInsightProvenance,
  teamPastMetricScope,
} from "@/lib/insights";

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
      teams: TeamRecord[];
      plans: NextGwPlan[];
      runs: AnalyticsRun[];
      manifest: DashboardManifest | null;
      defaultRunId: string;
    };

type ChartExtent = "all" | "frontier";

const FORM_LABELS: Record<WindowLabel, string> = {
  last_3: "Last 3",
  last_5: "Last 5",
  last_10: "Last 10",
  season_to_date: "Season to date",
};

const PAST_METRIC_LABELS: Record<TeamPastMetric, string> = {
  "xg-for": "xG for / match",
  "goals-for": "Goals for / match",
  xgc: "xGC / match",
  "goals-against": "Goals against / match",
};

const fmt = (value: number | null | undefined, digits = 6) =>
  value == null ? "—" : value.toFixed(digits);

function derivedRuns(teams: readonly TeamRecord[]): AnalyticsRun[] {
  const runs = new Map<string, AnalyticsRun>();
  for (const team of teams) {
    const gws = team.fixtures.map((fixture) => fixture.gw);
    const current = runs.get(team.run_id);
    const from = gws.length ? Math.min(...gws) : current?.gw_from ?? 1;
    const to = gws.length ? Math.max(...gws) : current?.gw_to ?? from;
    runs.set(team.run_id, {
      run_id: team.run_id,
      season: team.season,
      gw_from: current ? Math.min(current.gw_from, from) : from,
      gw_to: current ? Math.max(current.gw_to, to) : to,
      as_of: current?.as_of ?? team.as_of,
    });
  }
  return [...runs.values()].sort((left, right) => left.run_id.localeCompare(right.run_id));
}

const gwOptions = (from: number, to: number) =>
  Array.from({ length: Math.max(0, to - from + 1) }, (_, index) => from + index);

function chartTitle(view: TeamAnalyticsView, pastMetric: TeamPastMetric): string {
  if (view === "environment") return "Two-sided club environment";
  if (view === "attack-floor") return "Attacking opportunity with defensive floor";
  return `Past ${PAST_METRIC_LABELS[pastMetric]} vs future model context`;
}

function chartDescription(view: TeamAnalyticsView): string {
  if (view === "past-future") {
    return "Context-only comparison of a directly published latest-at-export observed form rate with future modelled lambdas. It is not vintage-aligned; no frontier or buy/avoid claim is made.";
  }
  if (view === "environment") {
    return "Lower expected goals against and higher expected goals for define the outlined Pareto frontier.";
  }
  return "Higher expected clean sheets and expected goals for define the outlined Pareto frontier.";
}

function chartReadingNote(view: TeamAnalyticsView): string {
  if (view === "environment") {
    return "Move up and left. No other club is as good or better on both axes and strictly better on one.";
  }
  if (view === "attack-floor") {
    return "Move up and right. No other club is as good or better on both axes and strictly better on one.";
  }
  return "No frontier is calculated here. Latest observed form is context beside the future forecast, not a buy or avoid signal.";
}

function chartAxisLabels(
  view: TeamAnalyticsView,
  pastMetric: TeamPastMetric,
): { x: string; y: string } {
  if (view === "environment") return { x: "Expected goals against", y: "Expected goals for" };
  if (view === "attack-floor") return { x: "Expected clean sheets", y: "Expected goals for" };
  const x = {
    "xg-for": "Past xG / match",
    "goals-for": "Past goals / match",
    xgc: "Past xGC / match",
    "goals-against": "Past goals against / match",
  }[pastMetric];
  const defence = pastMetric === "xgc" || pastMetric === "goals-against";
  return { x, y: defence ? "Future expected goals against" : "Future expected goals for" };
}

function shortRunId(runId: string): string {
  return runId.length > 12 ? `${runId.slice(0, 8)}…` : runId;
}

function numericBound(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function TeamAnalyticsPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [gwFrom, setGwFrom] = useState(1);
  const [gwTo, setGwTo] = useState(1);
  const [venue, setVenue] = useState<TeamAnalyticsVenue>("all");
  const [view, setView] = useState<TeamAnalyticsView>("environment");
  const [chartExtent, setChartExtent] = useState<ChartExtent>("all");
  const [xMinimum, setXMinimum] = useState("");
  const [xMaximum, setXMaximum] = useState("");
  const [formWindow, setFormWindow] = useState<WindowLabel>("last_5");
  const [pastMetric, setPastMetric] = useState<TeamPastMetric>("xg-for");

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadFixtureMatrix(), loadNextGw()])
      .then(([fixtureData, nextGw]) => {
        if (cancelled) return;
        const runs = fixtureData.manifest?.runs?.length
          ? fixtureData.manifest.runs.map((run) => ({
              run_id: run.run_id,
              season: run.season,
              gw_from: run.gw_from,
              gw_to: run.gw_to,
              as_of: run.as_of,
            }))
          : derivedRuns(fixtureData.teams);
        const defaultRun = defaultVintageRunId(
          runs,
          nextGw.plans,
          fixtureData.manifest?.runs.at(-1)?.run_id ?? null,
        );
        const selected = runs.find((run) => run.run_id === defaultRun) ?? runs[0];
        setState({
          status: "ready",
          teams: fixtureData.teams,
          plans: nextGw.plans,
          runs,
          manifest: fixtureData.manifest,
          defaultRunId: selected?.run_id ?? "",
        });
        setRunId(selected?.run_id ?? null);
        if (selected) {
          setGwFrom(selected.gw_from);
          setGwTo(selected.gw_to);
        }
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

  const selectedRun =
    state.status === "ready"
      ? state.runs.find((run) => run.run_id === (runId ?? state.defaultRunId)) ?? null
      : null;
  const activeRunId = selectedRun?.run_id ?? "";
  const scope = useMemo(
    () => ({
      runId: activeRunId,
      season: selectedRun?.season ?? "",
      gwFrom,
      gwTo,
      venue,
      formWindow,
    }),
    [activeRunId, formWindow, gwFrom, gwTo, selectedRun?.season, venue],
  );
  const analytics = useMemo(
    () =>
      state.status === "ready"
        ? buildTeamAnalyticsRows(state.teams, scope)
        : { rows: [], fixtureRows: 0, fallbackRows: 0 },
    [scope, state],
  );
  const plot = useMemo(
    () => buildTeamAnalyticsPlot(analytics.rows, view, pastMetric),
    [analytics.rows, pastMetric, view],
  );
  const facts = useMemo(
    () => buildTeamInsightFacts(analytics, plot, scope),
    [analytics, plot, scope],
  );
  const frontierCodes = useMemo(
    () => new Set(plot.frontier.map((row) => row.teamCode)),
    [plot.frontier],
  );
  const plottedCodes = useMemo(
    () => new Set(plot.plotted.map((point) => point.row.teamCode)),
    [plot.plotted],
  );
  const tableRows = useMemo(
    () =>
      [...analytics.rows].sort(
        (left, right) =>
          Number(frontierCodes.has(right.teamCode)) - Number(frontierCodes.has(left.teamCode)) ||
          left.teamCode - right.teamCode,
      ),
    [analytics.rows, frontierCodes],
  );
  const scatterPoints: AnalyticsScatterPoint[] = useMemo(
    () =>
      plot.plotted.map((point) => ({
        id: point.row.teamCode,
        label: point.row.teamName,
        x: point.x,
        y: point.y,
        xDisplay: point.x.toFixed(6),
        yDisplay: point.y.toFixed(6),
        isFrontier: point.isFrontier,
        radius: 5 + Math.min(point.row.fixtureCount, 4),
        color: point.row.fallbackFixtureCount ? "#f97316" : "#2563eb",
        groupLabel: `${point.row.fixtureCount} modelled fixture${
          point.row.fixtureCount === 1 ? "" : "s"
        }; ${point.row.fallbackFixtureCount} Stage A fallback row${
          point.row.fallbackFixtureCount === 1 ? "" : "s"
        }`,
      })),
    [plot.plotted],
  );
  const xMinimumValue = numericBound(xMinimum);
  const xMaximumValue = numericBound(xMaximum);
  const xRangeActive = xMinimumValue != null || xMaximumValue != null;
  const xRangeValid =
    xMinimumValue == null || xMaximumValue == null || xMinimumValue <= xMaximumValue;
  const xFocusedScatterPoints = useMemo(
    () =>
      !xRangeActive || !xRangeValid
        ? scatterPoints
        : scatterPoints.filter(
            (point) =>
              (xMinimumValue == null || point.x >= xMinimumValue) &&
              (xMaximumValue == null || point.x <= xMaximumValue),
          ),
    [scatterPoints, xMaximumValue, xMinimumValue, xRangeActive, xRangeValid],
  );
  const frontierOnly = chartExtent === "frontier" && plot.axes.showFrontier;
  const visibleScatterPoints = useMemo(
    () =>
      frontierOnly
        ? xFocusedScatterPoints.filter((point) => point.isFrontier === true)
        : xFocusedScatterPoints,
    [frontierOnly, xFocusedScatterPoints],
  );
  const xHiddenPoints = scatterPoints.length - xFocusedScatterPoints.length;
  const chartIsFiltered = frontierOnly || xHiddenPoints > 0;
  const resetChartXFocus = () => {
    setXMinimum("");
    setXMaximum("");
  };

  if (state.status === "loading") {
    return (
      <p role="status" className="p-6 text-muted-foreground">
        Loading team analytics…
      </p>
    );
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Team analytics</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">
          {state.message}
        </p>
      </div>
    );
  }
  if (!state.runs.length || !state.teams.length || !selectedRun) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">Team analytics</h1>
        <p className="mt-3 text-sm text-muted-foreground">
          No recorded forecast vintage has modelled team-fixture rows to analyse.
        </p>
      </div>
    );
  }

  const options = vintageOptions(state.runs, state.plans);
  const selectedVintageLabel = `${selectedRun.run_id} · ${selectedRun.season}`;
  const horizonLabel = `GW${gwFrom}-${gwTo} · ${venue} venue · ${analytics.fixtureRows} modelled team-fixture rows · axes fit ${frontierOnly ? "efficient frontier" : xHiddenPoints ? "horizontal focus" : "all plotted clubs"}`;
  const insightFacts = [
    insightFact(
      "coverage.fixture_rows",
      "coverage",
      `Scope: GW${gwFrom}-${gwTo}, ${venue} venue, ${facts.fixtureRows} modelled fixture rows; ${facts.omittedTeams} club${facts.omittedTeams === 1 ? " is" : "s are"} omitted from the plot.`,
      ["fixture_matrix.json"],
    ),
    insightFact(
      "coverage.fallback_rows",
      "coverage",
      `${facts.fallbackRows} fixture rows use the league-average fallback.`,
      ["fixture_matrix.json"],
    ),
    ...(facts.frontier.length ? [
      insightFact(
        "frontier.clubs",
        "frontier",
        `Pareto-efficient clubs (${facts.frontier.length}): ${facts.frontier.slice(0, 5).map((team) => team.teamName).join(", ")}${facts.frontier.length > 5 ? ", and others" : ""}.`,
        ["fixture_matrix.json"],
      ),
    ] : []),
    ...(facts.highestAttack ? [
      insightFact(
        "rank.highest_attack_total",
        "rank",
        `${facts.highestAttack.teamName} has the highest expected goals for (${facts.highestAttack.value.toFixed(2)}).`,
        ["fixture_matrix.json"],
      ),
    ] : []),
    ...(facts.lowestConceding ? [
      insightFact(
        "rank.lowest_defence_total",
        "rank",
        `${facts.lowestConceding.teamName} has the lowest expected goals against (${facts.lowestConceding.value.toFixed(2)}).`,
        ["fixture_matrix.json"],
      ),
    ] : []),
    ...(facts.highestExpectedCleanSheets ? [
      insightFact(
        "rank.highest_expected_clean_sheets",
        "rank",
        `Highest expected clean-sheet count: ${facts.highestExpectedCleanSheets.teamName} (${facts.highestExpectedCleanSheets.value.toFixed(2)}).`,
        ["fixture_matrix.json"],
      ),
    ] : []),
  ];
  const insightCaveats = [
    "Stage A lambdas are relative fixture signals, not calibrated current-season scoring levels.",
    "Expected clean sheets is a summed expected count, not a probability of at least one clean sheet.",
    "The efficient frontier is direct-value Pareto geometry, not a Markowitz EV-versus-standard-deviation frontier; no team PMF or standard deviation is regenerated in the browser.",
    view === "past-future"
      ? "Observed form is the latest snapshot at static export and may post-date the selected forecast vintage. It is reporting context only, not a vintage-aligned input or causal comparison."
      : "Pareto-frontier membership compares only the displayed axes and does not establish optimality.",
  ];

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Team analytics</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Compare published attack, defence, and clean-sheet signals from one forecast. These
            are shortlists, not an optimal squad or a guarantee.
          </p>
        </div>
        <VintageSelect
          options={options}
          value={selectedRun.run_id}
          onChange={(nextRunId) => {
            const next = state.runs.find((run) => run.run_id === nextRunId);
            if (!next) return;
            setRunId(nextRunId);
            setGwFrom(next.gw_from);
            setGwTo(next.gw_to);
            resetChartXFocus();
          }}
        />
      </div>

      <FilterPanel>
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            type="single"
            value={view}
            onValueChange={(value) => {
              if (!value) return;
              setView(value as TeamAnalyticsView);
              resetChartXFocus();
            }}
            variant="outline"
            aria-label="Team analytics view"
          >
            <ToggleGroupItem value="environment">Attack &amp; defence</ToggleGroupItem>
            <ToggleGroupItem value="attack-floor">Attack + defensive floor</ToggleGroupItem>
            <ToggleGroupItem value="past-future">Past vs future</ToggleGroupItem>
          </ToggleGroup>
          <ToggleGroup
            type="single"
            value={venue}
            onValueChange={(value) => {
              if (!value) return;
              setVenue(value as TeamAnalyticsVenue);
              resetChartXFocus();
            }}
            variant="outline"
            aria-label="Venue filter"
          >
            <ToggleGroupItem value="all">All</ToggleGroupItem>
            <ToggleGroupItem value="home">Home</ToggleGroupItem>
            <ToggleGroupItem value="away">Away</ToggleGroupItem>
          </ToggleGroup>
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>Modelled GWs</span>
            <Select
              value={String(gwFrom)}
              onValueChange={(value) => {
                setGwFrom(Math.min(Number(value), gwTo));
                resetChartXFocus();
              }}
            >
              <SelectTrigger size="sm" className="w-18" aria-label="From modelled gameweek">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {gwOptions(selectedRun.gw_from, gwTo).map((gw) => (
                  <SelectItem key={gw} value={String(gw)}>
                    GW{gw}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <span>to</span>
            <Select
              value={String(gwTo)}
              onValueChange={(value) => {
                setGwTo(Number(value));
                resetChartXFocus();
              }}
            >
              <SelectTrigger size="sm" className="w-18" aria-label="To modelled gameweek">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {gwOptions(gwFrom, selectedRun.gw_to).map((gw) => (
                  <SelectItem key={gw} value={String(gw)}>
                    GW{gw}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {view === "past-future" && (
            <>
              <Select
                value={formWindow}
                onValueChange={(value) => {
                  setFormWindow(value as WindowLabel);
                  resetChartXFocus();
                }}
              >
                <SelectTrigger size="sm" className="w-36" aria-label="Past form window">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {WINDOW_LABELS.map((window) => (
                    <SelectItem key={window} value={window}>
                      {FORM_LABELS[window]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <Select
                value={pastMetric}
                onValueChange={(value) => {
                  setPastMetric(value as TeamPastMetric);
                  resetChartXFocus();
                }}
              >
                <SelectTrigger size="sm" className="w-48" aria-label="Past metric">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(Object.keys(PAST_METRIC_LABELS) as TeamPastMetric[]).map((metric) => (
                    <SelectItem key={metric} value={metric}>
                      {PAST_METRIC_LABELS[metric]}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </>
          )}
          {plot.axes.showFrontier && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Chart extent</span>
              <Select
                value={chartExtent}
                onValueChange={(value) => setChartExtent(value as ChartExtent)}
              >
                <SelectTrigger size="sm" className="w-48" aria-label="Chart extent">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All plotted clubs</SelectItem>
                  <SelectItem value="frontier">Efficient frontier only</SelectItem>
                </SelectContent>
              </Select>
              <span className="text-xs">Axes fit the selected points</span>
            </div>
          )}
          <fieldset className="flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
            <legend className="sr-only">Horizontal chart focus</legend>
            <span>Horizontal focus</span>
            <label className="flex items-center gap-1">
              <span className="text-xs">Min</span>
              <input
                type="number"
                step="any"
                value={xMinimum}
                onChange={(event) => setXMinimum(event.target.value)}
                aria-label={`X minimum · ${plot.axes.xLabel}`}
                aria-invalid={!xRangeValid}
                className="h-8 w-24 rounded-md border bg-background px-2 tabular-nums text-foreground"
              />
            </label>
            <label className="flex items-center gap-1">
              <span className="text-xs">Max</span>
              <input
                type="number"
                step="any"
                value={xMaximum}
                onChange={(event) => setXMaximum(event.target.value)}
                aria-label={`X maximum · ${plot.axes.xLabel}`}
                aria-invalid={!xRangeValid}
                className="h-8 w-24 rounded-md border bg-background px-2 tabular-nums text-foreground"
              />
            </label>
            <button
              type="button"
              onClick={resetChartXFocus}
              disabled={!xRangeActive}
              className="h-8 rounded-md border bg-background px-3 text-xs text-foreground disabled:opacity-40"
            >
              Reset X
            </button>
            <span className="max-w-md text-xs">
              Bounds use {plot.axes.xLabel}. They filter chart points only; frontier membership
              and the exact table stay based on the full selected axis-complete club population.
            </span>
          </fieldset>
          {!xRangeValid && (
            <p role="alert" className="text-xs text-destructive">
              X minimum must not exceed X maximum. The chart remains unfiltered.
            </p>
          )}
          {view === "past-future" && (
            <p className="text-xs text-muted-foreground">
              Observed form is latest at static export, not frozen at the selected forecast
              vintage, and may post-date an older run. Each exact row shows its own form anchor.
            </p>
          )}
        </div>
      </FilterPanel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(22rem,0.7fr)]">
        <div className="space-y-2">
          <AnalyticsScatter
            title={chartTitle(view, pastMetric)}
            description={chartDescription(view)}
            readingNote={chartReadingNote(view)}
            points={visibleScatterPoints}
            xAxis={{
              label: plot.axes.xLabel,
              displayLabel: chartAxisLabels(view, pastMetric).x,
              direction: plot.axes.xDirection,
              format: (value) => value.toFixed(2),
              bounds: { min: 0 },
            }}
            yAxis={{
              label: plot.axes.yLabel,
              displayLabel: chartAxisLabels(view, pastMetric).y,
              direction: plot.axes.yDirection,
              format: (value) => value.toFixed(2),
              bounds: { min: 0 },
            }}
            vintageLabel={selectedVintageLabel}
            horizonLabel={horizonLabel}
            vintageDisplayLabel={`${selectedRun.season} · ${shortRunId(selectedRun.run_id)}`}
            horizonDisplayLabel={`GW${gwFrom}-${gwTo} · ${venue} · ${analytics.fixtureRows} fixtures`}
            medianX={chartIsFiltered ? null : plot.medianX}
            medianY={chartIsFiltered ? null : plot.medianY}
            emptyMessage={
              frontierOnly && xRangeActive && xRangeValid
                ? "No efficient-frontier club falls inside the selected horizontal focus. Reset X, widen the bounds, or show all clubs; the exact table remains unchanged."
                : xHiddenPoints
                ? "No eligible clubs fall inside the selected horizontal focus. Reset X or widen the bounds; the exact table remains unchanged."
                : "No clubs have complete axis values in this modelled scope. Nulls and blank weeks are omitted, never read as zero."
            }
          />

          <div
            className="flex flex-wrap gap-4 text-xs text-muted-foreground"
            aria-label="Chart legend"
          >
            <span>
              <span className="mr-1 inline-block size-2.5 rounded-full bg-blue-600" />
              No Stage A fallback row
            </span>
            <span>
              <span className="mr-1 inline-block size-2.5 rounded-full bg-orange-500" />
              Contains Stage A fallback row
            </span>
            {plot.axes.showFrontier && (
              <span>
                Outline = Pareto frontier
              </span>
            )}
            <span>Bubble size = modelled fixture count</span>
            <span>{plot.omitted.length} team(s) not plotted because an axis is null</span>
            {plot.axes.showFrontier && (
              <span>
                Chart shows {visibleScatterPoints.length} of {scatterPoints.length} eligible club(s);
                the exact table retains every club.
              </span>
            )}
            <span>
              Horizontal focus hides {xHiddenPoints} eligible club(s); full-population frontier
              membership is unchanged.
            </span>
          </div>
        </div>

        <InsightSummaryPanel
          items={insightFacts}
          caveats={insightCaveats}
          remote={{
            page: "team_analytics",
            provenance: publishedInsightProvenance(state.manifest, selectedRun),
            scope: compactInsightScope({
              gw_from: gwFrom,
              gw_to: gwTo,
              view,
              venue,
              form_window: formWindowScope(formWindow),
              past_metric: teamPastMetricScope(view, pastMetric),
            }),
            localScopeKey: JSON.stringify({
              runId: selectedRun.run_id,
              gwFrom,
              gwTo,
              venue,
              view,
              formWindow,
              pastMetric,
            }),
          }}
        />
      </div>

      <section className="space-y-2" aria-labelledby="team-analytics-exact-values">
        <h2 id="team-analytics-exact-values" className="text-sm font-semibold">
          Exact club-environment values
        </h2>
        <Table aria-label="Exact team analytics values">
          <TableHeader>
            <TableRow>
              <TableHead>Club</TableHead>
              <TableHead>Fixtures</TableHead>
              <TableHead>λ for total / fixture</TableHead>
              <TableHead>λ against total / fixture</TableHead>
              <TableHead>Expected CS count / fixture</TableHead>
              {view === "past-future" && <TableHead>{PAST_METRIC_LABELS[pastMetric]}</TableHead>}
              {view === "past-future" && <TableHead>Observed form anchor</TableHead>}
              <TableHead>Fallbacks</TableHead>
              <TableHead>Chart status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {tableRows.map((row) => (
              <TableRow key={row.teamCode}>
                <TableCell>
                  <span className="font-medium">{row.teamName}</span>{" "}
                  <span className="text-xs text-muted-foreground">{row.shortName}</span>
                </TableCell>
                <TableCell className="tabular-nums">{row.fixtureCount}</TableCell>
                <TableCell className="tabular-nums">
                  {fmt(row.lambdaForTotal)} / {fmt(row.lambdaForPerFixture)}
                </TableCell>
                <TableCell className="tabular-nums">
                  {fmt(row.lambdaAgainstTotal)} / {fmt(row.lambdaAgainstPerFixture)}
                </TableCell>
                <TableCell
                  className="tabular-nums"
                  title="Sum of per-fixture clean-sheet probabilities; expected count, not a probability"
                >
                  {fmt(row.expectedCleanSheets)} / {fmt(row.expectedCleanSheetsPerFixture)}
                </TableCell>
                {view === "past-future" && (
                  <>
                    <TableCell className="tabular-nums">
                      {fmt(
                        pastMetric === "xg-for"
                          ? row.past.xgForPerMatch
                          : pastMetric === "goals-for"
                            ? row.past.goalsForPerMatch
                            : pastMetric === "xgc"
                              ? row.past.xgcPerMatch
                              : row.past.goalsAgainstPerMatch,
                      )}
                    </TableCell>
                    <TableCell>{row.formLabel ?? "unavailable"}</TableCell>
                  </>
                )}
                <TableCell className="tabular-nums">{row.fallbackFixtureCount}</TableCell>
                <TableCell>
                  {!plottedCodes.has(row.teamCode)
                    ? "Not plotted — missing axis"
                    : frontierCodes.has(row.teamCode)
                      ? "Efficient frontier (Pareto)"
                      : view === "past-future"
                        ? "Context point"
                        : "Dominated environment"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </section>

      <div className="space-y-1 text-xs text-muted-foreground">
        {TEAM_ANALYTICS_CAVEATS.map((caveat) => <p key={caveat}>{caveat}</p>)}
        <p>
          Both DGW legs count separately. A blank week contributes no fixture. Current
          schedule-only rows beyond this vintage never enter this page.
        </p>
      </div>
    </div>
  );
}
