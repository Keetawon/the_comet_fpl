// Independently versioned observed sidecar. No forecast/optimizer read models enter these pages.
export type SdpScope = "team" | "player";
export type SdpSource = "sdp" | "fpl";
export type SourceAvailability = "AVAILABLE" | "PARTIAL" | "UNAVAILABLE";

export interface SdpMetric {
  key: string;
  label: string;
  group: string;
  source: SdpSource;
  scope: SdpScope | "both";
  unit: string;
  aggregation: "sum" | "mean";
  per90_denominator: "minutes_sdp" | "minutes_fpl" | null;
  verified_semantics: boolean;
  description?: string;
  provider_field?: string | null;
}

export interface SdpMatch {
  season: string;
  gw: number;
  fixture: number;
  kickoff_time: string;
  team_code: number;
  team_name: string;
  team_short_name: string;
  opponent_team_code: number;
  opponent_name: string;
  opponent_short_name: string;
  was_home: boolean;
  status: string;
  known_at: string;
  provider_match_id?: number | null;
  source_version?: string | null;
  sdp: Record<string, number | null>;
  // Player fields are absent on team rows. Unknown identities and measurements stay NULL.
  code?: number | null;
  provider_player_id?: number | null;
  web_name?: string | null;
  position?: string | null;
  provider_position?: string | null;
  provider_sub_position?: string | null;
  started?: boolean | null;
  bench?: boolean | null;
  appeared?: boolean | null;
  minutes_sdp?: number | null;
  nominal_minutes_sdp?: number | null;
  minutes_fpl?: number | null;
  fpl?: Record<string, number | null>;
}

export interface SdpStatsData {
  schema: "fpl.sdp-stats";
  json_schema_version: 1;
  as_of: string;
  source_status: {
    team_stats: SourceAvailability;
    player_stats: SourceAvailability;
    player_lineups: SourceAvailability;
    fpl_enrichment: SourceAvailability;
    latest_sdp_known_at: string | null;
    latest_fpl_known_at: string | null;
    latest_completed_kickoff: string | null;
    notes: string[];
  };
  coverage: {
    team_matches: number;
    player_matches: number;
    sdp_lineup_player_matches: number;
    fpl_player_matches: number;
    team_failures: number;
    unmapped_players: number;
    seasons: string[];
  };
  metrics: SdpMetric[];
  gameweeks: { season: string; gw: number; finished: boolean; fixtures_total: number; fixtures_completed: number; source_known_at: string }[];
  team_matches: SdpMatch[];
  player_matches: SdpMatch[];
}

const object = (v: unknown): v is Record<string, unknown> =>
  v != null && typeof v === "object" && !Array.isArray(v);
const positiveId = (v: unknown) => typeof v === "number" && Number.isSafeInteger(v) && v > 0;
const nullableNumber = (v: unknown) => v === null || (typeof v === "number" && Number.isFinite(v));
const timestamp = (v: unknown) => typeof v === "string" &&
  /(?:Z|[+-]\d\d:\d\d)$/.test(v) && Number.isFinite(Date.parse(v));

