const SQUAD_DRAFT_ROUTE = "squad-draft";
const OPTIMIZER_RUN_PARAM = "optimizer_run_id";
const SOURCE_PARAM = "source";
const MANAGER_CAPTURE_PARAM = "manager_capture_id";
const SERVER_TOKEN_PARAM = "server_token";

export type SquadDraftHandoffSource = "optimized" | "manager_current";

export interface SquadDraftHandoff {
  source: SquadDraftHandoffSource;
  optimizerRunId: string;
  managerCaptureId: string | null;
}

export interface SquadDraftHandoffOptions {
  source?: SquadDraftHandoffSource;
  managerCaptureId?: string | null;
  /** Fragment-only local plan-server credential, never sent to the dashboard HTTP server. */
  serverToken?: string | null;
}

function oneNonempty(
  params: URLSearchParams,
  key: string,
  label: string,
): string | null {
  if (!params.has(key)) return null;
  const values = params.getAll(key);
  if (values.length !== 1 || !values[0].trim()) {
    throw new Error(`Squad Draft handoff has an invalid ${label}.`);
  }
  return values[0].trim();
}

export function squadDraftHandoffHref(
  optimizerRunId: string,
  options: SquadDraftHandoffOptions = {},
): string {
  const runId = optimizerRunId.trim();
  if (!runId) throw new Error("Squad Draft handoff requires an optimizer run id.");
  const source = options.source ?? "optimized";
  const captureId = options.managerCaptureId?.trim() ?? "";
  if (source === "manager_current" && !captureId) {
    throw new Error("Current-team Squad Draft handoff requires a manager capture id.");
  }
  if (source === "optimized" && captureId) {
    throw new Error("Optimized Squad Draft handoff cannot carry a manager capture id.");
  }
  const params = new URLSearchParams();
  params.set(OPTIMIZER_RUN_PARAM, runId);
  // One-argument callers keep emitting the established legacy optimized link. New
  // multi-source callers pass source explicitly, while the parser treats both forms alike.
  if (options.source != null) params.set(SOURCE_PARAM, source);
  if (captureId) params.set(MANAGER_CAPTURE_PARAM, captureId);
  const token = options.serverToken?.trim();
  if (token) params.set(SERVER_TOKEN_PARAM, token);
  return `#${SQUAD_DRAFT_ROUTE}?${params.toString()}`;
}

/** Parse one typed handoff. A legacy optimizer_run_id-only link means optimized. */
export function squadDraftHandoff(hash: string): SquadDraftHandoff | null {
  const fragment = hash.startsWith("#") ? hash.slice(1) : hash;
  const [route, query = ""] = fragment.split("?", 2);
  if (route !== SQUAD_DRAFT_ROUTE) return null;
  const params = new URLSearchParams(query);
  const optimizerRunId = oneNonempty(
    params,
    OPTIMIZER_RUN_PARAM,
    "optimizer run id",
  );
  const rawSource = oneNonempty(params, SOURCE_PARAM, "source");
  const managerCaptureId = oneNonempty(
    params,
    MANAGER_CAPTURE_PARAM,
    "manager capture id",
  );
  if (optimizerRunId == null) {
    if (rawSource != null || managerCaptureId != null) {
      throw new Error("Squad Draft handoff requires an optimizer run id.");
    }
    return null;
  }
  const source = rawSource ?? "optimized";
  if (source !== "optimized" && source !== "manager_current") {
    throw new Error("Squad Draft handoff has an invalid source.");
  }
  if (source === "manager_current" && managerCaptureId == null) {
    throw new Error("Current-team Squad Draft handoff requires a manager capture id.");
  }
  if (source === "optimized" && managerCaptureId != null) {
    throw new Error("Optimized Squad Draft handoff cannot carry a manager capture id.");
  }
  return { source, optimizerRunId, managerCaptureId };
}

/** Compatibility helper for existing callers that only need the exact optimizer run id. */
export function squadDraftHandoffRunId(hash: string): string | null {
  return squadDraftHandoff(hash)?.optimizerRunId ?? null;
}

export function clearSquadDraftHandoff(): void {
  const fragment = window.location.hash.startsWith("#")
    ? window.location.hash.slice(1)
    : window.location.hash;
  const [route, query = ""] = fragment.split("?", 2);
  const params = new URLSearchParams(route === SQUAD_DRAFT_ROUTE ? query : "");
  params.delete(OPTIMIZER_RUN_PARAM);
  params.delete(SOURCE_PARAM);
  params.delete(MANAGER_CAPTURE_PARAM);
  const suffix = params.toString();
  const next =
    `${window.location.pathname}${window.location.search}#${SQUAD_DRAFT_ROUTE}` +
    (suffix ? `?${suffix}` : "");
  window.history.replaceState(window.history.state, "", next);
}
