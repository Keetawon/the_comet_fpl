// Next-GW helpers: explicit product ownership, architecture labelling, horizon EV sums (a
// null gameweek makes the total null, never a partial sum), and the platform-only diff.

import { describe, expect, it } from "vitest";
import sample from "@/data/sampleNextGw.json";
import type { NextGwPlan } from "@/data/types";
import {
  defaultPlan,
  diffPlans,
  horizonXp,
  isDefaultArchitecture,
  planDisplayLabel,
  planLabel,
  platformComparisonPlans,
  platformPlans,
  resolvedPlanKind,
} from "@/lib/nextGw";

const plans = sample.plans as unknown as NextGwPlan[];

describe("plan labelling", () => {
  it("identifies the frozen default architecture and labels both plans", () => {
    expect(isDefaultArchitecture(plans[0].component_modes)).toBe(true);
    expect(isDefaultArchitecture(plans[1].component_modes)).toBe(false);
    expect(planLabel(plans[0].component_modes)).toContain("default");
    expect(planLabel(plans[1].component_modes)).toContain("diagnostic");
    expect(defaultPlan(plans)).toBe(plans[0]);
  });

  it("falls back to the first plan when none matches the default architecture", () => {
    const diagnostic = plans.filter((p) => !isDefaultArchitecture(p.component_modes));
    expect(defaultPlan(diagnostic)).toBe(diagnostic[0]);
  });

  it("uses plan_kind rather than architecture or array order to separate custom plans", () => {
    const custom: NextGwPlan = {
      ...plans[0],
      optimizer_run_id: "custom-first",
      plan_kind: "user_custom",
      display_label: "Your plan — locked squad",
      policy: {
        locked_codes: [1],
        excluded_codes: [2],
        min_bench_appearance: 0.25,
      },
    };
    const shuffled = [custom, plans[1], plans[0]];

    expect(resolvedPlanKind(custom)).toBe("user_custom");
    expect(planDisplayLabel(custom)).toBe("Your plan — locked squad");
    expect(platformPlans(shuffled)).toEqual([plans[1], plans[0]]);
    expect(defaultPlan(platformPlans(shuffled))).toBe(plans[0]);
    expect(platformComparisonPlans(shuffled)).toEqual({
      defaultPlan: plans[0],
      diagnosticPlan: plans[1],
    });
  });

  it("fails closed when ownership is missing even for the default V3 architecture", () => {
    const stale = {
      component_modes: plans[0].component_modes,
      display_label: "stale V3 plan",
    };
    expect(() => resolvedPlanKind(stale)).toThrow(
      /plan_kind is required; product ownership is never inferred/,
    );
  });
});

describe("horizonXp", () => {
  it("sums the next N gameweeks from the plan's first week", () => {
    expect(horizonXp(plans[0], 1, 1)).toBe(7.4);
    expect(horizonXp(plans[0], 1, 3)).toBeCloseTo(7.4 + 6.1 + 5.5, 10);
    expect(horizonXp(plans[0], 1, 5)).toBeCloseTo(7.4 + 6.1 + 5.5 + 4.9 + 6.3, 10);
  });

  it("returns null, never a partial sum, when any gameweek in range is unmeasured", () => {
    expect(horizonXp(plans[0], 3, 2)).toBeNull(); // GW2 is null for code 3
    expect(horizonXp(plans[0], 3, 1)).toBe(2.1); // a single measured GW still shows
    expect(horizonXp(plans[0], 999, 1)).toBeNull(); // a code the plan never rated
  });
});

describe("diffPlans", () => {
  it("reports set overlap and captaincy agreement, never an EV comparison", () => {
    const diff = diffPlans(plans[0], plans[1]);
    expect(diff).not.toBeNull();
    // squads {1,2,3} vs {1,2,4}: overlap 2, unique [3] vs [4]; XI differs by one;
    // captain 1 vs 4 and vice 2 vs 1 both differ
    expect(diff!.squadOverlap).toBe(2);
    expect(diff!.squadSize).toBe(3);
    expect(diff!.xiOverlap).toBe(1);
    expect(diff!.captainAgrees).toBe(false);
    expect(diff!.viceAgrees).toBe(false);
    expect(diff!.uniqueToA).toEqual([3]);
    expect(diff!.uniqueToB).toEqual([4]);
    expect(JSON.stringify(diff!)).not.toContain("expected_points");
  });

  it("returns null when the plans' first weeks disagree on gameweek", () => {
    const shifted: NextGwPlan = {
      ...plans[1],
      weeks: [{ ...plans[1].weeks[0], gw: 2 }],
    };
    expect(diffPlans(plans[0], shifted)).toBeNull();
  });
});
