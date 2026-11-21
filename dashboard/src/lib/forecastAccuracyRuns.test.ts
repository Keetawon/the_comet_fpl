import { describe, expect, it } from "vitest";
import type { ComponentModes } from "@/data/types";
import {
  APPEARANCE_DEFAULT_SWITCHED_AT,
  accuracyComponentLabel,
  accuracyRunLabel,
  accuracyRunRole,
  defaultAccuracyRun,
  orderedAccuracyRuns,
  type AccuracyRunLike,
} from "./forecastAccuracyRuns";

function modes(
  attacking: string,
  assists: string,
  appearance = "rostered_decay",
): ComponentModes {
  return {
    attacking_mode: attacking,
    assists_mode: assists,
    appearance_mode: appearance,
  };
}

function run(
  runId: string,
  createdAt: string,
  componentModes: ComponentModes | null,
  scoredRows: number,
): AccuracyRunLike {
  return {
    run_id: runId,
    as_of: "2026-08-15T12:00:00Z",
    created_at: createdAt,
    season: "2026-27",
    gw_from: 1,
    gw_to: 5,
    status: "development_only_not_a_production_forecast",
    component_modes: componentModes,
    coverage: { scored_rows: scoredRows },
  };
}

// Derived from the exported switch instant: one hour either side of it.
const SWITCH_MILLIS = Date.parse(APPEARANCE_DEFAULT_SWITCHED_AT);
const PRE_SWITCH = new Date(SWITCH_MILLIS - 3_600_000).toISOString();
const POST_SWITCH = new Date(SWITCH_MILLIS + 3_600_000).toISOString();

