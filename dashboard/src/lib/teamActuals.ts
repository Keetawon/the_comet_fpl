import type {
  OutcomeStatus,
  TeamActualFixture,
  TeamActualsRecord,
  TeamObservedActualsRecord,
  TeamObservedFixture,
  TeamProvisionalActualsRecord,
} from "@/data/types";

type TeamObservedSourceFixture = TeamActualFixture & { outcome_status?: OutcomeStatus };
type TeamObservedCollection = Omit<TeamActualsRecord, "actuals"> & {
  actuals: readonly TeamObservedSourceFixture[];
};

export interface TeamActualGameweek {
  season: string;
  gw: number;
  outcome_status: OutcomeStatus;
}

export type TeamActualFixtureDetail = TeamObservedFixture & { season: string };

const TEAM_FIXTURE_IDENTITY_FIELDS = [
  "gw",
  "kickoff_time",
  "opponent_team_code",
  "opponent_short_name",
  "was_home",
] as const;

function normalizedTeamFixture(
  actual: TeamObservedSourceFixture,
  outcomeStatus: OutcomeStatus,
): TeamObservedFixture {
  return { ...actual, outcome_status: outcomeStatus };
}

function assertSameTeamFixtureIdentity(
  finalized: TeamObservedFixture,
  provisional: TeamObservedFixture,
  identity: string,
): void {
  if (
    TEAM_FIXTURE_IDENTITY_FIELDS.some(
      (field) => finalized[field] !== provisional[field],
    )
  ) {
    throw new Error(
      `finalized and provisional team rows disagree on fixture identity ${identity}`,
    );
  }
}

/** Merge finalized club history with one provisional capture for display only. */
export function mergeTeamActualRecords(
  finalizedRecords: readonly TeamActualsRecord[],
  provisionalRecords: readonly TeamProvisionalActualsRecord[],
): TeamObservedActualsRecord[] {
  const records = new Map<string, Map<number, TeamObservedFixture>>();
  const identityOf = (season: string, teamCode: number) => `${season}\u0000${teamCode}`;
  const add = (
    season: string,
    teamCode: number,
    actual: TeamObservedSourceFixture,
    status: OutcomeStatus,
  ) => {
    const recordIdentity = identityOf(season, teamCode);
    const fixtures = records.get(recordIdentity) ?? new Map<number, TeamObservedFixture>();
    const incoming = normalizedTeamFixture(actual, status);
    const existing = fixtures.get(actual.fixture);
    if (existing != null) {
      if (existing.outcome_status === status) {
        throw new Error(
          `duplicate ${status} team fixture ${season}/${teamCode}/${actual.fixture}`,
        );
      }
      const finalized = status === "finalized" ? incoming : existing;
      const provisional = status === "provisional" ? incoming : existing;
      assertSameTeamFixtureIdentity(
        finalized,
        provisional,
        `${season}/${teamCode}/${actual.fixture}`,
      );
      fixtures.set(actual.fixture, finalized);
    } else {
      fixtures.set(actual.fixture, incoming);
    }
    records.set(recordIdentity, fixtures);
  };

  for (const record of provisionalRecords) {
    for (const actual of record.actuals) {
      add(record.season, record.team_code, actual, "provisional");
    }
  }
  for (const record of finalizedRecords) {
    for (const actual of record.actuals) {
      add(record.season, record.team_code, actual, "finalized");
    }
  }

  return [...records.entries()]
    .map(([identity, fixtures]) => {
      const separator = identity.lastIndexOf("\u0000");
      const season = identity.slice(0, separator);
      const teamCode = Number(identity.slice(separator + 1));
      return {
        season,
        team_code: teamCode,
        actuals: [...fixtures.values()].sort(
          (left, right) =>
            left.gw - right.gw ||
            Date.parse(left.kickoff_time) - Date.parse(right.kickoff_time) ||
            left.fixture - right.fixture,
        ),
      };
    })
    .sort(
      (left, right) =>
        left.season.localeCompare(right.season) || left.team_code - right.team_code,
    );
}

function gameweekKey(season: string, gw: number): string {
  return `${season}:${gw}`;
}

function seasonStart(season: string): number {
  const match = /^(\d{4})-\d{2}$/.exec(season);
  return match == null ? Number.NEGATIVE_INFINITY : Number(match[1]);
}

export function teamActualGameweekLabel(gameweek: TeamActualGameweek): string {
  return `${gameweek.season} GW${gameweek.gw}${
    gameweek.outcome_status === "provisional" ? " (provisional)" : ""
  }`;
}

/**
 * The page-wide ended-GW window for the selected Actual scope.
 *
 * The labels are selected once across all clubs so every expanded row uses the same
 * comparison window. Season is part of the label, so a rolling early-season view can
 * continue through the immediately preceding season without confusing its GW numbers.
 * A double gameweek contributes one label and retains every fixture leg.
 */
export function latestTeamActualGameweeks(
  teams: readonly TeamObservedCollection[],
  gameweekLimit = 5,
): TeamActualGameweek[] {
  if (gameweekLimit <= 0) return [];
  const distinct = new Map<string, TeamActualGameweek>();
  for (const team of teams) {
    for (const actual of team.actuals) {
      const key = gameweekKey(team.season, actual.gw);
      const existing = distinct.get(key);
      const status = actual.outcome_status ?? "finalized";
      distinct.set(key, {
        season: team.season,
        gw: actual.gw,
        outcome_status:
          existing?.outcome_status === "provisional" || status === "provisional"
            ? "provisional"
            : "finalized",
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
  teams: readonly TeamObservedCollection[],
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
        outcome_status: actual.outcome_status ?? "finalized",
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
