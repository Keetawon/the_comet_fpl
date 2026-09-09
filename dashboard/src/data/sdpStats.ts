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
  omitted_zero_display?: boolean;
}

export const OMITTED_ZERO_POLICY_RECORDED_AT = "2026-09-09T02:47:16.006705+00:00";
export const OMITTED_ZERO_DISPLAY_FIELDS = new Set([
  "shots_inside_box", "shots_outside_box", "shots_blocked",
  "big_chances_created", "big_chances_scored", "big_chances_missed",
  "accurate_crosses", "corners", "blocks", "saves",
  "possession_won_attacking_third", "yellow_cards", "red_cards", "offsides",
]);

export interface SdpDisplayAssumption {
  value: 0;
  evidence_class: "owner_directed_omitted_count_assumption";
  policy_recorded_at: string;
  source_known_at: string;
  provider_match_id: number;
  provider_field: string;
  provider_field_state: "omitted";
  raw_payload_sha256: string;
}

export interface SdpDisplayCorrection {
  correction_id: string;
  value: 0;
  evidence_class: "owner_confirmed_display_correction";
  owner_confirmation_recorded_at: string;
  source_known_at: string;
  provider_match_id: number;
  provider_field: "ontargetScoringAtt" | "blockedScoringAtt" | "expectedGoalsOnTarget";
  provider_field_state: "omitted";
  raw_payload_sha256: string;
  corroboration: "shot_accounting_and_fpl_goalkeeper_proxy_zero" | "owner_confirmed_xgot_with_corroborated_zero_sot";
  relation: "direct" | "opponent_mirror";
  subject_team_code: number;
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
  display_corrections?: Record<string, SdpDisplayCorrection>;
  display_assumptions?: Record<string, SdpDisplayAssumption>;
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
  json_schema_version: 2 | 3 | 4;
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
  if (!object(payload) || payload.schema !== "fpl.sdp-stats" || ![2, 3, 4].includes(payload.json_schema_version as number) ||
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
  const corrections = new Map<string, { row: Record<string, unknown>; metric: string; correction: Record<string, unknown> }[]>();
  for (const m of payload.metrics) {
    if (!object(m) || !["team", "player", "both"].includes(String(m.scope)) ||
        !["sdp", "fpl"].includes(String(m.source)) ||
        !["sum", "mean"].includes(String(m.aggregation)) ||
        ![null, "minutes_sdp", "minutes_fpl"].includes(m.per90_denominator as null | string) ||
        typeof m.verified_semantics !== "boolean" ||
        (Number(payload.json_schema_version) >= 3 && typeof m.omitted_zero_display !== "boolean") ||
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
      if (scope === "team") {
        if (!object(row.display_corrections) ||
            (Number(payload.json_schema_version) >= 3 && !object(row.display_assumptions)) ||
            (row.display_assumptions !== undefined && !object(row.display_assumptions))) return fail();
        for (const [metric, assumption] of Object.entries(row.display_assumptions ?? {})) {
          if (!OMITTED_ZERO_DISPLAY_FIELDS.has(metric) || !object(assumption) ||
              assumption.value !== 0 || assumption.evidence_class !== "owner_directed_omitted_count_assumption" ||
              assumption.provider_field_state !== "omitted" || typeof assumption.provider_field !== "string" ||
              !assumption.provider_field || !positiveId(assumption.provider_match_id) ||
              assumption.provider_match_id !== row.provider_match_id ||
              typeof assumption.raw_payload_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(assumption.raw_payload_sha256) ||
              !timestamp(assumption.source_known_at) || Date.parse(assumption.source_known_at as string) > asOf ||
              assumption.policy_recorded_at !== OMITTED_ZERO_POLICY_RECORDED_AT ||
              Date.parse(assumption.policy_recorded_at as string) > asOf ||
              (row.sdp as Record<string, unknown>)[metric] !== null ||
              Object.hasOwn(row.display_corrections, metric)) return fail();
        }
        for (const [metric, correction] of Object.entries(row.display_corrections)) {
          if (!["shots_on_target", "shots_on_target_allowed", "shots_blocked", "expected_goals_on_target"].includes(metric) || !object(correction) ||
              (metric === "expected_goals_on_target" && Number(payload.json_schema_version) < 4) ||
              correction.value !== 0 || correction.evidence_class !== "owner_confirmed_display_correction" ||
              correction.provider_field !== (metric === "expected_goals_on_target" ? "expectedGoalsOnTarget" : metric === "shots_blocked" ? "blockedScoringAtt" : "ontargetScoringAtt") || correction.provider_field_state !== "omitted" ||
              correction.corroboration !== (metric === "expected_goals_on_target" ? "owner_confirmed_xgot_with_corroborated_zero_sot" : "shot_accounting_and_fpl_goalkeeper_proxy_zero") ||
              !["direct", "opponent_mirror"].includes(String(correction.relation)) ||
              typeof correction.correction_id !== "string" || !/^[a-z0-9-]+$/.test(correction.correction_id) ||
              typeof correction.raw_payload_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(correction.raw_payload_sha256) ||
              !positiveId(correction.provider_match_id) || !positiveId(correction.subject_team_code) ||
              !timestamp(correction.source_known_at) || !timestamp(correction.owner_confirmation_recorded_at) ||
              Date.parse(correction.source_known_at as string) > Date.parse(correction.owner_confirmation_recorded_at as string) ||
              Date.parse(correction.owner_confirmation_recorded_at as string) > asOf ||
              (row.sdp as Record<string, unknown>)[metric] !== null || row.status !== "UNAVAILABLE" ||
              (["shots_on_target", "shots_blocked", "expected_goals_on_target"].includes(metric) && (correction.relation !== "direct" || row.team_code !== correction.subject_team_code)) ||
              (metric === "shots_on_target_allowed" && (correction.relation !== "opponent_mirror" || row.opponent_team_code !== correction.subject_team_code))) return fail();
          const entries = corrections.get(correction.correction_id) ?? [];
          entries.push({ row, metric, correction });
          corrections.set(correction.correction_id, entries);
        }
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
  for (const entries of corrections.values()) {
    if (entries.length === 1 && ["shots_blocked", "expected_goals_on_target"].includes(entries[0].metric)) continue;
    if (entries.length !== 2 || new Set(entries.map(entry => entry.metric)).size !== 2) return fail();
    const direct = entries.find(entry => entry.metric === "shots_on_target");
    const mirror = entries.find(entry => entry.metric === "shots_on_target_allowed");
    if (!direct || !mirror || direct.row.season !== mirror.row.season || direct.row.fixture !== mirror.row.fixture ||
        direct.row.team_code !== mirror.row.opponent_team_code || direct.row.opponent_team_code !== mirror.row.team_code) return fail();
  }
  return payload as unknown as SdpStatsData;
}

export async function loadSdpStats(): Promise<SdpStatsData> {
  const base = import.meta.env.VITE_SDP_DATA_BASE ?? `${import.meta.env.BASE_URL}sdp`;
  const response = await fetch(`${base}/sdp_stats.json`);
  if (!response.ok) throw new Error("Observed SDP statistics have not been published for this dashboard.");
  return parseSdpStats(await response.json());
}
