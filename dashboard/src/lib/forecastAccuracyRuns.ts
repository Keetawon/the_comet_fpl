import type {
  ComponentModes,
  ForecastAccuracyRunProvenance,
} from "@/data/types";

export type AccuracyRunRole =
  | "incumbent_shadow"
  | "prospective_default"
  | "diagnostic_comparator"
  | "recorded_sensitivity"
  | "unclassified";

export interface AccuracyRunLike extends ForecastAccuracyRunProvenance {
  coverage: {
    scored_rows: number;
  };
}

/**
 * The instant the prospective appearance default switched from `seasonal` to
 * `rostered_decay`: commit 86f4a32, 2026-11-21T08:21:09Z (2026-11-21T15:21:09+07:00),
 * recorded in AGENTS.md. Classification is era-aware: a vintage is the prospective
 * default when its complete mode triple matches the default in effect AT ITS OWN
 * CREATION, so pre-switch `v3/coupled/seasonal` vintages -- including the formal GW1
 * deadline default -- keep the "Prospective default" label and are never rewritten to
 * sensitivities. The diagnostic comparator follows the same era rule because the
 * runbook's diagnostic command inherits the default appearance mode.
 */
export const APPEARANCE_DEFAULT_SWITCHED_AT = "2026-11-21T08:21:09Z";

const SWITCH_EPOCH = Date.parse(APPEARANCE_DEFAULT_SWITCHED_AT);

function isPreSwitch(createdAt?: string | null): boolean {
  const parsed = createdAt ? Date.parse(createdAt) : Number.NaN;
  // A vintage without a parsable creation time cannot be placed in an era; the
  // read model always carries created_at, so this only affects degenerate inputs,
  // which classify against the post-switch (current) defaults.
  return Number.isFinite(parsed) && parsed < SWITCH_EPOCH;
}

function matchesModes(
  modes: ComponentModes,
  attacking: string,
  assists: string,
  appearance: string,
) {
  return (
    modes.attacking_mode === attacking &&
    modes.assists_mode === assists &&
    modes.appearance_mode === appearance
  );
}

/**
 * Classify one immutable forecast vintage from its declared component modes and the
 * default era its creation time falls in. Missing modes never inherit the
 * prospective-default label.
 */
export function accuracyRunRole(
  modes: ComponentModes | null,
  createdAt?: string | null,
): AccuracyRunRole {
  if (
    !modes ||
    !modes.attacking_mode ||
    !modes.assists_mode ||
    !modes.appearance_mode
  ) {
    return "unclassified";
  }
  if (modes.forecast_role === "shadow_incumbent") return "incumbent_shadow";
  const eraAppearance = isPreSwitch(createdAt) ? "seasonal" : "rostered_decay";
  if (matchesModes(modes, "v3", "coupled", eraAppearance)) return "prospective_default";
  if (matchesModes(modes, "v1", "v1", eraAppearance)) return "diagnostic_comparator";
  return "recorded_sensitivity";
}

export function accuracyRunRoleLabel(role: AccuracyRunRole): string {
  switch (role) {
    case "incumbent_shadow":
      return "Incumbent shadow";
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
    ...(modes?.["football_environment.primary"] === "sdp_v2" ? ["SDP V2 + fallback"] : []),
  ].join(" · ");
}

export function accuracyRunLabel(run: AccuracyRunLike): string {
  return [
    accuracyRunRoleLabel(accuracyRunRole(run.component_modes, run.created_at)),
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
        accuracyRunRole(run.component_modes, run.created_at) === "prospective_default",
    ) ??
    ordered.find((run) => run.coverage.scored_rows > 0) ??
    ordered.find(
      (run) => accuracyRunRole(run.component_modes, run.created_at) === "prospective_default",
    ) ??
    ordered[0]
  );
}
