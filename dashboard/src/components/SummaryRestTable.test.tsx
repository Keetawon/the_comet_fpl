import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { SummaryRestTable } from "./SummaryRestTable";
import { loadRestSummary, type RestSummary } from "@/data/restSummary";
import type { PlayerFixture, PlayerRecord } from "@/data/types";
import { topNextPlayers } from "@/lib/summaryRest";

vi.mock("@/data/restSummary", () => ({ loadRestSummary: vi.fn() }));
const player = { code: 1, season: "2026-27", team_code: 10, web_name: "First player", team_short_name: "TST", position: "MID", fixtures: [{ fixture: 41, gw: 5, kickoff_time: "2026-09-20T14:00:00Z" } as PlayerFixture] } as PlayerRecord;
const report = { schema_version: 1, season: "2026-27", as_of: "2026-09-19T08:00:00Z", window_hours: 168, players: [{
  code: 1, team_code: 10, verdict: "unknown", next_fixture: { fixture_id: 41, gw: 5, kickoff: "2026-09-20T14:00:00Z", opponent_name: "Next team", was_home: true },
  last_appearance: null, rest_days: null, rest_hours: null, midweek_appearances: 0, midweek_nominal_minutes: null,
  international_window_overlap: false, unknown_reasons: ["roster_not_proven:900"],
}]} as RestSummary;
afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); });

it("keeps raw xP visible when the optional old-generation sidecar is absent", async () => {
  vi.mocked(loadRestSummary).mockRejectedValueOnce(new Error("missing"));
  render(<SummaryRestTable players={[{ player, xp: 6.7 }]} gw={5} />);
  expect(await screen.findByText(/Rest evidence unavailable/)).toBeInTheDocument();
  expect(screen.getByText("6.7")).toBeInTheDocument();
  expect(screen.getByText("Unknown")).toBeInTheDocument();
  expect(screen.queryByText("No midweek appearance")).not.toBeInTheDocument();
});

it("shows exact unknown reason/match identity, source semantics and no fabricated zero", async () => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-19T10:00:00Z"));
  vi.mocked(loadRestSummary).mockResolvedValueOnce(report);
  render(<SummaryRestTable players={[{ player, xp: 6.7 }]} gw={5} />);
  expect(await screen.findByText("2026-09-19 08:00 UTC")).toBeInTheDocument();
  expect(screen.getByText("roster_not_proven:900")).toBeInTheDocument();
  expect(screen.getByText(/not FPL minutes/)).toBeInTheDocument();
  expect(screen.getByText(/not verified recovery or fitness/)).toBeInTheDocument();
  expect(within(screen.getByRole("table")).queryByText("0")).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Top 15 players and midweek context" })).toHaveAttribute("tabindex", "0");
});

it("does not present an older GW as the next GW when there is no matching forecast", async () => {
  vi.mocked(loadRestSummary).mockRejectedValueOnce(new Error("absent"));
  render(<SummaryRestTable players={[]} gw={null} />);
  expect(screen.getByText(/published next GW is not covered/)).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  await screen.findByText(/Rest evidence unavailable/);
});

it("shows a current FPL concern beside a raw-xP leader without lowering or reordering xP", async () => {
  vi.mocked(loadRestSummary).mockRejectedValueOnce(new Error("absent"));
  const suspended: PlayerRecord = { ...player, fixtures: [{ ...player.fixtures[0], expected_points: 9 }], current_availability: {
    source: "FPL", season: player.season, code: player.code, status: "s", chance_of_playing_next_round: 0,
    news: "Suspended", news_added: null, captured_at: "2026-09-19T08:00:00Z", capture_id: "capture", source_sha256: "a".repeat(64), next_gw: 5, semantics: "current_reported_not_forecast",
  } };
  const other = { ...player, code: 2, web_name: "Second player", fixtures: [{ ...player.fixtures[0], expected_points: 4 }] };
  const before = JSON.stringify(suspended);
  render(<SummaryRestTable players={topNextPlayers([other, suspended], 5)} gw={5} />);
  await screen.findByText(/Rest evidence unavailable/);
  const rows = screen.getAllByRole("row");
  expect(within(rows[1]).getByText("suspended")).toBeInTheDocument();
  expect(within(rows[1]).getByText("9.0")).toBeInTheDocument();
  expect(within(rows[2]).getByText("Second player")).toBeInTheDocument();
  expect(screen.getByTitle(/FPL.*GW5/)).toHaveTextContent("suspended");
  expect(JSON.stringify(suspended)).toBe(before);
});

it("keeps a transfer's witnessed club distinct from the current forecast club", async () => {
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-19T10:00:00Z"));
  vi.mocked(loadRestSummary).mockResolvedValueOnce({ ...report, players: [{ ...report.players[0], last_appearance: {
    observed_team_code: 20, competition_id: 8, competition_name: "Premier League", provider_match_id: 900,
    kickoff: "2026-09-13T14:00:00Z", opponent_name: "Past opponent", nominal_minutes: 90, fpl_minutes: 89,
  } }] });
  render(<SummaryRestTable players={[{ player, xp: 6.7 }]} gw={5} />);
  expect(await screen.findByText(/appearance was for club code 20; current forecast club code 10/)).toBeInTheDocument();
  expect(screen.getByText("SDP: 90 nominal min · FPL: 89 min")).toBeInTheDocument();
});

it("keeps source time visible and moves detailed rest limits into a disclosure", async () => {
  const user = userEvent.setup();
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-19T10:00:00Z"));
  vi.mocked(loadRestSummary).mockResolvedValueOnce(report);
  render(<SummaryRestTable players={[{ player, xp: 6.7 }]} gw={5} />);
  expect(await screen.findByText("2026-09-19 08:00 UTC")).toBeVisible();
  const method = screen.getByText(/Club participation only/);
  expect(method).not.toBeVisible();
  expect(screen.getByText("Unknown")).toBeVisible();
  await user.click(screen.getByText("About points & rest"));
  expect(method).toBeVisible();
  expect(screen.getByText("6.7")).toBeVisible();
});
