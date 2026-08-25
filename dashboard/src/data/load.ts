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
  PlayerHorizon,
  PlayerHorizonsData,
  PlayerHorizonsRecord,
  PlayerRecord,
  SummaryData,
  TeamRecord,
} from "./types";
import { PLAYER_HORIZON_FIELDS } from "./types";

const BASE: string = import.meta.env.VITE_DATA_BASE ?? "/data";

// Session-level cache: players.json is ~15 MB, so every page fetches it through this
// map and the browser tab parses it exactly once. A failed fetch is evicted so it can
// be retried.
const cache = new Map<string, Promise<unknown>>();
const DASHBOARD_SCHEMA_VERSION = 4;
const HORIZON_VALUE_DECIMAL_PLACES = 6;
const PROBABILITY_TOLERANCE = 10 ** -HORIZON_VALUE_DECIMAL_PLACES;
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

function readModelObject(
  payload: unknown,
  filename: string,
  schema: string,
): Record<string, unknown> {
  if (!payload || typeof payload !== "object") {
    throw new Error(`invalid ${filename}: expected a schema-v4 object`);
  }
  const candidate = payload as Record<string, unknown>;
  if (
    candidate.schema !== schema ||
    candidate.json_schema_version !== DASHBOARD_SCHEMA_VERSION
  ) {
    throw new Error(
      `unsupported ${filename} schema: expected ${schema} version 4; ` +
        "republish the dashboard read models",
    );
  }
  return candidate;
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
    const payload = await fetchJson<unknown>("manifest.json");
    return readModelObject(
      payload,
      "manifest.json",
      "fpl.dashboard-read-models",
    ) as unknown as DashboardManifest;
  } catch {
    return null;
  }
}

export async function loadFixtureMatrix(): Promise<FixtureMatrixData> {
  const [payload, manifest] = await Promise.all([
    fetchJson<unknown>("fixture_matrix.json"),
    loadManifest(),
  ]);
  const candidate = readModelObject(
    payload,
    "fixture_matrix.json",
    "fpl.dashboard-fixture-matrix",
  );
  if (!Array.isArray(candidate.teams)) {
    throw new Error("invalid fixture_matrix.json: teams must be an array");
  }
  const teams = candidate.teams as TeamRecord[];
  const schedule = candidate.schedule as Partial<FixtureScheduleOverlay> | undefined;
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
    fetchJson<unknown>("players.json"),
    loadManifest(),
  ]);
  const candidate = readModelObject(payload, "players.json", "fpl.dashboard-players");
  if (!Array.isArray(candidate.players)) {
    throw new Error("invalid players.json: players must be an array");
  }
  return { players: candidate.players as PlayerRecord[], manifest };
}

function sameArray<T extends string | number>(value: unknown, expected: readonly T[]): boolean {
  return (
    Array.isArray(value) &&
    value.length === expected.length &&
    value.every((item, index) => item === expected[index])
  );
}

function hasExactKeys(value: object, expected: readonly string[]): boolean {
  const keys = Object.keys(value).sort();
  return sameArray(keys, [...expected].sort());
}

