// Bridge to the local plan server (src/fpl/jobs/plan_server.py, stdlib HTTP on :8765).
// The browser never computes and never queries anything: POST /plan asks the local Python
// process to run the SAME fail-closed jobs (optimizer + publish chain) and republish the
// static read models; the page then refetches them like any other reload.

export const PLAN_SERVER_PORT = 8765;
export const PLAN_SERVER_START_COMMAND =
  ".\\.venv\\Scripts\\python.exe -m fpl.jobs.plan_server";

export function planServerUrl(): string {
  // hostname-relative so it works from localhost dev AND the LAN preview on a phone.
  return `http://${window.location.hostname}:${PLAN_SERVER_PORT}`;
}

export interface PlanServerStatus {
  busy: boolean;
  stage: string | null;
  last_error: string | null;
  last_result: PlanSummary | null;
  worktree_clean: boolean;
  forecast_ready: boolean;
  /** Optional only for compatibility with an already-running pre-handshake server. */
  runtime?: PlanServerRuntime | null;
}

export interface PlanServerRuntime {
  python_executable: string;
  python_prefix: string;
  pulp_package_version: string | null;
  cbc_binary_version: string | null;
  solver_ready: boolean;
}

export interface PlanSummary {
  optimizer_run_id: string;
  decision_sha256: string;
  gw: number;
  gw_expected_points: number;
  horizon_expected_points: number;
  hit_points: number;
  squad_cost_tenths: number;
  captain: string;
  vice_captain: string;
  /** Present for a manager-owned transfer plan. */
  manager_capture_id?: string;
  manager_entry_name?: string;
  manager_planning_gw?: number;
  manager_existing_hit_points?: number;
  manager_initial_free_transfers?: number;
  manager_bank_tenths?: number;
  manager_squad_selling_value_tenths?: number;
  manager_weeks?: ManagerPlanWeekSummary[];
}

export interface ManagerPlanPlayerRef {
  code: number;
  web_name: string | null;
}

export interface ManagerPlanWeekSummary {
  gw: number;
  transfers_in: ManagerPlanPlayerRef[];
  transfers_out: ManagerPlanPlayerRef[];
  free_transfers_before: number;
  free_transfers_after: number;
  hit_points: number;
  bank_before_tenths: number;
  bank_after_tenths: number;
}

export type ManagerPlayerPosition = "GK" | "DEF" | "MID" | "FWD";

export interface ManagerTeamPlayer {
  element_id: number;
  code: number;
  web_name: string;
  position: ManagerPlayerPosition;
  team_id: number;
  team_code: number;
  /** Deadline now-cost from the captured bootstrap, not this manager's sale value. */
  now_cost: number;
  purchase_price: number;
  selling_price: number;
}

/** One immutable, mapped manager-team capture returned by both manager-team endpoints. */
export interface ManagerTeamPreview {
  capture_id: string;
  captured_at: string;
  manager_id: number;
  entry_name: string;
  picks_event: number;
  planning_gw: number;
  bank_tenths: number;
  squad_selling_value_tenths: number;
  free_transfers_available: number;
  free_transfers_source: string;
  existing_hit_points: number;
  players: ManagerTeamPlayer[];
}

/** null means the server is not running (offline chip; the command stays the fallback). */
function tokenHeaders(token?: string | null): Record<string, string> {
  const clean = token?.trim();
  // This non-simple header intentionally triggers the browser-managed CORS OPTIONS preflight.
  // JavaScript cannot attach credentials to that preflight; the server must advertise this
  // header in Access-Control-Allow-Headers and authenticate the following GET/POST request.
  return clean ? { "X-FPL-Plan-Token": clean } : {};
}

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be a JSON object.`);
  }
  return value as Record<string, unknown>;
}

function stringField(
  value: Record<string, unknown>,
  key: string,
  { allowEmpty = false }: { allowEmpty?: boolean } = {},
): string {
  const item = value[key];
  if (typeof item !== "string" || (!allowEmpty && !item.trim())) {
    throw new Error(`manager-team response has an invalid ${key}.`);
  }
  return item;
}

function integerField(
  value: Record<string, unknown>,
  key: string,
  minimum: number,
): number {
  const item = value[key];
  if (!Number.isSafeInteger(item) || Number(item) < minimum) {
    throw new Error(`manager-team response has an invalid ${key}.`);
  }
  return Number(item);
}

/** Validate the network boundary instead of trusting a TypeScript assertion over JSON. */
export function parseManagerTeamPreview(payload: unknown): ManagerTeamPreview {
  const value = record(payload, "manager-team response");
  const rawPlayers = value.players;
  if (!Array.isArray(rawPlayers) || rawPlayers.length !== 15) {
    throw new Error("manager-team response must contain exactly 15 players.");
  }
  const positions = new Set<ManagerPlayerPosition>(["GK", "DEF", "MID", "FWD"]);
  const players = rawPlayers.map((rawPlayer, index): ManagerTeamPlayer => {
    const player = record(rawPlayer, `manager-team player ${index + 1}`);
    const position = stringField(player, "position");
    if (!positions.has(position as ManagerPlayerPosition)) {
      throw new Error(`manager-team player ${index + 1} has an invalid position.`);
    }
    return {
      element_id: integerField(player, "element_id", 1),
      code: integerField(player, "code", 1),
      web_name: stringField(player, "web_name"),
      position: position as ManagerPlayerPosition,
      team_id: integerField(player, "team_id", 1),
      team_code: integerField(player, "team_code", 1),
      now_cost: integerField(player, "now_cost", 0),
      purchase_price: integerField(player, "purchase_price", 0),
      selling_price: integerField(player, "selling_price", 0),
    };
  });
  if (new Set(players.map((player) => player.element_id)).size !== players.length) {
    throw new Error("manager-team response contains duplicate element ids.");
  }
  if (new Set(players.map((player) => player.code)).size !== players.length) {
    throw new Error("manager-team response contains duplicate player codes.");
  }

  const preview: ManagerTeamPreview = {
    capture_id: stringField(value, "capture_id"),
    captured_at: stringField(value, "captured_at"),
    manager_id: integerField(value, "manager_id", 1),
    entry_name: stringField(value, "entry_name", { allowEmpty: true }),
    picks_event: integerField(value, "picks_event", 1),
    planning_gw: integerField(value, "planning_gw", 1),
    bank_tenths: integerField(value, "bank_tenths", 0),
    squad_selling_value_tenths: integerField(
      value,
      "squad_selling_value_tenths",
      0,
    ),
    free_transfers_available: integerField(value, "free_transfers_available", 0),
    free_transfers_source: stringField(value, "free_transfers_source"),
    existing_hit_points: integerField(value, "existing_hit_points", 0),
    players,
  };
  const sellingTotal = players.reduce((total, player) => total + player.selling_price, 0);
  if (sellingTotal !== preview.squad_selling_value_tenths) {
    throw new Error(
      "manager-team response squad selling value does not match its 15 player prices.",
    );
  }
  return preview;
}

async function postManagerTeam(
  path: "/manager-team" | "/manager-team/capture",
  body: Record<string, unknown>,
  token?: string | null,
): Promise<ManagerTeamPreview> {
  const response = await fetch(`${planServerUrl()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...tokenHeaders(token) },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(30_000),
  });
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`plan server returned ${response.status} without valid JSON.`);
  }
  const envelope = record(payload, "plan server response");
  if (!response.ok || envelope.ok === false) {
    throw new Error(
      typeof envelope.error === "string" && envelope.error.trim()
        ? envelope.error
        : `plan server returned ${response.status}`,
    );
  }
  return parseManagerTeamPreview(envelope);
}

