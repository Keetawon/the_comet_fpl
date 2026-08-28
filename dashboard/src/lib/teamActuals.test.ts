import { describe, expect, it } from "vitest";
import type { TeamActualFixture, TeamActualsRecord } from "@/data/types";
import {
  latestTeamActualGameweeks,
  teamActualDetailsForGameweeks,
} from "./teamActuals";

function actual(patch: Partial<TeamActualFixture> = {}): TeamActualFixture {
  return {
    gw: 7,
    fixture: 70,
    kickoff_time: "2026-09-12T14:00:00+00:00",
    opponent_team_code: 102,
    opponent_short_name: "BET",
    was_home: true,
    goals_for: 2,
    goals_against: 1,
    team_xg: 1.7,
    team_xgc: 0.9,
    team_bps: 72,
    defensive_contribution: 61,
    ...patch,
  };
}

function team(
  season: string,
  teamCode: number,
  actuals: TeamActualFixture[],
): TeamActualsRecord {
  return { season, team_code: teamCode, actuals };
}

describe("latestTeamActualGameweeks", () => {
  it("selects five shared distinct labels without crossing the caller's season scope", () => {
    const current = [
      team("2026-27", 101, [
        actual({ gw: 1, fixture: 10 }),
        actual({ gw: 3, fixture: 30 }),
        actual({ gw: 5, fixture: 50 }),
        actual({ gw: 7, fixture: 70 }),
        actual({ gw: 9, fixture: 90 }),
        actual({ gw: 10, fixture: 100 }),
      ]),
      team("2026-27", 102, [actual({ gw: 10, fixture: 101 })]),
    ];
    const prior = [team("2025-26", 101, [actual({ gw: 38, fixture: 380 })])];

    expect(latestTeamActualGameweeks(current)).toEqual([10, 9, 7, 5, 3]);
    expect(latestTeamActualGameweeks(prior)).toEqual([38]);
    expect(latestTeamActualGameweeks(current, 0)).toEqual([]);
  });
});

describe("teamActualDetailsForGameweeks", () => {
  it("keeps every DGW leg, nulls, and zeroes in newest-first fixture order", () => {
    const missingMetrics = actual({
      gw: 10,
      fixture: 101,
      kickoff_time: "2026-10-03T12:00:00+00:00",
      goals_for: 0,
      goals_against: 0,
      team_xg: null,
      team_xgc: null,
      team_bps: null,
      defensive_contribution: null,
    });
    const laterDgwLeg = actual({
      gw: 10,
      fixture: 102,
      kickoff_time: "2026-10-03T18:00:00+00:00",
    });
    const result = teamActualDetailsForGameweeks(
      [actual({ gw: 2, fixture: 20 }), missingMetrics, laterDgwLeg, actual({ gw: 8, fixture: 80 })],
      [10, 8],
    );

    expect(result.map((row) => row.fixture)).toEqual([102, 101, 80]);
    expect(result[1]).toBe(missingMetrics);
    expect(result[1]).toMatchObject({ goals_for: 0, team_xg: null, team_bps: null });
  });
});
