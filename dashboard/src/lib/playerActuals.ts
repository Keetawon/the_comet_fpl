import type {
  OutcomeStatus,
  PlayerActualFixture,
  PlayerActualsRecord,
  PlayerFormWindow,
  PlayerObservedActualsRecord,
  PlayerObservedFixture,
  PlayerProvisionalActualsRecord,
} from "@/data/types";

type PlayerObservedSourceFixture = Omit<PlayerActualFixture, "points_under_rules_2026_27"> & {
  points_under_rules_2026_27?: number | null;
  outcome_status?: OutcomeStatus;
  total_points_as_recorded?: number | null;
};

interface PlayerActualCollection {
  actuals: readonly PlayerObservedSourceFixture[];
}

interface SeasonalPlayerActualCollection extends PlayerActualCollection {
  season: string;
}

export interface ActualSeasonGameweek {
  season: string;
  gw: number;
  outcome_status: OutcomeStatus;
}

export interface PlayerHistoricalFixture extends PlayerActualFixture {
  season: string;
  outcome_status: OutcomeStatus;
  total_points_as_recorded: number | null;
}

export interface ActualGameweekRange {
  minGw: number;
  maxGw: number;
}

const seasonGameweekKey = (season: string, gw: number) => `${season}\u0000${gw}`;

const PLAYER_FIXTURE_IDENTITY_FIELDS = [
  "gw",
  "kickoff_time",
  "team_code",
  "team_short_name",
  "opponent_team_code",
  "opponent_short_name",
  "was_home",
] as const;

function normalizedPlayerFixture(
  actual: PlayerObservedSourceFixture,
  outcomeStatus: OutcomeStatus,
): PlayerObservedFixture {
  return {
    ...actual,
    points_under_rules_2026_27: actual.points_under_rules_2026_27 ?? null,
    outcome_status: outcomeStatus,
    total_points_as_recorded:
      outcomeStatus === "provisional" ? actual.total_points_as_recorded ?? null : null,
  };
}

function assertSamePlayerFixtureIdentity(
  finalized: PlayerObservedFixture,
  provisional: PlayerObservedFixture,
  identity: string,
): void {
  if (
    PLAYER_FIXTURE_IDENTITY_FIELDS.some(
      (field) => finalized[field] !== provisional[field],
    )
  ) {
    throw new Error(
      `finalized and provisional player rows disagree on fixture identity ${identity}`,
    );
  }
}

/**
 * Merge immutable finalized history with one latest provisional capture for display only.
 * A finalized row replaces its provisional predecessor, but fixture identity disagreement fails.
 */
export function mergePlayerActualRecords(
  finalizedRecords: readonly PlayerActualsRecord[],
  provisionalRecords: readonly PlayerProvisionalActualsRecord[],
): PlayerObservedActualsRecord[] {
  const records = new Map<string, Map<number, PlayerObservedFixture>>();
  const identityOf = (season: string, code: number) => `${season}\u0000${code}`;
  const add = (
    season: string,
    code: number,
    actual: PlayerObservedSourceFixture,
    status: OutcomeStatus,
  ) => {
    const recordIdentity = identityOf(season, code);
    const fixtures = records.get(recordIdentity) ?? new Map<number, PlayerObservedFixture>();
    const incoming = normalizedPlayerFixture(actual, status);
    const existing = fixtures.get(actual.fixture);
    if (existing != null) {
      if (existing.outcome_status === status) {
        throw new Error(
          `duplicate ${status} player fixture ${season}/${code}/${actual.fixture}`,
        );
      }
      const finalized = status === "finalized" ? incoming : existing;
      const provisional = status === "provisional" ? incoming : existing;
      assertSamePlayerFixtureIdentity(
        finalized,
        provisional,
        `${season}/${code}/${actual.fixture}`,
      );
      fixtures.set(actual.fixture, finalized);
    } else {
      fixtures.set(actual.fixture, incoming);
    }
    records.set(recordIdentity, fixtures);
  };

  for (const record of provisionalRecords) {
    for (const actual of record.actuals) add(record.season, record.code, actual, "provisional");
  }
  for (const record of finalizedRecords) {
    for (const actual of record.actuals) add(record.season, record.code, actual, "finalized");
  }

  return [...records.entries()]
    .map(([identity, fixtures]) => {
      const separator = identity.lastIndexOf("\u0000");
      const season = identity.slice(0, separator);
      const code = Number(identity.slice(separator + 1));
      return {
        season,
        code,
        actuals: [...fixtures.values()].sort(
          (left, right) =>
            left.gw - right.gw ||
            Date.parse(left.kickoff_time) - Date.parse(right.kickoff_time) ||
            left.fixture - right.fixture,
        ),
      };
    })
    .sort((left, right) => left.season.localeCompare(right.season) || left.code - right.code);
}

