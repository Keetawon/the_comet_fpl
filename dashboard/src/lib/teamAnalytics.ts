import type { TeamRecord, WindowLabel } from "@/data/types";
import {
  classifyPareto,
  type ParetoDirection,
  type ParetoPoint,
} from "@/lib/pareto";

export type TeamAnalyticsView = "environment" | "attack-floor" | "past-future";
export type TeamAnalyticsVenue = "all" | "home" | "away";
export type TeamPastMetric = "xg-for" | "goals-for" | "xgc" | "goals-against";

export interface TeamAnalyticsScope {
  runId: string;
  season: string;
  gwFrom: number;
  gwTo: number;
  venue: TeamAnalyticsVenue;
  formWindow: WindowLabel;
}

export interface TeamPastValues {
  xgForPerMatch: number | null;
  goalsForPerMatch: number | null;
  xgcPerMatch: number | null;
  goalsAgainstPerMatch: number | null;
}

export interface TeamAnalyticsRow {
  runId: string;
  season: string;
  asOf: string;
  teamCode: number;
  teamName: string;
  shortName: string;
  fixtureCount: number;
  lambdaForTotal: number | null;
  lambdaAgainstTotal: number | null;
  expectedCleanSheets: number | null;
  lambdaForPerFixture: number | null;
  lambdaAgainstPerFixture: number | null;
  expectedCleanSheetsPerFixture: number | null;
  fallbackFixtureCount: number;
  formLabel: string | null;
  past: TeamPastValues;
}

export interface TeamAnalyticsResult {
  rows: TeamAnalyticsRow[];
  fixtureRows: number;
  fallbackRows: number;
}

export interface TeamAnalyticsAxes {
  xLabel: string;
  yLabel: string;
  xDirection: ParetoDirection | "explanatory";
  yDirection: ParetoDirection | "explanatory";
  showFrontier: boolean;
}

export interface TeamAnalyticsPlottedRow {
  row: TeamAnalyticsRow;
  x: number;
  y: number;
  isFrontier: boolean;
}

export interface TeamAnalyticsPlot {
  axes: TeamAnalyticsAxes;
  plotted: TeamAnalyticsPlottedRow[];
  omitted: TeamAnalyticsRow[];
  frontier: TeamAnalyticsRow[];
  medianX: number | null;
  medianY: number | null;
}

export interface TeamDirectFact {
  teamCode: number;
  teamName: string;
  value: number;
}

export interface TeamInsightFacts {
  scope: {
    runId: string;
    season: string;
    gwFrom: number;
    gwTo: number;
    venue: TeamAnalyticsVenue;
  };
  plottedTeams: number;
  omittedTeams: number;
  fixtureRows: number;
  fallbackRows: number;
  frontier: { teamCode: number; teamName: string }[];
  highestAttack: TeamDirectFact | null;
  lowestAttack: TeamDirectFact | null;
  lowestConceding: TeamDirectFact | null;
  highestConceding: TeamDirectFact | null;
  highestExpectedCleanSheets: TeamDirectFact | null;
  caveats: readonly string[];
}

export const TEAM_ANALYTICS_CAVEATS = [
  "Stage A lambdas are relative fixture signals, not calibrated current-season scoring levels.",
  "Expected clean sheets is a summed expected count, not P(at least one clean sheet).",
  "Club environment does not choose a player or account for price, minutes, set pieces, transfers, or the three-player club cap.",
] as const;

const finiteOrNull = (value: number | null | undefined): number | null =>
  value != null && Number.isFinite(value) ? value : null;

function completeSum<T>(items: readonly T[], read: (item: T) => number | null): number | null {
  if (!items.length) return null;
  let total = 0;
  for (const item of items) {
    const value = finiteOrNull(read(item));
    if (value == null) return null;
    total += value;
  }
  return total;
}

const perFixture = (total: number | null, fixtureCount: number): number | null =>
  total == null || fixtureCount === 0 ? null : total / fixtureCount;

