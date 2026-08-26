// Pure player deep-analytics view model. All probability values are selected from one exact
// schema-v4 cumulative endpoint; this module never adds, complements, or reconstructs them.

import type { PlayerHorizonIndex } from "@/lib/playerHorizons";
import { playerHorizon } from "@/lib/playerHorizons";
import type { PlayerHorizon, PlayerRecord, WindowLabel } from "@/data/types";
import { classifyPareto, type ParetoDirection } from "@/lib/pareto";

export type PlayerAnalyticsView =
  | "value"
  | "upside_downside"
  | "differential"
  | "past_future";

export type HaulThreshold = 6 | 10 | 15;
export type PastMetric = "points" | "xg_per_90" | "xa_per_90";

export interface PlayerAnalyticsConfig {
  runId: string;
  season: string;
  gwFrom: number;
  gwTo: number;
  view: PlayerAnalyticsView;
  haulThreshold: HaulThreshold;
  formWindow: WindowLabel;
  pastMetric: PastMetric;
}

export interface PlayerAnalyticsCandidate {
  id: number;
  code: number;
  webName: string;
  position: string;
  teamCode: number;
  teamShortName: string;
  ownership: number | null;
  x: number | null;
  y: number | null;
  horizon: PlayerHorizon | null;
}

export interface PlayerAnalyticsRow extends Omit<PlayerAnalyticsCandidate, "x" | "y"> {
  x: number;
  y: number;
  isFrontier: boolean;
}

export interface PlayerInsightFact {
  id: string;
  kind: "scope" | "forecast" | "observed" | "coverage" | "caveat";
  statement: string;
  sources: readonly ("players.json" | "player_horizons.json")[];
}

export interface PlayerAnalyticsResult {
  config: PlayerAnalyticsConfig;
  eligibleCount: number;
  plotted: PlayerAnalyticsRow[];
  omitted: PlayerAnalyticsCandidate[];
  omittedCount: number;
  xAxis: { label: string; direction: ParetoDirection | "explanatory" };
  yAxis: { label: string; direction: "maximize" };
  facts: PlayerInsightFact[];
  caveats: string[];
}

export const PLAYER_ANALYTICS_VIEW_LABEL: Record<PlayerAnalyticsView, string> = {
  value: "Value frontier",
  upside_downside: "Upside / downside",
  differential: "Differential",
  past_future: "Past vs future",
};

export const PAST_METRIC_LABEL: Record<PastMetric, string> = {
  points: "Observed points under 2026/27 rules",
  xg_per_90: "Observed xG/90",
  xa_per_90: "Observed xA/90",
};

const FORM_WINDOW_SHORT: Record<WindowLabel, string> = {
  last_3: "last 3",
  last_5: "last 5",
  last_10: "last 10",
  season_to_date: "season to date",
};

function finiteOrNull(value: number | null | undefined): number | null {
  return value != null && Number.isFinite(value) ? value : null;
}

function upside(horizon: PlayerHorizon | null, threshold: HaulThreshold): number | null {
  if (horizon == null) return null;
  if (threshold === 6) return finiteOrNull(horizon.p_ge_6);
  if (threshold === 10) return finiteOrNull(horizon.p_ge_10);
  return finiteOrNull(horizon.p_ge_15);
}

function observedValue(
  player: PlayerRecord,
  window: WindowLabel,
  metric: PastMetric,
): number | null {
  const form = player.form?.windows[window];
  if (form == null) return null;
  if (metric === "points") return finiteOrNull(form.points_under_rules_2026_27);
  if (metric === "xg_per_90") return finiteOrNull(form.expected_goals_per_90);
  return finiteOrNull(form.expected_assists_per_90);
}

