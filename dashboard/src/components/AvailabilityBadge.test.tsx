import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import sample from "@/data/samplePlayers.json";
import type { PlayerRecord } from "@/data/types";
import { AvailabilityBadge } from "./AvailabilityBadge";

const frozen = sample.players[0] as unknown as PlayerRecord;
const player: PlayerRecord = { ...frozen, current_availability: {
  source: "FPL", season: frozen.season, code: frozen.code, status: "d",
  chance_of_playing_next_round: 75, news: "Unspecified injury - 75% chance of playing", news_added: null,
  captured_at: "2026-09-17T06:34:00Z", capture_id: "latest", source_sha256: "a".repeat(64),
  next_gw: 5, semantics: "current_reported_not_forecast",
} };

describe("reported availability badge", () => {
  it("shows current status, chance, source gameweek, capture time and news without changing the forecast", () => {
    const before = JSON.stringify(player);
    render(<AvailabilityBadge player={player} details />);
    expect(screen.getByText("doubtful · 75%")).toBeInTheDocument();
    expect(screen.getByText(/FPL · 2026-27 GW5 · captured 2026-09-17 06:34 UTC/)).toBeInTheDocument();
    expect(screen.getByText("Unspecified injury - 75% chance of playing")).toBeInTheDocument();
    expect(JSON.stringify(player)).toBe(before);
    expect(player.fixtures).toBe(frozen.fixtures);
    expect(player.availability_status).toBe(frozen.availability_status);
  });

  it("labels legacy forecast availability with its original date", () => {
    render(<AvailabilityBadge player={frozen} />);
    expect(screen.getByText(/Forecast status · /)).toHaveTextContent(frozen.as_of.slice(0, 10));
    expect(screen.queryByText(/captured/)).not.toBeInTheDocument();
  });

  it.each([null, { ...player.current_availability!, code: frozen.code + 1 }, { ...player.current_availability!, season: "2025-26" }])(
    "keeps missing or mismatched current evidence unknown",
    current_availability => {
      render(<AvailabilityBadge player={{ ...frozen, current_availability }} />);
      expect(screen.getByText("Unknown")).toBeInTheDocument();
      expect(screen.getByTitle(/Current FPL availability not published/)).toBeInTheDocument();
      expect(screen.queryByText(/Forecast status/)).not.toBeInTheDocument();
    },
  );

  it("exposes a zero chance even when the provider reports status available", () => {
    render(<AvailabilityBadge player={{ ...player, current_availability: {
      ...player.current_availability!, status: "a", chance_of_playing_next_round: 0,
    } }} />);
    expect(screen.getByText("available · 0%")).toHaveClass("text-amber-600");
  });
});