/** Load only precomputed cumulative summaries; this boundary never accepts a PMF. */
export async function loadPlayerHorizons(): Promise<PlayerHorizonsData> {
  const payload = await fetchJson<unknown>("player_horizons.json");
  if (!payload || typeof payload !== "object") {
    throw new Error("invalid player_horizons.json: expected a schema-v4 object");
  }
  const candidate = payload as Record<string, unknown>;
  const semantics = candidate.semantics as Record<string, unknown> | undefined;
  const thresholds = semantics?.thresholds as Record<string, unknown> | undefined;
  if (
    !hasExactKeys(payload, [
      "schema",
      "json_schema_version",
      "semantics",
      "horizon_fields",
      "players",
    ]) ||
    candidate.schema !== "fpl.dashboard-player-horizons" ||
    candidate.json_schema_version !== DASHBOARD_SCHEMA_VERSION ||
    !semantics ||
    !hasExactKeys(semantics, [
      "grain",
      "cumulative_from",
      "distribution_combination",
      "availability",
      "thresholds",
      "value_decimal_places",
      "probability_boundary_policy",
    ]) ||
    !thresholds ||
    !hasExactKeys(thresholds, ["p_le", "p_ge"]) ||
    !sameArray(semantics.grain, ["run_id", "season", "code", "gw_to"]) ||
    semantics.cumulative_from !== "dim_forecast_run.gw_from" ||
    semantics.distribution_combination !== "independent-gameweek-convolution-v1" ||
    semantics.availability !== "raw-model-distribution-unadjusted" ||
    semantics.value_decimal_places !== HORIZON_VALUE_DECIMAL_PLACES ||
    semantics.probability_boundary_policy !== "preserve-exact-zero-one-v1" ||
    !sameArray(thresholds.p_le, [2]) ||
    !sameArray(thresholds.p_ge, [2, 4, 6, 10, 15]) ||
    !sameArray(candidate.horizon_fields, PLAYER_HORIZON_FIELDS) ||
    !Array.isArray(candidate.players)
  ) {
    throw new Error(
      "unsupported player_horizons.json schema: expected version 4 cumulative raw-model " +
        "probabilities; republish the dashboard read models",
    );
  }

  const probabilities = ["p_le_2", "p_ge_2", "p_ge_4", "p_ge_6", "p_ge_10", "p_ge_15"] as const;
  const identities = new Set<string>();
  const endpointsByRun = new Map<string, string>();
  const players: PlayerHorizonsRecord[] = [];
  for (const [playerIndex, playerValue] of candidate.players.entries()) {
    const player = playerValue as Record<string, unknown>;
    if (
      !player ||
      typeof player !== "object" ||
      !hasExactKeys(player, ["run_id", "season", "code", "horizons"]) ||
      typeof player.run_id !== "string" ||
      !player.run_id ||
      typeof player.season !== "string" ||
      !player.season ||
      typeof player.code !== "number" ||
      !Number.isInteger(player.code) ||
      player.code <= 0 ||
      !Array.isArray(player.horizons) ||
      player.horizons.length === 0
    ) {
      throw new Error(`invalid player_horizons.json: player ${playerIndex} has no valid identity/horizons`);
    }
    const identity = JSON.stringify([player.run_id, player.season, player.code]);
    if (identities.has(identity)) {
      throw new Error(`invalid player_horizons.json: repeated player ${identity}`);
    }
    identities.add(identity);
    let previousGw = 0;
    let previousXp = -Infinity;
    let previousLe2 = Infinity;
    const previousGe = new Map<(typeof probabilities)[number], number>();
    const horizons: PlayerHorizon[] = [];
    for (const wireHorizon of player.horizons) {
      if (
        !Array.isArray(wireHorizon) ||
        wireHorizon.length !== PLAYER_HORIZON_FIELDS.length ||
        !wireHorizon.every(
          (value) =>
            Number.isFinite(value) &&
            hasAtMostDecimalPlaces(value, HORIZON_VALUE_DECIMAL_PLACES),
        )
      ) {
        throw new Error(
          `invalid player_horizons.json: ${String(player.run_id)}/${String(player.code)} horizon must be an eight-number six-decimal tuple`,
        );
      }
      const [gw_to, xp, p_le_2, p_ge_2, p_ge_4, p_ge_6, p_ge_10, p_ge_15] = wireHorizon;
      const horizon: PlayerHorizon = {
        gw_to,
        xp,
        p_le_2,
        p_ge_2,
        p_ge_4,
        p_ge_6,
        p_ge_10,
        p_ge_15,
      };
      if (
        !Number.isInteger(horizon.gw_to) ||
        horizon.gw_to <= previousGw ||
        (previousGw > 0 && horizon.gw_to !== previousGw + 1) ||
        horizon.xp < 0 ||
        horizon.xp < previousXp - PROBABILITY_TOLERANCE ||
        horizon.p_le_2 > previousLe2 + PROBABILITY_TOLERANCE
      ) {
        throw new Error(
          `invalid player_horizons.json: ${player.run_id}/${player.code} horizons are not ordered cumulative values`,
        );
      }
      for (const key of probabilities) {
        const value = horizon[key];
        if (
          !Number.isFinite(value) ||
          value < 0 ||
          value > 1 ||
          (key !== "p_le_2" &&
            value < (previousGe.get(key) ?? -Infinity) - PROBABILITY_TOLERANCE)
        ) {
          throw new Error(
            `invalid player_horizons.json: ${player.run_id}/${player.code} ${key} is not a cumulative probability`,
          );
        }
        if (key !== "p_le_2") previousGe.set(key, value);
      }
      if (
        !(
          horizon.p_ge_2 + PROBABILITY_TOLERANCE >= horizon.p_ge_4 &&
          horizon.p_ge_4 + PROBABILITY_TOLERANCE >= horizon.p_ge_6 &&
          horizon.p_ge_6 + PROBABILITY_TOLERANCE >= horizon.p_ge_10 &&
          horizon.p_ge_10 + PROBABILITY_TOLERANCE >= horizon.p_ge_15
        )
      ) {
        throw new Error(
          `invalid player_horizons.json: ${player.run_id}/${player.code} threshold tails are not ordered`,
        );
      }
      if (horizon.p_le_2 + horizon.p_ge_2 < 1 - PROBABILITY_TOLERANCE) {
        throw new Error(
          `invalid player_horizons.json: ${player.run_id}/${player.code} violates inclusive score-2 overlap`,
        );
      }
      previousGw = horizon.gw_to;
      previousXp = horizon.xp;
      previousLe2 = horizon.p_le_2;
      horizons.push(horizon);
    }
    const runKey = JSON.stringify([player.run_id, player.season]);
    const endpoints = horizons.map((horizon) => horizon.gw_to).join(",");
    const expectedEndpoints = endpointsByRun.get(runKey);
    if (expectedEndpoints != null && endpoints !== expectedEndpoints) {
      throw new Error(
        `invalid player_horizons.json: ${runKey} players do not share exact endpoints`,
      );
    }
    endpointsByRun.set(runKey, endpoints);
    players.push({
      run_id: player.run_id as string,
      season: player.season as string,
      code: player.code as number,
      horizons,
    });
  }
  return {
    schema: "fpl.dashboard-player-horizons",
    json_schema_version: DASHBOARD_SCHEMA_VERSION,
    semantics: semantics as unknown as PlayerHorizonsData["semantics"],
    horizon_fields: PLAYER_HORIZON_FIELDS,
    players,
  };
}