function axes(config: PlayerAnalyticsConfig): Pick<PlayerAnalyticsResult, "xAxis" | "yAxis"> {
  if (config.view === "value") {
    return {
      xAxis: { label: "Deadline price (£m)", direction: "minimize" },
      yAxis: { label: `Cumulative xP · GW${config.gwFrom}-${config.gwTo}`, direction: "maximize" },
    };
  }
  if (config.view === "upside_downside") {
    return {
      xAxis: { label: "P(total ≤ 2)", direction: "minimize" },
      yAxis: { label: `P(total ≥ ${config.haulThreshold})`, direction: "maximize" },
    };
  }
  if (config.view === "differential") {
    return {
      xAxis: { label: "Deadline ownership (%)", direction: "minimize" },
      yAxis: { label: `Cumulative xP · GW${config.gwFrom}-${config.gwTo}`, direction: "maximize" },
    };
  }
  return {
    xAxis: {
      label: `${PAST_METRIC_LABEL[config.pastMetric]} · ${FORM_WINDOW_SHORT[config.formWindow]}`,
      direction: "explanatory",
    },
    yAxis: { label: `Cumulative xP · GW${config.gwFrom}-${config.gwTo}`, direction: "maximize" },
  };
}

function candidate(
  player: PlayerRecord,
  horizonIndex: PlayerHorizonIndex,
  config: PlayerAnalyticsConfig,
): PlayerAnalyticsCandidate {
  const horizon = playerHorizon(
    horizonIndex,
    config.runId,
    config.season,
    player.code,
    config.gwTo,
  );
  let x: number | null;
  let y: number | null;
  if (config.view === "value") {
    x = player.now_cost == null ? null : finiteOrNull(player.now_cost / 10);
    y = finiteOrNull(horizon?.xp);
  } else if (config.view === "upside_downside") {
    x = finiteOrNull(horizon?.p_le_2);
    y = upside(horizon, config.haulThreshold);
  } else if (config.view === "differential") {
    x = finiteOrNull(player.selected_by_percent);
    y = finiteOrNull(horizon?.xp);
  } else {
    x = observedValue(player, config.formWindow, config.pastMetric);
    y = finiteOrNull(horizon?.xp);
  }
  return {
    id: player.code,
    code: player.code,
    webName: player.web_name,
    position: player.position,
    teamCode: player.team_code,
    teamShortName: player.team_short_name,
    ownership: finiteOrNull(player.selected_by_percent),
    x,
    y,
    horizon,
  };
}

function rowOrder(a: PlayerAnalyticsRow, b: PlayerAnalyticsRow): number {
  return (
    Number(b.isFrontier) - Number(a.isFrontier) ||
    b.y - a.y ||
    a.x - b.x ||
    a.code - b.code
  );
}

function factValue(config: PlayerAnalyticsConfig, axis: "x" | "y", value: number): string {
  if (config.view === "upside_downside") return `${(value * 100).toFixed(1)}%`;
  if (axis === "x" && config.view === "value") return `£${value.toFixed(1)}m`;
  if (axis === "x" && config.view === "differential") return `${value.toFixed(1)}%`;
  return String(value);
}