/** Aggregate only modelled fixture rows from one exact vintage and selected scope. */
export function buildTeamAnalyticsRows(
  teams: readonly TeamRecord[],
  scope: TeamAnalyticsScope,
): TeamAnalyticsResult {
  const selected = teams
    .filter((team) => team.run_id === scope.runId && team.season === scope.season)
    .sort((left, right) => left.team_code - right.team_code);
  const rows = selected.map((team): TeamAnalyticsRow => {
    const fixtures = team.fixtures.filter(
      (fixture) =>
        fixture.gw >= scope.gwFrom &&
        fixture.gw <= scope.gwTo &&
        (scope.venue === "all" ||
          (scope.venue === "home" ? fixture.was_home === true : fixture.was_home === false)),
    );
    const fixtureCount = fixtures.length;
    const lambdaForTotal = completeSum(fixtures, (fixture) => fixture.lambda_for);
    const lambdaAgainstTotal = completeSum(fixtures, (fixture) => fixture.lambda_against);
    const expectedCleanSheets = completeSum(
      fixtures,
      (fixture) => fixture.probability_clean_sheet,
    );
    const form = team.form?.windows[scope.formWindow] ?? null;
    return {
      runId: team.run_id,
      season: team.season,
      asOf: team.as_of,
      teamCode: team.team_code,
      teamName: team.team_name,
      shortName: team.short_name,
      fixtureCount,
      lambdaForTotal,
      lambdaAgainstTotal,
      expectedCleanSheets,
      lambdaForPerFixture: perFixture(lambdaForTotal, fixtureCount),
      lambdaAgainstPerFixture: perFixture(lambdaAgainstTotal, fixtureCount),
      expectedCleanSheetsPerFixture: perFixture(expectedCleanSheets, fixtureCount),
      fallbackFixtureCount: fixtures.filter(
        (fixture) => fixture.stage_a_league_average_team,
      ).length,
      formLabel: team.form ? `${team.form.season} GW${team.form.as_at_gw}` : null,
      past: {
        xgForPerMatch: finiteOrNull(form?.team_xg_per_match),
        goalsForPerMatch: finiteOrNull(form?.goals_for_per_match),
        xgcPerMatch: finiteOrNull(form?.team_xgc_per_match),
        goalsAgainstPerMatch: finiteOrNull(form?.goals_against_per_match),
      },
    };
  });
  return {
    rows,
    fixtureRows: rows.reduce((sum, row) => sum + row.fixtureCount, 0),
    fallbackRows: rows.reduce((sum, row) => sum + row.fallbackFixtureCount, 0),
  };
}

export function teamAnalyticsAxes(
  view: TeamAnalyticsView,
  pastMetric: TeamPastMetric,
): TeamAnalyticsAxes {
  if (view === "environment") {
    return {
      xLabel: "Summed expected goals against (λ against)",
      yLabel: "Summed expected goals for (λ for)",
      xDirection: "minimize",
      yDirection: "maximize",
      showFrontier: true,
    };
  }
  if (view === "attack-floor") {
    return {
      xLabel: "Expected clean sheets (summed expected count)",
      yLabel: "Summed expected goals for (λ for)",
      xDirection: "maximize",
      yDirection: "maximize",
      showFrontier: true,
    };
  }
  const defence = pastMetric === "xgc" || pastMetric === "goals-against";
  const pastLabel = {
    "xg-for": "Past team xG per match",
    "goals-for": "Past goals for per match",
    xgc: "Past team xGC per match",
    "goals-against": "Past goals against per match",
  }[pastMetric];
  return {
    xLabel: pastLabel,
    yLabel: defence
      ? "Future summed expected goals against (λ against)"
      : "Future summed expected goals for (λ for)",
    xDirection: "explanatory",
    yDirection: "explanatory",
    showFrontier: false,
  };
}

function pastValue(row: TeamAnalyticsRow, metric: TeamPastMetric): number | null {
  return {
    "xg-for": row.past.xgForPerMatch,
    "goals-for": row.past.goalsForPerMatch,
    xgc: row.past.xgcPerMatch,
    "goals-against": row.past.goalsAgainstPerMatch,
  }[metric];
}

