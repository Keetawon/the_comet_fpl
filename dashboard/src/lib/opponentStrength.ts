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

export interface OpponentStrength {
  index: number | null;
  avgFor: number | null;
  avgAgainst: number | null;
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
    result.set(code, { index, avgFor, avgAgainst });
  }
  return result;
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
