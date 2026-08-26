// Static read-model data layer. The dashboard reads ONLY these JSON files -- it never
// queries DuckDB and never reads Parquet. Point VITE_DATA_BASE at a copy of the published
// read-model directory (default: the files copied into public/data by the dev setup in
// README.md).

import type {
  DashboardManifest,
  FixtureScheduleOverlay,
  CleanSheetScoreBlock,
  ForecastAccuracyScoreBlock,
  NextGwPlan,
  OptimizerAuditData,
  PlanKind,
  PlayerForecastAccuracyRun,
  PlayerForecastCalibration,
  PlayerForecastCoverage,
  PlayerForecastObservation,
  PlayerForecastVsActualData,
  PlayerHorizon,
  PlayerHorizonsData,
  PlayerHorizonsRecord,
  PlayerRecord,
  SummaryData,
  TeamAccuracyScoreSet,
  TeamForecastAccuracyRun,
  TeamForecastCalibration,
  TeamForecastCoverage,
  TeamForecastObservation,
  TeamForecastVsActualData,
  TeamRecord,
} from "./types";
import { PLAYER_HORIZON_FIELDS } from "./types";

const BASE: string = import.meta.env.VITE_DATA_BASE ?? "/data";

// Session-level cache: players.json is ~15 MB, so every page fetches it through this
// map and the browser tab parses it exactly once. A failed fetch is evicted so it can
// be retried.
const cache = new Map<string, Promise<unknown>>();
const DASHBOARD_SCHEMA_VERSION = 5;
const FORECAST_ACCURACY_SCHEMA_VERSION = 5;
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
    throw new Error(`invalid ${filename}: expected a schema-v5 object`);
  }
  const candidate = payload as Record<string, unknown>;
  if (
    candidate.schema !== schema ||
    candidate.json_schema_version !== DASHBOARD_SCHEMA_VERSION
  ) {
    throw new Error(
      `unsupported ${filename} schema: expected ${schema} version ${DASHBOARD_SCHEMA_VERSION}; ` +
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
export async function loadDashboardManifest(): Promise<DashboardManifest | null> {
  try {
    const payload = await fetchJson<unknown>("manifest.json");
    const manifest = readModelObject(
      payload,
      "manifest.json",
      "fpl.dashboard-read-models",
    );
    if (
      typeof manifest.content_sha256 !== "string" ||
      !/^[0-9a-f]{64}$/.test(manifest.content_sha256) ||
      !Array.isArray(manifest.runs)
    ) {
      throw new Error("invalid manifest.json: published content hash or runs are missing");
    }
    return manifest as unknown as DashboardManifest;
  } catch {
    return null;
  }
}

export async function loadFixtureMatrix(): Promise<FixtureMatrixData> {
  const [payload, manifest] = await Promise.all([
    fetchJson<unknown>("fixture_matrix.json"),
    loadDashboardManifest(),
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
    loadDashboardManifest(),
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
    throw new Error("invalid player_horizons.json: expected a schema-v5 object");
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
      `unsupported player_horizons.json schema: expected version ${DASHBOARD_SCHEMA_VERSION} cumulative raw-model ` +
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

type JsonObject = Record<string, unknown>;

const SCORE_KEYS = [
  "rows",
  "distribution_rows",
  "forecast_total",
  "actual_total",
  "forecast_mean",
  "actual_mean",
  "bias",
  "mae",
  "rmse",
  "crps",
] as const;
const CLEAN_SHEET_SCORE_KEYS = ["rows", "predicted_mean", "observed_rate", "brier"] as const;
const PROVENANCE_KEYS = [
  "run_id",
  "as_of",
  "created_at",
  "season",
  "gw_from",
  "gw_to",
  "status",
  "component_modes",
] as const;

function strictObject(value: unknown, keys: readonly string[], subject: string): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value) || !hasExactKeys(value, keys)) {
    throw new Error(`invalid ${subject}: expected exact keys ${keys.join(", ")}`);
  }
  return value as JsonObject;
}

function objectValue(value: unknown, subject: string): JsonObject {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`invalid ${subject}: expected an object`);
  }
  return value as JsonObject;
}

function stringValue(value: unknown, subject: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`invalid ${subject}: expected a non-empty string`);
  }
  return value;
}

function nullableString(value: unknown, subject: string): string | null {
  if (value === null) return null;
  return stringValue(value, subject);
}

