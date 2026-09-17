// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { handleRequest, publicSquad, type Env } from "./manager-import";

function fixture() {
  const types = [1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 4, 4, 4];
  const bootstrap = {
    events: [
      { id: 1, deadline_time: "2026-08-21T17:30:00Z", is_next: false },
      { id: 4, deadline_time: "2026-09-11T17:30:00Z", is_next: false },
      { id: 5, deadline_time: "2026-09-18T17:30:00Z", is_next: true },
    ],
    elements: types.map((element_type, i) => ({ id: i + 1, code: 1000 + i, element_type, team: i + 1 })),
    teams: types.map((_, i) => ({ id: i + 1, code: 100 + i })),
  };
  const entry = { id: 42, current_event: 4, started_event: 3, name: "Not forwarded", player_first_name: "Private" };
  const picks = {
    active_chip: null as string | null, entry_history: { event: 4, bank: 90 },
    picks: types.map((_, i) => ({ element: i + 1, position: i + 1 })),
  };
  const fetcher = vi.fn<typeof fetch>(async input => {
    const url = String(input);
    const payload = url.endsWith("bootstrap-static/") ? bootstrap : url.endsWith("/picks/") ? picks : entry;
    return Response.json(payload);
  });
  return { bootstrap, entry, picks, fetcher };
}
const now = new Date("2026-09-17T03:00:00Z");
const origin = "https://www.thecometfpl.com";
function request(body: unknown = { manager_id: 42 }, headers = {}) {
  return new Request("https://manager-api.thecometfpl.com/manager-team", {
    method: "POST", headers: { Origin: origin, "Content-Type": "application/json", "CF-Connecting-IP": "192.0.2.1", ...headers },
    body: JSON.stringify(body),
  });
}
function environment(success = true): Env {
  return { ALLOWED_ORIGINS: origin, IMPORT_RATE_LIMITER: { limit: vi.fn(async () => ({ success })) } };
}

describe("bounded public FPL team service", () => {
  it("resolves 15 stable identities including late entrants without invented financial fields", async () => {
    const f = fixture();
    const result = await publicSquad(42, f.fetcher, now);
    expect(result).toMatchObject({ season: "2026-27", picks_event: 4, planning_gw: 5, source: "official_fpl_public_picks" });
    expect(result.players).toHaveLength(15);
    expect(result.players[0]).toEqual({ element_id: 1, code: 1000, position: "GK", team_code: 100 });
    for (const field of ["bank", "name", "player_first_name", "free_transfers", "selling_price", "now_cost"]) {
      expect(JSON.stringify(result)).not.toContain(`"${field}"`);
    }
    expect(result).toEqual(await publicSquad(42, f.fetcher, now));
    expect(result.snapshot_id).toMatch(/^[a-f0-9]{64}$/);
    expect(f.fetcher.mock.calls.every(([url, options]) => String(url).startsWith("https://fantasy.premierleague.com/api/") && options?.redirect === "error")).toBe(true);
  });

  it("labels a Free Hit squad rather than inventing permanent ownership", async () => {
    const f = fixture(); f.picks.active_chip = "freehit";
    expect((await publicSquad(42, f.fetcher, now)).active_chip).toBe("freehit");
  });

  it.each(["duplicate", "position", "club", "manager", "event", "future"])("fails closed for %s evidence", async kind => {
    const f = fixture();
    if (kind === "duplicate") f.picks.picks[1].element = 1;
    if (kind === "position") f.bootstrap.elements[0].element_type = 4;
    if (kind === "club") f.bootstrap.teams = [];
    if (kind === "manager") f.entry.id = 43;
    if (kind === "event") f.picks.entry_history.event = 3;
    if (kind === "future") f.bootstrap.events[1].deadline_time = "2026-09-20T00:00:00Z";
    await expect(publicSquad(42, f.fetcher, now)).rejects.toThrow();
  });

  it("returns no-store CORS JSON and never exposes a generic proxy or optimizer", async () => {
    vi.useFakeTimers(); vi.setSystemTime(now);
    try {
      const f = fixture(); const response = await handleRequest(request(), environment(), f.fetcher);
      expect(response.status).toBe(200);
      expect(response.headers.get("Access-Control-Allow-Origin")).toBe(origin);
      expect(response.headers.get("Cache-Control")).toBe("no-store");
      expect(response.headers.get("Access-Control-Allow-Credentials")).toBeNull();
      expect((await response.json()).players).toHaveLength(15);
      for (const path of ["/plan", "/status", "/manager-team?url=https://example.com"]) {
        expect((await handleRequest(new Request(`https://manager-api.thecometfpl.com${path}`, { headers: { Origin: origin } }), environment(), f.fetcher)).status).toBe(404);
      }
    } finally { vi.useRealTimers(); }
  });

  it.each([{ manager_id: -1 }, { manager_id: "42" }, { manager_id: true }, { manager_id: 42, url: "https://example.com" }])("rejects invalid requests before fetching: %j", async body => {
    const f = fixture();
    expect((await handleRequest(request(body), environment(), f.fetcher)).status).toBe(400);
    expect(f.fetcher).not.toHaveBeenCalled();
  });

  it("denies wrong origins, credentials, missing limiter and rate-limited requests", async () => {
    const f = fixture();
    expect((await handleRequest(request(undefined, { Origin: "https://evil.example" }), environment(), f.fetcher)).status).toBe(403);
    expect((await handleRequest(request(undefined, { Authorization: "Bearer never-forward" }), environment(), f.fetcher)).status).toBe(400);
    expect((await handleRequest(request(), { ALLOWED_ORIGINS: origin } as Env, f.fetcher)).status).toBe(503);
    const limited = await handleRequest(request(), environment(false), f.fetcher);
    expect(limited.status).toBe(429); expect(limited.headers.get("Retry-After")).toBe("60");
    expect(f.fetcher).not.toHaveBeenCalled();
  });

  it("allows only a bounded JSON preflight", async () => {
    const response = await handleRequest(new Request("https://manager-api.thecometfpl.com/manager-team", {
      method: "OPTIONS", headers: { Origin: origin, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type" },
    }), environment());
    expect(response.status).toBe(204);
    expect(response.headers.get("Access-Control-Allow-Headers")).toBe("Content-Type");
    expect((await handleRequest(request({ manager_id: "x".repeat(300) }), environment())).status).toBe(413);
  });

  it("retries one transient upstream failure, not missing managers or rate limits", async () => {
    const f = fixture(); f.fetcher.mockRejectedValueOnce(new Error("network"));
    expect((await publicSquad(42, f.fetcher, now)).players).toHaveLength(15);
    expect(f.fetcher).toHaveBeenCalledTimes(4);
    const absent = fixture(); absent.fetcher.mockResolvedValueOnce(new Response(null, { status: 404 }));
    await expect(publicSquad(42, absent.fetcher, now)).rejects.toThrow("not found");
    expect(absent.fetcher).toHaveBeenCalledTimes(2);
  });
});
