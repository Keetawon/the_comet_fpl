// Read-model shapes as emitted by fpl.publish.dashboard_json (schema
// fpl.dashboard-read-models v8; see docs/dashboard-json-contract.md).
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

/** One finalized observed fixture for a club in the enclosing explicit season. */
export interface TeamActualFixture {
  gw: number;
  fixture: number;
  kickoff_time: string;
  opponent_team_code: number;
  opponent_short_name: string;
  was_home: boolean;
  goals_for: number;
  goals_against: number;
  team_xg: number | null;
  team_xgc: number | null;
  /** Sum of the published player BPS rows for the fixture, not an average. */
  team_bps: number | null;
  /** Sum of published raw outfield defensive-contribution actions, not fantasy DC points. */
  defensive_contribution: number | null;
}

export interface TeamActualsRecord {
  season: string;
  team_code: number;
  actuals: TeamActualFixture[];
}

export interface TeamActualsData {
  schema: "fpl.dashboard-team-actuals";
  json_schema_version: 9;
  teams: TeamActualsRecord[];
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

/** One finalized observed fixture for a player in the enclosing explicit season. */
export interface PlayerActualFixture {
  gw: number;
  fixture: number;
  kickoff_time: string;
  team_code: number;
  team_short_name: string;
  opponent_team_code: number;
  opponent_short_name: string;
  was_home: boolean;
  minutes: number | null;
  starts: number | null;
  goals_scored: number | null;
  assists: number | null;
  clean_sheets: number | null;
  goals_conceded: number | null;
  saves: number | null;
  bonus: number | null;
  bps: number | null;
  defensive_contribution: number | null;
  expected_goals: number | null;
  expected_assists: number | null;
  expected_goals_conceded: number | null;
  points_under_rules_2026_27: number | null;
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
  /** True when the selected forecast vintage used its no-history player path. */
  cold_start_player: boolean;
  form: PlayerForm | null;
  avg_minutes_last_5: number | null;
  fixtures: PlayerFixture[];
}

/** Finalized fixture facts normalised once per season/player across forecast vintages. */
export interface PlayerActualsRecord {
  season: string;
  code: number;
  actuals: PlayerActualFixture[];
}

export interface PlayerActualsData {
  schema: "fpl.dashboard-player-actuals";
  json_schema_version: 9;
  players: PlayerActualsRecord[];
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

/** Canonical positional order retained in the compact schema-v9 wire payload. */
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
  json_schema_version: 9;
  semantics: PlayerHorizonSemantics;
  horizon_fields: typeof PLAYER_HORIZON_FIELDS;
  players: PlayerHorizonsRecord[];
}

/** Serialized payload shape before the loader decodes positional horizon values. */
export interface PlayerHorizonsWireData {
  schema: "fpl.dashboard-player-horizons";
  json_schema_version: 9;
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

// ---- schema-v9 prediction monitoring: immutable forecasts joined to final outcomes ----

export interface ForecastAccuracySemantics {
  [key: string]: unknown;
}

export interface ForecastAccuracyScoreBlock {
  rows: number;
  distribution_rows: number;
  forecast_total: number | null;
  actual_total: number | null;
  forecast_mean: number | null;
  actual_mean: number | null;
  /** Actual minus forecast. Positive means the model under-predicted this measure. */
  bias: number | null;
  mae: number | null;
  rmse: number | null;
  crps: number | null;
}

export interface CleanSheetScoreBlock {
  rows: number;
  predicted_mean: number | null;
  observed_rate: number | null;
  brier: number | null;
}

export interface ForecastAccuracyRunProvenance {
  run_id: string;
  as_of: string | null;
  created_at: string | null;
  season: string;
  gw_from: number;
  gw_to: number;
  status: string | null;
  component_modes: ComponentModes | null;
}

export interface PlayerForecastCoverage {
  forecast_rows: number;
  pending_rows: number;
  final_eligible_rows: number;
  missing_outcome_rows: number;
  legacy_unavailable_rows: number;
  scored_rows: number;
  distribution_scored_rows: number;
}

export interface PlayerAccuracyByPosition extends ForecastAccuracyScoreBlock {
  position: string;
}

export interface PlayerAccuracyByGameweek extends ForecastAccuracyScoreBlock {
  gw: number;
}

export interface PlayerAccuracyByTeam extends ForecastAccuracyScoreBlock {
  team_id: number;
  team_code: number | null;
  team_name: string;
  team_short_name: string;
}

export type PlayerCalibrationEvent = "points_le" | "points_ge";

export interface PlayerForecastCalibration {
  event: PlayerCalibrationEvent;
  threshold: 2 | 6 | 10;
  bucket: string;
  rows: number;
  predicted_mean: number;
  observed_rate: number;
}

export interface PlayerForecastObservation {
  gw: number;
  code: number;
  web_name: string;
  position: string;
  team_id: number;
  team_code: number | null;
  team_name: string;
  team_short_name: string;
  forecast_xp: number;
  actual_points: number;
  /** Actual points minus forecast xP. */
  residual: number;
  absolute_error: number;
  crps: number | null;
  p_le_2: number | null;
  p_ge_2: number | null;
  p_ge_6: number | null;
  p_ge_10: number | null;
}

export interface PlayerForecastAccuracyRun extends ForecastAccuracyRunProvenance {
  coverage: PlayerForecastCoverage;
  overall: ForecastAccuracyScoreBlock;
  by_position: PlayerAccuracyByPosition[];
  by_gw: PlayerAccuracyByGameweek[];
  by_team: PlayerAccuracyByTeam[];
  calibration: PlayerForecastCalibration[];
  observations: PlayerForecastObservation[];
}

export interface PlayerForecastVsActualData {
  schema: "fpl.dashboard-player-forecast-vs-actual";
  json_schema_version: 9;
  semantics: ForecastAccuracySemantics;
  has_outcomes: boolean;
  runs: PlayerForecastAccuracyRun[];
  /** Optional publication metadata loaded beside the exact JSON envelope. */
  manifest: DashboardManifest | null;
}

export interface TeamForecastCoverage {
  forecast_rows: number;
  pending_rows: number;
  missing_outcome_rows: number;
  invalid_fixture_rows: number;
  scored_rows: number;
  attack_distribution_scored_rows: number;
  defence_distribution_scored_rows: number;
  clean_sheet_scored_rows: number;
}

export interface TeamAccuracyScoreSet {
  attack: ForecastAccuracyScoreBlock;
  defence: ForecastAccuracyScoreBlock;
  clean_sheet: CleanSheetScoreBlock;
}

export interface TeamAccuracyByGameweek extends TeamAccuracyScoreSet {
  gw: number;
}

export interface TeamAccuracyByTeam extends TeamAccuracyScoreSet {
  team_id: number;
  team_code: number | null;
  team_name: string;
  team_short_name: string;
}

export interface TeamAccuracyByVenue extends TeamAccuracyScoreSet {
  venue: "home" | "away";
}

export interface TeamAccuracyByFallback extends TeamAccuracyScoreSet {
  stage_a_league_average_team: boolean;
}

export type TeamCalibrationEvent = "goals_ge" | "clean_sheet";

export interface TeamForecastCalibration {
  event: TeamCalibrationEvent;
  threshold: 1 | 2 | 3 | null;
  bucket: string;
  rows: number;
  predicted_mean: number;
  observed_rate: number;
}

export interface TeamForecastObservation {
  fixture: number;
  gw: number;
  kickoff_time: string | null;
  team_id: number;
  team_code: number | null;
  team_name: string;
  team_short_name: string;
  opponent_team_id: number;
  opponent_team_code: number | null;
  opponent_team_name: string;
  opponent_team_short_name: string;
  was_home: boolean;
  lambda_for: number;
  actual_goals_for: number;
  /** Actual goals scored minus lambda_for. Positive means more goals than forecast. */
  attack_residual: number;
  lambda_against: number;
  actual_goals_against: number;
  /** Actual goals conceded minus lambda_against. Positive is worse for the defending club. */
  defence_residual: number;
  probability_clean_sheet: number;
  actual_clean_sheet: boolean;
  attack_crps: number | null;
  defence_crps: number | null;
  clean_sheet_brier: number;
  stage_a_league_average_team: boolean;
}

export interface TeamForecastAccuracyRun extends ForecastAccuracyRunProvenance, TeamAccuracyScoreSet {
  coverage: TeamForecastCoverage;
  by_gw: TeamAccuracyByGameweek[];
  by_team: TeamAccuracyByTeam[];
  by_venue: TeamAccuracyByVenue[];
  by_fallback: TeamAccuracyByFallback[];
  calibration: TeamForecastCalibration[];
  observations: TeamForecastObservation[];
}

export interface TeamForecastVsActualData {
  schema: "fpl.dashboard-team-forecast-vs-actual";
  json_schema_version: 9;
  semantics: ForecastAccuracySemantics;
  has_outcomes: boolean;
  runs: TeamForecastAccuracyRun[];
  /** Optional publication metadata loaded beside the exact JSON envelope. */
  manifest: DashboardManifest | null;
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
