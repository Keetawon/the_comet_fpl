import { describe, expect, it } from "vitest";
import type { PlayerFixture, PlayerRecord, RulesSnapshot } from "@/data/types";
import {
  buildUserDraftLoadedHorizonContext,
  deriveUserDraftRules,
  rawPlayerGameweekXp,
  screenUserDraftHorizon,
  userDraftSelectionGuard,
  userDraftStructure,
  userDraftTotals,
} from "./userDraft";

const snapshot: RulesSnapshot = {
  contract_version: "test",
  season: "2026-27",
  squad_size: 15,
  budget_tenths: 1000,
  maximum_per_club: 3,
  positions: [
    { position: "GK", squad: 2, minimum_starters: 1, maximum_starters: 1 },
    { position: "DEF", squad: 5, minimum_starters: 3, maximum_starters: 5 },
    { position: "MID", squad: 5, minimum_starters: 2, maximum_starters: 5 },
    { position: "FWD", squad: 3, minimum_starters: 1, maximum_starters: 3 },
  ],
  lineup_starters: 11,
  captain_multiplier: 2,
  goalkeeper_bench_slots: 1,
  outfield_bench_slots: 3,
};

function fixture(gw: number, fixtureId: number, expectedPoints: number | null): PlayerFixture {
  return {
    gw,
    fixture: fixtureId,
    kickoff_time: `2026-08-${20 + gw}T12:00:00Z`,
    opponent_team_code: 900 + fixtureId,
    opponent_short_name: `O${fixtureId}`,
    was_home: true,
    expected_points: expectedPoints,
    probability_appears: null,
    probability_sixty_minutes: null,
    expected_goals: null,
    expected_assists: null,
    probability_clean_sheet: null,
    team_attack_ease_index: null,
    team_defence_ease_index: null,
    team_overall_ease_index: null,
    team_official_fdr: null,
    team_lambda_for: null,
    team_lambda_against: null,
    team_probability_clean_sheet: null,
  };
}

function player(
  code: number,
  position: string,
  teamCode: number,
  nowCost = 50,
  fixtures: PlayerFixture[] = [],
): PlayerRecord {
  return {
    run_id: "run-a",
    as_of: "2026-08-20T00:00:00Z",
    season: "2026-27",
    code,
    web_name: `Player ${code}`,
    position,
    team_code: teamCode,
    team_short_name: `T${teamCode}`,
    now_cost: nowCost,
    selected_by_percent: null,
    availability_status: "a",
    chance_of_playing: null,
    availability_multiplier: null,
    form: null,
    avg_minutes_last_5: null,
    fixtures,
  };
}

function legalSquad(
  xp: (code: number, gw: number) => number | null = () => 1,
  nowCost = 50,
): PlayerRecord[] {
  const positions = ["GK", "GK", ...Array(5).fill("DEF"), ...Array(5).fill("MID"), ...Array(3).fill("FWD")];
  return positions.map((position, index) => {
    const code = index + 1;
    const teamCode = (index % 5) + 1;
    return player(
      code,
      position,
      teamCode,
      nowCost,
      [1, 2, 3, 4, 5].map((gw) => fixture(gw, code * 10 + gw, xp(code, gw))),
    );
  });
}

describe("deriveUserDraftRules", () => {
  it("copies the recorded roster rules including the reference budget", () => {
    expect(deriveUserDraftRules(snapshot)).toEqual({
      squadSize: 15,
      budgetTenths: 1000,
      maximumPerClub: 3,
      lineupStarters: 11,
      positions: [
        { position: "GK", squad: 2, minimumStarters: 1, maximumStarters: 1 },
        { position: "DEF", squad: 5, minimumStarters: 3, maximumStarters: 5 },
        { position: "MID", squad: 5, minimumStarters: 2, maximumStarters: 5 },
        { position: "FWD", squad: 3, minimumStarters: 1, maximumStarters: 3 },
      ],
      positionQuota: { GK: 2, DEF: 5, MID: 5, FWD: 3 },
    });
  });

  it("rejects a snapshot whose quotas do not form its declared squad", () => {
    expect(() =>
      deriveUserDraftRules({
        ...snapshot,
        positions: snapshot.positions.map((item) =>
          item.position === "FWD" ? { ...item, squad: 2, maximum_starters: 2 } : item,
        ),
      }),
    ).toThrow(/position quotas total 14/);
  });
});

