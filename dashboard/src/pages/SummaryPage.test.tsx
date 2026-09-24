import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SummaryPage } from "./SummaryPage";

const { load } = vi.hoisted(() => {
  const run = { run_id: "frozen", season: "2026-27", gw_from: 5, gw_to: 5 };
  const plan = {
    forecast_run_id: run.run_id, component_modes: null,
    policy: { locked_codes: [], excluded_codes: [], min_bench_appearance: 0 },
    weeks: [{ gw: 5, players: [], hit_points: 0, squad_cost: 1000 }],
  };
  return { load: {
    loadSummary: vi.fn().mockResolvedValue({ latest_run: run, next_gameweek: { gw: 5 } }),
    loadPlayers: vi.fn().mockResolvedValue({ manifest: null, players: [{
      ...run, code: 1, web_name: "Observed player", position: "DEF", team_short_name: "TST",
      now_cost: 50, availability_status: "a", as_of: "2026-09-15T00:00:00Z",
      fixtures: [{ gw: 5, expected_points: 4.5 }],
    }] }),
    loadFixtureMatrix: vi.fn().mockResolvedValue({ manifest: null, teams: [], schedule: { teams: [{ season: "2026-27", fixtures: [
      { fixture: 51, gw: 5, kickoff_time: "2026-09-20T14:00:00Z" },
      { fixture: 61, gw: 6, kickoff_time: "2026-09-26T14:00:00Z" },
    ] }] } }),
    loadNextGw: vi.fn().mockResolvedValue({ plans: [
      { ...plan, optimizer_run_id: "formal", plan_kind: "platform_default" },
      { ...plan, optimizer_run_id: "private", plan_kind: "user_custom" },
    ] }),
  } };
});
vi.mock("@/data/load", () => load);
vi.mock("@/data/restSummary", () => ({ loadRestSummary: vi.fn().mockRejectedValue(new Error("Old generation without rest evidence")) }));
// No insight request is part of this presentation test.
vi.mock("@/components/InsightSummaryPanel", () => ({ InsightSummaryPanel: () => null }));
vi.mock("@/components/NewsFeed", () => ({ NewsFeed: () => <p>Latest published news</p> }));

beforeEach(() => vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-19T12:00:00Z")));
afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks(); });

it.each([false, true])("keeps published xP but hides all optimizer cards when hosted=%s", async hosted => {
  vi.stubEnv("VITE_HOSTED_STATIC", String(hosted));
  render(<SummaryPage />);
  await screen.findByRole("heading", { name: "Summary" });
  expect(screen.getAllByText("4.5")).toHaveLength(1);
  expect(screen.queryByText(/Platform recommendation/ ) !== null).toBe(!hosted);
  expect(screen.queryByText("Your custom plan") !== null).toBe(!hosted);
  expect(screen.queryByRole("link", { name: /Open your plan in Plan Builder/ }) !== null).toBe(!hosted);
});

it("uses current FPL reports in the availability watch while retaining raw xP", async () => {
  vi.stubEnv("VITE_HOSTED_STATIC", "true");
  const player = {
    run_id: "frozen", season: "2026-27", code: 1, web_name: "Observed player", position: "DEF",
    team_short_name: "TST", now_cost: 50, availability_status: "a", as_of: "2026-09-15T00:00:00Z",
    fixtures: [{ gw: 5, expected_points: 4.5 }],
    current_availability: {
      source: "FPL", season: "2026-27", code: 1, status: "d", chance_of_playing_next_round: 75,
      news: "Unspecified injury", news_added: null, captured_at: "2026-09-17T06:34:00Z",
      capture_id: "latest", source_sha256: "a".repeat(64), next_gw: 5,
      semantics: "current_reported_not_forecast",
    },
  };
  const before = JSON.stringify(player);
  load.loadPlayers.mockResolvedValueOnce({ manifest: null, players: [player] });
  render(<SummaryPage />);
  expect(await screen.findAllByText("doubtful")).toHaveLength(2);
  expect(screen.getByText("Unspecified injury")).toBeInTheDocument();
  expect(screen.getAllByText("4.5")).toHaveLength(2);
  expect(JSON.stringify(player)).toBe(before);
});

it("puts player decisions first and keeps forecast controls behind an accessible disclosure", async () => {
  vi.stubEnv("VITE_HOSTED_STATIC", "true");
  const user = userEvent.setup();
  render(<SummaryPage />);
  await screen.findByRole("heading", { name: "Summary" });
  expect(screen.getByRole("link", { name: /Find your next pick/ })).toHaveAttribute("href", "#players");
  expect(screen.getByRole("link", { name: /Score Prediction/ })).toHaveAttribute("href", "#score-prediction");
  expect(screen.getByRole("link", { name: /Read the latest news/ })).toHaveAttribute("href", "#news");
  expect(screen.getByText(/Forecast as of 2026-09-15/)).toBeVisible();
  const details = screen.getByText("Data & forecast details").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(screen.getByText("Forecast reference: frozen")).not.toBeVisible();
  await user.click(screen.getByText("Data & forecast details"));
  expect(details).toHaveAttribute("open");
  expect(screen.getByText("Forecast reference: frozen")).toBeVisible();
  expect(screen.queryByText("Your local plans")).not.toBeInTheDocument();
});

it("never relabels an uncovered forecast as the current gameweek", async () => {
  vi.mocked(Date.now).mockReturnValue(Date.parse("2026-09-24T12:00:00Z"));
  load.loadSummary.mockResolvedValueOnce({ latest_run: { run_id: "frozen", season: "2026-27", gw_from: 5, gw_to: 5 }, next_gameweek: { gw: 6 } });
  render(<SummaryPage />);
  expect(await screen.findByText("Not covered")).toBeInTheDocument();
  expect(screen.getByText("Kickoff information unavailable")).toBeInTheDocument();
  expect(screen.getByText(/published next GW is not covered/)).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
});

it("rolls the homepage forward even when retained summary metadata still calls GW5 next", async () => {
  render(<SummaryPage />);
  await screen.findByRole("heading", { name: "Top 15 players · GW5" });
  vi.mocked(Date.now).mockReturnValue(Date.parse("2026-09-24T12:00:00Z"));
  fireEvent.focus(window);
  expect(await screen.findByText("Not covered")).toBeVisible();
  expect(screen.queryByRole("heading", { name: "Top 15 players · GW5" })).not.toBeInTheDocument();
  expect(screen.queryByText(/First kickoff 2026-09-20/)).not.toBeInTheDocument();
});