function hasAtMostDecimalPlaces(value: number, decimalPlaces: number): boolean {
  return Number(value.toFixed(decimalPlaces)) === value;
}

export async function loadNextGw(): Promise<{ plans: NextGwPlan[] }> {
  const payload = await fetchJson<unknown>("next_gw.json");
  const candidate = readModelObject(payload, "next_gw.json", "fpl.dashboard-next-gw");
  if (!Array.isArray(candidate.plans)) {
    throw new Error("invalid next_gw.json schema v4: plans must be an array");
  }
  for (const [index, rawPlan] of candidate.plans.entries()) {
    if (!rawPlan || typeof rawPlan !== "object") {
      throw new Error(`invalid next_gw.json schema v4: plan ${index} must be an object`);
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
        `invalid next_gw.json schema v4: plan ${runId} has no valid plan_kind; ` +
          "ownership is never inferred from model architecture",
      );
    }
    if (typeof plan.display_label !== "string" || !plan.display_label.trim()) {
      throw new Error(
        `invalid next_gw.json schema v4: plan ${runId} has no display_label`,
      );
    }
    if (!plan.policy || typeof plan.policy !== "object") {
      throw new Error(`invalid next_gw.json schema v4: plan ${runId} has no policy`);
    }
  }
  return { plans: candidate.plans as NextGwPlan[] };
}

export async function loadSummary(): Promise<SummaryData> {
  const payload = await fetchJson<unknown>("summary.json");
  return readModelObject(
    payload,
    "summary.json",
    "fpl.dashboard-summary",
  ) as unknown as SummaryData;
}

export async function loadForecastVsActual(): Promise<ForecastVsActualData> {
  const payload = await fetchJson<unknown>("forecast_vs_actual.json");
  return readModelObject(
    payload,
    "forecast_vs_actual.json",
    "fpl.dashboard-forecast-vs-actual",
  ) as unknown as ForecastVsActualData;
}

export async function loadOptimizerAudit(): Promise<OptimizerAuditData> {
  const payload = await fetchJson<unknown>("optimizer_audit.json");
  return readModelObject(
    payload,
    "optimizer_audit.json",
    "fpl.dashboard-optimizer-audit",
  ) as unknown as OptimizerAuditData;
}