/**
 * Shared rolling ended-GW labels across an explicitly ordered set of seasons.
 *
 * The caller supplies newest season first, so the season boundary is deterministic and does not
 * depend on string ordering. The page-wide set is selected before any player's detail is built;
 * an individual player with a gap therefore cannot backfill an older gameweek.
 */
export function latestActualGameweeks(
  players: readonly SeasonalPlayerActualCollection[],
  seasonsNewestFirst: readonly string[],
  gameweekLimit = 5,
): ActualSeasonGameweek[] {
  if (gameweekLimit <= 0) return [];
  return actualGameweeksChronological(players, seasonsNewestFirst)
    .slice(-gameweekLimit)
    .reverse();
}

/** Exact published season/GW keys in chronological order across the allowed two-season scope. */
export function actualGameweeksChronological(
  players: readonly SeasonalPlayerActualCollection[],
  seasonsNewestFirst: readonly string[],
): ActualSeasonGameweek[] {
  const seasonRank = new Map(seasonsNewestFirst.map((season, index) => [season, index]));
  const gameweeks = new Map<string, ActualSeasonGameweek>();
  for (const player of players) {
    if (!seasonRank.has(player.season)) continue;
    for (const actual of player.actuals) {
      const key = seasonGameweekKey(player.season, actual.gw);
      const existing = gameweeks.get(key);
      const outcomeStatus = actual.outcome_status ?? "finalized";
      const gameweek = {
        season: player.season,
        gw: actual.gw,
        outcome_status:
          existing?.outcome_status === "provisional" || outcomeStatus === "provisional"
            ? "provisional" as const
            : "finalized" as const,
      };
      gameweeks.set(key, gameweek);
    }
  }
  return [...gameweeks.values()]
    .sort(
      (left, right) =>
        (seasonRank.get(right.season) ?? Number.MIN_SAFE_INTEGER) -
          (seasonRank.get(left.season) ?? Number.MIN_SAFE_INTEGER) ||
        left.gw - right.gw,
    );
}

/**
 * Fixture-grain observations for an exact page-wide set of season/gameweek keys.
 *
 * Callers may pass the selectable main-table slice or the fixed latest-five expansion window.
 * Every double-gameweek leg is retained, and gaps are never backfilled separately for a player.
 */
export function latestPlayerActualDetails(
  players: readonly SeasonalPlayerActualCollection[],
  selectedGameweeks: readonly ActualSeasonGameweek[],
): PlayerHistoricalFixture[] {
  const selectedOrder = new Map(
    selectedGameweeks.map((gameweek, index) => [
      seasonGameweekKey(gameweek.season, gameweek.gw),
      index,
    ]),
  );
  return players
    .flatMap((player) =>
      player.actuals.map((actual) => ({
        ...actual,
        season: player.season,
        points_under_rules_2026_27: actual.points_under_rules_2026_27 ?? null,
        outcome_status: actual.outcome_status ?? "finalized",
        total_points_as_recorded: actual.total_points_as_recorded ?? null,
      })),
    )
    .filter((row) => selectedOrder.has(seasonGameweekKey(row.season, row.gw)))
    .sort(
      (left, right) =>
        (selectedOrder.get(seasonGameweekKey(left.season, left.gw)) ??
          Number.MAX_SAFE_INTEGER) -
          (selectedOrder.get(seasonGameweekKey(right.season, right.gw)) ??
            Number.MAX_SAFE_INTEGER) ||
        Date.parse(right.kickoff_time) - Date.parse(left.kickoff_time) ||
        right.fixture - left.fixture,
    );
}

/** Stable visible label for an exact ended season/GW selector. */
export function actualGameweekLabel(gameweek: ActualSeasonGameweek): string {
  return `${gameweek.season} GW${gameweek.gw}${
    gameweek.outcome_status === "provisional" ? " (provisional)" : ""
  }`;
}

/** Bounds come only from supplied observed rows for the explicitly selected season/player set. */
export function actualGameweekRange(
  players: readonly PlayerActualCollection[],
): ActualGameweekRange | null {
  const gameweeks = players.flatMap((player) => player.actuals.map((actual) => actual.gw));
  if (gameweeks.length === 0) return null;
  return { minGw: Math.min(...gameweeks), maxGw: Math.max(...gameweeks) };
}

/**
 * Descriptive BPS rate for the selected observed scope.
 * Every appeared fixture is one denominator unit; DNPs are excluded and partial BPS evidence
 * fails closed rather than depressing the average silently.
 */
export function averageBpsPerAppearance(
  actuals: readonly PlayerObservedSourceFixture[],
): number | null {
  const appeared = actuals.filter(
    (row) => row.minutes != null && row.minutes >= 1,
  );
  if (
    appeared.length === 0 ||
    appeared.some((row) => row.bps == null || !Number.isFinite(row.bps))
  ) {
    return null;
  }
  return appeared.reduce((total, row) => total + (row.bps ?? 0), 0) / appeared.length;
}

