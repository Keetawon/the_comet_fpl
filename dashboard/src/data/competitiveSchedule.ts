import { resolveDataUrl } from "./publicData";

export interface ScheduleSource { payload_id: string; sha256: string; known_at: string }
export interface CupMatch {
  provider_match_id: number;
  home_team_code: number | null; away_team_code: number | null;
  home_name: string; away_name: string; home_short: string; away_short: string;
  kickoff_time: string | null; status: string; source_payload_id: string;
}
export interface CupCompetition {
  competition_id: number; name: string;
  status: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE" | "NOT_PUBLISHED";
  issues: string[]; sources: ScheduleSource[]; matches: CupMatch[];
}
export interface CompetitiveSchedule {
  schema_version: 1; semantics: "current_schedule_not_prediction";
  season: string; as_of: string; verified_team_codes: number[];
  identity_sources: ScheduleSource[]; competitions: CupCompetition[];
}

export async function loadCompetitiveSchedule(): Promise<CompetitiveSchedule> {
  const response = await fetch(await resolveDataUrl("sdp/competitive_schedule.json"));
  if (!response.ok) throw new Error(`Competitive schedule unavailable (HTTP ${response.status})`);
  const value = await response.json() as CompetitiveSchedule;
  if (value.schema_version !== 1 || value.semantics !== "current_schedule_not_prediction" ||
      !Array.isArray(value.competitions) || !Array.isArray(value.verified_team_codes) ||
      !Number.isFinite(Date.parse(value.as_of))) throw new Error("Invalid competitive schedule");
  const competitions = new Set<number>();
  for (const comp of value.competitions) {
    if (competitions.has(comp.competition_id) || comp.competition_id === 8 ||
        !["AVAILABLE", "PARTIAL", "UNAVAILABLE", "NOT_PUBLISHED"].includes(comp.status) ||
        !Array.isArray(comp.matches) || !Array.isArray(comp.sources)) throw new Error("Invalid competition");
    competitions.add(comp.competition_id);
    const ids = new Set<number>();
    for (const match of comp.matches) {
      if (ids.has(match.provider_match_id) || !Number.isInteger(match.provider_match_id) ||
          (match.kickoff_time !== null && !Number.isFinite(Date.parse(match.kickoff_time))) ||
          !comp.sources.some((s) => s.payload_id === match.source_payload_id && Date.parse(s.known_at) <= Date.parse(value.as_of)) ||
          ![match.home_team_code, match.away_team_code].some((c) => c !== null && value.verified_team_codes.includes(c))) {
        throw new Error("Invalid competitive fixture identity/date/source");
      }
      ids.add(match.provider_match_id);
    }
  }
  return value;
}
