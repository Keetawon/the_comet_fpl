// Player chip semantics: the headline is the fixture xP; the colour follows the view's CLUB
// metric (or official FDR when that source is selected); NULL in either stays neutral.

import { describe, expect, it } from "vitest";
import type { PlayerFixture } from "@/data/types";
import { easeBucket } from "@/lib/difficulty";
import { playerChipBucket, playerChipMetric } from "@/lib/playerChips";

const fixture = (overrides: Partial<PlayerFixture>): PlayerFixture => ({
  gw: 1,
  fixture: 100,
  kickoff_time: null,
  opponent_team_code: 102,
  opponent_short_name: "BET",
  was_home: true,
  expected_points: 7.4,
  probability_appears: null,
  probability_sixty_minutes: null,
  expected_goals: null,
  expected_assists: null,
  probability_clean_sheet: null,
  team_attack_ease_index: 129.8,
  team_defence_ease_index: 112.0,
  team_overall_ease_index: 120.5,
  team_official_fdr: 2,
  team_lambda_for: 2.4,
  team_lambda_against: 1.1,
  team_probability_clean_sheet: 0.38,
  ...overrides,
});

describe("playerChipMetric", () => {
  it("headlines the xP while the colour tracks the club ease metric", () => {
    const f = fixture({});
    const metric = playerChipMetric(f, "attack", "ease");
    expect(metric.value).toBe(7.4);
    expect(metric.display).toBe("7.4");
    // colour comes from the club attack ease, not from the headline xP
    expect(playerChipBucket(f, "attack", "ease")).toBe(easeBucket(129.8));
    expect(playerChipBucket(f, "attack", "ease")).toBe("much-easier");
    // defence view colours on the club's defence ease
    expect(playerChipBucket(f, "defense", "ease")).toBe(easeBucket(112.0));
    expect(playerChipBucket(f, "defense", "ease")).toBe("easier");
    // overall view colours on the club's overall ease
    expect(playerChipBucket(f, "overall", "ease")).toBe(easeBucket(120.5));
  });

  it("keeps every primitive behind the colour in the tooltip", () => {
    const title = playerChipMetric(fixture({}), "overall", "ease").title;
    expect(title).toContain("xP 7.40");
    expect(title).toContain("club λfor 2.40");
    expect(title).toContain("λagainst 1.10");
    expect(title).toContain("club CS 38%");
    expect(title).toContain("FDR 2");
  });

  it("FDR colour source switches the headline and the bucket, never blending ease", () => {
    const f = fixture({ team_official_fdr: 5 });
    const metric = playerChipMetric(f, "attack", "fdr");
    expect(metric.value).toBe(5);
    expect(metric.display).toBe("FDR 5");
    expect(playerChipBucket(f, "attack", "fdr")).toBe("much-harder");
  });

  it("null club metric -> neutral colour with no fabricated bucket, xP still readable", () => {
    const f = fixture({ team_overall_ease_index: null, team_official_fdr: null });
    expect(playerChipBucket(f, "overall", "ease")).toBeNull();
    expect(playerChipBucket(f, "overall", "fdr")).toBeNull();
    expect(playerChipMetric(f, "overall", "ease").display).toBe("7.4");
  });

  it("null xP -> blank headline (never 0), colour independent of the headline", () => {
    const metric = playerChipMetric(fixture({ expected_points: null }), "overall", "ease");
    expect(metric.value).toBeNull();
    expect(metric.display).toBe("–");
    expect(playerChipBucket(fixture({ expected_points: null }), "overall", "ease")).toBe(
      "much-easier",
    );
  });
});