describe("forecast accuracy run selection", () => {
  it("exports the documented switch instant (commit 86f4a32)", () => {
    expect(APPEARANCE_DEFAULT_SWITCHED_AT).toBe("2026-11-21T08:21:09Z");
  });

  it("classifies the default that was in effect at the vintage's creation", () => {
    // Pre-switch (and every formal GW1-era vintage): v3/coupled/seasonal IS the default.
    expect(accuracyRunRole(modes("v3", "coupled", "seasonal"), PRE_SWITCH)).toBe(
      "prospective_default",
    );
    // From the switch instant on: v3/coupled/rostered_decay is the default.
    expect(accuracyRunRole(modes("v3", "coupled", "rostered_decay"), POST_SWITCH)).toBe(
      "prospective_default",
    );
    // A post-switch seasonal run is a recorded sensitivity, never a relabelled default.
    expect(accuracyRunRole(modes("v3", "coupled", "seasonal"), POST_SWITCH)).toBe(
      "recorded_sensitivity",
    );
    // A pre-switch rostered_decay run did not exist, but classifies consistently.
    expect(accuracyRunRole(modes("v3", "coupled", "rostered_decay"), PRE_SWITCH)).toBe(
      "recorded_sensitivity",
    );
    expect(accuracyRunRole(modes("v3", "coupled", "model"), POST_SWITCH)).toBe(
      "recorded_sensitivity",
    );
    expect(
      accuracyRunRole({ attacking_mode: "v3", assists_mode: "coupled" }, POST_SWITCH),
    ).toBe("unclassified");
    expect(accuracyRunRole(null, POST_SWITCH)).toBe("unclassified");
  });

  it("applies the same era rule to the diagnostic comparator", () => {
    // Before the switch the runbook's diagnostic command ran v1/v1/seasonal.
    expect(accuracyRunRole(modes("v1", "v1", "seasonal"), PRE_SWITCH)).toBe(
      "diagnostic_comparator",
    );
    // After it the diagnostic command inherits the default appearance mode.
    expect(accuracyRunRole(modes("v1", "v1", "rostered_decay"), POST_SWITCH)).toBe(
      "diagnostic_comparator",
    );
    // The pre-switch diagnostic triple is a sensitivity after the switch, and vice versa.
    expect(accuracyRunRole(modes("v1", "v1", "seasonal"), POST_SWITCH)).toBe(
      "recorded_sensitivity",
    );
    expect(accuracyRunRole(modes("v1", "v1", "rostered_decay"), PRE_SWITCH)).toBe(
      "recorded_sensitivity",
    );
  });

  it("labels pre-switch default vintages as Prospective default in the composed label", () => {
    const gw1Default = run("7425b337c746abcdef", "2026-08-21T09:00:00Z",
      modes("v3", "coupled", "seasonal"), 584);
    expect(accuracyRunRole(gw1Default.component_modes, gw1Default.created_at)).toBe(
      "prospective_default",
    );
    expect(accuracyRunLabel(gw1Default)).toContain("Prospective default");
    expect(accuracyRunLabel(gw1Default)).toContain("appearance seasonal");
  });

  it("prefers the newest scored default across the switch, pre-switch defaults included", () => {
    // The newest SCORED default is a pre-switch seasonal vintage sitting below newer
    // post-switch sensitivities: it must still be the page's opening selection.
    const scoredPreSwitchDefault = run(
      "scored-pre-switch-default",
      "2026-11-01T12:00:00Z",
      modes("v3", "coupled", "seasonal"),
      584,
    );
    const newerSensitivity = run(
      "newer-sensitivity",
      "2026-11-20T12:00:00Z",
      modes("v3", "coupled", "seasonal"),
      0,
    );
    const newestPendingPostSwitchDefault = run(
      "newest-pending-post-switch-default",
      "2026-11-22T12:00:00Z",
      modes("v3", "coupled", "rostered_decay"),
      0,
    );

    expect(
      defaultAccuracyRun([newerSensitivity, newestPendingPostSwitchDefault, scoredPreSwitchDefault])
        ?.run_id,
    ).toBe("scored-pre-switch-default");
  });

  it("prefers a scored prospective default over newer scored or pending alternatives", () => {
    // August 2026 vintages: the era's default triple is v3/coupled/seasonal.
    const scoredDefault = run(
      "scored-default",
      "2026-08-15T12:01:00Z",
      modes("v3", "coupled", "seasonal"),
      584,
    );
    const newerDiagnostic = run(
      "newer-diagnostic",
      "2026-08-15T12:03:00Z",
      modes("v1", "v1", "seasonal"),
      584,
    );
    const newestPendingDefault = run(
      "newest-pending-default",
      "2026-08-15T12:05:00Z",
      modes("v3", "coupled", "seasonal"),
      0,
    );

    expect(
      defaultAccuracyRun([newerDiagnostic, newestPendingDefault, scoredDefault])?.run_id,
    ).toBe("scored-default");
  });

  it("falls back to a scored alternative, then a pending default, then any vintage", () => {
    const scoredDiagnostic = run(
      "scored-diagnostic",
      "2026-08-15T12:03:00Z",
      modes("v1", "v1", "seasonal"),
      2,
    );
    const pendingDefault = run(
      "pending-default",
      "2026-08-15T12:02:00Z",
      modes("v3", "coupled", "seasonal"),
      0,
    );
    const pendingUnknown = run(
      "pending-unknown",
      "2026-08-15T12:04:00Z",
      null,
      0,
    );

    expect(defaultAccuracyRun([pendingDefault, scoredDiagnostic])?.run_id).toBe(
      "scored-diagnostic",
    );
    expect(defaultAccuracyRun([pendingUnknown, pendingDefault])?.run_id).toBe(
      "pending-default",
    );
    expect(defaultAccuracyRun([pendingUnknown])?.run_id).toBe("pending-unknown");
  });

  it("orders options newest-first without mutating input and labels exact provenance", () => {
    const older = run(
      "7425b337c746abcdef",
      "2026-08-15T12:01:00Z",
      modes("v3", "coupled", "seasonal"),
      584,
    );
    const newer = run(
      "9649bb64d50fabcdef",
      "2026-08-15T12:02:00Z",
      modes("v1", "v1", "seasonal"),
      584,
    );
    const input = [older, newer];

    expect(orderedAccuracyRuns(input).map(({ run_id }) => run_id)).toEqual([
      newer.run_id,
      older.run_id,
    ]);
    expect(input.map(({ run_id }) => run_id)).toEqual([older.run_id, newer.run_id]);
    expect(accuracyComponentLabel(older.component_modes)).toBe(
      "goals v3 · assists coupled · appearance seasonal",
    );
    expect(accuracyRunLabel(older)).toBe(
      "Prospective default · goals v3 · assists coupled · appearance seasonal · " +
        "2026-27 GW1-5 · 584 scored · 7425b337c746",
    );
  });
});


it("labels incumbent shadow separately and opens its scored primary counterpart", () => {
  // September 2026 vintages: the era's default triple is v3/coupled/seasonal.
  const primary = run("primary", "2026-09-09T06:00:00Z",
    {...modes("v3", "coupled", "seasonal"), forecast_role: "primary", "football_environment.primary": "sdp_v2"}, 654);
  const shadow = run("shadow", "2026-09-09T06:01:00Z",
    {...modes("v3", "coupled", "seasonal"), forecast_role: "shadow_incumbent"}, 654);
  expect(defaultAccuracyRun([shadow, primary])?.run_id).toBe("primary");
  expect(accuracyRunLabel(shadow)).toContain("Incumbent shadow");
  expect(accuracyRunLabel(primary)).toContain("SDP V2 + fallback");
  expect(defaultAccuracyRun([shadow])?.run_id).toBe("shadow");
});
