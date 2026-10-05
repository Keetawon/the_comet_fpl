import { afterEach, describe, expect, it, vi } from "vitest";
import { applyLivePlayers, applyLiveSchedule, applyLiveTeams, validateLiveFpl, type LiveFpl } from "./liveFpl";
import samplePlayers from "./samplePlayers.json";
import sampleMatrix from "./sampleFixtureMatrix.json";
import type { PlayerRecord, TeamRecord, FixtureScheduleOverlay } from "./types";

function official(): LiveFpl {
  const stamp = "2026-09-28T04:00:00Z";
  return {
    schema: "fpl.current-official-reporting", schema_version: 1, season: "2026-27",
    captured_at: stamp, capture_id: "a".repeat(64),
    sources: { "bootstrap-static": "b".repeat(64), fixtures: "c".repeat(64) },
    players: Array.from({ length: 400 }, (_, i) => {
      const common = { source: "FPL" as const, season: "2026-27", code: i + 1,
        captured_at: stamp, capture_id: "a".repeat(64), source_sha256: "b".repeat(64),
        semantics: "current_reported_not_forecast" as const };
      return { season: "2026-27", code: i + 1,
        current_availability: { ...common, status: "i", chance_of_playing_next_round: 0,
          news: "Knee injury", news_added: null, next_gw: 6 }, current_price: { ...common, now_cost: 75 } };
    }),
    fixtures: Array.from({ length: 380 }, (_, i) => [
      { fixture: i + 1, team_code: 101, opponent_team_code: 102, was_home: true, official_fdr: 4 },
      { fixture: i + 1, team_code: 102, opponent_team_code: 101, was_home: false, official_fdr: null },
    ]).flat(),
  };
}

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); vi.resetModules(); });

describe("independent current official reporting", () => {
  it("updates reporting on every vintage by permanent identity without changing forecasts or inputs", () => {
    const live = validateLiveFpl(official());
    const players = structuredClone(samplePlayers.players) as PlayerRecord[];
    players[0].fixtures[0] = { ...players[0].fixtures[0], fixture: 1, was_home: true, opponent_team_code: 102 };
    const original = structuredClone(players);
    const applied = applyLivePlayers(players, live);
    expect(applied[0].current_availability?.chance_of_playing_next_round).toBe(0);
    expect(applied[0].current_price?.now_cost).toBe(75);
    expect(applied[0].fixtures[0].team_official_fdr).toBe(4);
    const { current_availability: _a, current_price: _p, fixtures, ...rest } = applied[0];
    expect(rest).toEqual(Object.fromEntries(Object.entries(original[0]).filter(([key]) => key !== "fixtures")));
    expect(fixtures.map(({ team_official_fdr: _f, ...f }) => f)).toEqual(original[0].fixtures.map(({ team_official_fdr: _f, ...f }) => f));
    expect(players).toEqual(original);
    expect(applyLivePlayers([{ ...players[0], season: "2025-26" }], live)[0].current_availability).toBeUndefined();
    const newer = { ...applied[0], current_availability: { ...live.players[0].current_availability, captured_at: "2026-10-01T00:00:00Z" } };
    expect(applyLivePlayers([newer], live)[0].current_availability).toBe(newer.current_availability);
  });

  it("requires exact fixture sides, keeps null FDR null, and updates both team views", () => {
    const live = official();
    const teams = structuredClone(sampleMatrix.teams) as TeamRecord[];
    teams[0].team_code = 101;
    teams[0].fixtures[0] = { ...teams[0].fixtures[0], fixture: 1, was_home: true, opponent_team_code: 102 };
    expect(applyLiveTeams(teams, live)[0].fixtures[0].official_fdr).toBe(4);
    const schedule = { schema_version: 2, semantics: "current_at_export_not_forecast_vintage", export_created_at: "old", database_sha256: "hash",
      teams: [{ season: "2026-27", team_code: 102, team_name: "B", short_name: "B",
        fixtures: [{ gw: 1, fixture: 1, kickoff_time: null, opponent_team_code: 101, opponent_short_name: "A", was_home: false, official_fdr: 5 }] }] } as FixtureScheduleOverlay;
    expect(applyLiveSchedule(schedule, live).teams[0].fixtures[0].official_fdr).toBeNull();
    teams[0].fixtures[0].opponent_team_code = 103;
    expect(applyLiveTeams(teams, live)[0].fixtures[0].official_fdr).toBeNull();
    expect(applyLiveTeams(teams, null)).toBe(teams);
    expect(applyLiveTeams(teams, live, "2026-10-01T00:00:00Z")).toBe(teams);
    const freshSchedule = { ...schedule, export_created_at: "2026-10-01T00:00:00Z" };
    expect(applyLiveSchedule(freshSchedule, live)).toBe(freshSchedule);
  });

  it.each(["duplicate", "season", "source", "chance", "fixture", "partial"])("rejects %s before applying any row", defect => {
    const live = official();
    if (defect === "duplicate") live.players[1] = live.players[0];
    if (defect === "season") live.players[0].season = "2025-26";
    if (defect === "source") live.players[0].current_availability.capture_id = "d".repeat(64);
    if (defect === "chance") live.players[0].current_availability.chance_of_playing_next_round = 101;
    if (defect === "fixture") live.fixtures[0].opponent_team_code = 103;
    if (defect === "partial") live.fixtures.pop();
    expect(() => validateLiveFpl(live)).toThrow();
  });

  it("pins one cloud response across pages and leaves the base usable on failure", async () => {
    vi.stubEnv("VITE_PUBLIC_DATA_POINTER", "https://data.thecometfpl.com/current.json");
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(official())));
    vi.stubGlobal("fetch", fetch);
    const { loadLiveFpl } = await import("./liveFpl");
    expect(await loadLiveFpl()).not.toBeNull();
    await loadLiveFpl();
    expect(fetch).toHaveBeenCalledTimes(1);
    vi.resetModules();
    fetch.mockRejectedValue(new Error("offline"));
    expect(await (await import("./liveFpl")).loadLiveFpl()).toBeNull();
  });

  it("does not make network requests for local tools or unapproved origins", async () => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    vi.stubEnv("VITE_PUBLIC_DATA_POINTER", "https://unapproved.example/current.json");
    expect(await (await import("./liveFpl")).loadLiveFpl()).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
  });
});