function factsFor(
  result: Omit<PlayerAnalyticsResult, "facts">,
): PlayerInsightFact[] {
  const { config, plotted, eligibleCount, omittedCount } = result;
  const facts: PlayerInsightFact[] = [
    {
      id: "scope",
      kind: "scope",
      statement: `${PLAYER_ANALYTICS_VIEW_LABEL[config.view]} uses vintage ${config.runId} and the exact fixed-start GW${config.gwFrom}-${config.gwTo} endpoint.`,
      sources: ["players.json", "player_horizons.json"],
    },
  ];
  const bestY = [...plotted].sort((a, b) => b.y - a.y || a.code - b.code)[0];
  if (bestY) {
    facts.push({
      id: `highest-y.${bestY.code}`,
      // The vertical axis is a future forecast in every view, including past-vs-future.
      kind: "forecast",
      statement: `${bestY.webName} has the highest plotted ${result.yAxis.label}: ${factValue(config, "y", bestY.y)}.`,
      sources: ["players.json", "player_horizons.json"],
    });
  }
  if (config.view !== "past_future") {
    const frontier = plotted.filter((row) => row.isFrontier).slice(0, 5);
    if (frontier.length) {
      facts.push({
        id: "frontier.members",
        kind: "forecast",
        statement: `Pareto frontier (${frontier.length}${plotted.filter((row) => row.isFrontier).length > frontier.length ? "+" : ""} shown): ${frontier.map((row) => row.webName).join(", ")}.`,
        sources: ["players.json", "player_horizons.json"],
      });
    }
  }
  facts.push({
    id: "coverage.omitted",
    kind: "coverage",
    statement: `${plotted.length} of ${eligibleCount} filtered players are plotted; ${omittedCount} are omitted because at least one selected axis value is unmeasured.`,
    sources: ["players.json", "player_horizons.json"],
  });
  return facts;
}

/**
 * Build one exact player-analytics view. `players` may contain many vintages; only the configured
 * run and season are eligible, preventing a caller from accidentally mixing repeated players.
 */
export function buildPlayerAnalytics(
  players: readonly PlayerRecord[],
  horizonIndex: PlayerHorizonIndex,
  config: PlayerAnalyticsConfig,
): PlayerAnalyticsResult {
  const exactPlayers = players.filter(
    (player) => player.run_id === config.runId && player.season === config.season,
  );
  const candidates = exactPlayers.map((player) => candidate(player, horizonIndex, config));
  let plotted: PlayerAnalyticsRow[];
  let omitted: PlayerAnalyticsCandidate[];
  const selectedAxes = axes(config);
  if (config.view === "past_future") {
    plotted = candidates
      .filter((point): point is PlayerAnalyticsCandidate & { x: number; y: number } =>
        point.x != null && point.y != null && Number.isFinite(point.x) && Number.isFinite(point.y),
      )
      .map((point) => ({ ...point, isFrontier: false }));
    omitted = candidates.filter(
      (point) => point.x == null || point.y == null || !Number.isFinite(point.x) || !Number.isFinite(point.y),
    );
  } else {
    const classification = classifyPareto(candidates, {
      x: selectedAxes.xAxis.direction as ParetoDirection,
      y: "maximize",
    });
    plotted = classification.plotted.map(({ point, isFrontier }) => ({
      ...point,
      x: point.x as number,
      y: point.y as number,
      isFrontier,
    }));
    omitted = classification.omitted;
  }
  plotted.sort(rowOrder);
  omitted.sort((a, b) => a.code - b.code);
  const partial: Omit<PlayerAnalyticsResult, "facts"> = {
    config,
    eligibleCount: candidates.length,
    plotted,
    omitted,
    omittedCount: omitted.length,
    ...selectedAxes,
    caveats: [
      "Price and ownership are deadline-vintage overlays.",
      "Cumulative probabilities are raw published model values from the run's fixed start; the reported availability multiplier is not applied.",
      config.view === "past_future"
        ? "Past form is observed and cumulative xP is a future forecast; the comparison is explanatory, not causal."
        : "Pareto-frontier membership is an exploration aid, not an optimal squad or transfer recommendation.",
    ],
  };
  return { ...partial, facts: factsFor(partial) };
}

/** User-facing exact value for the authoritative table. */
export function formatPlayerAnalyticsValue(
  config: PlayerAnalyticsConfig,
  axis: "x" | "y",
  value: number,
): string {
  if (config.view === "upside_downside") {
    return `${(value * 100).toFixed(2)}% (${value.toFixed(6)})`;
  }
  if (axis === "x" && config.view === "value") return `£${value.toFixed(1)}m`;
  if (axis === "x" && config.view === "differential") return `${value.toFixed(1)}%`;
  if (axis === "y") return value.toFixed(6);
  return String(value);
}
