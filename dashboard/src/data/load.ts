// Static read-model data layer. The dashboard reads ONLY these JSON files -- it never
// queries DuckDB and never reads Parquet. Point VITE_DATA_BASE at a copy of the published
// read-model directory (default: the files copied into public/data by the dev setup in
// README.md).

import type {
  DashboardManifest,
  ForecastVsActualData,
  NextGwPlan,
  PlayerRecord,
  SummaryData,
  TeamRecord,
} from "./types";

const BASE: string = import.meta.env.VITE_DATA_BASE ?? "/data";

async function fetchJson<T>(name: string): Promise<T> {
  const response = await fetch(`${BASE}/${name}`);
  if (!response.ok) {
    throw new Error(
      `could not load ${BASE}/${name} (${response.status}); generate the read models ` +
        `first -- see dashboard/README.md`,
    );
  }
  return (await response.json()) as T;
}

export interface FixtureMatrixData {
  teams: TeamRecord[];
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
    fetchJson<{ teams: TeamRecord[] }>("fixture_matrix.json"),
    loadManifest(),
  ]);
  const teams = payload.teams;
  const versions = new Set(teams.flatMap((t) => t.fixtures.map((f) => f.ease_index_formula_version)));
  return {
    teams,
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
  const payload = await fetchJson<{ plans: NextGwPlan[] }>("next_gw.json");
  return { plans: payload.plans };
}

export async function loadSummary(): Promise<SummaryData> {
  return fetchJson<SummaryData>("summary.json");
}

export async function loadForecastVsActual(): Promise<ForecastVsActualData> {
  return fetchJson<ForecastVsActualData>("forecast_vs_actual.json");
}
