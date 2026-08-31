import { describe, expect, it } from "vitest";
import type { ComponentModes } from "@/data/types";
import {
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
  appearance = "seasonal",
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

describe("forecast accuracy run selection", () => {
  it("classifies only the complete frozen mode triples as default or comparator", () => {
    expect(accuracyRunRole(modes("v3", "coupled"))).toBe("prospective_default");
    expect(accuracyRunRole(modes("v1", "v1"))).toBe("diagnostic_comparator");
    expect(accuracyRunRole(modes("v3", "coupled", "model"))).toBe("recorded_sensitivity");
    expect(accuracyRunRole({ attacking_mode: "v3", assists_mode: "coupled" })).toBe(
      "unclassified",
    );
    expect(accuracyRunRole(null)).toBe("unclassified");
  });

  it("prefers a scored prospective default over newer scored or pending alternatives", () => {
    const scoredDefault = run(
      "scored-default",
      "2026-08-15T12:01:00Z",
      modes("v3", "coupled"),
      584,
    );
    const newerDiagnostic = run(
      "newer-diagnostic",
      "2026-08-15T12:03:00Z",
      modes("v1", "v1"),
      584,
    );
    const newestPendingDefault = run(
      "newest-pending-default",
      "2026-08-15T12:05:00Z",
      modes("v3", "coupled"),
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
      modes("v1", "v1"),
      2,
    );
    const pendingDefault = run(
      "pending-default",
      "2026-08-15T12:02:00Z",
      modes("v3", "coupled"),
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
      modes("v3", "coupled"),
      584,
    );
    const newer = run(
      "9649bb64d50fabcdef",
      "2026-08-15T12:02:00Z",
      modes("v1", "v1"),
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
