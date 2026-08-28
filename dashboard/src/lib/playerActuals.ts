import type { PlayerActualFixture, PlayerFormWindow } from "@/data/types";

interface PlayerActualCollection {
  actuals: readonly PlayerActualFixture[];
}

interface SeasonalPlayerActualCollection extends PlayerActualCollection {
  season: string;
}

export interface ActualSeasonGameweek {
  season: string;
  gw: number;
}

export interface PlayerHistoricalFixture extends PlayerActualFixture {
  season: string;
}

export interface ActualGameweekRange {
  minGw: number;
  maxGw: number;
}

const seasonGameweekKey = (season: string, gw: number) => `${season}\u0000${gw}`;

/**
 * Shared rolling completed-GW labels across an explicitly ordered set of seasons.
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
  const seasonRank = new Map(seasonsNewestFirst.map((season, index) => [season, index]));
  const gameweeks = new Map<string, ActualSeasonGameweek>();
  for (const player of players) {
    if (!seasonRank.has(player.season)) continue;
    for (const actual of player.actuals) {
      const gameweek = { season: player.season, gw: actual.gw };
      gameweeks.set(seasonGameweekKey(gameweek.season, gameweek.gw), gameweek);
    }
  }
  return [...gameweeks.values()]
    .sort(
      (left, right) =>
        (seasonRank.get(left.season) ?? Number.MAX_SAFE_INTEGER) -
          (seasonRank.get(right.season) ?? Number.MAX_SAFE_INTEGER) ||
        right.gw - left.gw,
    )
    .slice(0, gameweekLimit);
}

/**
 * Fixture-grain history for an expanded Players row.
 *
 * The limit is five distinct completed season/gameweeks, not five fixtures: every leg of a
 * double gameweek is retained. Selection uses the shared page-level rolling window, so gaps are
 * not backfilled separately for a player.
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
      player.actuals.map((actual) => ({ ...actual, season: player.season })),
    )
    .filter((row) => selectedOrder.has(seasonGameweekKey(row.season, row.gw)))
    .sort(
      (left, right) =>
        (selectedOrder.get(seasonGameweekKey(left.season, left.gw)) ??
          Number.MAX_SAFE_INTEGER) -
          (selectedOrder.get(seasonGameweekKey(right.season, right.gw)) ??
            Number.MAX_SAFE_INTEGER) ||
        (right.kickoff_time ?? "").localeCompare(left.kickoff_time ?? "") ||
        right.fixture - left.fixture,
    );
}

/** Bounds come only from finalized actual rows for the explicitly selected season/player set. */
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
  actuals: readonly PlayerActualFixture[],
  gwFrom: number,
  gwTo: number,
): number | null {
  const appeared = actuals.filter(
    (row) => row.gw >= gwFrom && row.gw <= gwTo && row.minutes != null && row.minutes >= 1,
  );
  if (
    appeared.length === 0 ||
    appeared.some((row) => row.bps == null || !Number.isFinite(row.bps))
  ) {
    return null;
  }
  return appeared.reduce((total, row) => total + (row.bps ?? 0), 0) / appeared.length;
}

function sumMeasured(
  rows: readonly PlayerActualFixture[],
  key: keyof PlayerActualFixture,
): number | null {
  const values = rows
    .map((row) => row[key])
    .filter((value): value is number => typeof value === "number");
  return values.length === 0 ? null : values.reduce((total, value) => total + value, 0);
}

/**
 * Aggregate already-published observations with the same NULL rules as mart_fact_player_form.
 * An empty range has no observed form; it is never replaced by a previous-season window.
 */
export function aggregatePlayerActuals(
  actuals: readonly PlayerActualFixture[],
  gwFrom: number,
  gwTo: number,
): PlayerFormWindow | null {
  const selected = actuals.filter((row) => row.gw >= gwFrom && row.gw <= gwTo);
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
  const points =
    appeared.length > 0 && appeared.every((row) => row.points_under_rules_2026_27 != null)
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
