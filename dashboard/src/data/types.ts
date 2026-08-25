// Read-model shapes as emitted by fpl.publish.dashboard_json (schema
// fpl.dashboard-read-models v4; see docs/dashboard-json-contract.md).
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

/**
 * Official fixture identity from the latest BI export. These rows carry current official FDR
 * but no forecast/ease fields: they are current schedule context, not a recorded vintage.
 */
export interface ScheduleFixture {
  gw: number;
  fixture: number;
  kickoff_time: string | null;
  opponent_team_code: number;
  opponent_short_name: string;
  was_home: boolean | null;
  /** Added in schedule schema v2; absent in legacy v1 read models. */
  official_fdr?: number | null;
}

export interface ScheduleTeam {
  season: string;
  team_code: number;
  team_name: string;
  short_name: string;
  fixtures: ScheduleFixture[];
}

export interface FixtureScheduleOverlay {
  schema_version: 1 | 2;
  semantics: "current_at_export_not_forecast_vintage";
  export_created_at: string;
  database_sha256: string;
  teams: ScheduleTeam[];
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
  clean_sheets: number | null;
  /** Goals conceded while the player was on the pitch, not the club's full-match total. */
  goals_conceded: number | null;
  saves: number | null;
  bonus: number | null;
  bps: number | null;
  defensive_contribution: number | null;
  expected_goals: number | null;
  expected_assists: number | null;
  expected_goals_conceded: number | null;
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

/** One exact endpoint lookup with six-decimal published scalars, for all fixtures. */
export interface PlayerHorizon {
  gw_to: number;
  xp: number;
  p_le_2: number;
  p_ge_2: number;
  p_ge_4: number;
  p_ge_6: number;
  p_ge_10: number;
  p_ge_15: number;
}

/** Canonical positional order in the compact schema-v4 wire payload. */
export const PLAYER_HORIZON_FIELDS = [
  "gw_to",
  "xp",
  "p_le_2",
  "p_ge_2",
  "p_ge_4",
  "p_ge_6",
  "p_ge_10",
  "p_ge_15",
] as const;

export type PlayerHorizonWire = [
  gw_to: number,
  xp: number,
  p_le_2: number,
  p_ge_2: number,
  p_ge_4: number,
  p_ge_6: number,
  p_ge_10: number,
  p_ge_15: number,
];

export interface PlayerHorizonsRecord {
  run_id: string;
  season: string;
  code: number;
  horizons: PlayerHorizon[];
}

export interface PlayerHorizonsWireRecord {
  run_id: string;
  season: string;
  code: number;
  horizons: PlayerHorizonWire[];
}

export interface PlayerHorizonSemantics {
  grain: ["run_id", "season", "code", "gw_to"];
  cumulative_from: "dim_forecast_run.gw_from";
  distribution_combination: "independent-gameweek-convolution-v1";
  availability: "raw-model-distribution-unadjusted";
  thresholds: {
    p_le: [2];
    p_ge: [2, 4, 6, 10, 15];
  };
  value_decimal_places: 6;
  probability_boundary_policy: "preserve-exact-zero-one-v1";
}

export interface PlayerHorizonsData {
  schema: "fpl.dashboard-player-horizons";
  json_schema_version: 4;
  semantics: PlayerHorizonSemantics;
  horizon_fields: typeof PLAYER_HORIZON_FIELDS;
  players: PlayerHorizonsRecord[];
}

/** Serialized payload shape before the loader decodes positional horizon values. */
export interface PlayerHorizonsWireData {
  schema: "fpl.dashboard-player-horizons";
  json_schema_version: 4;
  semantics: PlayerHorizonSemantics;
  horizon_fields: typeof PLAYER_HORIZON_FIELDS;
  players: PlayerHorizonsWireRecord[];
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
  attacking_mode?: string | null;
  assists_mode?: string | null;
  appearance_mode?: string | null;
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

export type PlanKind = "platform_default" | "platform_diagnostic" | "user_custom";

export interface PlanPolicySummary {
  locked_codes: number[];
  excluded_codes: number[];
  min_bench_appearance: number;
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
  plan_kind: PlanKind;
  display_label: string;
  policy: PlanPolicySummary;
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
  plan_kind: PlanKind;
  display_label: string;
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

// ---- forecast_vs_actual.json (P1.7e): vintages scored against finalised outcomes ----

export interface ScoreBlock {
  rows: number;
  mean_ev: number | null;
  mean_actual: number | null;
  bias: number | null;
  mae: number | null;
  crps: number | null;
}

export interface FvaPosition extends ScoreBlock {
  position: string;
}

export interface FvaGw extends ScoreBlock {
  gw: number;
}

export interface FvaCalibration {
  bucket: string;
  threshold_points: number;
  rows: number;
  predicted_mean: number;
  observed_rate: number;
}

export interface FvaRun extends ScoreBlock {
  run_id: string;
  season: string;
  gw_from: number;
  gw_to: number;
  by_position: FvaPosition[];
  by_gw: FvaGw[];
  calibration: FvaCalibration[];
}

export interface ForecastVsActualData {
  has_outcomes: boolean;
  runs: FvaRun[];
}

// ---- optimizer_audit.json (P1.7e): provenance behind each optimizer decision ----

export interface AuditProvenance {
  optimizer_commit_sha: string;
  optimizer_worktree_clean: boolean;
  forecast_artifact_sha256: string;
  forecast_commit_sha: string;
  squad_rules_path: string;
  squad_rules_contract_version: string;
  squad_rules_sha256: string;
}

export interface AuditSolver {
  name: string;
  package: string;
  package_version: string;
  binary_version: string;
  options: string[];
  seed: number;
  status: string;
}

export interface SearchPolicy {
  candidate_pool_per_position: number;
  transfer_depth: number;
  transition_limit_per_state: number;
  beam_width: number;
  free_transfer_per_gameweek: number;
  free_transfer_bank_cap: number;
  hit_cost_points: number;
  maximum_transfers_per_gameweek: number;
  risk_lambda: number;
  min_bench_appearance: number;
  locked_codes: number[];
  excluded_codes: number[];
  plan_origin: "platform" | "user_custom";
  search_method: string;
  optimality_scope: string;
  [key: string]: unknown;
}

export interface RulesPosition {
  position: string;
  squad: number;
  minimum_starters: number;
  maximum_starters: number;
}

export interface RulesSnapshot {
  contract_version: string;
  season: string;
  squad_size: number;
  budget_tenths: number;
  maximum_per_club: number;
  positions: RulesPosition[];
  lineup_starters: number;
  captain_multiplier: number;
  goalkeeper_bench_slots: number;
  outfield_bench_slots: number;
  [key: string]: unknown;
}

export interface AuditPlan {
  optimizer_run_id: string;
  decision_sha256: string;
  forecast_run_id: string;
  component_modes: ComponentModes | null;
  plan_kind: PlanKind;
  display_label: string;
  as_of: string | null;
  season: string;
  gw_from: number;
  gw_to: number;
  provenance: AuditProvenance;
  solver: AuditSolver;
  search_policy: SearchPolicy;
  rules_snapshot: RulesSnapshot;
  assumptions: string[];
  status: string;
}

export interface OptimizerAuditData {
  plans: AuditPlan[];
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
