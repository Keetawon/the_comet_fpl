import { describe, expect, it } from "vitest";
import type { TeamActualFixture, TeamActualsRecord } from "@/data/types";
import {
  latestTeamActualGameweeks,
  mergeTeamActualRecords,
  teamActualGameweekLabel,
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
      { season: "2026-27", gw: 1, outcome_status: "finalized" },
      { season: "2025-26", gw: 38, outcome_status: "finalized" },
      { season: "2025-26", gw: 37, outcome_status: "finalized" },
      { season: "2025-26", gw: 36, outcome_status: "finalized" },
      { season: "2025-26", gw: 35, outcome_status: "finalized" },
    ]);
    expect(latestTeamActualGameweeks(current)).toEqual([
      { season: "2026-27", gw: 1, outcome_status: "finalized" },
    ]);
    expect(latestTeamActualGameweeks(current, 0)).toEqual([]);
  });

  it("marks and labels a gameweek provisional when any club row is provisional", () => {
    const records = mergeTeamActualRecords(
      [team("2026-27", 101, [actual({ gw: 1, fixture: 10 })])],
      [team("2026-27", 101, [actual({ gw: 2, fixture: 20 })])],
    );
    const gameweeks = latestTeamActualGameweeks(records);

    expect(gameweeks).toEqual([
      { season: "2026-27", gw: 2, outcome_status: "provisional" },
      { season: "2026-27", gw: 1, outcome_status: "finalized" },
    ]);
    expect(teamActualGameweekLabel(gameweeks[0])).toBe("2026-27 GW2 (provisional)");
  });
});

describe("mergeTeamActualRecords", () => {
  it("lets finalized rows replace matching provisional rows and fails on identity drift", () => {
    const finalized = actual({ fixture: 70, goals_for: 3 });
    const provisional = actual({ fixture: 70, goals_for: 2 });
    const merged = mergeTeamActualRecords(
      [team("2026-27", 101, [finalized])],
      [team("2026-27", 101, [provisional])],
    );

    expect(merged[0].actuals).toEqual([{ ...finalized, outcome_status: "finalized" }]);
    expect(() =>
      mergeTeamActualRecords(
        [team("2026-27", 101, [finalized])],
        [
          team("2026-27", 101, [
            actual({ fixture: 70, opponent_team_code: 999 }),
          ]),
        ],
      ),
    ).toThrow(/disagree on fixture identity/);
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
        { season: "2026-27", gw: 1, outcome_status: "finalized" },
        { season: "2025-26", gw: 38, outcome_status: "finalized" },
      ],
    );

    expect(result.map((row) => row.fixture)).toEqual([102, 101, 380]);
    expect(result.map((row) => row.season)).toEqual(["2026-27", "2026-27", "2025-26"]);
    expect(result[1]).toMatchObject({
      ...missingMetrics,
      season: "2026-27",
      outcome_status: "finalized",
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
        { season: "2026-27", gw: 1, outcome_status: "finalized" },
        { season: "2025-26", gw: 38, outcome_status: "finalized" },
      ],
    );

    expect(result.map((row) => row.fixture)).toEqual([10, 380]);
  });
});