export function parseSdpStats(payload: unknown): SdpStatsData {
  const fail = () => { throw new Error("The observed SDP file is invalid or incompatible. Republish its source data."); };
  if (!object(payload) || payload.schema !== "fpl.sdp-stats" || payload.json_schema_version !== 1 ||
      !timestamp(payload.as_of) || !object(payload.source_status) || !object(payload.coverage) ||
      !Array.isArray(payload.metrics) || !Array.isArray(payload.team_matches) ||
      !Array.isArray(payload.player_matches) || !Array.isArray(payload.gameweeks)) return fail();
  const asOf = Date.parse(payload.as_of as string);
  const status = payload.source_status;
  for (const key of ["team_stats", "player_stats", "player_lineups", "fpl_enrichment"]) {
    if (!["AVAILABLE", "PARTIAL", "UNAVAILABLE"].includes(String(status[key]))) return fail();
  }
  for (const key of ["latest_sdp_known_at", "latest_fpl_known_at", "latest_completed_kickoff"]) {
    if (status[key] !== null && (!timestamp(status[key]) || Date.parse(status[key] as string) > asOf)) return fail();
  }
  if (!Array.isArray(status.notes) || status.notes.some(v => typeof v !== "string")) return fail();
  for (const key of ["team_matches", "player_matches", "sdp_lineup_player_matches", "fpl_player_matches", "team_failures", "unmapped_players"]) {
    const value = payload.coverage[key];
    if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) return fail();
  }
  if (!Array.isArray(payload.coverage.seasons) || payload.coverage.seasons.some(v => typeof v !== "string")) return fail();
  const gameweeks = new Set<string>();
  for (const gw of payload.gameweeks) {
    if (!object(gw) || typeof gw.season !== "string" || !positiveId(gw.gw) ||
        typeof gw.finished !== "boolean" || !timestamp(gw.source_known_at) ||
        Date.parse(gw.source_known_at as string) > asOf ||
        typeof gw.fixtures_total !== "number" || !Number.isSafeInteger(gw.fixtures_total) || gw.fixtures_total < 0 ||
        typeof gw.fixtures_completed !== "number" || !Number.isSafeInteger(gw.fixtures_completed) ||
        gw.fixtures_completed < 0 || gw.fixtures_completed > gw.fixtures_total) return fail();
    const key = `${gw.season}:${gw.gw}`;
    if (gameweeks.has(key)) return fail();
    gameweeks.add(key);
  }
  const catalog = new Set<string>();
  for (const m of payload.metrics) {
    if (!object(m) || !["team", "player", "both"].includes(String(m.scope)) ||
        !["sdp", "fpl"].includes(String(m.source)) ||
        !["sum", "mean"].includes(String(m.aggregation)) ||
        ![null, "minutes_sdp", "minutes_fpl"].includes(m.per90_denominator as null | string) ||
        typeof m.verified_semantics !== "boolean" ||
        [m.key, m.label, m.group, m.unit].some(v => typeof v !== "string")) return fail();
    if (m.per90_denominator !== null && m.per90_denominator !== `minutes_${m.source}`) return fail();
    const key = `${m.scope}:${m.source}:${m.key}`;
    if (catalog.has(key)) return fail();
    catalog.add(key);
  }
  for (const scope of ["team", "player"] as const) {
    const seen = new Set<string>();
    for (const row of payload[`${scope}_matches`] as unknown[]) {
      if (!object(row) || !positiveId(row.fixture) || !positiveId(row.gw) ||
          !positiveId(row.team_code) || !positiveId(row.opponent_team_code) ||
          row.team_code === row.opponent_team_code || typeof row.was_home !== "boolean" ||
          typeof row.season !== "string" || !timestamp(row.kickoff_time) || !timestamp(row.known_at) ||
          Date.parse(row.kickoff_time as string) >= asOf || Date.parse(row.known_at as string) > asOf ||
          [row.team_name, row.team_short_name, row.opponent_name, row.opponent_short_name, row.status].some(v => typeof v !== "string") ||
          !["FINAL", "PROVISIONAL", "UNAVAILABLE"].includes(String(row.status)) || !object(row.sdp)) return fail();
      for (const source of [row.sdp, row.fpl]) {
        if (source !== undefined && (!object(source) || Object.values(source).some(v => !nullableNumber(v)))) return fail();
      }
      if (scope === "player") {
        if (!positiveId(row.code) && !positiveId(row.provider_player_id)) return fail();
        if (row.code != null && !positiveId(row.code)) return fail();
        if (row.provider_player_id != null && !positiveId(row.provider_player_id)) return fail();
        for (const field of ["web_name", "position", "provider_position", "provider_sub_position"]) {
          if (row[field] != null && typeof row[field] !== "string") return fail();
        }
        for (const field of ["minutes_sdp", "minutes_fpl", "nominal_minutes_sdp"]) {
          if (row[field] !== undefined && (!nullableNumber(row[field]) || (typeof row[field] === "number" && row[field] < 0))) return fail();
        }
        for (const field of ["started", "bench", "appeared"]) {
          if (row[field] !== undefined && row[field] !== null && typeof row[field] !== "boolean") return fail();
        }
      }
      const identity = scope === "team" ? row.team_code : row.code != null ? `fpl:${row.code}` : `sdp:${row.provider_player_id}`;
      const key = `${row.season}:${row.fixture}:${identity}`;
      if (seen.has(key)) return fail();
      seen.add(key);
    }
  }
  return payload as unknown as SdpStatsData;
}

export async function loadSdpStats(): Promise<SdpStatsData> {
  const base = import.meta.env.VITE_SDP_DATA_BASE ?? `${import.meta.env.BASE_URL}sdp`;
  const response = await fetch(`${base}/sdp_stats.json`);
  if (!response.ok) throw new Error("Observed SDP statistics have not been published for this dashboard.");
  return parseSdpStats(await response.json());
}
