// Pure helpers for the manual User Draft sandbox. They operate only on one loaded
// forecast vintage and the recorded FPL roster-shape rules. Cost is reported, never
// used as a selection constraint: an intentionally unaffordable draft is still useful.

import type { PlayerRecord, RulesSnapshot } from "@/data/types";

export interface UserDraftPositionRule {
  position: string;
  squad: number;
  minimumStarters: number;
  maximumStarters: number;
}

export interface UserDraftRules {
  squadSize: number;
  budgetTenths: number;
  maximumPerClub: number;
  lineupStarters: number;
  positions: readonly UserDraftPositionRule[];
  positionQuota: Readonly<Record<string, number>>;
}

export type UserDraftSelectionBlockReason =
  | "duplicate_player"
  | "squad_full"
  | "unknown_position"
  | "position_full"
  | "club_full";

export type UserDraftSelectionGuard =
  | { allowed: true; reason: null }
  | { allowed: false; reason: UserDraftSelectionBlockReason };

export type UserDraftStructureIssue =
  | "duplicate_player"
  | "squad_overflow"
  | "unknown_position"
  | "position_overflow"
  | "club_overflow";

export interface UserDraftStructure {
  selectedCount: number;
  uniquePlayerCount: number;
  positionCounts: Readonly<Record<string, number>>;
  clubCounts: Readonly<Record<string, number>>;
  issues: readonly UserDraftStructureIssue[];
  isValidPartial: boolean;
  isComplete: boolean;
}

export interface UserDraftTotals {
  selectedCount: number;
  totalCostTenths: number | null;
  xpByGw: Readonly<Record<number, number | null>>;
  totalThreeGameweeksXp: number | null;
  totalFiveGameweeksXp: number | null;
}

export interface UserDraftSquadGameweekScreen {
  gw: number;
  totalXp: number;
}

export interface UserDraftIndividualGameweekScreen {
  gw: number;
  playerCode: number;
  playerName: string;
  expectedPoints: number;
}

export interface UserDraftHorizonScreen {
  /** Present only for a structurally complete squad and a fully measured gameweek. */
  highestCompleteSquadGameweek: UserDraftSquadGameweekScreen | null;
  /** A descriptive raw-xP screen; it assigns no captain, lineup, or other playing role. */
  highestIndividualPlayerGameweek: UserDraftIndividualGameweekScreen | null;
}

export interface UserDraftGameweekLineupContext {
  gw: number;
  available: boolean;
  fullSquadXp: number | null;
  bestLegalXiXp: number | null;
  benchXp: number | null;
  bestLegalXiCodes: readonly number[] | null;
}

export interface UserDraftBenchGameweekScreen {
  gw: number;
  benchXp: number;
}

export interface UserDraftLoadedHorizonContext {
  gameweeks: readonly UserDraftGameweekLineupContext[];
  highestBenchXpGameweek: UserDraftBenchGameweekScreen | null;
}

