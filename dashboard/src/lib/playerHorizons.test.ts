import { describe, expect, it } from "vitest";
import sample from "@/data/samplePlayerHorizons.json";
import type { PlayerHorizonsRecord } from "@/data/types";
import { indexPlayerHorizons, playerHorizon } from "./playerHorizons";

const records: PlayerHorizonsRecord[] = sample.players.map((player) => ({
  ...player,
  horizons: player.horizons.map(
    ([gw_to, xp, p_le_2, p_ge_2, p_ge_4, p_ge_6, p_ge_10, p_ge_15]) => ({
      gw_to,
      xp,
      p_le_2,
      p_ge_2,
      p_ge_4,
      p_ge_6,
      p_ge_10,
      p_ge_15,
    }),
  ),
}));
const index = indexPlayerHorizons(records);

describe("playerHorizon", () => {
  it("returns the exact published endpoint without probability arithmetic", () => {
    expect(playerHorizon(index, "run-a", "2026-27", 1, 2)).toEqual(
      records[0].horizons[1],
    );
  });

  it("does not interpolate, substitute another vintage, or accept a missing endpoint", () => {
    expect(playerHorizon(index, "run-a", "2026-27", 1, 6)).toBeNull();
    expect(playerHorizon(index, "another-run", "2026-27", 1, 2)).toBeNull();
    expect(playerHorizon(index, "run-a", "2025-26", 1, 2)).toBeNull();
  });
});