function integerValue(value: unknown, subject: string, minimum = 0): number {
  if (!Number.isInteger(value) || (value as number) < minimum) {
    throw new Error(`invalid ${subject}: expected an integer >= ${minimum}`);
  }
  return value as number;
}

function wholeValue(value: unknown, subject: string): number {
  if (!Number.isInteger(value)) {
    throw new Error(`invalid ${subject}: expected an integer`);
  }
  return value as number;
}

function finiteValue(value: unknown, subject: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`invalid ${subject}: expected a finite number`);
  }
  return value;
}

function nullableFinite(value: unknown, subject: string): number | null {
  return value === null ? null : finiteValue(value, subject);
}

function probabilityValue(value: unknown, subject: string): number {
  const result = finiteValue(value, subject);
  if (result < 0 || result > 1) {
    throw new Error(`invalid ${subject}: probability must fall in [0, 1]`);
  }
  return result;
}

function nullableProbability(value: unknown, subject: string): number | null {
  return value === null ? null : probabilityValue(value, subject);
}

function validateComponentModes(value: unknown, subject: string): void {
  if (value === null) return;
  const modes = objectValue(value, subject);
  if (!Object.values(modes).every((mode) => mode === null || typeof mode === "string")) {
    throw new Error(`invalid ${subject}: component modes must be strings or null`);
  }
}

function validateProvenance(record: JsonObject, subject: string): void {
  stringValue(record.run_id, `${subject}.run_id`);
  nullableString(record.as_of, `${subject}.as_of`);
  nullableString(record.created_at, `${subject}.created_at`);
  stringValue(record.season, `${subject}.season`);
  const gwFrom = integerValue(record.gw_from, `${subject}.gw_from`, 1);
  const gwTo = integerValue(record.gw_to, `${subject}.gw_to`, 1);
  if (gwTo < gwFrom) throw new Error(`invalid ${subject}: gw_to precedes gw_from`);
  nullableString(record.status, `${subject}.status`);
  validateComponentModes(record.component_modes, `${subject}.component_modes`);
}

function validateScoreFields(record: JsonObject, subject: string): ForecastAccuracyScoreBlock {
  const rows = integerValue(record.rows, `${subject}.rows`);
  const distributionRows = integerValue(
    record.distribution_rows,
    `${subject}.distribution_rows`,
  );
  if (distributionRows > rows) {
    throw new Error(`invalid ${subject}: distribution_rows exceeds rows`);
  }
  for (const key of [
    "forecast_total",
    "actual_total",
    "forecast_mean",
    "actual_mean",
    "bias",
    "mae",
    "rmse",
    "crps",
  ] as const) {
    nullableFinite(record[key], `${subject}.${key}`);
  }
  for (const key of ["mae", "rmse", "crps"] as const) {
    const value = record[key];
    if (typeof value === "number" && value < 0) {
      throw new Error(`invalid ${subject}.${key}: score must be non-negative`);
    }
  }
  return record as unknown as ForecastAccuracyScoreBlock;
}

function validateScoreBlock(value: unknown, subject: string): ForecastAccuracyScoreBlock {
  return validateScoreFields(strictObject(value, SCORE_KEYS, subject), subject);
}

function validateCleanSheetFields(record: JsonObject, subject: string): CleanSheetScoreBlock {
  integerValue(record.rows, `${subject}.rows`);
  if (record.predicted_mean !== null) probabilityValue(record.predicted_mean, `${subject}.predicted_mean`);
  if (record.observed_rate !== null) probabilityValue(record.observed_rate, `${subject}.observed_rate`);
  const brier = nullableFinite(record.brier, `${subject}.brier`);
  if (brier != null && brier < 0) throw new Error(`invalid ${subject}.brier: score must be non-negative`);
  return record as unknown as CleanSheetScoreBlock;
}

function validateCleanSheetBlock(value: unknown, subject: string): CleanSheetScoreBlock {
  return validateCleanSheetFields(strictObject(value, CLEAN_SHEET_SCORE_KEYS, subject), subject);
}

