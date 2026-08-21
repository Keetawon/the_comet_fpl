// Static read-model data layer. The dashboard reads ONLY these JSON files -- it never
// queries DuckDB and never reads Parquet. Point VITE_DATA_BASE at a copy of the published
// read-model directory (default: the files copied into public/data by the dev setup in
// README.md).

import type {
  DashboardManifest,
  FixtureScheduleOverlay,
  ForecastVsActualData,
  NextGwPlan,
  OptimizerAuditData,
  PlanKind,
  PlayerRecord,
  SummaryData,
  TeamRecord,
} from "./types";

const BASE: string = import.meta.env.VITE_DATA_BASE ?? "/data";

// Session-level cache: players.json is ~15 MB, so every page fetches it through this
// map and the browser tab parses it exactly once. A failed fetch is evicted so it can
// be retried.
const cache = new Map<string, Promise<unknown>>();
const NEXT_GW_SCHEMA_VERSION = 3;
const PLAN_KINDS = new Set<PlanKind>([
  "platform_default",
  "platform_diagnostic",
  "user_custom",
]);

function fetchJson<T>(name: string): Promise<T> {
  const hit = cache.get(name);
  if (hit) return hit as Promise<T>;
  const pending = (async () => {
    const response = await fetch(`${BASE}/${name}`);
    if (!response.ok) {
      throw new Error(
        `could not load ${BASE}/${name} (${response.status}); generate the read models ` +
          `first -- see dashboard/README.md`,
      );
    }
    return (await response.json()) as T;
  })();
  cache.set(name, pending);
  pending.catch(() => cache.delete(name));
  return pending as Promise<T>;
}

export interface FixtureMatrixData {
  teams: TeamRecord[];
  schedule: FixtureScheduleOverlay;
  manifest: DashboardManifest | null;
  easeIndexFormulaVersion: string;
}

export interface PlayersData {
  players: PlayerRecord[];
  manifest: DashboardManifest | null;
}

/** The manifest is optional metadata; every record repeats run_id/as_of anyway. */
async function loadManifest(): Promise<DashboardManifest | null> {
  try {
    return await fetchJson<DashboardManifest>("manifest.json");
  } catch {
    return null;
  }
}

export async function loadFixtureMatrix(): Promise<FixtureMatrixData> {
  const [payload, manifest] = await Promise.all([
    fetchJson<{ teams: TeamRecord[]; schedule?: unknown }>("fixture_matrix.json"),
    loadManifest(),
  ]);
  const teams = payload.teams;
  const schedule = payload.schedule as Partial<FixtureScheduleOverlay> | undefined;
  if (
    (schedule?.schema_version !== 1 && schedule?.schema_version !== 2) ||
    schedule?.semantics !== "current_at_export_not_forecast_vintage" ||
    typeof schedule.export_created_at !== "string" ||
    typeof schedule.database_sha256 !== "string" ||
    !Array.isArray(schedule.teams)
  ) {
    throw new Error(
      "invalid fixture_matrix.json: current official schedule overlay is missing; " +
        "republish the dashboard read models",
    );
  }
  const versions = new Set(teams.flatMap((t) => t.fixtures.map((f) => f.ease_index_formula_version)));
  return {
    teams,
    schedule: schedule as FixtureScheduleOverlay,
    manifest,
    easeIndexFormulaVersion: versions.size === 1 ? [...versions][0] : [...versions].join(", "),
  };
}

export async function loadPlayers(): Promise<PlayersData> {
  const [payload, manifest] = await Promise.all([
    fetchJson<{ players: PlayerRecord[] }>("players.json"),
    loadManifest(),
  ]);
  return { players: payload.players, manifest };
}

export async function loadNextGw(): Promise<{ plans: NextGwPlan[] }> {
  const payload = await fetchJson<unknown>("next_gw.json");
  if (!payload || typeof payload !== "object") {
    throw new Error("invalid next_gw.json: expected a schema-v3 object");
  }
  const candidate = payload as {
    json_schema_version?: unknown;
    plans?: unknown;
  };
  if (candidate.json_schema_version !== NEXT_GW_SCHEMA_VERSION) {
    throw new Error(
      "unsupported next_gw.json schema: expected version 3 with explicit plan ownership; " +
        "republish the dashboard read models",
    );
  }
  if (!Array.isArray(candidate.plans)) {
    throw new Error("invalid next_gw.json schema v3: plans must be an array");
  }
  for (const [index, rawPlan] of candidate.plans.entries()) {
    if (!rawPlan || typeof rawPlan !== "object") {
      throw new Error(`invalid next_gw.json schema v3: plan ${index} must be an object`);
    }
    const plan = rawPlan as {
      optimizer_run_id?: unknown;
      plan_kind?: unknown;
      display_label?: unknown;
      policy?: unknown;
    };
    const runId =
      typeof plan.optimizer_run_id === "string" && plan.optimizer_run_id
        ? plan.optimizer_run_id
        : `index ${index}`;
    if (typeof plan.plan_kind !== "string" || !PLAN_KINDS.has(plan.plan_kind as PlanKind)) {
      throw new Error(
        `invalid next_gw.json schema v3: plan ${runId} has no valid plan_kind; ` +
          "ownership is never inferred from model architecture",
      );
    }
    if (typeof plan.display_label !== "string" || !plan.display_label.trim()) {
      throw new Error(
        `invalid next_gw.json schema v3: plan ${runId} has no display_label`,
      );
    }
    if (!plan.policy || typeof plan.policy !== "object") {
      throw new Error(`invalid next_gw.json schema v3: plan ${runId} has no policy`);
    }
  }
  return { plans: candidate.plans as NextGwPlan[] };
}

export async function loadSummary(): Promise<SummaryData> {
  return fetchJson<SummaryData>("summary.json");
}

export async function loadForecastVsActual(): Promise<ForecastVsActualData> {
  return fetchJson<ForecastVsActualData>("forecast_vs_actual.json");
}

export async function loadOptimizerAudit(): Promise<OptimizerAuditData> {
  return fetchJson<OptimizerAuditData>("optimizer_audit.json");
}
