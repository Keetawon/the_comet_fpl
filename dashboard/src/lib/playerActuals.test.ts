import { describe, expect, it } from "vitest";
import type { PlayerActualFixture } from "@/data/types";
import {
  actualGameweekRange,
  actualGameweekLabel,
  actualGameweeksChronological,
  aggregatePlayerActuals,
  averageBpsPerAppearance,
  latestActualGameweeks,
  latestPlayerActualDetails,
} from "./playerActuals";

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
          bps: 99,
          defensive_contribution: 0,
          expected_goals: 0,
          expected_assists: 0,
          expected_goals_conceded: 0,
          points_under_rules_2026_27: 0,
        }),
      ],
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
    expect(result?.bps).toBe(58);
  });

  it("keeps absent, unmeasured, and zero observations distinct", () => {
    expect(aggregatePlayerActuals([])).toBeNull();
    const dnp = aggregatePlayerActuals(
      [actual({ minutes: 0, starts: null, expected_goals: null, expected_assists: null })],
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

  it("averages BPS over appearances, counts DGW legs, and fails closed on missing evidence", () => {
    const appeared = [
      actual({ fixture: 20, bps: 40 }),
      actual({ fixture: 21, minutes: 60, bps: 18 }),
      actual({ fixture: 22, minutes: 0, bps: 99 }),
    ];
    expect(averageBpsPerAppearance(appeared)).toBe(29);
    expect(averageBpsPerAppearance([actual({ bps: 0 })])).toBe(0);
    expect(averageBpsPerAppearance([actual({ minutes: 0, bps: 99 })])).toBeNull();
    expect(
      averageBpsPerAppearance(
        [actual({ fixture: 20, bps: 40 }), actual({ fixture: 21, bps: null })],
      ),
    ).toBeNull();
  });
});

describe("actualGameweekRange", () => {
  it("uses only published finalized actual rows", () => {
    const players = [
      { actuals: [actual({ gw: 3 }), actual({ gw: 5 })] },
      { actuals: [actual({ gw: 4 })] },
    ];
    expect(actualGameweekRange(players)).toEqual({ minGw: 3, maxGw: 5 });
    expect(actualGameweekRange([{ actuals: [] }])).toBeNull();
  });
});

describe("latestPlayerActualDetails", () => {
  it("rolls across the season boundary, keeps DGWs, and does not backfill a player's gaps", () => {
    const pageGameweeks = latestActualGameweeks(
      [
        {
          season: "2026-27",
          actuals: [actual({ gw: 1, fixture: 101 })],
        },
        {
          season: "2025-26",
          actuals: [34, 35, 36, 37, 38].map((gw) => actual({ gw, fixture: gw * 10 })),
        },
        {
          season: "2024-25",
          actuals: [actual({ gw: 38, fixture: 2438 })],
        },
      ],
      ["2026-27", "2025-26"],
    );
    const result = latestPlayerActualDetails(
      [
        {
          season: "2026-27",
          actuals: [
            actual({ gw: 1, fixture: 101, kickoff_time: "2026-08-15T12:00:00+00:00" }),
            actual({ gw: 1, fixture: 102, kickoff_time: "2026-08-15T16:00:00+00:00" }),
          ],
        },
        {
          season: "2025-26",
          actuals: [
            actual({ gw: 34, fixture: 340 }),
            actual({ gw: 35, fixture: 350 }),
            actual({ gw: 36, fixture: 360 }),
            actual({ gw: 38, fixture: 380 }),
          ],
        },
      ],
      pageGameweeks,
    );

    expect(pageGameweeks).toEqual([
      { season: "2026-27", gw: 1 },
      { season: "2025-26", gw: 38 },
      { season: "2025-26", gw: 37 },
      { season: "2025-26", gw: 36 },
      { season: "2025-26", gw: 35 },
    ]);
    expect(result.map((row) => row.fixture)).toEqual([102, 101, 380, 360, 350]);
    expect(result.map((row) => `${row.season}/GW${row.gw}`)).toEqual([
      "2026-27/GW1",
      "2026-27/GW1",
      "2025-26/GW38",
      "2025-26/GW36",
      "2025-26/GW35",
    ]);
  });

  it("enumerates exact endpoint options chronologically and selects inclusively by index", () => {
    const records = [
      {
        season: "2026-27",
        actuals: [actual({ gw: 1, fixture: 101 }), actual({ gw: 3, fixture: 103 })],
      },
      {
        season: "2025-26",
        actuals: [actual({ gw: 35, fixture: 350 }), actual({ gw: 38, fixture: 380 })],
      },
      {
        season: "2024-25",
        actuals: [actual({ gw: 38, fixture: 2438 })],
      },
    ];
    const chronological = actualGameweeksChronological(records, ["2026-27", "2025-26"]);

    expect(chronological.map(actualGameweekLabel)).toEqual([
      "2025-26 GW35",
      "2025-26 GW38",
      "2026-27 GW1",
      "2026-27 GW3",
    ]);
    const selected = chronological.slice(1, 3);
    expect(
      latestPlayerActualDetails(records, selected).map((row) => `${row.season}/${row.fixture}`),
    ).toEqual(["2025-26/380", "2026-27/101"]);
  });

  it("preserves DNP, zero, and null fixture evidence without substituting other rows", () => {
    const dnp = actual({
      gw: 4,
      minutes: 0,
      starts: 0,
      expected_goals: 0,
      expected_assists: null,
      bps: null,
    });
    expect(
      latestPlayerActualDetails(
        [{ season: "2026-27", actuals: [dnp] }],
        [{ season: "2026-27", gw: 4 }],
      ),
    ).toEqual([{ ...dnp, season: "2026-27" }]);
    expect(
      latestPlayerActualDetails(
        [{ season: "2026-27", actuals: [dnp] }],
        [{ season: "2026-27", gw: 5 }, { season: "2025-26", gw: 38 }],
      ),
    ).toEqual([]);
    expect(
      latestActualGameweeks(
        [{ season: "2026-27", actuals: [dnp] }],
        ["2026-27", "2025-26"],
        0,
      ),
    ).toEqual([]);
  });
});
