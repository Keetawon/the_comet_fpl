// Next-GW plan helpers: architecture labelling from component modes, the default-vs-
// diagnostic diff (derived here, not precomputed -- both plans ship complete), and horizon
// EV sums. Cross-plan EV differences are NEVER shown: they measure the two models'
// calibration against each other, not squad quality (DEV-ROADMAP P0.3).

import type { NextGwPlan, PlanWeek } from "@/data/types";

export interface ComponentModes {
  attacking_mode?: string | null;
  assists_mode?: string | null;
  appearance_mode?: string | null;
  [key: string]: string | null | undefined;
}

/** Anything plan-shaped that carries component modes (next-GW plans and audit plans). */
export interface ModeCarrier {
  component_modes: ComponentModes | null;
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

/** The plan the page opens on: the default architecture if present, else the first. */
export function defaultPlan<T extends ModeCarrier>(plans: T[]): T | null {
  return plans.find((p) => isDefaultArchitecture(p.component_modes)) ?? plans[0] ?? null;
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
    labelA: planLabel(a.component_modes),
    labelB: planLabel(b.component_modes),
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
