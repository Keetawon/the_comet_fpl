/** Public FPL picks only. No optimizer, accounts, database or manager capture store. */
export interface Env {
  ALLOWED_ORIGINS: string;
  IMPORT_RATE_LIMITER: { limit(options: { key: string }): Promise<{ success: boolean }> };
}

class ImportError extends Error {
  constructor(readonly status: number, message: string) { super(message); }
}

const FPL = "https://fantasy.premierleague.com/api/";
const positions: Record<number, string> = { 1: "GK", 2: "DEF", 3: "MID", 4: "FWD" };
const quotas: Record<string, number> = { GK: 2, DEF: 5, MID: 5, FWD: 3 };

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new ImportError(502, "FPL returned incomplete squad data. Please try again later.");
  }
  return value as Record<string, unknown>;
}

function rows(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) throw new ImportError(502, "FPL returned incomplete squad data.");
  return value.map(record);
}

function integer(value: unknown, minimum = 1): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < minimum) {
    throw new ImportError(502, "FPL returned an invalid player or event identity.");
  }
  return value;
}

function instant(value: unknown): string {
  if (typeof value !== "string" || !/(Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value))) {
    throw new ImportError(502, "FPL returned an invalid deadline.");
  }
  return value;
}

async function boundedJson(message: Request | Response, maximum: number): Promise<unknown> {
  const reader = message.body?.getReader();
  if (!reader) throw new ImportError(400, "A JSON request is required.");
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maximum) throw new ImportError(413, "Response or request exceeds the import limit.");
      chunks.push(value);
    }
  } finally { await reader.cancel(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  try { return JSON.parse(new TextDecoder().decode(bytes)) as unknown; }
  catch { throw new ImportError(502, "An unreadable response was received. Please try again later."); }
}

async function upstream(path: string, fetcher: typeof fetch): Promise<Record<string, unknown>> {
  // Only fixed paths and validated numeric IDs; never accept a user-provided upstream URL.
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const response = await fetcher(`${FPL}${path}`, {
        // Workerd supports manual/follow only; non-2xx below rejects every redirect.
        headers: { Accept: "application/json" }, redirect: "manual",
        signal: AbortSignal.timeout(6000),
      });
      if (response.status === 404) throw new ImportError(404, "Manager or published squad not found. Check the Manager ID; picks appear after the first deadline.");
      if (response.status === 429) throw new ImportError(503, "FPL is busy. Please wait before trying again.");
      if (response.status >= 500 && attempt === 0) { await response.body?.cancel(); continue; }
      if (!response.ok || !response.headers.get("Content-Type")?.includes("application/json")) {
        throw new ImportError(502, "FPL is temporarily unavailable. Your draft has not changed.");
      }
      return record(await boundedJson(response, 4_000_000));
    } catch (error) {
      if (error instanceof ImportError) throw error;
      if (attempt === 1) throw new ImportError(504, "FPL could not be reached. Please try again.");
    }
  }
  throw new ImportError(504, "FPL did not respond in time.");
}

export async function publicSquad(managerId: number, fetcher = fetch, now = new Date()) {
  const [bootstrap, entry] = await Promise.all([
    upstream("bootstrap-static/", fetcher), upstream(`entry/${managerId}/`, fetcher),
  ]);
  if (integer(entry.id) !== managerId) throw new ImportError(502, "FPL returned a different manager.");
  const events = rows(bootstrap.events);
  const eventId = integer(entry.current_event);
  const event = events.filter(row => row.id === eventId);
  const first = events.filter(row => row.id === 1);
  const next = events.filter(row => row.is_next === true);
  if (event.length !== 1 || first.length !== 1 || next.length > 1) {
    throw new ImportError(502, "FPL event chronology is unavailable.");
  }
  const deadline = instant(event[0].deadline_time);
  const firstDeadline = instant(first[0].deadline_time);
  if (Date.parse(deadline) > now.getTime() || Date.parse(firstDeadline) > Date.parse(deadline)) {
    throw new ImportError(409, "This squad has not been published by FPL yet.");
  }
  const planningGw = next.length ? integer(next[0].id) : null;
  if (planningGw !== null && (planningGw <= eventId || Date.parse(instant(next[0].deadline_time)) <= now.getTime())) {
    throw new ImportError(409, "FPL is updating the gameweek. Please try again shortly.");
  }
  const year = new Date(firstDeadline).getUTCFullYear();
  const season = `${year}-${String(year + 1).slice(-2)}`;
  const picks = await upstream(`entry/${managerId}/event/${eventId}/picks/`, fetcher);
  if (integer(record(picks.entry_history).event) !== eventId) {
    throw new ImportError(502, "FPL returned picks for a different gameweek.");
  }
  if (picks.active_chip !== null && typeof picks.active_chip !== "string") {
    throw new ImportError(502, "FPL chip status is unavailable.");
  }
  const elements = rows(bootstrap.elements);
  const teams = rows(bootstrap.teams);
  const picked = rows(picks.picks).sort((a, b) => integer(a.position) - integer(b.position));
  if (picked.length !== 15 || new Set(picked.map(row => integer(row.element))).size !== 15 ||
      picked.some((row, index) => integer(row.position) !== index + 1)) {
    throw new ImportError(502, "FPL did not return 15 unique squad members.");
  }
  const players = picked.map(pick => {
    const matches = elements.filter(element => element.id === pick.element);
    if (matches.length !== 1) throw new ImportError(502, "An FPL player identity is unavailable or ambiguous.");
    const player = matches[0];
    const club = teams.filter(team => team.id === player.team);
    const position = positions[integer(player.element_type)];
    if (club.length !== 1 || !position) throw new ImportError(502, "An FPL position or club is unavailable.");
    return {
      element_id: integer(player.id), code: integer(player.code), position,
      team_code: integer(club[0].code),
    };
  });
  if (new Set(players.map(player => player.code)).size !== 15 ||
      Object.entries(quotas).some(([pos, quota]) => players.filter(player => player.position === pos).length !== quota)) {
    throw new ImportError(502, "FPL returned an inconsistent squad shape.");
  }
  // No manager name, bank, prices, transfers, credentials or inferred ownership is returned.
  const result = {
    schema: "fpl.public-manager-squad", schema_version: 1, source: "official_fpl_public_picks",
    manager_id: managerId, season, picks_event: eventId, picks_deadline: deadline,
    planning_gw: planningGw, active_chip: picks.active_chip,
    captured_at: now.toISOString(), players,
  };
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(result)));
  const snapshotId = [...new Uint8Array(hash)].map(byte => byte.toString(16).padStart(2, "0")).join("");
  return { ...result, snapshot_id: snapshotId };
}

