import type { PlayerActualFixture, PlayerFormWindow } from "@/data/types";

interface PlayerActualCollection {
  actuals: readonly PlayerActualFixture[];
}

export interface ActualGameweekRange {
  minGw: number;
  maxGw: number;
}

/** Bounds come only from finalized actual rows for the explicitly selected season/player set. */
export function actualGameweekRange(
  players: readonly PlayerActualCollection[],
): ActualGameweekRange | null {
  const gameweeks = players.flatMap((player) => player.actuals.map((actual) => actual.gw));
  if (gameweeks.length === 0) return null;
  return { minGw: Math.min(...gameweeks), maxGw: Math.max(...gameweeks) };
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
