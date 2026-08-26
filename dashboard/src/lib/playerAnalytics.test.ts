import { describe, expect, it } from "vitest";
import type {
  PlayerFormWindow,
  PlayerHorizonsRecord,
  PlayerRecord,
  WindowLabel,
} from "@/data/types";
import { indexPlayerHorizons } from "@/lib/playerHorizons";
import {
  buildPlayerAnalytics,
  formatPlayerAnalyticsValue,
  type PlayerAnalyticsConfig,
} from "./playerAnalytics";

const baseWindow: PlayerFormWindow = {
  rostered_fixtures: 5,
  appearances: 5,
  starts: 5,
  did_not_play: 0,
  minutes: 450,
  goals_scored: 2,
  assists: 1,
  clean_sheets: 2,
  goals_conceded: 5,
  saves: 0,
  bonus: 7,
  bps: 90,
  defensive_contribution: 25,
  expected_goals: 1.8,
  expected_assists: 0.9,
  expected_goals_conceded: 4.7,
  expected_goals_per_90: 0.36,
  expected_assists_per_90: 0.18,
  points_under_rules_2026_27: 31,
};

function windows(overrides: Partial<PlayerFormWindow> = {}): Record<WindowLabel, PlayerFormWindow> {
  const value = { ...baseWindow, ...overrides };
  return {
    last_3: value,
    last_5: value,
    last_10: value,
    season_to_date: value,
  };
}

function player(
  code: number,
  name: string,
  overrides: Partial<PlayerRecord> = {},
): PlayerRecord {
  return {
    run_id: "run-a",
    as_of: "2026-08-21T17:30:00+00:00",
    season: "2026-27",
    code,
    web_name: name,
    position: "MID",
    team_code: 100 + code,
    team_short_name: `T${code}`,
    now_cost: 50,
    selected_by_percent: 10,
    availability_status: "a",
    chance_of_playing: null,
    availability_multiplier: 1,
    form: { season: "2025-26", as_at_gw: 38, windows: windows() },
    actuals: [],
    avg_minutes_last_5: 90,
    fixtures: [],
    ...overrides,
  };
}

const horizonRecords: PlayerHorizonsRecord[] = [
  {
    run_id: "run-a",
    season: "2026-27",
    code: 1,
    horizons: [
      { gw_to: 2, xp: 7, p_le_2: 0.6, p_ge_2: 0.5, p_ge_4: 0.3, p_ge_6: 0.2, p_ge_10: 0.1, p_ge_15: 0.01 },
      { gw_to: 3, xp: 12, p_le_2: 0.11, p_ge_2: 0.9, p_ge_4: 0.8, p_ge_6: 0.73, p_ge_10: 0.41, p_ge_15: 0.2 },
    ],
  },
  {
    run_id: "run-a",
    season: "2026-27",
    code: 2,
    horizons: [
      { gw_to: 2, xp: 6, p_le_2: 0.5, p_ge_2: 0.6, p_ge_4: 0.4, p_ge_6: 0.3, p_ge_10: 0.2, p_ge_15: 0.02 },
      { gw_to: 3, xp: 9, p_le_2: 0.3, p_ge_2: 0.75, p_ge_4: 0.6, p_ge_6: 0.52, p_ge_10: 0.25, p_ge_15: 0.08 },
    ],
  },
  {
    run_id: "run-b",
    season: "2026-27",
    code: 1,
    horizons: [
      { gw_to: 3, xp: 99, p_le_2: 0.99, p_ge_2: 0.99, p_ge_4: 0.99, p_ge_6: 0.99, p_ge_10: 0.99, p_ge_15: 0.99 },
    ],
  },
];

const baseConfig: PlayerAnalyticsConfig = {
  runId: "run-a",
  season: "2026-27",
  gwFrom: 2,
  gwTo: 3,
  view: "value",
  haulThreshold: 6,
  formWindow: "last_5",
  pastMetric: "points",
};

