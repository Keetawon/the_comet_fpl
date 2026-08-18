// Bridge to the local plan server (src/fpl/jobs/plan_server.py, stdlib HTTP on :8765).
// The browser never computes and never queries anything: POST /plan asks the local Python
// process to run the SAME fail-closed jobs (optimizer + publish chain) and republish the
// static read models; the page then refetches them like any other reload.

export const PLAN_SERVER_PORT = 8765;

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
}

/** null means the server is not running (offline chip; the command stays the fallback). */
function tokenHeaders(token?: string | null): Record<string, string> {
  const clean = token?.trim();
  // This non-simple header intentionally triggers the browser-managed CORS OPTIONS preflight.
  // JavaScript cannot attach credentials to that preflight; the server must advertise this
  // header in Access-Control-Allow-Headers and authenticate the following GET/POST request.
  return clean ? { "X-FPL-Plan-Token": clean } : {};
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
