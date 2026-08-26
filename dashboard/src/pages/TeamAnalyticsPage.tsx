import { useEffect, useMemo, useState } from "react";
import { AnalyticsScatter, type AnalyticsScatterPoint } from "@/components/AnalyticsScatter";
import { FilterPanel } from "@/components/FilterPanel";
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
import type { NextGwPlan, TeamRecord, WindowLabel } from "@/data/types";
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

interface AnalyticsRun {
  run_id: string;
  season: string;
  gw_from: number;
  gw_to: number;
}

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      teams: TeamRecord[];
      plans: NextGwPlan[];
      runs: AnalyticsRun[];
      defaultRunId: string;
    };

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
    return "Context-only comparison of a directly published observed form rate with future modelled lambdas; no frontier or buy/avoid claim.";
  }
  return "Pareto frontier means nondominated club environments in this selected scope, not an optimal FPL squad.";
}

export function TeamAnalyticsPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [gwFrom, setGwFrom] = useState(1);
  const [gwTo, setGwTo] = useState(1);
  const [venue, setVenue] = useState<TeamAnalyticsVenue>("all");
  const [view, setView] = useState<TeamAnalyticsView>("environment");
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
  const horizonLabel = `GW${gwFrom}-${gwTo} · ${venue} venue · ${analytics.fixtureRows} modelled team-fixture rows`;
  const frontierLabel = facts.frontier.length
    ? facts.frontier.map((team) => team.teamName).join(", ")
    : "None (this view is explanatory or has no complete axes)";

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Team analytics</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Compare risk-aware club environments from one recorded forecast vintage. These are
            exposure shortlists, not optimal teams or guarantees.
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
          }}
        />
      </div>

      <FilterPanel>
        <div className="flex flex-wrap items-center gap-3">
          <ToggleGroup
            type="single"
            value={view}
            onValueChange={(value) => value && setView(value as TeamAnalyticsView)}
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
            onValueChange={(value) => value && setVenue(value as TeamAnalyticsVenue)}
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
              onValueChange={(value) => setGwFrom(Math.min(Number(value), gwTo))}
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
            <Select value={String(gwTo)} onValueChange={(value) => setGwTo(Number(value))}>
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
                onValueChange={(value) => setFormWindow(value as WindowLabel)}
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
                onValueChange={(value) => setPastMetric(value as TeamPastMetric)}
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
        </div>
      </FilterPanel>

      <AnalyticsScatter
        title={chartTitle(view, pastMetric)}
        description={chartDescription(view)}
        points={scatterPoints}
        xAxis={{
          label: plot.axes.xLabel,
          direction: plot.axes.xDirection,
          format: (value) => value.toFixed(2),
        }}
        yAxis={{
          label: plot.axes.yLabel,
          direction: plot.axes.yDirection,
          format: (value) => value.toFixed(2),
        }}
        vintageLabel={selectedVintageLabel}
        horizonLabel={horizonLabel}
        medianX={plot.medianX}
        medianY={plot.medianY}
        emptyMessage="No clubs have complete axis values in this modelled scope. Nulls and blank weeks are omitted, never read as zero."
      />

      <div className="flex flex-wrap gap-4 text-xs text-muted-foreground" aria-label="Chart legend">
        <span><span className="mr-1 inline-block size-2.5 rounded-full bg-blue-600" />No Stage A fallback row</span>
        <span><span className="mr-1 inline-block size-2.5 rounded-full bg-orange-500" />Contains Stage A fallback row</span>
        {plot.axes.showFrontier && <span>Heavy outline = Pareto-nondominated environment</span>}
        <span>Bubble size = modelled fixture count</span>
        <span>{plot.omitted.length} team(s) not plotted because an axis is null</span>
      </div>

      <section className="rounded-lg border p-4" aria-labelledby="team-insight-facts">
        <h2 id="team-insight-facts" className="text-sm font-semibold">
          Deterministic insight facts
        </h2>
        <p className="mt-1 text-xs text-muted-foreground">
          Direct sums, ranks, and display geometry only; no model quantity or probability is
          reconstructed here.
        </p>
        <ul className="mt-3 grid gap-2 text-sm md:grid-cols-2">
          <li>Scope: GW{facts.scope.gwFrom}-{facts.scope.gwTo}, {facts.scope.venue} venue, {facts.fixtureRows} modelled fixture rows.</li>
          <li>Exposure frontier: {frontierLabel}.</li>
          <li>Highest summed λ for: {facts.highestAttack ? `${facts.highestAttack.teamName} (${fmt(facts.highestAttack.value)})` : "—"}.</li>
          <li>Lowest summed λ against: {facts.lowestConceding ? `${facts.lowestConceding.teamName} (${fmt(facts.lowestConceding.value)})` : "—"}.</li>
          <li>Highest expected CS count: {facts.highestExpectedCleanSheets ? `${facts.highestExpectedCleanSheets.teamName} (${fmt(facts.highestExpectedCleanSheets.value)})` : "—"}.</li>
          <li>{facts.fallbackRows} Stage A fallback row(s); {facts.omittedTeams} team(s) omitted from the chart.</li>
        </ul>
      </section>

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
                <TableCell className="tabular-nums">{fmt(row.lambdaForTotal)} / {fmt(row.lambdaForPerFixture)}</TableCell>
                <TableCell className="tabular-nums">{fmt(row.lambdaAgainstTotal)} / {fmt(row.lambdaAgainstPerFixture)}</TableCell>
                <TableCell className="tabular-nums" title="Sum of per-fixture clean-sheet probabilities; expected count, not a probability">
                  {fmt(row.expectedCleanSheets)} / {fmt(row.expectedCleanSheetsPerFixture)}
                </TableCell>
                {view === "past-future" && (
                  <TableCell className="tabular-nums">
                    {fmt(
                      pastMetric === "xg-for"
                        ? row.past.xgForPerMatch
                        : pastMetric === "goals-for"
                          ? row.past.goalsForPerMatch
                          : pastMetric === "xgc"
                            ? row.past.xgcPerMatch
                            : row.past.goalsAgainstPerMatch,
                    )}{" "}
                    <span className="text-xs text-muted-foreground">{row.formLabel ?? "unavailable"}</span>
                  </TableCell>
                )}
                <TableCell className="tabular-nums">{row.fallbackFixtureCount}</TableCell>
                <TableCell>
                  {!plottedCodes.has(row.teamCode)
                    ? "Not plotted — missing axis"
                    : frontierCodes.has(row.teamCode)
                      ? "Pareto frontier"
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
