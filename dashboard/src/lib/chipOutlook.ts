// Plan-bound squad totals for the loaded optimizer horizon. These are raw model-xP
// summaries, not a chip optimizer: they deliberately do not invent autosub probabilities,
// future availability, chip inventory, or gameweeks outside the published plan.

import type { NextGwPlan, PlanPlayer, PlanWeek } from "@/data/types";

export interface PlanWeekChipOutlook {
  gw: number;
  startingXiXp: number | null;
  benchXp: number | null;
  squadXp: number | null;
  completeSquad: boolean;
}

export interface PlanChipOutlook {
  weeks: PlanWeekChipOutlook[];
  highestBenchXpGw: number | null;
}

function measuredSum(players: PlanPlayer[]): number | null {
  let total = 0;
  for (const player of players) {
    if (player.expected_points == null || !Number.isFinite(player.expected_points)) return null;
    total += player.expected_points;
  }
  return total;
}

function hasCompleteSquadContract(week: PlanWeek): boolean {
  const uniqueCodes = new Set(week.players.map((player) => player.code));
  const starters = week.players.filter((player) => player.role === "starting_xi");
  const benchGoalkeepers = week.players.filter(
    (player) => player.role === "bench_goalkeeper",
  );
  const benchOutfield = week.players.filter((player) => player.role === "bench_outfield");
  const captain = starters.filter((player) => player.code === week.captain_code);
  const viceCaptain = starters.filter((player) => player.code === week.vice_captain_code);
  const flaggedCaptains = week.players.filter((player) => player.is_captain);
  const flaggedViceCaptains = week.players.filter((player) => player.is_vice_captain);
  return (
    week.players.length === 15 &&
    uniqueCodes.size === 15 &&
    starters.length === 11 &&
    benchGoalkeepers.length === 1 &&
    benchOutfield.length === 3 &&
    captain.length === 1 &&
    viceCaptain.length === 1 &&
    captain[0].code !== viceCaptain[0].code &&
    flaggedCaptains.length === 1 &&
    flaggedCaptains[0].code === captain[0].code &&
    flaggedViceCaptains.length === 1 &&
    flaggedViceCaptains[0].code === viceCaptain[0].code
  );
}

function weekOutlook(week: PlanWeek): PlanWeekChipOutlook {
  const completeSquad = hasCompleteSquadContract(week);
  if (!completeSquad) {
    return {
      gw: week.gw,
      startingXiXp: null,
      benchXp: null,
      squadXp: null,
      completeSquad,
    };
  }

  const starters = week.players.filter((player) => player.role === "starting_xi");
  const bench = week.players.filter((player) => player.role !== "starting_xi");
  const startingXiXp = measuredSum(starters);
  const benchXp = measuredSum(bench);
  const squadXp =
    startingXiXp == null || benchXp == null ? null : startingXiXp + benchXp;

  return {
    gw: week.gw,
    startingXiXp,
    benchXp,
    squadXp,
    completeSquad,
  };
}

/**
 * Derive raw XI, bench, and full-squad xP totals per published plan week. Any missing player
 * xP propagates to the aggregate that needs it; a partial sum is never presented as measured.
 * The highest-bench marker uses the four bench players' complete raw xP, with the earliest
 * gameweek winning an exact tie.
 */
export function buildPlanChipOutlook(plan: NextGwPlan): PlanChipOutlook {
  const weeks = [...plan.weeks].sort((left, right) => left.gw - right.gw).map(weekOutlook);
  let highestBenchXpGw: number | null = null;
  let highestBenchXp = Number.NEGATIVE_INFINITY;
  for (const week of weeks) {
    if (week.benchXp != null && week.benchXp > highestBenchXp) {
      highestBenchXp = week.benchXp;
      highestBenchXpGw = week.gw;
    }
  }

  return { weeks, highestBenchXpGw };
}