export interface ObservedPointsTotal {
  points: number | null;
  includesProvisional: boolean;
}

/**
 * Display-only points total with the two sources kept explicit: finalized rows use the
 * 2026/27 replay, while provisional rows use raw FPL points from the latest capture.
 */
export function aggregateObservedPoints(
  actuals: readonly PlayerObservedSourceFixture[],
): ObservedPointsTotal {
  const includesProvisional = actuals.some(
    (row) => row.outcome_status === "provisional",
  );
  const values = actuals.map((row) =>
    row.outcome_status === "provisional"
      ? row.total_points_as_recorded ?? null
      : row.points_under_rules_2026_27,
  );
  return {
    points:
      actuals.length > 0 && values.every((value) => value != null)
        ? values.reduce<number>((total, value) => total + (value ?? 0), 0)
        : null,
    includesProvisional,
  };
}

function sumMeasured(
  rows: readonly PlayerObservedSourceFixture[],
  key: keyof PlayerActualFixture,
): number | null {
  const values = rows
    .map((row) => row[key])
    .filter((value): value is number => typeof value === "number");
  return values.length === 0 ? null : values.reduce((total, value) => total + value, 0);
}

/**
 * Display-only observed xGI/90. Keep the two published component rates authoritative and
 * fail closed unless both are finite; a missing component must never be treated as zero.
 */
export function expectedGoalInvolvementsPer90(
  form: PlayerFormWindow | null | undefined,
): number | null {
  const expectedGoalsPer90 = form?.expected_goals_per_90;
  const expectedAssistsPer90 = form?.expected_assists_per_90;
  return expectedGoalsPer90 != null &&
    expectedAssistsPer90 != null &&
    Number.isFinite(expectedGoalsPer90) &&
    Number.isFinite(expectedAssistsPer90)
    ? expectedGoalsPer90 + expectedAssistsPer90
    : null;
}

/**
 * Aggregate already-selected, already-published observations with the same NULL rules as
 * mart_fact_player_form. An empty selection has no observed form; this helper never backfills it.
 */
export function aggregatePlayerActuals(
  actuals: readonly PlayerObservedSourceFixture[],
): PlayerFormWindow | null {
  const selected = actuals;
  if (selected.length === 0) return null;

  const appeared = selected.filter((row) => row.minutes != null && row.minutes >= 1);
  const measuredGoals = appeared.filter((row) => row.expected_goals != null);
  const measuredAssists = appeared.filter((row) => row.expected_assists != null);
  const goalMinutes = sumMeasured(measuredGoals, "minutes");
  const assistMinutes = sumMeasured(measuredAssists, "minutes");
  const expectedGoals = sumMeasured(appeared, "expected_goals");
  const expectedAssists = sumMeasured(appeared, "expected_assists");
  const starts = selected.every((row) => row.starts != null)
    ? selected.reduce((total, row) => total + (row.starts ?? 0), 0)
    : null;
  const includesProvisional = selected.some(
    (row) => row.outcome_status === "provisional",
  );
  const points =
    !includesProvisional &&
    appeared.length > 0 &&
    appeared.every((row) => row.points_under_rules_2026_27 != null)
      ? appeared.reduce((total, row) => total + (row.points_under_rules_2026_27 ?? 0), 0)
      : null;

  return {
    rostered_fixtures: selected.length,
    appearances: appeared.length,
    starts,
    did_not_play: selected.filter((row) => row.minutes === 0).length,
    minutes: sumMeasured(selected, "minutes"),
    goals_scored: sumMeasured(appeared, "goals_scored"),
    assists: sumMeasured(appeared, "assists"),
    clean_sheets: sumMeasured(appeared, "clean_sheets"),
    goals_conceded: sumMeasured(appeared, "goals_conceded"),
    saves: sumMeasured(appeared, "saves"),
    bonus: sumMeasured(appeared, "bonus"),
    bps: sumMeasured(appeared, "bps"),
    defensive_contribution: sumMeasured(appeared, "defensive_contribution"),
    expected_goals: expectedGoals,
    expected_assists: expectedAssists,
    expected_goals_conceded: sumMeasured(appeared, "expected_goals_conceded"),
    expected_goals_per_90:
      expectedGoals != null && goalMinutes != null && goalMinutes > 0
        ? (90 * expectedGoals) / goalMinutes
        : null,
    expected_assists_per_90:
      expectedAssists != null && assistMinutes != null && assistMinutes > 0
        ? (90 * expectedAssists) / assistMinutes
        : null,
    points_under_rules_2026_27: points,
  };
}
