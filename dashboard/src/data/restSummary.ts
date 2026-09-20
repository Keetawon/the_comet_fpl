import { resolveDataUrl } from "./publicData";

export interface RestAppearance {
  observed_team_code?: number | null;
  competition_id: number;
  competition_name: string;
  provider_match_id: number;
  kickoff: string;
  opponent_name: string | null;
  nominal_minutes: number | null;
  fpl_minutes?: number | null;
  fpl_fixture_id?: number | null;
}

export interface PlayerRest {
  code: number;
  team_code: number;
  verdict: "midweek_played" | "full_rest" | "unknown";
  coverage_complete?: boolean;
  last_appearance: RestAppearance | null;
  next_fixture: {
    gw: number;
    fixture_id?: number | null;
    kickoff: string | null;
    opponent_name: string | null;
    was_home: boolean | null;
  } | null;
  rest_hours: number | null;
  rest_days: number | null;
  midweek_appearances: number;
  midweek_nominal_minutes: number | null;
  international_window_overlap: boolean;
  unknown_reasons: string[];
  evidence_versions?: { provider_match_id: number; competition_id: number; known_at: string | null; version_id: string | null; roster_proven: boolean }[];
}

export interface RestSummary {
  schema_version: 1;
  semantics: "descriptive_observed_rest_not_forecast";
  season: string;
  as_of: string;
  window_hours: number;
  midweek_definition: "Monday_through_Thursday_UTC";
  duration_definition: "nominal_period_clock_intervals_v1_not_fpl_minutes";
  promotion_permitted: false;
  players: PlayerRest[];
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
const date = (value: unknown): value is string => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const natural = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const measured = (value: unknown): boolean => value === null || (typeof value === "number" && Number.isFinite(value) && value >= 0);
const nullableText = (value: unknown): boolean => value === null || typeof value === "string";

/** Validate the additive public sidecar; an older generation may have none. */
export function parseRestSummary(value: unknown): RestSummary {
  if (!object(value) || value.schema_version !== 1 || value.semantics !== "descriptive_observed_rest_not_forecast" ||
      value.promotion_permitted !== false || typeof value.season !== "string" || !date(value.as_of) ||
      !natural(value.window_hours) || value.window_hours === 0 || !Array.isArray(value.players) ||
      value.midweek_definition !== "Monday_through_Thursday_UTC" ||
      value.duration_definition !== "nominal_period_clock_intervals_v1_not_fpl_minutes") throw new Error("Invalid published rest summary.");
  const codes = new Set<number>();
  for (const row of value.players) {
    if (!object(row) || !natural(row.code) || row.code === 0 || codes.has(row.code) || !natural(row.team_code) || row.team_code === 0 ||
        !["midweek_played", "full_rest", "unknown"].includes(String(row.verdict)) ||
        !measured(row.rest_hours) || (row.rest_days !== null && !natural(row.rest_days)) || !measured(row.midweek_nominal_minutes) ||
        !natural(row.midweek_appearances) || !Array.isArray(row.unknown_reasons) ||
        !row.unknown_reasons.every((reason: unknown) => typeof reason === "string") ||
        typeof row.international_window_overlap !== "boolean" ||
        (row.coverage_complete !== undefined && typeof row.coverage_complete !== "boolean") ||
        (row.verdict === "midweek_played") !== (row.midweek_appearances > 0) ||
        (row.verdict === "unknown" && row.unknown_reasons.length === 0)) throw new Error("Invalid rest player identity or evidence.");
    codes.add(row.code);
    const last = row.last_appearance;
    if (last !== null && (!object(last) || !date(last.kickoff) || Date.parse(last.kickoff) >= Date.parse(value.as_of) ||
        !natural(last.provider_match_id) || last.provider_match_id === 0 || typeof last.competition_name !== "string" ||
        ![8, 1, 2, 5, 6, 1125].includes(last.competition_id as number) || !nullableText(last.opponent_name) ||
        (last.observed_team_code != null && (!natural(last.observed_team_code) || last.observed_team_code === 0)) ||
        !measured(last.nominal_minutes) || (last.fpl_minutes !== undefined && !measured(last.fpl_minutes)))) throw new Error("Invalid witnessed appearance.");
    const next = row.next_fixture;
    if (next !== null && (!object(next) || !natural(next.gw) || next.gw < 1 || next.gw > 38 ||
        (next.kickoff !== null && !date(next.kickoff)) ||
        !nullableText(next.opponent_name) || (next.was_home !== null && typeof next.was_home !== "boolean") ||
        (next.fixture_id != null && (!natural(next.fixture_id) || next.fixture_id === 0)))) throw new Error("Invalid next rest fixture.");
    if ((last === null || next === null || next.kickoff === null) && (row.rest_days !== null || row.rest_hours !== null)) throw new Error("Rest gap has missing endpoints.");
    if (row.evidence_versions !== undefined && (!Array.isArray(row.evidence_versions) || row.evidence_versions.some((source: unknown) =>
      !object(source) || !natural(source.provider_match_id) || !nullableText(source.version_id) ||
      (source.known_at !== null && (!date(source.known_at) || Date.parse(source.known_at) > Date.parse(value.as_of as string))) || typeof source.roster_proven !== "boolean"))) throw new Error("Invalid rest source cutoff.");
  }
  return value as unknown as RestSummary;
}

export async function loadRestSummary(): Promise<RestSummary> {
  const url = await resolveDataUrl("sdp/rest_summary.json");
  const response = await fetch(url, { signal: AbortSignal.timeout(15_000) });
  if (!response.ok) throw new Error(`Rest summary unavailable (HTTP ${response.status}).`);
  return parseRestSummary(await response.json());
}
