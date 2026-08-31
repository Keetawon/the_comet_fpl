import type {
  ComponentModes,
  ForecastAccuracyRunProvenance,
} from "@/data/types";

export type AccuracyRunRole =
  | "prospective_default"
  | "diagnostic_comparator"
  | "recorded_sensitivity"
  | "unclassified";

export interface AccuracyRunLike extends ForecastAccuracyRunProvenance {
  coverage: {
    scored_rows: number;
  };
}

const DEFAULT_MODES = {
  attacking: "v3",
  assists: "coupled",
  appearance: "seasonal",
} as const;

const DIAGNOSTIC_MODES = {
  attacking: "v1",
  assists: "v1",
  appearance: "seasonal",
} as const;

function matchesModes(
  modes: ComponentModes,
  expected: typeof DEFAULT_MODES | typeof DIAGNOSTIC_MODES,
) {
  return (
    modes.attacking_mode === expected.attacking &&
    modes.assists_mode === expected.assists &&
    modes.appearance_mode === expected.appearance
  );
}

/**
 * Classify one immutable forecast vintage from its declared component modes.
 * Missing modes never inherit the prospective-default label.
 */
export function accuracyRunRole(
  modes: ComponentModes | null,
): AccuracyRunRole {
  if (
    !modes ||
    !modes.attacking_mode ||
    !modes.assists_mode ||
    !modes.appearance_mode
  ) {
    return "unclassified";
  }
  if (matchesModes(modes, DEFAULT_MODES)) return "prospective_default";
  if (matchesModes(modes, DIAGNOSTIC_MODES)) return "diagnostic_comparator";
  return "recorded_sensitivity";
}

export function accuracyRunRoleLabel(role: AccuracyRunRole): string {
  switch (role) {
    case "prospective_default":
      return "Prospective default";
    case "diagnostic_comparator":
      return "Diagnostic comparator";
    case "recorded_sensitivity":
      return "Recorded sensitivity";
    case "unclassified":
      return "Unclassified vintage";
  }
}

export function accuracyComponentLabel(modes: ComponentModes | null): string {
  return [
    `goals ${modes?.attacking_mode ?? "?"}`,
    `assists ${modes?.assists_mode ?? "?"}`,
    `appearance ${modes?.appearance_mode ?? "?"}`,
  ].join(" · ");
}

export function accuracyRunLabel(run: AccuracyRunLike): string {
  return [
    accuracyRunRoleLabel(accuracyRunRole(run.component_modes)),
    accuracyComponentLabel(run.component_modes),
    `${run.season} GW${run.gw_from}-${run.gw_to}`,
    `${run.coverage.scored_rows} scored`,
    run.run_id.slice(0, 12),
  ].join(" · ");
}

function runTimestamp(run: AccuracyRunLike): number {
  for (const value of [run.created_at, run.as_of]) {
    if (!value) continue;
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return Number.NEGATIVE_INFINITY;
}

/** Newest first without mutating the read-model array. */
export function orderedAccuracyRuns<T extends AccuracyRunLike>(runs: readonly T[]): T[] {
  return [...runs].sort(
    (left, right) =>
      runTimestamp(right) - runTimestamp(left) ||
      right.run_id.localeCompare(left.run_id),
  );
}

/**
 * Monitoring opens on the newest scored prospective-default vintage. If one does
 * not exist, retain a useful scored view before falling back to pending vintages.
 */
export function defaultAccuracyRun<T extends AccuracyRunLike>(
  runs: readonly T[],
): T | undefined {
  const ordered = orderedAccuracyRuns(runs);
  return (
    ordered.find(
      (run) =>
        run.coverage.scored_rows > 0 &&
        accuracyRunRole(run.component_modes) === "prospective_default",
    ) ??
    ordered.find((run) => run.coverage.scored_rows > 0) ??
    ordered.find(
      (run) => accuracyRunRole(run.component_modes) === "prospective_default",
    ) ??
    ordered[0]
  );
}