function validatePlayerCoverage(value: unknown, subject: string): PlayerForecastCoverage {
  const keys = [
    "forecast_rows",
    "pending_rows",
    "final_eligible_rows",
    "missing_outcome_rows",
    "legacy_unavailable_rows",
    "scored_rows",
    "distribution_scored_rows",
  ] as const;
  const coverage = strictObject(value, keys, subject);
  for (const key of keys) integerValue(coverage[key], `${subject}.${key}`);
  if (
    (coverage.scored_rows as number) > (coverage.final_eligible_rows as number) ||
    (coverage.final_eligible_rows as number) > (coverage.forecast_rows as number) ||
    (coverage.distribution_scored_rows as number) > (coverage.scored_rows as number)
  ) {
    throw new Error(`invalid ${subject}: scored/final/distribution coverage is inconsistent`);
  }
  return coverage as unknown as PlayerForecastCoverage;
}

function validatePlayerCalibration(value: unknown, subject: string): PlayerForecastCalibration {
  const row = strictObject(
    value,
    ["event", "threshold", "bucket", "rows", "predicted_mean", "observed_rate"],
    subject,
  );
  const event = row.event;
  const threshold = row.threshold;
  if (
    (event !== "points_le" && event !== "points_ge") ||
    !Number.isInteger(threshold) ||
    (event === "points_le" ? threshold !== 2 : ![2, 6, 10].includes(threshold as number))
  ) {
    throw new Error(`invalid ${subject}: unsupported inclusive calibration event/threshold`);
  }
  stringValue(row.bucket, `${subject}.bucket`);
  integerValue(row.rows, `${subject}.rows`);
  probabilityValue(row.predicted_mean, `${subject}.predicted_mean`);
  probabilityValue(row.observed_rate, `${subject}.observed_rate`);
  return row as unknown as PlayerForecastCalibration;
}

function validatePlayerObservation(value: unknown, subject: string): PlayerForecastObservation {
  const row = strictObject(
    value,
    [
      "gw",
      "code",
      "web_name",
      "position",
      "team_id",
      "team_code",
      "team_name",
      "team_short_name",
      "forecast_xp",
      "actual_points",
      "residual",
      "absolute_error",
      "crps",
      "p_le_2",
      "p_ge_2",
      "p_ge_6",
      "p_ge_10",
    ],
    subject,
  );
  integerValue(row.gw, `${subject}.gw`, 1);
  integerValue(row.code, `${subject}.code`, 1);
  stringValue(row.web_name, `${subject}.web_name`);
  stringValue(row.position, `${subject}.position`);
  integerValue(row.team_id, `${subject}.team_id`, 1);
  if (row.team_code !== null) integerValue(row.team_code, `${subject}.team_code`, 1);
  stringValue(row.team_name, `${subject}.team_name`);
  stringValue(row.team_short_name, `${subject}.team_short_name`);
  const forecast = finiteValue(row.forecast_xp, `${subject}.forecast_xp`);
  const actual = wholeValue(row.actual_points, `${subject}.actual_points`);
  const residual = finiteValue(row.residual, `${subject}.residual`);
  const absoluteError = finiteValue(row.absolute_error, `${subject}.absolute_error`);
  if (
    Math.abs(residual - (actual - forecast)) > 1e-6 ||
    Math.abs(absoluteError - Math.abs(residual)) > 1e-6
  ) {
    throw new Error(`invalid ${subject}: residual fields do not reconcile`);
  }
  const crps = nullableFinite(row.crps, `${subject}.crps`);
  if (crps != null && crps < 0) throw new Error(`invalid ${subject}.crps: score must be non-negative`);
  for (const key of ["p_le_2", "p_ge_2", "p_ge_6", "p_ge_10"] as const) {
    nullableProbability(row[key], `${subject}.${key}`);
  }
  return row as unknown as PlayerForecastObservation;
}

function validatePlayerSplit(
  value: unknown,
  identityKeys: readonly string[],
  subject: string,
): JsonObject {
  const row = strictObject(value, [...identityKeys, ...SCORE_KEYS], subject);
  validateScoreFields(row, subject);
  return row;
}

