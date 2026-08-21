// Opponent strength: a club-quality index derived at display time ONLY from the run's
// published team lambdas. For each club we average its lambda-for and lambda-against
// across the loaded horizon and combine them multiplicatively, the same shape as the
// overall ease index but measured on the OPPONENT club itself:
//
//   strength_club = 100 * sqrt((avgFor / league) * (league / avgAgainst))
//
// ~100 = an average club. HIGHER = a STRONGER opponent, i.e. a harder fixture -- the
// reverse direction of an ease index, which is exactly why the fixture grid colours on
// it: a strong club's own row stops being uniformly green because the colour now
// follows the opponent, not the row club. It is never blended into the published ease
// indices or the official FDR.

import type { TeamRecord } from "@/data/types";
import type { DifficultyBucket } from "@/lib/difficulty";

export const OPPONENT_STRENGTH_FORMULA = "opponent-strength-v1";
export const SCHEDULE_EASE_PROXY_FORMULA = "fixture-ease-proxy-v1";

export interface OpponentStrength {
  index: number | null;
  avgFor: number | null;
  avgAgainst: number | null;
  leagueAverage: number | null;
}

export interface ScheduleEaseProxy {
  attackEase: number | null;
  defenceEase: number | null;
  overallEase: number | null;
  probabilityCleanSheet: number | null;
}

export function buildOpponentStrength(teams: TeamRecord[]): Map<number, OpponentStrength> {
  const leagueValues: number[] = [];
  const perTeam = new Map<number, { for: number[]; against: number[] }>();
  for (const team of teams) {
    for (const f of team.fixtures) {
      if (f.lambda_for == null || f.lambda_against == null) continue;
      leagueValues.push(f.lambda_for, f.lambda_against);
      const bucket = perTeam.get(team.team_code) ?? { for: [], against: [] };
      bucket.for.push(f.lambda_for);
      bucket.against.push(f.lambda_against);
      perTeam.set(team.team_code, bucket);
    }
  }
  const league =
    leagueValues.length
      ? leagueValues.reduce((a, b) => a + b, 0) / leagueValues.length
      : null;
  const result = new Map<number, OpponentStrength>();
  for (const [code, { for: fs, against }] of perTeam) {
    const avgFor = fs.reduce((a, b) => a + b, 0) / fs.length;
    const avgAgainst = against.reduce((a, b) => a + b, 0) / against.length;
    const index =
      league != null && league > 0
        ? 100 * Math.sqrt((avgFor / league) * (league / avgAgainst))
        : null;
    result.set(code, { index, avgFor, avgAgainst, leagueAverage: league });
  }
  return result;
}

/**
 * Display-only later-schedule proxy. It composes the selected vintage's average club attack and
 * defence levels for the named club and its opponent. It deliberately has no later fixture model,
 * venue adjustment, or schedule input beyond the opponent identity.
 */
export function scheduleEaseProxy(
  own: OpponentStrength | null | undefined,
  opponent: OpponentStrength | null | undefined,
): ScheduleEaseProxy {
  const unavailable: ScheduleEaseProxy = {
    attackEase: null,
    defenceEase: null,
    overallEase: null,
    probabilityCleanSheet: null,
  };
  const league = own?.leagueAverage;
  if (
    own == null ||
    opponent == null ||
    league == null ||
    !Number.isFinite(league) ||
    league <= 0 ||
    own.avgFor == null ||
    own.avgAgainst == null ||
    opponent.avgFor == null ||
    opponent.avgAgainst == null
  ) {
    return unavailable;
  }

  const lambdaFor = (own.avgFor * opponent.avgAgainst) / league;
  const lambdaAgainst = (own.avgAgainst * opponent.avgFor) / league;
  if (
    !Number.isFinite(lambdaFor) ||
    lambdaFor < 0 ||
    !Number.isFinite(lambdaAgainst) ||
    lambdaAgainst < 0
  ) {
    return unavailable;
  }
  const attackEase = (100 * lambdaFor) / league;
  const defenceEase = lambdaAgainst > 0 ? (100 * league) / lambdaAgainst : null;
  return {
    attackEase,
    defenceEase,
    overallEase:
      defenceEase == null ? null : Math.sqrt(Math.max(0, attackEase * defenceEase)),
    probabilityCleanSheet: Math.exp(-lambdaAgainst),
  };
}

/**
 * Reversed-direction bucketing: a HIGH index is a strong opponent = hard = red. The
 * bucket names stay ease-worded (green end = "much-easier") because they name the
 * fixture, not the club.
 */
export function opponentStrengthBucket(value: number | null | undefined): DifficultyBucket | null {
  if (value == null) return null;
  if (value <= 85) return "much-easier";
  if (value <= 95) return "easier";
  if (value <= 105) return "average";
  if (value <= 120) return "harder";
  return "much-harder";
}
