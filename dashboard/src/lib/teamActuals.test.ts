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
  it("selects five shared distinct season/GW labels across a season boundary", () => {
    const current = [
      team("2026-27", 101, [
        actual({ gw: 1, fixture: 10 }),
      ]),
      team("2026-27", 102, [actual({ gw: 1, fixture: 11 })]),
    ];
    const prior = [
      team("2025-26", 101, [
        actual({ gw: 34, fixture: 340 }),
        actual({ gw: 35, fixture: 350 }),
        actual({ gw: 36, fixture: 360 }),
        actual({ gw: 37, fixture: 370 }),
        actual({ gw: 38, fixture: 380 }),
      ]),
    ];

    expect(latestTeamActualGameweeks([...current, ...prior])).toEqual([
      { season: "2026-27", gw: 1 },
      { season: "2025-26", gw: 38 },
      { season: "2025-26", gw: 37 },
      { season: "2025-26", gw: 36 },
      { season: "2025-26", gw: 35 },
    ]);
    expect(latestTeamActualGameweeks(current)).toEqual([{ season: "2026-27", gw: 1 }]);
    expect(latestTeamActualGameweeks(current, 0)).toEqual([]);
  });
});

describe("teamActualDetailsForGameweeks", () => {
  it("keeps every DGW leg, nulls, and zeroes in newest-first cross-season order", () => {
    const missingMetrics = actual({
      gw: 1,
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
      gw: 1,
      fixture: 102,
      kickoff_time: "2026-10-03T18:00:00+00:00",
    });
    const result = teamActualDetailsForGameweeks(
      [
        team("2025-26", 101, [actual({ gw: 38, fixture: 380 })]),
        team("2026-27", 101, [missingMetrics, laterDgwLeg]),
      ],
      [
        { season: "2026-27", gw: 1 },
        { season: "2025-26", gw: 38 },
      ],
    );

    expect(result.map((row) => row.fixture)).toEqual([102, 101, 380]);
    expect(result.map((row) => row.season)).toEqual(["2026-27", "2026-27", "2025-26"]);
    expect(result[1]).toMatchObject({
      ...missingMetrics,
      season: "2026-27",
      goals_for: 0,
      team_xg: null,
      team_bps: null,
    });
  });

  it("does not backfill a club from gameweeks outside the shared page window", () => {
    const result = teamActualDetailsForGameweeks(
      [
        team("2025-26", 101, [
          actual({ gw: 34, fixture: 340 }),
          actual({ gw: 38, fixture: 380 }),
        ]),
        team("2026-27", 101, [actual({ gw: 1, fixture: 10 })]),
      ],
      [
        { season: "2026-27", gw: 1 },
        { season: "2025-26", gw: 38 },
      ],
    );

    expect(result.map((row) => row.fixture)).toEqual([10, 380]);
  });
});
