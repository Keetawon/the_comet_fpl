import type { TeamActualFixture, TeamActualsRecord } from "@/data/types";

export interface TeamActualGameweek {
  season: string;
  gw: number;
}

export type TeamActualFixtureDetail = TeamActualFixture & { season: string };

function gameweekKey(season: string, gw: number): string {
  return `${season}:${gw}`;
}

function seasonStart(season: string): number {
  const match = /^(\d{4})-\d{2}$/.exec(season);
  return match == null ? Number.NEGATIVE_INFINITY : Number(match[1]);
}

/**
 * The page-wide completed-GW window for the selected Actual scope.
 *
 * The labels are selected once across all clubs so every expanded row uses the same
 * comparison window. Season is part of the label, so a rolling early-season view can
 * continue through the immediately preceding season without confusing its GW numbers.
 * A double gameweek contributes one label and retains every fixture leg.
 */
export function latestTeamActualGameweeks(
  teams: readonly TeamActualsRecord[],
  gameweekLimit = 5,
): TeamActualGameweek[] {
  if (gameweekLimit <= 0) return [];
  const distinct = new Map<string, TeamActualGameweek>();
  for (const team of teams) {
    for (const actual of team.actuals) {
      distinct.set(gameweekKey(team.season, actual.gw), {
        season: team.season,
        gw: actual.gw,
      });
    }
  }
  return [...distinct.values()]
    .sort(
      (left, right) =>
        seasonStart(right.season) - seasonStart(left.season) ||
        right.season.localeCompare(left.season) ||
        right.gw - left.gw,
    )
    .slice(0, gameweekLimit);
}

/** Fixture-grain club results inside the shared page window, newest first. */
export function teamActualDetailsForGameweeks(
  teams: readonly TeamActualsRecord[],
  gameweeks: readonly TeamActualGameweek[],
): TeamActualFixtureDetail[] {
  const rank = new Map(
    gameweeks.map((gameweek, index) => [gameweekKey(gameweek.season, gameweek.gw), index]),
  );
  return teams
    .flatMap((team) =>
      team.actuals.map((actual) => ({
        ...actual,
        season: team.season,
      })),
    )
    .filter((actual) => rank.has(gameweekKey(actual.season, actual.gw)))
    .sort(
      (left, right) =>
        (rank.get(gameweekKey(left.season, left.gw)) ?? Number.MAX_SAFE_INTEGER) -
          (rank.get(gameweekKey(right.season, right.gw)) ?? Number.MAX_SAFE_INTEGER) ||
        right.kickoff_time.localeCompare(left.kickoff_time) ||
        right.fixture - left.fixture,
    );
}
