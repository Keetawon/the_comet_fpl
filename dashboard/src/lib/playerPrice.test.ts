import { describe, expect, it } from "vitest";
import sample from "@/data/samplePlayers.json";
import type { PlayerRecord } from "@/data/types";
import { INITIAL_PLAYER_FILTERS, matchesPlayerFilters } from "@/components/PlayerFiltersBar";
import { playerPrice, playerPriceTitle } from "./playerPrice";

const frozen = sample.players[0] as unknown as PlayerRecord;
const player: PlayerRecord = { ...frozen, now_cost: 48, current_price: {
  source: "FPL", season: frozen.season, code: frozen.code, now_cost: 49,
  captured_at: "2026-09-17T13:40:49Z", capture_id: "latest", source_sha256: "b".repeat(64),
  semantics: "current_reported_not_forecast",
} };

describe("current display price versus frozen planning price", () => {
  it("uses the current report for display/filtering without changing forecast or default planning filters", () => {
    const before = JSON.stringify(player);
    expect(playerPrice(player, "current")).toBe(49);
    expect(playerPrice(player, "forecast")).toBe(48);
    const filters = { ...INITIAL_PLAYER_FILTERS, maxPrice: "4.8" };
    expect(matchesPlayerFilters(player, filters, "current")).toBe(false);
    expect(matchesPlayerFilters(player, filters)).toBe(true);
    expect(playerPriceTitle(player, "current")).toContain("captured 2026-09-17T13:40:49Z");
    expect(JSON.stringify(player)).toBe(before);
  });

  it("keeps missing/legacy prices unavailable and rejects foreign reporting identity", () => {
    for (const current_price of [undefined, null, { ...player.current_price!, now_cost: null },
      { ...player.current_price!, code: -1 }, { ...player.current_price!, season: "2025-26" },
    ]) {
      const record = { ...player, current_price };
      expect(playerPrice(record, "current")).toBeNull();
      expect(playerPrice(record, "forecast")).toBe(48);
      expect(matchesPlayerFilters(record, { ...INITIAL_PLAYER_FILTERS, minPrice: "0" }, "current")).toBe(false);
    }
  });
});
