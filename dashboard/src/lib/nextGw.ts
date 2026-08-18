// Next-GW plan helpers: architecture labelling from component modes, the default-vs-
// diagnostic diff (derived here, not precomputed -- both plans ship complete), and horizon
// EV sums. Cross-plan EV differences are NEVER shown: they measure the two models'
// calibration against each other, not squad quality (DEV-ROADMAP P0.3).

import type { NextGwPlan, PlanKind, PlanWeek } from "@/data/types";

export interface ComponentModes {
  attacking_mode?: string | null;
  assists_mode?: string | null;
  appearance_mode?: string | null;
  [key: string]: string | null | undefined;
}

/** Anything plan-shaped that carries component modes (next-GW plans and audit plans). */
export interface ModeCarrier {
  component_modes: ComponentModes | null;
  plan_kind?: PlanKind;
  display_label?: string;
}

/** True when the plan's forecast ran the frozen default architecture. */
export function isDefaultArchitecture(modes: ComponentModes | null): boolean {
  return modes?.attacking_mode === "v3" && modes?.assists_mode === "coupled";
}

export function planLabel(modes: ComponentModes | null): string {
  if (!modes) return "unknown architecture";
  const goals = modes.attacking_mode ?? "?";
  const assists = modes.assists_mode ?? "?";
  const tag = isDefaultArchitecture(modes) ? "default" : "diagnostic";
  return `${goals} goals / ${assists} assists (${tag})`;
}

/** Product ownership is explicit in the read model; architecture never decides it. */
export function resolvedPlanKind(plan: ModeCarrier): PlanKind {
  if (
    plan.plan_kind === "platform_default" ||
    plan.plan_kind === "platform_diagnostic" ||
    plan.plan_kind === "user_custom"
  ) {
    return plan.plan_kind;
  }
  throw new Error(
    "plan_kind is required; product ownership is never inferred from model architecture",
  );
}

export function isPlatformPlan(plan: ModeCarrier): boolean {
  return resolvedPlanKind(plan) !== "user_custom";
}

export function platformPlans<T extends ModeCarrier>(plans: T[]): T[] {
  return plans.filter(isPlatformPlan);
}

export function planDisplayLabel(plan: ModeCarrier): string {
  if (plan.display_label) return plan.display_label;
  const architecture = planLabel(plan.component_modes).replace(/ ((default|diagnostic))$/, "");
  switch (resolvedPlanKind(plan)) {
    case "platform_default":
      return "Platform default — " + architecture;
    case "platform_diagnostic":
      return "Diagnostic sensitivity — " + architecture;
    case "user_custom":
      return "Your plan — " + architecture;
  }
}

/** The plan the page opens on: the default architecture if present, else the first. */
export function defaultPlan<T extends ModeCarrier>(plans: T[]): T | null {
  return (
    plans.find((p) => resolvedPlanKind(p) === "platform_default") ??
    plans.find((p) => resolvedPlanKind(p) === "platform_diagnostic") ??
    plans.find((p) => resolvedPlanKind(p) === "user_custom") ??
    null
  );
}

/** The only pair valid for the formal default-vs-diagnostic set comparison. */
export function platformComparisonPlans<T extends ModeCarrier>(
  plans: T[],
): { defaultPlan: T; diagnosticPlan: T } | null {
  const platformDefault = plans.find((p) => resolvedPlanKind(p) === "platform_default");
  const diagnostic = plans.find((p) => resolvedPlanKind(p) === "platform_diagnostic");
  return platformDefault && diagnostic
    ? { defaultPlan: platformDefault, diagnosticPlan: diagnostic }
    : null;
}

/**
 * A player's EV over the next `weeks` gameweeks from the plan's first week. Any unmeasured
 * (null) gameweek makes the total null -- never a partial sum dressed as measured.
 */
export function horizonXp(
  plan: NextGwPlan,
  code: number,
  weeks: number,
): number | null {
  const byGw = plan.player_xp[String(code)];
  if (!byGw) return null;
  let total: number | null = 0;
  for (let gw = plan.gw_from; gw < plan.gw_from + weeks; gw++) {
    const value = byGw[String(gw)];
    if (value == null) return null;
    total += value;
  }
  return total;
}

export interface PlanDiff {
  planA: string;
  planB: string;
  labelA: string;
  labelB: string;
  gw: number;
  squadOverlap: number;
  squadSize: number;
  xiOverlap: number;
  captainAgrees: boolean;
  viceAgrees: boolean;
  sharedCodes: number[];
  uniqueToA: number[];
  uniqueToB: number[];
}

function weekSquad(week: PlanWeek): { squad: Set<number>; xi: Set<number> } {
  const squad = new Set(week.players.map((p) => p.code));
  const xi = new Set(week.players.filter((p) => p.role === "starting_xi").map((p) => p.code));
  return { squad, xi };
}

function overlap(a: Set<number>, b: Set<number>): number {
  let count = 0;
  for (const value of a) if (b.has(value)) count++;
  return count;
}

/** Default-vs-diagnostic diff at the two plans' first shared gameweek. */
export function diffPlans(a: NextGwPlan, b: NextGwPlan): PlanDiff | null {
  const firstA = a.weeks[0];
  const firstB = b.weeks[0];
  if (!firstA || !firstB || firstA.gw !== firstB.gw) return null;
  const squadA = weekSquad(firstA);
  const squadB = weekSquad(firstB);
  const shared = [...squadA.squad].filter((code) => squadB.squad.has(code)).sort((x, y) => x - y);
  return {
    planA: a.optimizer_run_id,
    planB: b.optimizer_run_id,
    labelA: planDisplayLabel(a),
    labelB: planDisplayLabel(b),
    gw: firstA.gw,
    squadOverlap: shared.length,
    squadSize: Math.max(squadA.squad.size, squadB.squad.size),
    xiOverlap: overlap(squadA.xi, squadB.xi),
    captainAgrees: firstA.captain_code === firstB.captain_code,
    viceAgrees: firstA.vice_captain_code === firstB.vice_captain_code,
    sharedCodes: shared,
    uniqueToA: [...squadA.squad].filter((code) => !squadB.squad.has(code)).sort((x, y) => x - y),
    uniqueToB: [...squadB.squad].filter((code) => !squadA.squad.has(code)).sort((x, y) => x - y),
  };
}

/** Resolves a code to a display name inside one plan's weeks (any week that names it). */
export function playerName(plan: NextGwPlan, code: number): string {
  for (const week of plan.weeks) {
    const player = week.players.find((p) => p.code === code);
    if (player) return player.web_name;
  }
  return `code ${code}`;
}
