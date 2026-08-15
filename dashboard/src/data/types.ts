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

// ---- next_gw.json (P1.7d): optimizer plans joined to forecast EV and overlay context ----

export type PlanRole = "starting_xi" | "bench_goalkeeper" | "bench_outfield";

export interface ComponentModes {
  attacking?: string | null;
  assists?: string | null;
  appearance?: string | null;
  share_signal?: string | null;
  [key: string]: string | null | undefined;
}

export interface PlanPlayer {
  code: number;
  web_name: string;
  position: string;
  team_code: number;
  team_short_name: string;
  now_cost: number | null;
  role: PlanRole;
  bench_order_index: number | null;
  is_captain: boolean;
  is_vice_captain: boolean;
  transferred_in: boolean;
  transferred_out: boolean;
  expected_points: number | null;
}

export interface PlanWeek {
  gw: number;
  hit_points: number;
  squad_cost: number;
  captain_code: number;
  vice_captain_code: number;
  players: PlanPlayer[];
}

export interface SquadContext {
  selected_by_percent: number | null;
  availability_status: string | null;
  chance_of_playing: number | null;
  availability_multiplier: number | null;
  cold_start_player: boolean;
  stage_a_league_average_team: boolean;
  attacking_signal_cold_start: boolean;
  assist_signal_cold_start: boolean;
  transferred_no_rescale: boolean;
}

export interface NextGwPlan {
  optimizer_run_id: string;
  decision_sha256: string;
  forecast_run_id: string;
  as_of: string | null;
  season: string;
  gw_from: number;
  gw_to: number;
  component_modes: ComponentModes | null;
  weeks: PlanWeek[];
  player_xp: Record<string, Record<string, number | null>>;
  squad_context: Record<string, SquadContext>;
}

// ---- summary.json (P1.7d): the landing snapshot ----

export interface SummaryPlayer {
  code: number;
  web_name: string | null;
  position: string | null;
  team_short_name: string | null;
  expected_points: number | null;
}

export interface SummaryFixture {
  team_short_name: string | null;
  opponent_short_name: string | null;
  was_home: boolean | null;
  overall_ease_index: number | null;
  official_fdr: number | null;
}

export interface SummaryPlan {
  optimizer_run_id: string;
  decision_sha256: string;
  forecast_run_id: string;
  component_modes: ComponentModes | null;
}

export interface SummaryData {
  latest_run: {
    run_id: string;
    as_of: string | null;
    created_at: string | null;
    season: string;
    gw_from: number;
    gw_to: number;
    status: string | null;
    component_modes: ComponentModes | null;
  } | null;
  roster: { players: number; teams: number };
  next_gameweek: {
    gw: number;
    first_kickoff: string | null;
    last_kickoff: string | null;
    fixture_count: number | null;
  } | null;
  top_xp: SummaryPlayer[];
  horizon_top_xp: SummaryPlayer[];
  flagged_top_xp: SummaryPlayer[];
  easiest_fixtures: SummaryFixture[];
  hardest_fixtures: SummaryFixture[];
  optimizer_plans: SummaryPlan[];
  ease_index_formula_version: string | null;
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
