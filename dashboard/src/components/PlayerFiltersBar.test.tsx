import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import sample from "@/data/samplePlayers.json";
import type { PlayerRecord } from "@/data/types";
import { INITIAL_PLAYER_FILTERS, matchesPlayerFilters, PlayerFiltersBar } from "./PlayerFiltersBar";

function reportedPlayer(status: string | null): PlayerRecord {
  const player = sample.players[0] as unknown as PlayerRecord;
  return { ...player, availability_status: "a", current_availability: {
    source: "FPL", season: player.season, code: player.code, status,
    chance_of_playing_next_round: 0, news: null, news_added: null,
    captured_at: "2026-09-17T06:34:00Z", capture_id: "latest", source_sha256: "a".repeat(64),
    next_gw: 5, semantics: "current_reported_not_forecast",
  } };
}

describe("unavailable player display filter", () => {
  it("hides only u, keeping injury, doubt, suspension, unknown and zero-chance players", () => {
    for (const status of ["u", "a", "i", "d", "s", "n", "x", null, "unknown"]) {
      const player = reportedPlayer(status);
      const before = JSON.stringify(player);
      expect(matchesPlayerFilters(player, INITIAL_PLAYER_FILTERS)).toBe(status !== "u");
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, hideUnavailable: false })).toBe(true);
      expect(JSON.stringify(player)).toBe(before);
    }
  });

  it("combines with other filters and exposes an accessible reversible control", async () => {
    const user = userEvent.setup();
    const player = reportedPlayer("u");
    function Harness() {
      const [filters, setFilters] = useState(INITIAL_PLAYER_FILTERS);
      return <>
        <PlayerFiltersBar filters={filters} onChange={setFilters} teams={[]} showFormWindow={false} />
        {matchesPlayerFilters(player, filters) && <p>Departed player</p>}
      </>;
    }
    render(<Harness />);
    const toggle = screen.getByRole("checkbox", { name: "Hide unavailable" });
    expect(toggle).toBeChecked();
    expect(screen.queryByText("Departed player")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(screen.getByText("Departed player")).toBeInTheDocument();
    await user.click(toggle);
    expect(screen.queryByText("Departed player")).not.toBeInTheDocument();
    expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, hideUnavailable: false, maxPrice: "0" })).toBe(false);
    expect(matchesPlayerFilters(reportedPlayer("i"), { ...INITIAL_PLAYER_FILTERS, availability: "flagged" })).toBe(true);
    expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availability: "flagged" })).toBe(false);
  });

  it("never treats vintage or missing evidence as current availability", () => {
    for (const current_availability of [undefined, null]) {
      const player = { ...reportedPlayer("a"), availability_status: "u", current_availability };
      expect(matchesPlayerFilters(player, INITIAL_PLAYER_FILTERS)).toBe(true);
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availability: "available" })).toBe(false);
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availability: "flagged" })).toBe(false);
    }
    // FPL status and explicit chance can disagree; the reported chance must stay visible.
    expect(matchesPlayerFilters(reportedPlayer("a"), { ...INITIAL_PLAYER_FILTERS, availability: "available" })).toBe(false);
    expect(matchesPlayerFilters(reportedPlayer("a"), { ...INITIAL_PLAYER_FILTERS, availability: "flagged" })).toBe(true);
  });
});
