import type { CompetitiveSchedule } from "@/data/competitiveSchedule";
import type { FixtureScheduleOverlay } from "@/data/types";
export const schedule: FixtureScheduleOverlay = {
  schema_version: 2, semantics: "current_at_export_not_forecast_vintage",
  export_created_at: "2026-09-15T00:00:00Z", database_sha256: "d".repeat(64),
  teams: [{ season: "2026-27", team_code: 3, team_name: "Arsenal", short_name: "ARS", fixtures: [
    { fixture: 40, gw: 5, kickoff_time: "2026-09-19T14:00:00Z", opponent_team_code: 36,
      opponent_short_name: "BHA", was_home: true, official_fdr: 5 },
    { fixture: 41, gw: 5, kickoff_time: "2026-09-21T19:00:00Z", opponent_team_code: 7,
      opponent_short_name: "AVL", was_home: false, official_fdr: null },
  ] }],
};
export const cups: CompetitiveSchedule = {
  schema_version: 1, semantics: "current_schedule_not_prediction", season: "2026-27",
  as_of: "2026-09-15T00:00:00Z", verified_team_codes: [3], identity_sources: [],
  competitions: [{ competition_id: 2, name: "League Cup", status: "AVAILABLE", issues: [],
    sources: [{payload_id: "p", sha256: "h", known_at: "2026-09-14T00:00:00Z"}],
    matches: [{ provider_match_id: 123, home_team_code: 3, away_team_code: null,
      home_name: "Arsenal", away_name: "Cup opponent", home_short: "ARS", away_short: "CUP",
      kickoff_time: "2026-09-16T19:00:00Z", status: "PreMatch", source_payload_id: "p" }] }],
};