export async function handleRequest(request: Request, env: Env, fetcher = fetch): Promise<Response> {
  const origin = request.headers.get("Origin") ?? "";
  const allowed = (env.ALLOWED_ORIGINS ?? "").split(",").map(value => value.trim()).filter(Boolean);
  const headers = new Headers({
    "Content-Type": "application/json", "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff", Vary: "Origin",
  });
  if (allowed.includes(origin)) headers.set("Access-Control-Allow-Origin", origin);
  const reply = (body: unknown, status: number) => new Response(JSON.stringify(body), { status, headers });
  if (!origin || !allowed.includes(origin)) return reply({ error: "Origin is not allowed." }, 403);
  const url = new URL(request.url);
  if (url.pathname !== "/manager-team" || url.search) return reply({ error: "Not found." }, 404);
  if (request.method === "OPTIONS") {
    if (request.headers.get("Access-Control-Request-Method") !== "POST" ||
        (request.headers.get("Access-Control-Request-Headers") ?? "").toLowerCase().split(",").some(header => header.trim() && header.trim() !== "content-type")) {
      return reply({ error: "Unsupported request." }, 403);
    }
    headers.set("Access-Control-Allow-Methods", "POST");
    headers.set("Access-Control-Allow-Headers", "Content-Type");
    return new Response(null, { status: 204, headers });
  }
  if (request.method !== "POST") return reply({ error: "Use POST." }, 405);
  if (request.headers.has("Authorization") || request.headers.has("Cookie") ||
      request.headers.get("Content-Type")?.split(";", 1)[0] !== "application/json") {
    return reply({ error: "Send only a Manager ID as JSON, without credentials." }, 400);
  }
  try {
    // Public data service, not authentication. CORS alone is not abuse protection.
    const ip = request.headers.get("CF-Connecting-IP");
    if (!ip || !env.IMPORT_RATE_LIMITER) throw new ImportError(503, "Manager import is not configured yet.");
    if (!(await env.IMPORT_RATE_LIMITER.limit({ key: ip })).success) {
      headers.set("Retry-After", "60");
      throw new ImportError(429, "Too many imports. Please wait a minute and try again.");
    }
    const body = record(await boundedJson(request, 256));
    if (Object.keys(body).length !== 1 || !Object.hasOwn(body, "manager_id") ||
        typeof body.manager_id !== "number" || !Number.isSafeInteger(body.manager_id) || body.manager_id < 1 || body.manager_id > 9_999_999_999) {
      throw new ImportError(400, "Enter a positive FPL Manager ID (up to 10 digits).");
    }
    return reply(await publicSquad(body.manager_id, fetcher), 200);
  } catch (error) {
    if (error instanceof ImportError) return reply({ error: error.message }, error.status);
    return reply({ error: "Manager import is temporarily unavailable. Please try again later." }, 503);
  }
}

// Keep Cloudflare's third ExecutionContext argument separate from the injectable test fetcher.
export default { fetch: (request: Request, env: Env) => handleRequest(request, env) };
