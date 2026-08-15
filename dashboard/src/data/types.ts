// Read-model shapes as emitted by fpl.publish.dashboard_json (schema
// fpl.dashboard-read-models v1; see docs/dashboard-json-contract.md).
// Nullable fields are `| null`: NULL means unmeasured/unavailable and must
// never be rendered as 0, "", or a fabricated colour.

export type WindowLabel = "last_3" | "last_5" | "last_10" | "season_to_date";

export const WINDOW_LABELS: readonly WindowLabel[] = [
  "last_3",
  "last_5",
  "last_10",
  "season_to_date",
];

export interface TeamFormWindow {
  matches_played: number | null;
  goals_for: number | null;
  goals_against: number | null;
  clean_sheets: number | null;
  wins: number | null;
  draws: number | null;
  losses: number | null;
  team_xg: number | null;
  team_xgc: number | null;
  goals_for_per_match: number | null;
  goals_against_per_match: number | null;
  team_xg_per_match: number | null;
  team_xgc_per_match: number | null;
}

export interface TeamForm {
  season: string;
  as_at_gw: number;
  windows: Record<WindowLabel, TeamFormWindow>;
}

export interface TeamFixture {
  gw: number;
  fixture: number;
  kickoff_time: string | null;
  opponent_team_code: number;
  opponent_short_name: string;
  was_home: boolean | null;
  lambda_for: number | null;
  lambda_against: number | null;
  probability_clean_sheet: number | null;
  attack_ease_index: number | null;
  defence_ease_index: number | null;
  overall_ease_index: number | null;
  ease_index_formula_version: string;
  official_fdr: number | null;
  stage_a_league_average_team: boolean;
}

export interface TeamRecord {
  run_id: string;
  as_of: string;
  season: string;
  team_code: number;
  team_name: string;
  short_name: string;
  form: TeamForm | null;
  fixtures: TeamFixture[];
}

export interface PlayerFormWindow {
  rostered_fixtures: number | null;
  appearances: number | null;
  starts: number | null;
  did_not_play: number | null;
  minutes: number | null;
  goals_scored: number | null;
  assists: number | null;
  bonus: number | null;
  bps: number | null;
  defensive_contribution: number | null;
  expected_goals: number | null;
  expected_assists: number | null;
  expected_goals_per_90: number | null;
  expected_assists_per_90: number | null;
  points_under_rules_2026_27: number | null;
}

export interface PlayerForm {
  season: string;
  as_at_gw: number;
  windows: Record<WindowLabel, PlayerFormWindow>;
}

export interface PlayerFixture {
  gw: number;
  fixture: number;
  kickoff_time: string | null;
  opponent_team_code: number;
  opponent_short_name: string;
  was_home: boolean | null;
  expected_points: number | null;
  probability_appears: number | null;
  probability_sixty_minutes: number | null;
  expected_goals: number | null;
  expected_assists: number | null;
  probability_clean_sheet: number | null;
  team_attack_ease_index: number | null;
  team_defence_ease_index: number | null;
  team_overall_ease_index: number | null;
  team_official_fdr: number | null;
  /** The player's CLUB primitives for the same fixture (behind the chip colour). */
  team_lambda_for: number | null;
  team_lambda_against: number | null;
  /** The club's clean-sheet probability -- a different measure from the player's own CS. */
  team_probability_clean_sheet: number | null;
}

export interface PlayerRecord {
  run_id: string;
  as_of: string;
  season: string;
  code: number;
  web_name: string;
  position: string;
  team_code: number;
  team_short_name: string;
  now_cost: number | null;
  selected_by_percent: number | null;
  availability_status: string | null;
  chance_of_playing: number | null;
  availability_multiplier: number | null;
  form: PlayerForm | null;
  avg_minutes_last_5: number | null;
  fixtures: PlayerFixture[];
}

export interface ForecastRun {
  run_id: string;
  as_of: string;
  season: string;
  gw_from: number;
  gw_to: number;
  horizon_gameweeks: number;
}

export interface DashboardManifest {
  schema: string;
  json_schema_version: number;
  generated_at: string;
  ease_index_formula_version: string;
  run_ids: string[];
  runs: ForecastRun[];
  source: {
    export_schema: string;
    export_schema_version: number;
    semantic_contract_version: number;
    export_content_sha256: string;
    export_created_at: string;
    database_sha256: string;
  };
  files: Record<string, { row_count: number; sha256: string }>;
  content_sha256: string;
}