function requirePositiveInteger(value: number, label: string): void {
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${label} must be a positive integer`);
  }
}

function requireNonnegativeInteger(value: number, label: string): void {
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`${label} must be a nonnegative integer`);
  }
}

/** Copy the roster-shape contract from a published optimizer rules snapshot. */
export function deriveUserDraftRules(snapshot: RulesSnapshot): UserDraftRules {
  requirePositiveInteger(snapshot.squad_size, "squad_size");
  requirePositiveInteger(snapshot.budget_tenths, "budget_tenths");
  requirePositiveInteger(snapshot.maximum_per_club, "maximum_per_club");
  requirePositiveInteger(snapshot.lineup_starters, "lineup_starters");
  if (snapshot.lineup_starters > snapshot.squad_size) {
    throw new Error("lineup_starters cannot exceed squad_size");
  }
  if (snapshot.positions.length === 0) {
    throw new Error("positions must not be empty");
  }

  const seen = new Set<string>();
  const positions = snapshot.positions.map(
    ({ position, squad, minimum_starters, maximum_starters }) => {
      const cleanPosition = position.trim();
      if (!cleanPosition) throw new Error("position must not be empty");
      if (seen.has(cleanPosition)) throw new Error(`duplicate position ${cleanPosition}`);
      requirePositiveInteger(squad, `${cleanPosition} squad quota`);
      requireNonnegativeInteger(minimum_starters, `${cleanPosition} minimum starters`);
      requireNonnegativeInteger(maximum_starters, `${cleanPosition} maximum starters`);
      if (minimum_starters > maximum_starters) {
        throw new Error(`${cleanPosition} minimum starters cannot exceed maximum starters`);
      }
      if (maximum_starters > squad) {
        throw new Error(`${cleanPosition} maximum starters cannot exceed squad quota`);
      }
      seen.add(cleanPosition);
      return {
        position: cleanPosition,
        squad,
        minimumStarters: minimum_starters,
        maximumStarters: maximum_starters,
      };
    },
  );
  const quotaTotal = positions.reduce((total, item) => total + item.squad, 0);
  if (quotaTotal !== snapshot.squad_size) {
    throw new Error(
      `position quotas total ${quotaTotal}, expected squad_size ${snapshot.squad_size}`,
    );
  }
  const minimumLineup = positions.reduce(
    (total, item) => total + item.minimumStarters,
    0,
  );
  const maximumLineup = positions.reduce(
    (total, item) => total + item.maximumStarters,
    0,
  );
  if (minimumLineup > snapshot.lineup_starters || maximumLineup < snapshot.lineup_starters) {
    throw new Error("position starter bounds cannot form lineup_starters");
  }

  return {
    squadSize: snapshot.squad_size,
    budgetTenths: snapshot.budget_tenths,
    maximumPerClub: snapshot.maximum_per_club,
    lineupStarters: snapshot.lineup_starters,
    positions,
    positionQuota: Object.fromEntries(
      positions.map(({ position, squad }) => [position, squad]),
    ),
  };
}

function countBy<T>(values: readonly T[], keyOf: (value: T) => string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const value of values) {
    const key = keyOf(value);
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
}

/** Explain whether one more player can be added. Budget is deliberately absent. */
export function userDraftSelectionGuard(
  selected: readonly PlayerRecord[],
  candidate: PlayerRecord,
  rules: UserDraftRules,
): UserDraftSelectionGuard {
  if (selected.some((player) => player.code === candidate.code)) {
    return { allowed: false, reason: "duplicate_player" };
  }
  if (selected.length >= rules.squadSize) {
    return { allowed: false, reason: "squad_full" };
  }
  const positionQuota = rules.positionQuota[candidate.position];
  if (positionQuota == null) {
    return { allowed: false, reason: "unknown_position" };
  }
  if (selected.filter((player) => player.position === candidate.position).length >= positionQuota) {
    return { allowed: false, reason: "position_full" };
  }
  if (selected.filter((player) => player.team_code === candidate.team_code).length >= rules.maximumPerClub) {
    return { allowed: false, reason: "club_full" };
  }
  return { allowed: true, reason: null };
}

/** Report partial validity separately from exact roster-shape completeness. */
export function userDraftStructure(
  selected: readonly PlayerRecord[],
  rules: UserDraftRules,
): UserDraftStructure {
  const uniquePlayerCount = new Set(selected.map((player) => player.code)).size;
  const positionCounts = countBy(selected, (player) => player.position);
  const clubCounts = countBy(selected, (player) => String(player.team_code));
  const issues = new Set<UserDraftStructureIssue>();

  if (uniquePlayerCount !== selected.length) issues.add("duplicate_player");
  if (selected.length > rules.squadSize) issues.add("squad_overflow");
  for (const [position, count] of Object.entries(positionCounts)) {
    const quota = rules.positionQuota[position];
    if (quota == null) issues.add("unknown_position");
    else if (count > quota) issues.add("position_overflow");
  }
  if (Object.values(clubCounts).some((count) => count > rules.maximumPerClub)) {
    issues.add("club_overflow");
  }

  const isValidPartial = issues.size === 0;
  const isComplete =
    isValidPartial &&
    selected.length === rules.squadSize &&
    rules.positions.every(
      ({ position, squad }) => (positionCounts[position] ?? 0) === squad,
    );
  return {
    selectedCount: selected.length,
    uniquePlayerCount,
    positionCounts,
    clubCounts,
    issues: [...issues],
    isValidPartial,
    isComplete,
  };
}

/** Sum a player's distinct fixtures in one GW. A blank gameweek is a measured zero. */
export function rawPlayerGameweekXp(player: PlayerRecord, gw: number): number | null {
  if (!Number.isInteger(gw) || gw <= 0) throw new Error("gw must be a positive integer");
  const fixtures = player.fixtures.filter((fixture) => fixture.gw === gw);
  if (fixtures.length === 0) return 0;

  const fixtureIds = new Set<number>();
  let total = 0;
  for (const fixture of fixtures) {
    if (fixtureIds.has(fixture.fixture)) return null;
    fixtureIds.add(fixture.fixture);
    if (fixture.expected_points == null || !Number.isFinite(fixture.expected_points)) {
      return null;
    }
    total += fixture.expected_points;
  }
  return total;
}

function chronologicalGameweeks(loadedGws: readonly number[]): number[] {
  const seen = new Set<number>();
  for (const gw of loadedGws) {
    if (!Number.isInteger(gw) || gw <= 0) throw new Error("gameweeks must be positive integers");
    if (seen.has(gw)) throw new Error(`duplicate loaded gameweek ${gw}`);
    seen.add(gw);
  }
  return [...loadedGws].sort((left, right) => left - right);
}

function strictSum(values: readonly (number | null)[]): number | null {
  let total = 0;
  for (const value of values) {
    if (value == null || !Number.isFinite(value)) return null;
    total += value;
  }
  return total;
}

function cumulativeXp(
  xpByGw: Readonly<Record<number, number | null>>,
  gws: readonly number[],
  count: number,
): number | null {
  if (gws.length < count) return null;
  return strictSum(gws.slice(0, count).map((gw) => xpByGw[gw] ?? null));
}

/** Strict selected-set totals: one unknown input makes its dependent total unknown. */
export function userDraftTotals(
  selected: readonly PlayerRecord[],
  loadedGws: readonly number[],
): UserDraftTotals {
  const gws = chronologicalGameweeks(loadedGws);
  const uniqueSelection = new Set(selected.map((player) => player.code)).size === selected.length;
  const costs = selected.map((player) =>
    player.now_cost != null && Number.isFinite(player.now_cost) && player.now_cost >= 0
      ? player.now_cost
      : null,
  );
  const totalCostTenths = uniqueSelection ? strictSum(costs) : null;
  const xpByGw: Record<number, number | null> = {};
  for (const gw of gws) {
    xpByGw[gw] = uniqueSelection
      ? strictSum(selected.map((player) => rawPlayerGameweekXp(player, gw)))
      : null;
  }

  return {
    selectedCount: selected.length,
    totalCostTenths,
    xpByGw,
    totalThreeGameweeksXp: uniqueSelection ? cumulativeXp(xpByGw, gws, 3) : null,
    totalFiveGameweeksXp: uniqueSelection ? cumulativeXp(xpByGw, gws, 5) : null,
  };
}

/**
 * Screen the loaded horizon by raw xP only. These outputs do not choose lineup roles and
 * do not constitute a playing-chip recommendation.
 */
export function screenUserDraftHorizon(
  selected: readonly PlayerRecord[],
  rules: UserDraftRules,
  loadedGws: readonly number[],
): UserDraftHorizonScreen {
  const gws = chronologicalGameweeks(loadedGws);
  const structure = userDraftStructure(selected, rules);
  const totals = userDraftTotals(selected, gws);

  let highestCompleteSquadGameweek: UserDraftSquadGameweekScreen | null = null;
  if (structure.isComplete) {
    for (const gw of gws) {
      const totalXp = totals.xpByGw[gw] ?? null;
      if (
        totalXp != null &&
        (highestCompleteSquadGameweek == null ||
          totalXp > highestCompleteSquadGameweek.totalXp)
      ) {
        highestCompleteSquadGameweek = { gw, totalXp };
      }
    }
  }

  // Chronological GW order, then stable player code, makes exact ties deterministic.
  const stablePlayers = [...selected].sort((left, right) => left.code - right.code);
  let highestIndividualPlayerGameweek: UserDraftIndividualGameweekScreen | null = null;
  for (const gw of gws) {
    for (const player of stablePlayers) {
      const expectedPoints = rawPlayerGameweekXp(player, gw);
      if (
        expectedPoints != null &&
        (highestIndividualPlayerGameweek == null ||
          expectedPoints > highestIndividualPlayerGameweek.expectedPoints)
      ) {
        highestIndividualPlayerGameweek = {
          gw,
          playerCode: player.code,
          playerName: player.web_name,
          expectedPoints,
        };
      }
    }
  }

  return { highestCompleteSquadGameweek, highestIndividualPlayerGameweek };
}

function isLegalUserDraftLineup(
  lineup: readonly PlayerRecord[],
  rules: UserDraftRules,
): boolean {
  if (lineup.length !== rules.lineupStarters) return false;
  const counts = countBy(lineup, (player) => player.position);
  return rules.positions.every(({ position, minimumStarters, maximumStarters }) => {
    const count = counts[position] ?? 0;
    return count >= minimumStarters && count <= maximumStarters;
  });
}

interface ScoredUserDraftLineup {
  totalXp: number;
  codes: readonly number[];
}

function bestLegalUserDraftLineup(
  selected: readonly PlayerRecord[],
  rules: UserDraftRules,
  gw: number,
): ScoredUserDraftLineup | null {
  const scored = [...selected]
    .sort((left, right) => left.code - right.code)
    .map((player) => ({ player, xp: rawPlayerGameweekXp(player, gw) }));
  if (scored.some(({ xp }) => xp == null)) return null;

  let best: ScoredUserDraftLineup | null = null;
  const chosen: PlayerRecord[] = [];
  const visit = (start: number, totalXp: number): void => {
    if (chosen.length === rules.lineupStarters) {
      if (isLegalUserDraftLineup(chosen, rules) && (best == null || totalXp > best.totalXp)) {
        best = { totalXp, codes: chosen.map((player) => player.code) };
      }
      return;
    }
    const needed = rules.lineupStarters - chosen.length;
    for (let index = start; index <= scored.length - needed; index += 1) {
      const candidate = scored[index];
      if (candidate.xp == null) continue;
      chosen.push(candidate.player);
      visit(index + 1, totalXp + candidate.xp);
      chosen.pop();
    }
  };
  visit(0, 0);
  return best;
}

/**
 * Build descriptive loaded-horizon lineup context for one complete manual squad. "Bench"
 * means the players outside that GW's maximum-raw-xP legal XI. This does not apply captain
 * multipliers, hits, autosubs, availability overlays, or recommend when to play anything.
 */
export function buildUserDraftLoadedHorizonContext(
  selected: readonly PlayerRecord[],
  rules: UserDraftRules,
  loadedGws: readonly number[],
): UserDraftLoadedHorizonContext {
  const gws = chronologicalGameweeks(loadedGws);
  const complete = userDraftStructure(selected, rules).isComplete;
  const gameweeks = gws.map<UserDraftGameweekLineupContext>((gw) => {
    if (!complete) {
      return {
        gw,
        available: false,
        fullSquadXp: null,
        bestLegalXiXp: null,
        benchXp: null,
        bestLegalXiCodes: null,
      };
    }
    const fullSquadXp = strictSum(selected.map((player) => rawPlayerGameweekXp(player, gw)));
    const bestLineup = bestLegalUserDraftLineup(selected, rules, gw);
    if (fullSquadXp == null || bestLineup == null) {
      return {
        gw,
        available: false,
        fullSquadXp: null,
        bestLegalXiXp: null,
        benchXp: null,
        bestLegalXiCodes: null,
      };
    }
    return {
      gw,
      available: true,
      fullSquadXp,
      bestLegalXiXp: bestLineup.totalXp,
      benchXp: fullSquadXp - bestLineup.totalXp,
      bestLegalXiCodes: bestLineup.codes,
    };
  });

  let highestBenchXpGameweek: UserDraftBenchGameweekScreen | null = null;
  for (const context of gameweeks) {
    if (
      context.benchXp != null &&
      (highestBenchXpGameweek == null || context.benchXp > highestBenchXpGameweek.benchXp)
    ) {
      highestBenchXpGameweek = { gw: context.gw, benchXp: context.benchXp };
    }
  }
  return { gameweeks, highestBenchXpGameweek };
}