function validatePlayerRun(value: unknown, index: number): PlayerForecastAccuracyRun {
  const subject = `player_forecast_vs_actual.json run ${index}`;
  const keys = [
    ...PROVENANCE_KEYS,
    "coverage",
    "overall",
    "by_position",
    "by_gw",
    "by_team",
    "calibration",
    "observations",
  ];
  const run = strictObject(value, keys, subject);
  validateProvenance(run, subject);
  const coverage = validatePlayerCoverage(run.coverage, `${subject}.coverage`);
  const overall = validateScoreBlock(run.overall, `${subject}.overall`);
  if (overall.rows !== coverage.scored_rows || overall.distribution_rows !== coverage.distribution_scored_rows) {
    throw new Error(`invalid ${subject}: overall score rows do not reconcile with coverage`);
  }
  if (!Array.isArray(run.by_position) || !Array.isArray(run.by_gw) || !Array.isArray(run.by_team)) {
    throw new Error(`invalid ${subject}: score splits must be arrays`);
  }
  for (const [splitIndex, value] of run.by_position.entries()) {
    const row = validatePlayerSplit(value, ["position"], `${subject}.by_position[${splitIndex}]`);
    stringValue(row.position, `${subject}.by_position[${splitIndex}].position`);
  }
  for (const [splitIndex, value] of run.by_gw.entries()) {
    const row = validatePlayerSplit(value, ["gw"], `${subject}.by_gw[${splitIndex}]`);
    integerValue(row.gw, `${subject}.by_gw[${splitIndex}].gw`, 1);
  }
  for (const [splitIndex, value] of run.by_team.entries()) {
    const row = validatePlayerSplit(
      value,
      ["team_id", "team_code", "team_name", "team_short_name"],
      `${subject}.by_team[${splitIndex}]`,
    );
    integerValue(row.team_id, `${subject}.by_team[${splitIndex}].team_id`, 1);
    if (row.team_code !== null) integerValue(row.team_code, `${subject}.by_team[${splitIndex}].team_code`, 1);
    stringValue(row.team_name, `${subject}.by_team[${splitIndex}].team_name`);
    stringValue(row.team_short_name, `${subject}.by_team[${splitIndex}].team_short_name`);
  }
  if (!Array.isArray(run.calibration)) throw new Error(`invalid ${subject}.calibration: expected an array`);
  run.calibration.forEach((row, rowIndex) =>
    validatePlayerCalibration(row, `${subject}.calibration[${rowIndex}]`),
  );
  if (!Array.isArray(run.observations)) throw new Error(`invalid ${subject}.observations: expected an array`);
  const identities = new Set<string>();
  run.observations.forEach((row, rowIndex) => {
    const observation = validatePlayerObservation(row, `${subject}.observations[${rowIndex}]`);
    const identity = `${observation.gw}/${observation.code}`;
    if (identities.has(identity)) throw new Error(`invalid ${subject}: duplicate observation ${identity}`);
    identities.add(identity);
  });
  if (run.observations.length !== coverage.scored_rows) {
    throw new Error(`invalid ${subject}: observation count does not reconcile with coverage`);
  }
  return run as unknown as PlayerForecastAccuracyRun;
}

function validateTeamCoverage(value: unknown, subject: string): TeamForecastCoverage {
  const keys = [
    "forecast_rows",
    "pending_rows",
    "missing_outcome_rows",
    "invalid_fixture_rows",
    "scored_rows",
    "attack_distribution_scored_rows",
    "defence_distribution_scored_rows",
    "clean_sheet_scored_rows",
  ] as const;
  const coverage = strictObject(value, keys, subject);
  for (const key of keys) integerValue(coverage[key], `${subject}.${key}`);
  if (
    (coverage.scored_rows as number) > (coverage.forecast_rows as number) ||
    (coverage.attack_distribution_scored_rows as number) > (coverage.scored_rows as number) ||
    (coverage.defence_distribution_scored_rows as number) > (coverage.scored_rows as number) ||
    (coverage.clean_sheet_scored_rows as number) > (coverage.scored_rows as number)
  ) {
    throw new Error(`invalid ${subject}: scored/distribution coverage is inconsistent`);
  }
  return coverage as unknown as TeamForecastCoverage;
}

function validateTeamScoreSet(value: unknown, subject: string): TeamAccuracyScoreSet {
  const set = strictObject(value, ["attack", "defence", "clean_sheet"], subject);
  validateScoreBlock(set.attack, `${subject}.attack`);
  validateScoreBlock(set.defence, `${subject}.defence`);
  validateCleanSheetBlock(set.clean_sheet, `${subject}.clean_sheet`);
  return set as unknown as TeamAccuracyScoreSet;
}

