const SQUAD_DRAFT_ROUTE = "squad-draft";
const OPTIMIZER_RUN_PARAM = "optimizer_run_id";

export function squadDraftHandoffHref(optimizerRunId: string): string {
  const runId = optimizerRunId.trim();
  if (!runId) throw new Error("Squad Draft handoff requires an optimizer run id.");
  return `#${SQUAD_DRAFT_ROUTE}?${OPTIMIZER_RUN_PARAM}=${encodeURIComponent(runId)}`;
}

export function squadDraftHandoffRunId(hash: string): string | null {
  const fragment = hash.startsWith("#") ? hash.slice(1) : hash;
  const [route, query = ""] = fragment.split("?", 2);
  if (route !== SQUAD_DRAFT_ROUTE) return null;
  const params = new URLSearchParams(query);
  if (!params.has(OPTIMIZER_RUN_PARAM)) return null;
  const values = params.getAll(OPTIMIZER_RUN_PARAM);
  if (values.length !== 1 || !values[0].trim()) {
    throw new Error("Squad Draft handoff has an invalid optimizer run id.");
  }
  return values[0].trim();
}

export function clearSquadDraftHandoff(): void {
  const next = `${window.location.pathname}${window.location.search}#${SQUAD_DRAFT_ROUTE}`;
  window.history.replaceState(window.history.state, "", next);
}