/** Fetch and persist a new immutable current-team capture for one public FPL manager. */
export function fetchManagerTeam(
  managerId: number | string,
  token?: string | null,
): Promise<ManagerTeamPreview> {
  const clean = String(managerId).trim();
  if (!/^\d{1,10}$/.test(clean) || Number(clean) <= 0) {
    return Promise.reject(new Error("FPL manager id must be a positive integer."));
  }
  return postManagerTeam("/manager-team", { manager_id: Number(clean) }, token);
}

/** Reload an already captured team exactly; this never substitutes a newer live team. */
export function fetchManagerTeamCapture(
  captureId: string,
  token?: string | null,
): Promise<ManagerTeamPreview> {
  const clean = captureId.trim();
  if (!clean) return Promise.reject(new Error("Manager capture id must not be empty."));
  return postManagerTeam("/manager-team/capture", { capture_id: clean }, token);
}

export async function fetchPlanStatus(token?: string | null): Promise<PlanServerStatus | null> {
  try {
    const response = await fetch(`${planServerUrl()}/status`, {
      headers: tokenHeaders(token),
      signal: AbortSignal.timeout(4000),
    });
    if (!response.ok) return null;
    return (await response.json()) as PlanServerStatus;
  } catch {
    return null;
  }
}

export interface SolveRequest {
  locks: number[];
  excludes: number[];
  minBenchAppearance: number | null;
}

export interface SolveManagerPlanRequest extends SolveRequest {
  captureId: string;
  /** null uses the capture's measured/derived free-transfer count. */
  freeTransfersOverride: number | null;
}

/** POST the wizard's rules and wait for the full solve + republish (minutes, not seconds).
 * onStage is polled from GET /status while the POST is in flight so the UI can show progress. */
export async function solvePlan(
  request: SolveRequest,
  onStage?: (stage: string | null) => void,
  token?: string | null,
): Promise<PlanSummary> {
  const poll = window.setInterval(() => {
    void fetchPlanStatus(token).then((status) => onStage?.(status?.stage ?? null));
  }, 2500);
  try {
    const response = await fetch(`${planServerUrl()}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...tokenHeaders(token) },
      body: JSON.stringify({
        locks: request.locks,
        excludes: request.excludes,
        min_bench_appearance: request.minBenchAppearance,
      }),
      signal: AbortSignal.timeout(10 * 60 * 1000),
    });
    const payload = (await response.json()) as { ok: boolean; error?: string } & PlanSummary;
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error ?? `plan server returned ${response.status}`);
    }
    return payload;
  } finally {
    window.clearInterval(poll);
  }
}

/** Solve a transfer path from one exact manager capture, including transfer-hit accounting. */
export async function solveManagerPlan(
  request: SolveManagerPlanRequest,
  onStage?: (stage: string | null) => void,
  token?: string | null,
): Promise<PlanSummary> {
  const captureId = request.captureId.trim();
  if (!captureId) throw new Error("Manager capture id must not be empty.");
  const poll = window.setInterval(() => {
    void fetchPlanStatus(token).then((status) => onStage?.(status?.stage ?? null));
  }, 2500);
  try {
    const response = await fetch(`${planServerUrl()}/manager-plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...tokenHeaders(token) },
      body: JSON.stringify({
        capture_id: captureId,
        locks: request.locks,
        excludes: request.excludes,
        min_bench_appearance: request.minBenchAppearance,
        free_transfers_override: request.freeTransfersOverride,
      }),
      signal: AbortSignal.timeout(10 * 60 * 1000),
    });
    const payload = (await response.json()) as {
      ok: boolean;
      error?: string;
    } & PlanSummary;
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error ?? `plan server returned ${response.status}`);
    }
    return payload;
  } finally {
    window.clearInterval(poll);
  }
}
