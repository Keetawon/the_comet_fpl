import { describe, expect, it } from "vitest";
import { defaultVintageRunId } from "./vintage";

const runs = [
  { run_id: "old-plan", gw_from: 3, gw_to: 7 },
  { run_id: "latest-primary", gw_from: 4, gw_to: 8 },
];
const plans = [
  {
    forecast_run_id: "old-plan",
    component_modes: {
      attacking_mode: "v3",
      assists_mode: "coupled",
      appearance_mode: "seasonal",
      share_signal_kind: "expected_goals",
    },
    plan_kind: "platform_default" as const,
  },
];

describe("default forecast vintage", () => {
  it("does not let an old optimizer plan pin exploratory pages to a stale horizon", () => {
    expect(defaultVintageRunId(runs, plans, "latest-primary")).toBe("latest-primary");
  });

  it("falls back to the exact platform plan when the published latest run is absent", () => {
    expect(defaultVintageRunId(runs, plans, "missing-run")).toBe("old-plan");
  });
});
