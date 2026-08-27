import type { DashboardManifest, ForecastRun, WindowLabel } from "@/data/types";
import type {
  InsightDisplayScope,
} from "@/lib/planServer";

export type LocalInsightFactKind =
  | "published_scalar"
  | "allowed_sum"
  | "rank"
  | "frontier"
  | "coverage"
  | "comparison";

export type LocalInsightReadModel =
  | "manifest.json"
  | "summary.json"
  | "fixture_matrix.json"
  | "players.json"
  | "player_actuals.json"
  | "player_horizons.json"
  | "player_forecast_vs_actual.json"
  | "team_forecast_vs_actual.json";

export interface LocalInsightFact {
  id: string;
  kind: LocalInsightFactKind;
  statement: string;
  sourceReadModels: readonly LocalInsightReadModel[];
}

export interface InsightProvenance {
  manifestSha256: string;
  runId: string;
  season: string;
  asOf: string;
}

export interface InsightRunIdentity {
  run_id: string;
  season: string;
  as_of?: string | null;
  gw_from?: number;
  gw_to?: number;
}

const timezoneAware = (value: string) =>
  /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));

/** Bind one visible run to the exact published manifest that carried it. */
export function publishedInsightProvenance(
  manifest: DashboardManifest | null,
  run: InsightRunIdentity | null | undefined,
): InsightProvenance | null {
  if (manifest == null || run == null || !/^[0-9a-f]{64}$/.test(manifest.content_sha256)) {
    return null;
  }
  const published = manifest.runs.find(
    (candidate) =>
      candidate.run_id === run.run_id &&
      candidate.season === run.season &&
      (run.gw_from == null || candidate.gw_from === run.gw_from) &&
      (run.gw_to == null || candidate.gw_to === run.gw_to),
  );
  const asOf = run.as_of ?? published?.as_of;
  if (published == null || asOf == null || !timezoneAware(asOf)) return null;
  return {
    manifestSha256: manifest.content_sha256,
    runId: run.run_id,
    season: run.season,
    asOf,
  };
}

export function insightFact(
  id: string,
  kind: LocalInsightFactKind,
  statement: string,
  sourceReadModels: readonly LocalInsightReadModel[],
): LocalInsightFact {
  return { id, kind, statement, sourceReadModels };
}

/** Remove undefined keys so the wire scope contains only frozen optional fields. */
export function compactInsightScope(scope: InsightDisplayScope): InsightDisplayScope {
  return Object.fromEntries(
    Object.entries(scope).filter(([, value]) => value !== undefined),
  ) as InsightDisplayScope;
}

export function formWindowScope(window: WindowLabel): 3 | 5 | 10 | "season_to_date" {
  if (window === "last_3") return 3;
  if (window === "last_5") return 5;
  if (window === "last_10") return 10;
  return "season_to_date";
}

/** Preserve integer-tenths filter semantics for arbitrary decimal number-input values. */
export function minPriceTenthsScope(value: string): number | undefined {
  if (value === "") return undefined;
  const price = Number(value);
  return Number.isFinite(price) ? Math.ceil(price * 10) : undefined;
}

export function maxPriceTenthsScope(value: string): number | undefined {
  if (value === "") return undefined;
  const price = Number(value);
  return Number.isFinite(price) ? Math.floor(price * 10) : undefined;
}

export function minAverageMinutesScope(value: string): number | undefined {
  if (value === "") return undefined;
  const minutes = Number(value);
  return Number.isFinite(minutes) ? minutes : undefined;
}

export function playerPastMetricScope(
  view: InsightDisplayScope["view"],
  metric: "points" | "xg_per_90" | "xa_per_90",
): typeof metric | undefined {
  return view === "past_future" ? metric : undefined;
}

export function teamPastMetricScope(
  view: InsightDisplayScope["view"],
  metric: "xg-for" | "goals-for" | "xgc" | "goals-against",
): typeof metric | undefined {
  return view === "past-future" ? metric : undefined;
}

export function playerPositionScope(value: string): "all" | "GK" | "DEF" | "MID" | "FWD" {
  return value === "GK" || value === "DEF" || value === "MID" || value === "FWD"
    ? value
    : "all";
}

export function manifestRun(
  manifest: DashboardManifest | null,
  runId: string,
): ForecastRun | null {
  return manifest?.runs.find((run) => run.run_id === runId) ?? null;
}