describe("rawPlayerGameweekXp", () => {
  it("sums a double gameweek, treats no fixture as zero, and propagates null", () => {
    const candidate = player(1, "MID", 1, 75, [
      fixture(1, 11, 2.25),
      fixture(1, 12, 3.5),
      fixture(3, 13, null),
    ]);

    expect(rawPlayerGameweekXp(candidate, 1)).toBe(5.75);
    expect(rawPlayerGameweekXp(candidate, 2)).toBe(0);
    expect(rawPlayerGameweekXp(candidate, 3)).toBeNull();
  });

  it("fails closed on a duplicate fixture row instead of double counting it", () => {
    const candidate = player(1, "MID", 1, 75, [
      fixture(1, 11, 2),
      fixture(1, 11, 2),
    ]);
    expect(rawPlayerGameweekXp(candidate, 1)).toBeNull();
  });
});

describe("user draft roster shape", () => {
  const rules = deriveUserDraftRules(snapshot);

  it("blocks duplicate, full-squad, position, club, and unknown-position additions", () => {
    const first = player(1, "GK", 1);
    expect(userDraftSelectionGuard([first], first, rules)).toEqual({
      allowed: false,
      reason: "duplicate_player",
    });
    expect(userDraftSelectionGuard(legalSquad(), player(99, "MID", 9), rules).reason).toBe(
      "squad_full",
    );
    expect(
      userDraftSelectionGuard([first, player(2, "GK", 2)], player(3, "GK", 3), rules).reason,
    ).toBe("position_full");
    expect(
      userDraftSelectionGuard(
        [player(1, "GK", 7), player(2, "DEF", 7), player(3, "MID", 7)],
        player(4, "FWD", 7),
        rules,
      ).reason,
    ).toBe("club_full");
    expect(userDraftSelectionGuard([], player(1, "AM", 1), rules).reason).toBe(
      "unknown_position",
    );
  });

  it("allows an unaffordable player and reports partial versus exact completeness", () => {
    const expensive = legalSquad(() => 1, 100);
    const partial = expensive.slice(0, 14);
    expect(userDraftSelectionGuard(partial, expensive[14], rules)).toEqual({
      allowed: true,
      reason: null,
    });
    expect(userDraftTotals(expensive, [1, 2, 3, 4, 5]).totalCostTenths).toBe(1500);
    expect(userDraftStructure(partial, rules)).toMatchObject({
      selectedCount: 14,
      isValidPartial: true,
      isComplete: false,
    });
    expect(userDraftStructure(expensive, rules)).toMatchObject({
      selectedCount: 15,
      uniquePlayerCount: 15,
      issues: [],
      isValidPartial: true,
      isComplete: true,
    });
  });

  it("detects malformed stored selections without counting them as complete", () => {
    const malformed = legalSquad();
    malformed[14] = malformed[0];
    const structure = userDraftStructure(malformed, rules);
    expect(structure.isValidPartial).toBe(false);
    expect(structure.isComplete).toBe(false);
    expect(structure.issues).toContain("duplicate_player");
  });
});

describe("userDraftTotals", () => {
  it("reports strict cost, GW, three-GW, and five-GW selected-set totals", () => {
    const selected = [
      player(1, "GK", 1, 45, [
        fixture(1, 11, 2),
        fixture(1, 12, 3),
        fixture(3, 13, 4),
        fixture(4, 14, 5),
        fixture(5, 15, 6),
      ]),
      player(2, "DEF", 2, 55, [
        fixture(1, 21, 1),
        fixture(2, 22, 2),
        fixture(3, 23, 3),
        fixture(4, 24, 4),
        fixture(5, 25, 5),
      ]),
    ];

    expect(userDraftTotals(selected, [5, 3, 1, 4, 2])).toEqual({
      selectedCount: 2,
      totalCostTenths: 100,
      xpByGw: { 1: 6, 2: 2, 3: 7, 4: 9, 5: 11 },
      totalThreeGameweeksXp: 15,
      totalFiveGameweeksXp: 35,
    });
  });

  it("never publishes a partial sum when price, player xP, or horizon coverage is missing", () => {
    const unknown = player(1, "GK", 1, 45, [
      fixture(1, 11, 2),
      fixture(2, 12, null),
    ]);
    const unknownPrice = player(2, "DEF", 2, 50, [fixture(1, 21, 3)]);
    unknownPrice.now_cost = null;

    const totals = userDraftTotals([unknown, unknownPrice], [1, 2, 3, 4, 5]);
    expect(totals.totalCostTenths).toBeNull();
    expect(totals.xpByGw).toEqual({ 1: 5, 2: null, 3: 0, 4: 0, 5: 0 });
    expect(totals.totalThreeGameweeksXp).toBeNull();
    expect(totals.totalFiveGameweeksXp).toBeNull();
    expect(userDraftTotals([unknown], [1, 2]).totalThreeGameweeksXp).toBeNull();
  });

  it("fails all dependent totals closed for a duplicate selected code", () => {
    const candidate = player(1, "MID", 1, 70, [fixture(1, 11, 4)]);
    expect(userDraftTotals([candidate, candidate], [1, 2, 3, 4, 5])).toEqual({
      selectedCount: 2,
      totalCostTenths: null,
      xpByGw: { 1: null, 2: null, 3: null, 4: null, 5: null },
      totalThreeGameweeksXp: null,
      totalFiveGameweeksXp: null,
    });
  });
});

