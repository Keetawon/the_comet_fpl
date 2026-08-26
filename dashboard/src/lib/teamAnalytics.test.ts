import { describe, expect, it } from "vitest";
import type { TeamFixture, TeamRecord, TeamFormWindow } from "@/data/types";
import {
  buildTeamAnalyticsPlot,
  buildTeamAnalyticsRows,
  buildTeamInsightFacts,
  type TeamAnalyticsScope,
} from "./teamAnalytics";

const formWindow = (overrides: Partial<TeamFormWindow> = {}): TeamFormWindow => ({
  matches_played: 5,
  goals_for: 8,
  goals_against: 5,
  clean_sheets: 2,
  wins: 3,
  draws: 1,
  losses: 1,
  team_xg: 9,
  team_xgc: 6,
  goals_for_per_match: 1.6,
  goals_against_per_match: 1,
  team_xg_per_match: 1.8,
  team_xgc_per_match: 1.2,
  ...overrides,
});

const fixture = (overrides: Partial<TeamFixture> = {}): TeamFixture => ({
  gw: 1,
  fixture: 100,
  kickoff_time: "2026-08-22T14:00:00+00:00",
  opponent_team_code: 2,
  opponent_short_name: "BET",
  was_home: true,
  lambda_for: 1,
  lambda_against: 1,
  probability_clean_sheet: 0.25,
  attack_ease_index: 100,
  defence_ease_index: 100,
  overall_ease_index: 100,
  ease_index_formula_version: "fixture-ease-v1",
  official_fdr: 3,
  stage_a_league_average_team: false,
  ...overrides,
});

const team = (
  teamCode: number,
  fixtures: TeamFixture[],
  overrides: Partial<TeamRecord> = {},
): TeamRecord => ({
  run_id: "run-a",
  as_of: "2026-08-21T17:30:00+00:00",
  season: "2026-27",
  team_code: teamCode,
  team_name: `Team ${teamCode}`,
  short_name: `T${teamCode}`,
  form: {
    season: "2025-26",
    as_at_gw: 38,
    windows: {
      last_3: formWindow({ team_xg_per_match: 1.3 }),
      last_5: formWindow({ team_xg_per_match: 1.5 }),
      last_10: formWindow({ team_xg_per_match: 1.7 }),
      season_to_date: formWindow({ team_xg_per_match: 1.9 }),
    },
  },
  fixtures,
  ...overrides,
});

const scope = (overrides: Partial<TeamAnalyticsScope> = {}): TeamAnalyticsScope => ({
  runId: "run-a",
  season: "2026-27",
  gwFrom: 1,
  gwTo: 5,
  venue: "all",
  formWindow: "last_5",
  ...overrides,
});

