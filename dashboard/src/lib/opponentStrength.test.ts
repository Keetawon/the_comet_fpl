// Opponent-strength derivation: index values from the sample lambdas, bucket direction
// (high = strong opponent = the red end), and NULL propagation.

import { describe, expect, it } from "vitest";
import sample from "@/data/sampleFixtureMatrix.json";
import type { TeamRecord } from "@/data/types";
import {
  buildOpponentStrength,
  OPPONENT_STRENGTH_FORMULA,
  opponentStrengthBucket,
  scheduleEaseProxy,
} from "@/lib/opponentStrength";

const teams = sample.teams as TeamRecord[];

describe("buildOpponentStrength", () => {
  it("rates the club that scores little and concedes lots as weak, the strong club high", () => {
    const strength = buildOpponentStrength(teams);
    // Beta: avgFor 1.35, avgAgainst 1.65 vs league 1.35 -> ~90 (weak)
    expect(strength.get(102)!.index).toBeCloseTo(90.5, 0);
    // Alpha: avgFor 1.5, avgAgainst 1.05 -> ~119.5 (strong)
    expect(strength.get(101)!.index).toBeCloseTo(119.5, 0);
  });

  it("keeps clubs whose lambdas are all-null out of the map entirely", () => {
    const strength = buildOpponentStrength([
      ...teams,
      { ...teams[0], team_code: 999, fixtures: [] },
    ]);
    expect(strength.has(999)).toBe(false);
  });
});

describe("scheduleEaseProxy", () => {
  it("composes the selected-vintage club and opponent averages without a later forecast", () => {
    const strength = buildOpponentStrength(teams);
    const proxy = scheduleEaseProxy(strength.get(101), strength.get(102));
    expect(proxy.attackEase).toBeCloseTo(135.8, 1);
    expect(proxy.defenceEase).toBeCloseTo(128.6, 1);
    expect(proxy.overallEase).toBeCloseTo(132.1, 1);
    expect(proxy.probabilityCleanSheet).toBeCloseTo(Math.exp(-1.05), 6);
  });

  it("preserves missing inputs as null instead of fabricating an average fixture", () => {
    expect(scheduleEaseProxy(undefined, undefined)).toEqual({
      attackEase: null,
      defenceEase: null,
      overallEase: null,
      probabilityCleanSheet: null,
    });
  });
});

describe("opponentStrengthBucket", () => {
  it("reverses the ease direction: a high index is a hard opponent", () => {
    expect(opponentStrengthBucket(84)).toBe("much-easier");
    expect(opponentStrengthBucket(90)).toBe("easier");
    expect(opponentStrengthBucket(100)).toBe("average");
    expect(opponentStrengthBucket(110)).toBe("harder");
    expect(opponentStrengthBucket(125)).toBe("much-harder");
  });

  it("returns null for unmeasured strength, never a fabricated bucket", () => {
    expect(opponentStrengthBucket(null)).toBeNull();
    expect(opponentStrengthBucket(undefined)).toBeNull();
  });
});

it("exposes both factors without changing the composite formula", () => {
  const teams = [
    { team_code: 1, fixtures: [{ lambda_for: 1.8, lambda_against: 1.5 }] },
    { team_code: 2, fixtures: [{ lambda_for: 1.5, lambda_against: 1.2 }] },
    { team_code: 3, fixtures: [{ lambda_for: null, lambda_against: null }] },
  ] as TeamRecord[];
  const all = buildOpponentStrength(teams);
  const opponent = all.get(1)!;
  expect(OPPONENT_STRENGTH_FORMULA).toBe("opponent-strength-v1");
  expect(opponent.attackStrength).toBeCloseTo(120);
  expect(opponent.defenceStrength).toBeCloseTo(100);
  expect(opponent.index).toBeCloseTo(100 * Math.sqrt(1.2));
  expect(all.has(3)).toBe(false);
});
