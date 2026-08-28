import type { TeamActualFixture, TeamActualsRecord } from "@/data/types";

/**
 * The page-wide completed-GW window for one explicitly selected Actual season.
 *
 * The labels are selected once across all clubs so every expanded row uses the same
 * comparison window. A double gameweek contributes one label and retains every fixture leg.
 */
export function latestTeamActualGameweeks(
  teams: readonly TeamActualsRecord[],
  gameweekLimit = 5,
): number[] {
  if (gameweekLimit <= 0) return [];
  return [...new Set(teams.flatMap((team) => team.actuals.map((actual) => actual.gw)))]
    .sort((left, right) => right - left)
    .slice(0, gameweekLimit);
}

/** Fixture-grain club results inside the shared page window, newest first. */
export function teamActualDetailsForGameweeks(
  actuals: readonly TeamActualFixture[],
  gameweeks: readonly number[],
): TeamActualFixture[] {
  const selectedGameweeks = new Set(gameweeks);
  return actuals
    .filter((actual) => selectedGameweeks.has(actual.gw))
    .sort(
      (left, right) =>
        right.gw - left.gw ||
        right.kickoff_time.localeCompare(left.kickoff_time) ||
        right.fixture - left.fixture,
    );
}