function validateTeamSplit(
  value: unknown,
  identityKeys: readonly string[],
  subject: string,
): JsonObject {
  const row = strictObject(value, [...identityKeys, "attack", "defence", "clean_sheet"], subject);
  validateScoreBlock(row.attack, `${subject}.attack`);
  validateScoreBlock(row.defence, `${subject}.defence`);
  validateCleanSheetBlock(row.clean_sheet, `${subject}.clean_sheet`);
  return row;
}

function validateTeamCalibration(value: unknown, subject: string): TeamForecastCalibration {
  const row = strictObject(
    value,
    ["event", "threshold", "bucket", "rows", "predicted_mean", "observed_rate"],
    subject,
  );
  if (
    (row.event === "goals_ge" && ![1, 2, 3].includes(row.threshold as number)) ||
    (row.event === "clean_sheet" && row.threshold !== null) ||
    (row.event !== "goals_ge" && row.event !== "clean_sheet")
  ) {
    throw new Error(`invalid ${subject}: unsupported calibration event/threshold`);
  }
  stringValue(row.bucket, `${subject}.bucket`);
  integerValue(row.rows, `${subject}.rows`);
  probabilityValue(row.predicted_mean, `${subject}.predicted_mean`);
  probabilityValue(row.observed_rate, `${subject}.observed_rate`);
  return row as unknown as TeamForecastCalibration;
}

function validateTeamObservation(value: unknown, subject: string): TeamForecastObservation {
  const row = strictObject(
    value,
    [
      "fixture",
      "gw",
      "kickoff_time",
      "team_id",
      "team_code",
      "team_name",
      "team_short_name",
      "opponent_team_id",
      "opponent_team_code",
      "opponent_team_name",
      "opponent_team_short_name",
      "was_home",
      "lambda_for",
      "actual_goals_for",
      "attack_residual",
      "lambda_against",
      "actual_goals_against",
      "defence_residual",
      "probability_clean_sheet",
      "actual_clean_sheet",
      "attack_crps",
      "defence_crps",
      "clean_sheet_brier",
      "stage_a_league_average_team",
    ],
    subject,
  );
  for (const key of ["fixture", "gw", "team_id", "opponent_team_id"] as const) {
    integerValue(row[key], `${subject}.${key}`, 1);
  }
  for (const key of ["team_code", "opponent_team_code"] as const) {
    if (row[key] !== null) integerValue(row[key], `${subject}.${key}`, 1);
  }
  for (const key of [
    "team_name",
    "team_short_name",
    "opponent_team_name",
    "opponent_team_short_name",
  ] as const) {
    stringValue(row[key], `${subject}.${key}`);
  }
  nullableString(row.kickoff_time, `${subject}.kickoff_time`);
  if (typeof row.was_home !== "boolean") throw new Error(`invalid ${subject}.was_home: expected boolean`);
  const lambdaFor = finiteValue(row.lambda_for, `${subject}.lambda_for`);
  const goalsFor = integerValue(row.actual_goals_for, `${subject}.actual_goals_for`);
  const attackResidual = finiteValue(row.attack_residual, `${subject}.attack_residual`);
  const lambdaAgainst = finiteValue(row.lambda_against, `${subject}.lambda_against`);
  const goalsAgainst = integerValue(row.actual_goals_against, `${subject}.actual_goals_against`);
  const defenceResidual = finiteValue(row.defence_residual, `${subject}.defence_residual`);
  if (
    lambdaFor < 0 ||
    lambdaAgainst < 0 ||
    goalsFor < 0 ||
    goalsAgainst < 0 ||
    Math.abs(attackResidual - (goalsFor - lambdaFor)) > 1e-6 ||
    Math.abs(defenceResidual - (goalsAgainst - lambdaAgainst)) > 1e-6
  ) {
    throw new Error(`invalid ${subject}: goal/residual fields do not reconcile`);
  }
  probabilityValue(row.probability_clean_sheet, `${subject}.probability_clean_sheet`);
  if (typeof row.actual_clean_sheet !== "boolean") {
    throw new Error(`invalid ${subject}.actual_clean_sheet: expected boolean`);
  }
  if (row.actual_clean_sheet !== (goalsAgainst === 0)) {
    throw new Error(`invalid ${subject}: clean-sheet outcome disagrees with goals against`);
  }
  for (const key of ["attack_crps", "defence_crps"] as const) {
    const score = nullableFinite(row[key], `${subject}.${key}`);
    if (score != null && score < 0) throw new Error(`invalid ${subject}.${key}: score must be non-negative`);
  }
  const brier = finiteValue(row.clean_sheet_brier, `${subject}.clean_sheet_brier`);
  if (brier < 0) throw new Error(`invalid ${subject}.clean_sheet_brier: score must be non-negative`);
  if (typeof row.stage_a_league_average_team !== "boolean") {
    throw new Error(`invalid ${subject}.stage_a_league_average_team: expected boolean`);
  }
  return row as unknown as TeamForecastObservation;
}

