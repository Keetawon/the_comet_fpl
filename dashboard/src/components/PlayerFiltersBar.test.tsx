import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
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
    expect(matchesPlayerFilters(reportedPlayer("i"), { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["i", "d"] })).toBe(true);
    expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["i", "d"] })).toBe(false);
  });

  it("never treats vintage or missing evidence as current availability", () => {
    for (const current_availability of [undefined, null]) {
      const player = { ...reportedPlayer("a"), availability_status: "u", current_availability };
      expect(matchesPlayerFilters(player, INITIAL_PLAYER_FILTERS)).toBe(true);
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["a", "d"] })).toBe(false);
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["unknown"] })).toBe(true);
    }
    // Status filtering does not reclassify an a report even when its chance is 0%.
    expect(matchesPlayerFilters(reportedPlayer("a"), { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["a"] })).toBe(true);
    expect(matchesPlayerFilters(reportedPlayer("a"), { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["d"] })).toBe(false);
    for (const patch of [
      { code: -1 }, { season: "wrong" }, { source: "other" }, { semantics: "forecast" },
    ]) {
      const player = reportedPlayer("a");
      Object.assign(player.current_availability!, patch);
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["a"] })).toBe(false);
      expect(matchesPlayerFilters(player, { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["unknown"] })).toBe(true);
    }
  });

  it("unions exact current status codes, intersects other filters and leaves records unchanged", () => {
    const filters = { ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["a", "d"] };
    for (const status of ["a", "d", "i", "s", "u", "n", "x", null, "new-code"]) {
      const player = reportedPlayer(status);
      const before = JSON.stringify(player);
      expect(matchesPlayerFilters(player, filters)).toBe(status === "a" || status === "d");
      expect(matchesPlayerFilters(player, { ...filters, maxPrice: "0" })).toBe(false);
      expect(matchesPlayerFilters(player, {
        ...INITIAL_PLAYER_FILTERS, availabilityStatuses: ["unknown"],
      })).toBe(status == null || status === "new-code");
      if (status != null && status !== "new-code") {
        expect(matchesPlayerFilters(player, {
          ...INITIAL_PLAYER_FILTERS, hideUnavailable: false, availabilityStatuses: [status],
        })).toBe(true);
      }
      expect(JSON.stringify(player)).toBe(before);
    }
  });

  it("selects multiple statuses and makes explicit Unavailable selection compatible with hiding", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [filters, setFilters] = useState(INITIAL_PLAYER_FILTERS);
      return <>
        <PlayerFiltersBar filters={filters} onChange={setFilters} teams={[]} showFormWindow={false} />
        {["a", "d", "i", "u"].map((status) => matchesPlayerFilters(reportedPlayer(status), filters)
          && <p key={status}>Player {status}</p>)}
      </>;
    }
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Availability filter: All statuses" }));
    const choices = screen.getByRole("dialog", { name: "Avail choices" });
    await user.click(within(choices).getByRole("checkbox", { name: "Available" }));
    await user.click(within(choices).getByRole("checkbox", { name: "Doubtful" }));
    expect(screen.getByText("Player a")).toBeInTheDocument();
    expect(screen.getByText("Player d")).toBeInTheDocument();
    expect(screen.queryByText("Player i")).not.toBeInTheDocument();
    await user.click(within(choices).getByRole("checkbox", { name: "Unavailable" }));
    expect(screen.getByText("Player u")).toBeInTheDocument();
    const hide = screen.getByRole("checkbox", { name: "Hide unavailable" });
    expect(hide).not.toBeChecked();
    await user.keyboard("{Escape}");
    await user.click(hide);
    expect(screen.queryByText("Player u")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Availability filter: 2 selected" }));
    expect(screen.getByRole("checkbox", { name: "Unavailable" })).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByText("Player i")).toBeInTheDocument();
    expect(screen.queryByText("Player u")).not.toBeInTheDocument();
  });
});