describe("buildPlayerAnalytics", () => {
  it("selects one exact cumulative endpoint and never substitutes another vintage", () => {
    const result = buildPlayerAnalytics(
      [player(1, "Alpha"), player(2, "Beta")],
      indexPlayerHorizons(horizonRecords),
      baseConfig,
    );

    expect(result.plotted.find((row) => row.code === 1)?.y).toBe(12);
    expect(result.plotted.find((row) => row.code === 1)?.horizon?.p_ge_6).toBe(0.73);
    expect(result.plotted.every((row) => row.y !== 99)).toBe(true);
    expect(result.facts[0].statement).toContain("exact fixed-start GW2-3 endpoint");
  });

  it("uses published downside and selected upside scalars without probability arithmetic", () => {
    const result = buildPlayerAnalytics(
      [player(1, "Alpha")],
      indexPlayerHorizons(horizonRecords),
      { ...baseConfig, view: "upside_downside", haulThreshold: 10 },
    );

    expect(result.plotted[0]).toMatchObject({ x: 0.11, y: 0.41 });
    // These deliberately differ from any sum/complement of the GW2 endpoint.
    expect(result.plotted[0].x).not.toBeCloseTo(1 - 0.6);
    expect(result.plotted[0].y).not.toBeCloseTo(0.1 + 0.41);
    expect(formatPlayerAnalyticsValue(result.config, "y", result.plotted[0].y)).toBe(
      "41.00% (0.410000)",
    );
  });

  it("maps deadline price and ownership to the two left-and-up frontier views", () => {
    const players = [
      player(1, "Alpha", { now_cost: 50, selected_by_percent: 20 }),
      player(2, "Beta", { now_cost: 60, selected_by_percent: 5 }),
    ];
    const index = indexPlayerHorizons(horizonRecords);

    const value = buildPlayerAnalytics(players, index, baseConfig);
    expect(value.plotted.find((row) => row.code === 1)).toMatchObject({ x: 5, y: 12 });
    expect(value.plotted.find((row) => row.code === 1)?.isFrontier).toBe(true);
    expect(value.plotted.find((row) => row.code === 2)?.isFrontier).toBe(false);

    const differential = buildPlayerAnalytics(players, index, {
      ...baseConfig,
      view: "differential",
    });
    expect(differential.plotted.find((row) => row.code === 1)?.x).toBe(20);
    expect(differential.plotted.find((row) => row.code === 2)?.x).toBe(5);
    expect(differential.plotted.filter((row) => row.isFrontier).map((row) => row.code)).toEqual([
      1,
      2,
    ]);
  });

  it("uses a directly published observed form value in explanatory past-vs-future mode", () => {
    const alpha = player(1, "Alpha", {
      form: {
        season: "2025-26",
        as_at_gw: 38,
        windows: windows({ expected_goals_per_90: 0.456 }),
      },
    });
    const result = buildPlayerAnalytics([alpha], indexPlayerHorizons(horizonRecords), {
      ...baseConfig,
      view: "past_future",
      pastMetric: "xg_per_90",
    });

    expect(result.plotted[0]).toMatchObject({ x: 0.456, y: 12, isFrontier: false });
    expect(result.xAxis.direction).toBe("explanatory");
    expect(result.caveats).toContain(
      "Past form is observed and cumulative xP is a future forecast; the comparison is explanatory, not causal.",
    );
  });

  it("omits null axes visibly instead of turning them into zero", () => {
    const result = buildPlayerAnalytics(
      [
        player(1, "No Price", { now_cost: null }),
        player(2, "No Horizon"),
        player(3, "Wrong Vintage", { run_id: "run-b" }),
      ],
      indexPlayerHorizons(horizonRecords.filter((record) => record.code !== 2)),
      baseConfig,
    );

    expect(result.eligibleCount).toBe(2);
    expect(result.plotted).toEqual([]);
    expect(result.omitted.map((row) => row.webName)).toEqual(["No Price", "No Horizon"]);
    expect(result.omittedCount).toBe(2);
    expect(result.facts.at(-1)?.statement).toContain("2 are omitted");
  });
});
