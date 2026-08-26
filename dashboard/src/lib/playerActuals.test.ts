import { describe, expect, it } from "vitest";
import type { PlayerActualFixture, PlayerRecord } from "@/data/types";
import { actualGameweekRange, aggregatePlayerActuals } from "./playerActuals";

function actual(patch: Partial<PlayerActualFixture> = {}): PlayerActualFixture {
  return {
    gw: 2,
    fixture: 20,
    kickoff_time: "2026-08-22T14:00:00+00:00",
    minutes: 90,
    starts: 1,
    goals_scored: 1,
    assists: 0,
    clean_sheets: 1,
    goals_conceded: 0,
    saves: 0,
    bonus: 3,
    bps: 40,
    defensive_contribution: 7,
    expected_goals: 0.4,
    expected_assists: 0.1,
    expected_goals_conceded: 0.8,
    points_under_rules_2026_27: 10,
    ...patch,
  };
}

describe("aggregatePlayerActuals", () => {
  it("merges every DGW leg and uses measured-signal minutes for per-90 rates", () => {
    const result = aggregatePlayerActuals(
      [
        actual(),
        actual({
          fixture: 21,
          minutes: 60,
          goals_scored: 0,
          assists: 1,
          clean_sheets: 0,
          goals_conceded: 2,
          bonus: 0,
          bps: 18,
          defensive_contribution: 4,
          expected_goals: null,
          expected_assists: 0.2,
          expected_goals_conceded: null,
          points_under_rules_2026_27: null,
        }),
        actual({
          gw: 3,
          fixture: 30,
          minutes: 0,
          starts: 0,
          goals_scored: 0,
          assists: 0,
          clean_sheets: 0,
          goals_conceded: 0,
          saves: 0,
          bonus: 0,
          bps: 0,
          defensive_contribution: 0,
          expected_goals: 0,
          expected_assists: 0,
          expected_goals_conceded: 0,
          points_under_rules_2026_27: 0,
        }),
      ],
      2,
      3,
    );

    expect(result).toMatchObject({
      rostered_fixtures: 3,
      appearances: 2,
      starts: 2,
      did_not_play: 1,
      minutes: 150,
      goals_scored: 1,
      assists: 1,
      expected_goals: 0.4,
      expected_goals_per_90: 0.4,
      points_under_rules_2026_27: null,
    });
    expect(result?.expected_assists).toBeCloseTo(0.3);
    expect(result?.expected_assists_per_90).toBeCloseTo(0.18);
  });

  it("keeps absent, unmeasured, and zero observations distinct", () => {
    expect(aggregatePlayerActuals([], 1, 3)).toBeNull();
    const dnp = aggregatePlayerActuals(
      [actual({ minutes: 0, starts: null, expected_goals: null, expected_assists: null })],
      2,
      2,
    );
    expect(dnp).toMatchObject({
      rostered_fixtures: 1,
      appearances: 0,
      starts: null,
      did_not_play: 1,
      minutes: 0,
      goals_scored: null,
      expected_goals: null,
      expected_goals_per_90: null,
      points_under_rules_2026_27: null,
    });
  });
});

describe("actualGameweekRange", () => {
  it("uses only published finalized actual rows", () => {
    const players = [
      { actuals: [actual({ gw: 3 }), actual({ gw: 5 })] },
      { actuals: [actual({ gw: 4 })] },
    ] as PlayerRecord[];
    expect(actualGameweekRange(players)).toEqual({ minGw: 3, maxGw: 5 });
    expect(actualGameweekRange([{ actuals: [] } as unknown as PlayerRecord])).toBeNull();
  });
});
