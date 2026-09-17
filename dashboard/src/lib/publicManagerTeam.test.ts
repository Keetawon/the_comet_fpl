import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchPublicManagerTeam, parsePublicManagerSquad, publicManagerImportUrl, publicSquadDraft } from "./publicManagerTeam";
import { deriveUserDraftRules } from "./userDraft";
import type { PlayerRecord, RulesSnapshot } from "@/data/types";
import audit from "@/data/sampleOptimizerAudit.json";
import sample from "@/data/samplePlayers.json";

const rules = deriveUserDraftRules(audit.plans[0].rules_snapshot as RulesSnapshot);
const positions = ["GK", "GK", ...Array(5).fill("DEF"), ...Array(5).fill("MID"), ...Array(3).fill("FWD")] as string[];
const players = positions.map((position, i) => ({
  ...sample.players[0], season: "2026-27", position, code: 1000 + i, team_code: 100 + i,
})) as unknown as PlayerRecord[];
const payload = {
  schema: "fpl.public-manager-squad", schema_version: 1, source: "official_fpl_public_picks",
  manager_id: 42, season: "2026-27", picks_event: 4, picks_deadline: "2026-09-11T17:30:00Z",
  planning_gw: 5, captured_at: "2026-09-17T03:00:00Z", snapshot_id: "a".repeat(64), active_chip: null,
  players: players.map((player, i) => ({ code: player.code, team_code: player.team_code, position: player.position, element_id: i + 1 })),
};

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("public membership boundary", () => {
  it("maps only stable codes and preserves published prices and every forecast byte", () => {
    const before = JSON.stringify(players);
    const parsed = parsePublicManagerSquad({ ...payload, bank: 100, manager_name: "not forwarded" }, 42);
    const result = publicSquadDraft(parsed, { season: "2026-27", gw_from: 5 }, players, rules);
    expect(result).toHaveLength(15);
    expect(result[0]).toBe(players[0]);
    expect(JSON.stringify(players)).toBe(before);
    expect(parsed).not.toHaveProperty("bank");
    expect(parsed).not.toHaveProperty("manager_name");
  });

  it.each(["season", "gw", "duplicate", "position", "club", "missing"])("rejects %s mismatch atomically", issue => {
    const parsed = parsePublicManagerSquad(payload, 42);
    const roster = structuredClone(players);
    const forecast = { season: "2026-27", gw_from: 5 };
    if (issue === "season") forecast.season = "2025-26";
    if (issue === "gw") forecast.gw_from = 4;
    if (issue === "duplicate") roster.push(roster[0]);
    if (issue === "position") roster[0].position = "FWD";
    if (issue === "club") roster[0].team_code = 999;
    if (issue === "missing") roster.pop();
    const before = JSON.stringify(roster);
    expect(() => publicSquadDraft(parsed, forecast, roster, rules)).toThrow();
    expect(JSON.stringify(roster)).toBe(before);
  });

  it("rejects wrong manager, future picks, duplicate identity and malformed payloads", () => {
    expect(() => parsePublicManagerSquad(payload, 99)).toThrow();
    expect(() => parsePublicManagerSquad({ ...payload, picks_deadline: "2026-09-18T03:00:00Z" }, 42)).toThrow();
    expect(() => parsePublicManagerSquad({ ...payload, players: Array(15).fill(payload.players[0]) }, 42)).toThrow();
    expect(() => parsePublicManagerSquad(null, 42)).toThrow();
  });

  it("stays disabled without an explicitly configured HTTPS endpoint", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    for (const url of ["", "http://localhost:8765/manager-team", "https://example.com/manager-team?key=secret", "https://user:pass@example.com/manager-team"]) {
      vi.stubEnv("VITE_PUBLIC_MANAGER_IMPORT_URL", url);
      expect(publicManagerImportUrl()).toBeNull();
      await expect(fetchPublicManagerTeam("42")).rejects.toThrow("not been enabled");
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("sends only an ID in a no-store POST without credentials or referrer", async () => {
    vi.stubEnv("VITE_PUBLIC_MANAGER_IMPORT_URL", "https://manager-api.thecometfpl.com/manager-team");
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => payload });
    vi.stubGlobal("fetch", fetcher);
    expect((await fetchPublicManagerTeam("42")).picks_event).toBe(4);
    expect(fetcher).toHaveBeenCalledWith("https://manager-api.thecometfpl.com/manager-team", expect.objectContaining({
      body: '{"manager_id":42}', method: "POST", credentials: "omit", cache: "no-store", referrerPolicy: "no-referrer", redirect: "error",
      headers: { "Content-Type": "application/json" },
    }));
  });

  it("reports unavailable service and invalid ID without changing any draft", async () => {
    vi.stubEnv("VITE_PUBLIC_MANAGER_IMPORT_URL", "https://manager-api.thecometfpl.com/manager-team");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network")));
    await expect(fetchPublicManagerTeam("42")).rejects.toThrow("Could not reach");
    await expect(fetchPublicManagerTeam("https://example.com")).rejects.toThrow("positive");
  });
});
