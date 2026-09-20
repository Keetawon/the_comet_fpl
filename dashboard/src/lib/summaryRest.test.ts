import { describe, expect, it } from "vitest";
import type { PlayerFixture, PlayerRecord, SummaryData } from "@/data/types";
import { parseRestSummary, type RestSummary } from "@/data/restSummary";
import { matchingRest, summaryNextGw, topNextPlayers } from "./summaryRest";

const kickoff = "2026-09-20T14:00:00Z";
const now = Date.parse("2026-09-19T10:00:00Z");
function player(code: number, xp: number | null): PlayerRecord {
  return { code, season: "2026-27", run_id: "frozen", team_code: 10, position: "MID", web_name: `P${code}`, fixtures: [
    { gw: 5, fixture: 41, kickoff_time: kickoff, expected_points: xp } as PlayerFixture,
    { gw: 6, fixture: 51, kickoff_time: "2026-09-26T14:00:00Z", expected_points: 100 - code } as PlayerFixture,
  ] } as PlayerRecord;
}
function report(): RestSummary {
  return { schema_version: 1, semantics: "descriptive_observed_rest_not_forecast", season: "2026-27", as_of: "2026-09-19T08:00:00Z",
    window_hours: 168, midweek_definition: "Monday_through_Thursday_UTC", duration_definition: "nominal_period_clock_intervals_v1_not_fpl_minutes", promotion_permitted: false,
    players: [{ code: 1, team_code: 10, verdict: "midweek_played", coverage_complete: false, last_appearance: {
      competition_id: 5, competition_name: "Champions League", provider_match_id: 900, kickoff: "2026-09-16T18:00:00Z", opponent_name: "Opp", nominal_minutes: 90,
    }, next_fixture: { gw: 5, fixture_id: 41, kickoff, opponent_name: "Next", was_home: true }, rest_days: 4, rest_hours: 92, midweek_appearances: 1,
    midweek_nominal_minutes: 90, international_window_overlap: false, unknown_reasons: ["schedule_coverage_unproven"],
    evidence_versions: [{ provider_match_id: 900, competition_id: 5, known_at: "2026-09-19T07:00:00Z", version_id: "version", roster_proven: true }],
    }],
  };
}

describe("Summary next-GW ranking", () => {
  it("uses the published next GW, not the first stale horizon; no out-of-range/season substitution", () => {
    const summary = { latest_run: { season: "2026-27" }, next_gameweek: { gw: 5 } } as SummaryData;
    expect(summaryNextGw(summary, { season: "2026-27", gw_from: 3, gw_to: 7 })).toBe(5);
    expect(summaryNextGw(summary, { season: "2026-27", gw_from: 1, gw_to: 3 })).toBeNull();
    expect(summaryNextGw(summary, { season: "2025-26", gw_from: 1, gw_to: 38 })).toBeNull();
    expect(summaryNextGw({ ...summary, next_gameweek: null }, { season: "2026-27", gw_from: 1, gw_to: 38 })).toBeNull();
  });
  it("shows only 15 raw next-GW values, breaks ties by stable code, and never uses availability or horizon", () => {
    const players: PlayerRecord[] = Array.from({ length: 20 }, (_, i) => ({ ...player(20 - i, 20 - i), availability_multiplier: 0 }));
    players.push({ ...player(21, 20), availability_status: "i" });
    const before = JSON.stringify(players);
    const ranked = topNextPlayers(players, 5);
    expect(ranked).toHaveLength(15);
    expect(ranked.slice(0, 3).map(({ player: p }) => p.code)).toEqual([20, 21, 19]);
    expect(ranked[0].xp).toBe(20);
    expect(JSON.stringify(players)).toBe(before);
  });
  it("sums distinct DGW legs strictly and rejects missing, nonfinite, duplicate and nonplayer rows", () => {
    const dgw = player(1, 4); dgw.fixtures.push({ ...dgw.fixtures[0], fixture: 42, expected_points: 5 });
    const missing = player(2, 4); missing.fixtures.push({ ...missing.fixtures[0], fixture: 42, expected_points: null });
    const duplicate = player(3, 4); duplicate.fixtures.push({ ...duplicate.fixtures[0] });
    const manager = { ...player(5, 999), position: "AM" };
    expect(topNextPlayers([dgw, missing, duplicate, player(4, NaN), manager], 5).map(({ xp }) => xp)).toEqual([9]);
    expect(topNextPlayers([dgw, dgw], 5)).toEqual([]);
    expect(topNextPlayers([dgw], null)).toEqual([]);
  });
});

describe("rest display evidence binding", () => {
  it("joins exact season/code/club and fixture without changing ranking", () => {
    expect(matchingRest(report(), player(1, 4), 5, now).rest?.verdict).toBe("midweek_played");
    for (const patch of [{ season: "2025-26" }, { code: 2 }, { team_code: 11 }]) expect(matchingRest(report(), { ...player(1, 4), ...patch }, 5, now).rest).toBeNull();
    expect(matchingRest(report(), player(1, 4), 6, now).rest).toBeNull();
    const changed = report(); changed.players[0].next_fixture!.fixture_id = 42;
    expect(matchingRest(changed, player(1, 4), 5, now).rest).toBeNull();
  });
  it("fails closed for old generations, incomplete rest proof, future report or started fixture", () => {
    expect(matchingRest(null, player(1, 4), 5, now).rest).toBeNull();
    const partial = report(); partial.players[0] = { ...partial.players[0], verdict: "full_rest", midweek_appearances: 0 };
    expect(matchingRest(partial, player(1, 4), 5, now).rest).toBeNull();
    partial.players[0].coverage_complete = true;
    expect(matchingRest(partial, player(1, 4), 5, now).rest?.verdict).toBe("full_rest");
    expect(matchingRest(report(), player(1, 4), 5, Date.parse(kickoff)).reason).toMatch(/stale/);
    expect(matchingRest(report(), player(1, 4), 5, 0).rest).toBeNull();
  });
  it("validates sidecar missing values and immutable source cutoffs", () => {
    expect(parseRestSummary(report())).toEqual(report());
    const value = report(); value.players[0].rest_days = null; value.players[0].rest_hours = null;
    value.players[0].last_appearance!.nominal_minutes = null;
    expect(parseRestSummary(value).players[0].last_appearance!.nominal_minutes).toBeNull();
    for (const bad of [null, {}, { ...report(), promotion_permitted: true }, { ...report(), players: [...report().players, ...report().players] }]) expect(() => parseRestSummary(bad)).toThrow();
    value.players[0].evidence_versions![0].known_at = "2026-09-20T00:00:00Z";
    expect(() => parseRestSummary(value)).toThrow(/cutoff/);
  });
});
