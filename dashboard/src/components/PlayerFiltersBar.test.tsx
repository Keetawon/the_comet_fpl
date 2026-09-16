import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import sample from "@/data/samplePlayers.json";
import type { PlayerRecord } from "@/data/types";
import { INITIAL_PLAYER_FILTERS, matchesPlayerFilters, PlayerFiltersBar } from "./PlayerFiltersBar";

describe("unavailable player display filter", () => {
  it("hides only u, keeping injury, doubt, suspension, unknown and zero-chance players", () => {
    for (const status of ["u", "a", "i", "d", "s", "n", "x", null, "unknown"]) {
      const player = {
        ...sample.players[0], availability_status: status, chance_of_playing: 0,
      } as unknown as PlayerRecord;
      const before = JSON.stringify(player);
      expect(matchesPlayerFilters(player, INITIAL_PLAYER_FILTERS)).toBe(status !== "u");
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, hideUnavailable: false })).toBe(true);
      expect(JSON.stringify(player)).toBe(before);
    }
  });

  it("combines with other filters and exposes an accessible reversible control", async () => {
    const user = userEvent.setup();
    const player = { ...sample.players[0], availability_status: "u" } as unknown as PlayerRecord;
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
    expect(matchesPlayerFilters({ ...player, availability_status: "i" }, { ...INITIAL_PLAYER_FILTERS, availability: "flagged" })).toBe(true);
    expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availability: "flagged" })).toBe(false);
  });
});
