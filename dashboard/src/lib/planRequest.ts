// The plan-builder wizard cannot run the optimizer (the solver is PuLP/CBC in Python; the
// dashboard is a static renderer of recorded artifacts). When the owner finishes the wizard
// we persist their request here so the Next GW page can show it as explicitly NOT YET
// APPLIED -- the recorded plans predate the rules, and nothing re-solves until the emitted
// command is run and the read models are re-published (dashboard/README.md).

export interface PlanRequestLock {
  code: number;
  web_name: string;
  now_cost: number | null;
}

export interface PlanRequest {
  version: 1;
  createdAt: string;
  threshold: string;
  thresholdLabel: string;
  locks: PlanRequestLock[];
  command: string;
}

export const PLAN_REQUEST_KEY = "fpl-plan-request";

export function readPlanRequest(): PlanRequest | null {
  try {
    const raw = window.localStorage.getItem(PLAN_REQUEST_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PlanRequest;
    if (parsed?.version !== 1 || !Array.isArray(parsed.locks) || typeof parsed.command !== "string") {
      return null;
    }
    return parsed;
  } catch {
    return null; // corrupted or private mode: no panel, never a crash
  }
}

export function writePlanRequest(request: PlanRequest): void {
  try {
    window.localStorage.setItem(PLAN_REQUEST_KEY, JSON.stringify(request));
  } catch {
    /* private mode: the wizard still works, the page just won't show the panel */
  }
}

export function clearPlanRequest(): void {
  try {
    window.localStorage.removeItem(PLAN_REQUEST_KEY);
  } catch {
    /* private mode */
  }
}
