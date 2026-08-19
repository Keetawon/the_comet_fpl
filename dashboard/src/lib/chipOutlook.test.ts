import { describe, expect, it } from "vitest";
import type { NextGwPlan, PlanPlayer, PlanRole, PlanWeek } from "@/data/types";
import { buildPlanChipOutlook } from "./chipOutlook";

function player(
  code: number,
  role: PlanRole,
  expectedPoints: number | null,
  options: { captain?: boolean; benchOrder?: number } = {},
): PlanPlayer {
  return {
    code,
    web_name: `Player ${code}`,
    position: role === "bench_goalkeeper" || code === 2 ? "GK" : "MID",
    team_code: 100 + code,
    team_short_name: `T${code}`,
    now_cost: 50,
    role,
    bench_order_index: options.benchOrder ?? null,
    is_captain: options.captain ?? false,
    is_vice_captain: code === 2,
    transferred_in: false,
    transferred_out: false,
    expected_points: expectedPoints,
  };
}

function week(
  gw: number,
  benchValues: readonly number[],
  options: { hit?: number; replacementCode?: number } = {},
): PlanWeek {
  const starters = [
    player(1, "starting_xi", 6, { captain: true }),
    ...Array.from({ length: 10 }, (_, index) => player(index + 2, "starting_xi", 2)),
  ];
  const benchCodes = [12, 13, 14, options.replacementCode ?? 15];
  const bench = benchCodes.map((code, index) =>
    player(
      code,
      index === 0 ? "bench_goalkeeper" : "bench_outfield",
      benchValues[index],
      { benchOrder: index === 0 ? undefined : index },
    ),
  );
  if (options.replacementCode != null) bench[3].transferred_in = true;
  return {
    gw,
    hit_points: options.hit ?? 0,
    squad_cost: 750,
    captain_code: 1,
    vice_captain_code: 2,
    players: [...starters, ...bench],
  };
}

function plan(weeks: PlanWeek[], gwTo = weeks.at(-1)?.gw ?? 1): NextGwPlan {
  return {
    optimizer_run_id: "plan-a",
    decision_sha256: "decision-a",
    forecast_run_id: "forecast-a",
    as_of: "2026-08-19T00:00:00Z",
    season: "2026-27",
    gw_from: 1,
    gw_to: gwTo,
    component_modes: { attacking_mode: "v3", assists_mode: "coupled" },
    plan_kind: "platform_default",
    display_label: "Platform default",
    policy: { locked_codes: [], excluded_codes: [], min_bench_appearance: 0 },
    weeks,
    // Deliberately stale: the chip outlook must use each transfer-aware PlanWeek squad.
    player_xp: {},
    squad_context: {},
  };
}

describe("buildPlanChipOutlook", () => {
  it("derives raw XI, bench, and squad totals from each post-transfer squad", () => {
    const result = buildPlanChipOutlook(
      plan([
        week(1, [1, 2, 3, 4], { hit: 4 }),
        week(2, [1, 2, 3, 10], { replacementCode: 99 }),
      ], 2),
    );

    expect(result.weeks[0]).toMatchObject({
      startingXiXp: 26,
      benchXp: 10,
      squadXp: 36,
      completeSquad: true,
    });
    expect(result.weeks[1]).toMatchObject({
      startingXiXp: 26,
      benchXp: 16,
      squadXp: 42,
      completeSquad: true,
    });
    expect(result.highestBenchXpGw).toBe(2);
  });

  it("propagates nulls without turning a partial squad sum into a total", () => {
    const benchNull = week(1, [1, 2, 3, 4]);
    benchNull.players.find((candidate) => candidate.code === 15)!.expected_points = null;
    const starterNull = week(2, [1, 2, 3, 4]);
    starterNull.players.find((candidate) => candidate.code === 5)!.expected_points = null;

    const result = buildPlanChipOutlook(plan([benchNull, starterNull], 2));

    expect(result.weeks[0]).toMatchObject({
      startingXiXp: 26,
      benchXp: null,
      squadXp: null,
    });
    expect(result.weeks[1]).toMatchObject({
      startingXiXp: null,
      benchXp: 10,
      squadXp: null,
    });
    expect(result.highestBenchXpGw).toBe(2);
  });

  it("fails closed for a malformed squad", () => {
    const malformed = week(1, [1, 2, 3, 4]);
    malformed.players.pop();

    const result = buildPlanChipOutlook(plan([malformed], 2));

    expect(result.weeks[0]).toMatchObject({
      completeSquad: false,
      startingXiXp: null,
      benchXp: null,
      squadXp: null,
    });
    expect(result.highestBenchXpGw).toBeNull();
  });

  it("chooses the earliest gameweek when complete bench xP ties", () => {
    const result = buildPlanChipOutlook(
      plan([week(2, [1, 2, 3, 4]), week(1, [4, 3, 2, 1])], 2),
    );

    expect(result.weeks.map((item) => item.gw)).toEqual([1, 2]);
    expect(result.highestBenchXpGw).toBe(1);
  });
});