describe("screenUserDraftHorizon", () => {
  const rules = deriveUserDraftRules(snapshot);
  const squad = legalSquad((code, gw) => {
    if (gw === 1 && (code === 1 || code === 2)) return 9;
    if (gw === 2 || gw === 3) return 3;
    if (gw === 4 && code === 15) return null;
    return 1;
  });

  it("screens complete all-player totals and individual xP with deterministic earliest ties", () => {
    expect(screenUserDraftHorizon(squad, rules, [5, 3, 1, 4, 2])).toEqual({
      highestCompleteSquadGameweek: { gw: 2, totalXp: 45 },
      highestIndividualPlayerGameweek: {
        gw: 1,
        playerCode: 1,
        playerName: "Player 1",
        expectedPoints: 9,
      },
    });
  });

  it("withholds the all-player screen for a partial squad but still screens its players", () => {
    expect(screenUserDraftHorizon(squad.slice(0, 14), rules, [1, 2, 3, 4, 5])).toEqual({
      highestCompleteSquadGameweek: null,
      highestIndividualPlayerGameweek: {
        gw: 1,
        playerCode: 1,
        playerName: "Player 1",
        expectedPoints: 9,
      },
    });
  });
});

describe("buildUserDraftLoadedHorizonContext", () => {
  const rules = deriveUserDraftRules(snapshot);

  it("uses the maximum-xP legal XI and resolves the highest bench-xP tie to the earliest GW", () => {
    const squad = legalSquad((code, gw) => {
      if (code === 15 && gw === 1) return 10;
      if (code === 2 && gw === 2) return 10;
      return 1;
    });

    const context = buildUserDraftLoadedHorizonContext(squad, rules, [2, 1]);
    expect(context.gameweeks.map(({ gw }) => gw)).toEqual([1, 2]);
    expect(context.gameweeks[0]).toMatchObject({
      gw: 1,
      available: true,
      fullSquadXp: 24,
      bestLegalXiXp: 20,
      benchXp: 4,
    });
    expect(context.gameweeks[0].bestLegalXiCodes).toContain(15);
    expect(context.gameweeks[1].bestLegalXiCodes).toContain(2);
    expect(context.gameweeks[1].bestLegalXiCodes).not.toContain(1);
    expect(context.highestBenchXpGameweek).toEqual({ gw: 1, benchXp: 4 });
  });

  it("makes incomplete squads and null-player gameweeks unavailable without partial sums", () => {
    const squad = legalSquad((code, gw) => (code === 15 && gw === 2 ? null : 1));
    const completeContext = buildUserDraftLoadedHorizonContext(squad, rules, [1, 2]);
    expect(completeContext.gameweeks[0]).toMatchObject({
      available: true,
      fullSquadXp: 15,
      bestLegalXiXp: 11,
      benchXp: 4,
    });
    expect(completeContext.gameweeks[1]).toEqual({
      gw: 2,
      available: false,
      fullSquadXp: null,
      bestLegalXiXp: null,
      benchXp: null,
      bestLegalXiCodes: null,
    });
    expect(completeContext.highestBenchXpGameweek).toEqual({ gw: 1, benchXp: 4 });

    const partialContext = buildUserDraftLoadedHorizonContext(squad.slice(0, 14), rules, [1]);
    expect(partialContext).toEqual({
      gameweeks: [
        {
          gw: 1,
          available: false,
          fullSquadXp: null,
          bestLegalXiXp: null,
          benchXp: null,
          bestLegalXiCodes: null,
        },
      ],
      highestBenchXpGameweek: null,
    });
  });
});