function validateTeamRun(value: unknown, index: number): TeamForecastAccuracyRun {
  const subject = `team_forecast_vs_actual.json run ${index}`;
  const run = strictObject(
    value,
    [
      ...PROVENANCE_KEYS,
      "coverage",
      "attack",
      "defence",
      "clean_sheet",
      "by_gw",
      "by_team",
      "by_venue",
      "by_fallback",
      "calibration",
      "observations",
    ],
    subject,
  );
  validateProvenance(run, subject);
  const coverage = validateTeamCoverage(run.coverage, `${subject}.coverage`);
  const scores = validateTeamScoreSet(
    { attack: run.attack, defence: run.defence, clean_sheet: run.clean_sheet },
    `${subject}.scores`,
  );
  if (
    scores.attack.rows !== coverage.scored_rows ||
    scores.defence.rows !== coverage.scored_rows ||
    scores.attack.distribution_rows !== coverage.attack_distribution_scored_rows ||
    scores.defence.distribution_rows !== coverage.defence_distribution_scored_rows ||
    scores.clean_sheet.rows !== coverage.clean_sheet_scored_rows
  ) {
    throw new Error(`invalid ${subject}: score rows do not reconcile with coverage`);
  }
  for (const key of ["by_gw", "by_team", "by_venue", "by_fallback", "calibration", "observations"] as const) {
    if (!Array.isArray(run[key])) throw new Error(`invalid ${subject}.${key}: expected an array`);
  }
  const byGw = run.by_gw as unknown[];
  const byTeam = run.by_team as unknown[];
  const byVenue = run.by_venue as unknown[];
  const byFallback = run.by_fallback as unknown[];
  const calibration = run.calibration as unknown[];
  const observations = run.observations as unknown[];
  byGw.forEach((value, splitIndex) => {
    const row = validateTeamSplit(value, ["gw"], `${subject}.by_gw[${splitIndex}]`);
    integerValue(row.gw, `${subject}.by_gw[${splitIndex}].gw`, 1);
  });
  byTeam.forEach((value, splitIndex) => {
    const row = validateTeamSplit(
      value,
      ["team_id", "team_code", "team_name", "team_short_name"],
      `${subject}.by_team[${splitIndex}]`,
    );
    integerValue(row.team_id, `${subject}.by_team[${splitIndex}].team_id`, 1);
    if (row.team_code !== null) integerValue(row.team_code, `${subject}.by_team[${splitIndex}].team_code`, 1);
    stringValue(row.team_name, `${subject}.by_team[${splitIndex}].team_name`);
    stringValue(row.team_short_name, `${subject}.by_team[${splitIndex}].team_short_name`);
  });
  byVenue.forEach((value, splitIndex) => {
    const row = validateTeamSplit(value, ["venue"], `${subject}.by_venue[${splitIndex}]`);
    if (row.venue !== "home" && row.venue !== "away") {
      throw new Error(`invalid ${subject}.by_venue[${splitIndex}].venue`);
    }
  });
  byFallback.forEach((value, splitIndex) => {
    const row = validateTeamSplit(
      value,
      ["stage_a_league_average_team"],
      `${subject}.by_fallback[${splitIndex}]`,
    );
    if (typeof row.stage_a_league_average_team !== "boolean") {
      throw new Error(`invalid ${subject}.by_fallback[${splitIndex}].stage_a_league_average_team`);
    }
  });
  calibration.forEach((row, rowIndex) =>
    validateTeamCalibration(row, `${subject}.calibration[${rowIndex}]`),
  );
  const identities = new Set<string>();
  const byFixture = new Map<number, TeamForecastObservation[]>();
  observations.forEach((row, rowIndex) => {
    const observation = validateTeamObservation(row, `${subject}.observations[${rowIndex}]`);
    const identity = `${observation.fixture}/${observation.team_id}`;
    if (identities.has(identity)) throw new Error(`invalid ${subject}: duplicate observation ${identity}`);
    identities.add(identity);
    const sides = byFixture.get(observation.fixture) ?? [];
    sides.push(observation);
    byFixture.set(observation.fixture, sides);
  });
  for (const [fixture, sides] of byFixture) {
    if (sides.length !== 2) {
      throw new Error(`invalid ${subject}: finalized fixture ${fixture} does not have two sides`);
    }
    const [first, second] = sides;
    if (
      first.opponent_team_id !== second.team_id ||
      second.opponent_team_id !== first.team_id ||
      first.was_home === second.was_home ||
      first.gw !== second.gw ||
      first.kickoff_time !== second.kickoff_time ||
      first.actual_goals_for !== second.actual_goals_against ||
      first.actual_goals_against !== second.actual_goals_for ||
      Math.abs(first.lambda_for - second.lambda_against) > 1e-6 ||
      Math.abs(first.lambda_against - second.lambda_for) > 1e-6
    ) {
      throw new Error(`invalid ${subject}: finalized fixture ${fixture} sides are not reciprocal`);
    }
  }
  if (observations.length !== coverage.scored_rows) {
    throw new Error(`invalid ${subject}: observation count does not reconcile with coverage`);
  }
  return run as unknown as TeamForecastAccuracyRun;
}