describe("buildTeamAnalyticsRows", () => {
  it("isolates one vintage, modelled GW range, and venue", () => {
    const teams = [
      team(1, [
        fixture({ gw: 1, fixture: 101, was_home: true, lambda_for: 1 }),
        fixture({ gw: 2, fixture: 102, was_home: false, lambda_for: 2 }),
      ]),
      team(1, [fixture({ gw: 2, fixture: 202, lambda_for: 99 })], {
        run_id: "run-b",
      }),
      team(1, [fixture({ gw: 2, fixture: 203, lambda_for: 88 })], {
        season: "2025-26",
      }),
    ];
    const result = buildTeamAnalyticsRows(
      teams,
      scope({ gwFrom: 2, gwTo: 2, venue: "away" }),
    );
    expect(result.rows).toHaveLength(1);
    expect(result.rows[0].fixtureCount).toBe(1);
    expect(result.rows[0].lambdaForTotal).toBe(2);
  });

  it("counts both DGW legs and fabricates nothing for a blank team", () => {
    const result = buildTeamAnalyticsRows(
      [
        team(1, [
          fixture({ gw: 2, fixture: 102, lambda_for: 1.2 }),
          fixture({ gw: 2, fixture: 103, lambda_for: 1.8 }),
        ]),
        team(2, [fixture({ gw: 3, fixture: 104 })]),
      ],
      scope({ gwFrom: 2, gwTo: 2 }),
    );
    expect(result.rows[0]).toMatchObject({ fixtureCount: 2, lambdaForTotal: 3 });
    expect(result.rows[1]).toMatchObject({
      fixtureCount: 0,
      lambdaForTotal: null,
      lambdaAgainstTotal: null,
      expectedCleanSheets: null,
    });
    expect(result.fixtureRows).toBe(2);
  });

  it("sums clean-sheet probabilities as an expected count and counts fallbacks", () => {
    const result = buildTeamAnalyticsRows(
      [
        team(1, [
          fixture({ probability_clean_sheet: 0.2, stage_a_league_average_team: true }),
          fixture({ fixture: 101, probability_clean_sheet: 0.3 }),
        ]),
      ],
      scope(),
    );
    expect(result.rows[0].expectedCleanSheets).toBeCloseTo(0.5);
    expect(result.rows[0].expectedCleanSheets).not.toBeCloseTo(0.44);
    expect(result.rows[0].expectedCleanSheetsPerFixture).toBeCloseTo(0.25);
    expect(result).toMatchObject({ fixtureRows: 2, fallbackRows: 1 });
  });

  it("makes a partially null aggregate null instead of summing measured fixtures", () => {
    const result = buildTeamAnalyticsRows(
      [
        team(1, [
          fixture({ probability_clean_sheet: 0.2 }),
          fixture({ fixture: 101, probability_clean_sheet: null }),
        ]),
      ],
      scope(),
    );
    expect(result.rows[0].expectedCleanSheets).toBeNull();
    expect(result.rows[0].lambdaForTotal).toBe(2);
    expect(buildTeamAnalyticsPlot(result.rows, "attack-floor", "xg-for").omitted).toHaveLength(1);
    expect(buildTeamAnalyticsPlot(result.rows, "environment", "xg-for").plotted).toHaveLength(1);
  });

  it("uses the selected observed form window without deriving a future rate", () => {
    const result = buildTeamAnalyticsRows(
      [team(1, [fixture({ lambda_for: 3 })])],
      scope({ formWindow: "last_3" }),
    );
    expect(result.rows[0].past.xgForPerMatch).toBe(1.3);
    const plot = buildTeamAnalyticsPlot(result.rows, "past-future", "xg-for");
    expect(plot.plotted[0]).toMatchObject({ x: 1.3, y: 3, isFrontier: false });
    expect(plot.frontier).toEqual([]);
  });
});

describe("team Pareto and insight facts", () => {
  it("applies minimize-against/maximize-for dominance", () => {
    const result = buildTeamAnalyticsRows(
      [
        team(1, [fixture({ lambda_against: 1, lambda_for: 3 })]),
        team(2, [fixture({ lambda_against: 2, lambda_for: 2 })]),
        team(3, [fixture({ lambda_against: 0.8, lambda_for: 1 })]),
      ],
      scope(),
    );
    const plot = buildTeamAnalyticsPlot(result.rows, "environment", "xg-for");
    expect(plot.frontier.map((row) => row.teamCode)).toEqual([1, 3]);
    expect(plot.plotted.find((point) => point.row.teamCode === 2)?.isFrontier).toBe(false);
  });

  it("builds deterministic facts from direct values and the selected scope", () => {
    const result = buildTeamAnalyticsRows(
      [
        team(2, [fixture({ lambda_against: 2, lambda_for: 1, probability_clean_sheet: 0.1 })]),
        team(1, [fixture({ lambda_against: 1, lambda_for: 3, probability_clean_sheet: 0.4 })]),
      ],
      scope({ gwFrom: 1, gwTo: 3, venue: "home" }),
    );
    const plot = buildTeamAnalyticsPlot(result.rows, "attack-floor", "xg-for");
    const facts = buildTeamInsightFacts(
      result,
      plot,
      scope({ gwFrom: 1, gwTo: 3, venue: "home" }),
    );
    expect(facts.scope).toMatchObject({ gwFrom: 1, gwTo: 3, venue: "home" });
    expect(facts.frontier).toEqual([{ teamCode: 1, teamName: "Team 1" }]);
    expect(facts.highestAttack).toMatchObject({ teamCode: 1, value: 3 });
    expect(facts.lowestConceding).toMatchObject({ teamCode: 1, value: 1 });
    expect(facts.highestExpectedCleanSheets).toMatchObject({ teamCode: 1, value: 0.4 });
  });
});