function coordinates(
  row: TeamAnalyticsRow,
  view: TeamAnalyticsView,
  pastMetric: TeamPastMetric,
): { x: number | null; y: number | null } {
  if (view === "environment") {
    return { x: row.lambdaAgainstTotal, y: row.lambdaForTotal };
  }
  if (view === "attack-floor") {
    return { x: row.expectedCleanSheets, y: row.lambdaForTotal };
  }
  const defence = pastMetric === "xgc" || pastMetric === "goals-against";
  return {
    x: pastValue(row, pastMetric),
    y: defence ? row.lambdaAgainstTotal : row.lambdaForTotal,
  };
}

interface TeamParetoPoint extends ParetoPoint {
  id: number;
  row: TeamAnalyticsRow;
}

function median(values: number[]): number | null {
  if (!values.length) return null;
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2
    ? ordered[middle]
    : (ordered[middle - 1] + ordered[middle]) / 2;
}

export function buildTeamAnalyticsPlot(
  rows: readonly TeamAnalyticsRow[],
  view: TeamAnalyticsView,
  pastMetric: TeamPastMetric,
): TeamAnalyticsPlot {
  const axes = teamAnalyticsAxes(view, pastMetric);
  const points: TeamParetoPoint[] = rows.map((row) => ({
    id: row.teamCode,
    row,
    ...coordinates(row, view, pastMetric),
  }));
  const classified = classifyPareto(points, {
    // Past-vs-future uses this classifier only for finite/null partitioning; its result is
    // never exposed as a frontier. The chart axes remain explicitly explanatory.
    x: axes.xDirection === "explanatory" ? "maximize" : axes.xDirection,
    y: axes.yDirection === "explanatory" ? "maximize" : axes.yDirection,
  });
  const plotted = classified.plotted.map(({ point, isFrontier }) => ({
    row: point.row,
    x: point.x as number,
    y: point.y as number,
    isFrontier: axes.showFrontier && isFrontier,
  }));
  return {
    axes,
    plotted,
    omitted: classified.omitted.map((point) => point.row),
    frontier: axes.showFrontier
      ? classified.frontier.map((point) => point.row)
      : [],
    medianX: median(plotted.map((point) => point.x)),
    medianY: median(plotted.map((point) => point.y)),
  };
}

function directFact(
  rows: readonly TeamAnalyticsRow[],
  read: (row: TeamAnalyticsRow) => number | null,
  direction: "minimum" | "maximum",
): TeamDirectFact | null {
  const eligible = rows
    .map((row) => ({ row, value: finiteOrNull(read(row)) }))
    .filter((entry): entry is { row: TeamAnalyticsRow; value: number } => entry.value != null)
    .sort((left, right) => {
      const valueOrder =
        direction === "minimum"
          ? left.value - right.value
          : right.value - left.value;
      return valueOrder || left.row.teamCode - right.row.teamCode;
    });
  const best = eligible[0];
  return best
    ? { teamCode: best.row.teamCode, teamName: best.row.teamName, value: best.value }
    : null;
}

export function buildTeamInsightFacts(
  result: TeamAnalyticsResult,
  plot: TeamAnalyticsPlot,
  scope: TeamAnalyticsScope,
): TeamInsightFacts {
  return {
    scope: {
      runId: scope.runId,
      season: scope.season,
      gwFrom: scope.gwFrom,
      gwTo: scope.gwTo,
      venue: scope.venue,
    },
    plottedTeams: plot.plotted.length,
    omittedTeams: plot.omitted.length,
    fixtureRows: result.fixtureRows,
    fallbackRows: result.fallbackRows,
    frontier: plot.frontier
      .map((row) => ({ teamCode: row.teamCode, teamName: row.teamName }))
      .sort((left, right) => left.teamCode - right.teamCode),
    highestAttack: directFact(result.rows, (row) => row.lambdaForTotal, "maximum"),
    lowestAttack: directFact(result.rows, (row) => row.lambdaForTotal, "minimum"),
    lowestConceding: directFact(
      result.rows,
      (row) => row.lambdaAgainstTotal,
      "minimum",
    ),
    highestConceding: directFact(
      result.rows,
      (row) => row.lambdaAgainstTotal,
      "maximum",
    ),
    highestExpectedCleanSheets: directFact(
      result.rows,
      (row) => row.expectedCleanSheets,
      "maximum",
    ),
    caveats: TEAM_ANALYTICS_CAVEATS,
  };
}