function forecastAccuracyEnvelope(
  payload: unknown,
  filename: string,
  schema: string,
): JsonObject {
  const envelope = strictObject(
    payload,
    ["schema", "json_schema_version", "semantics", "has_outcomes", "runs"],
    filename,
  );
  if (envelope.schema !== schema || envelope.json_schema_version !== FORECAST_ACCURACY_SCHEMA_VERSION) {
    throw new Error(`unsupported ${filename} schema: expected ${schema} version 5; republish the dashboard read models`);
  }
  objectValue(envelope.semantics, `${filename}.semantics`);
  if (typeof envelope.has_outcomes !== "boolean" || !Array.isArray(envelope.runs)) {
    throw new Error(`invalid ${filename}: has_outcomes must be boolean and runs must be an array`);
  }
  return envelope;
}

export async function loadPlayerForecastVsActual(): Promise<PlayerForecastVsActualData> {
  const filename = "player_forecast_vs_actual.json";
  const [payload, manifest] = await Promise.all([
    fetchJson<unknown>(filename),
    loadDashboardManifest(),
  ]);
  const envelope = forecastAccuracyEnvelope(
    payload,
    filename,
    "fpl.dashboard-player-forecast-vs-actual",
  );
  const runs = (envelope.runs as unknown[]).map(validatePlayerRun);
  if (envelope.has_outcomes !== runs.some((run) => run.coverage.scored_rows > 0)) {
    throw new Error(`invalid ${filename}: has_outcomes does not reconcile with scored coverage`);
  }
  return { ...envelope, runs, manifest } as unknown as PlayerForecastVsActualData;
}

export async function loadTeamForecastVsActual(): Promise<TeamForecastVsActualData> {
  const filename = "team_forecast_vs_actual.json";
  const [payload, manifest] = await Promise.all([
    fetchJson<unknown>(filename),
    loadDashboardManifest(),
  ]);
  const envelope = forecastAccuracyEnvelope(
    payload,
    filename,
    "fpl.dashboard-team-forecast-vs-actual",
  );
  const runs = (envelope.runs as unknown[]).map(validateTeamRun);
  if (envelope.has_outcomes !== runs.some((run) => run.coverage.scored_rows > 0)) {
    throw new Error(`invalid ${filename}: has_outcomes does not reconcile with scored coverage`);
  }
  return { ...envelope, runs, manifest } as unknown as TeamForecastVsActualData;
}

/** Temporary source-compatibility alias; it loads the explicit schema-v5 player file. */
export const loadForecastVsActual = loadPlayerForecastVsActual;

export async function loadOptimizerAudit(): Promise<OptimizerAuditData> {
  const payload = await fetchJson<unknown>("optimizer_audit.json");
  return readModelObject(
    payload,
    "optimizer_audit.json",
    "fpl.dashboard-optimizer-audit",
  ) as unknown as OptimizerAuditData;
}
