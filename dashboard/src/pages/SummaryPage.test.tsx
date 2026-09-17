import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SummaryPage } from "./SummaryPage";

const { load } = vi.hoisted(() => {
  const run = { run_id: "frozen", season: "2026-27", gw_from: 5, gw_to: 5 };
  const plan = {
    forecast_run_id: run.run_id, component_modes: null,
    policy: { locked_codes: [], excluded_codes: [], min_bench_appearance: 0 },
    weeks: [{ gw: 5, players: [], hit_points: 0, squad_cost: 1000 }],
  };
  return { load: {
    loadSummary: vi.fn().mockResolvedValue({ latest_run: run, next_gameweek: null }),
    loadPlayers: vi.fn().mockResolvedValue({ manifest: null, players: [{
      ...run, code: 1, web_name: "Observed player", position: "DEF", team_short_name: "TST",
      now_cost: 50, availability_status: "a", as_of: "2026-09-15T00:00:00Z",
      fixtures: [{ gw: 5, expected_points: 4.5 }],
    }] }),
    loadFixtureMatrix: vi.fn().mockResolvedValue({ manifest: null, teams: [] }),
    loadNextGw: vi.fn().mockResolvedValue({ plans: [
      { ...plan, optimizer_run_id: "formal", plan_kind: "platform_default" },
      { ...plan, optimizer_run_id: "private", plan_kind: "user_custom" },
    ] }),
  } };
});
vi.mock("@/data/load", () => load);
// No insight request is part of this presentation test.
vi.mock("@/components/InsightSummaryPanel", () => ({ InsightSummaryPanel: () => null }));

afterEach(() => vi.unstubAllEnvs());

it.each([false, true])("keeps published xP but hides all optimizer cards when hosted=%s", async hosted => {
  vi.stubEnv("VITE_HOSTED_STATIC", String(hosted));
  render(<SummaryPage />);
  await screen.findByRole("heading", { name: "Summary" });
  expect(screen.getAllByText("4.5")).toHaveLength(2);
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
  expect(await screen.findByText("doubtful · 75%")).toBeInTheDocument();
  expect(screen.getByText("Unspecified injury")).toBeInTheDocument();
  expect(screen.getAllByText("4.5")).toHaveLength(3);
  expect(JSON.stringify(player)).toBe(before);
});
