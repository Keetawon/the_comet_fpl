import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MatchPreviews } from "./MatchPreviews";
import { loadPlayers } from "@/data/load";
import { loadNewsFeed, type NewsStory, type PublicNewsFeed } from "@/data/newsFeed";
import { loadRestSummary, type RestSummary } from "@/data/restSummary";
import { fetchInsightStatus, fetchInsightSummary } from "@/lib/planServer";
import type { PlayerRecord, TeamFixture, TeamFormWindow, TeamRecord } from "@/data/types";

vi.mock("@/data/load", () => ({ loadPlayers: vi.fn() }));
vi.mock("@/data/newsFeed", () => ({ loadNewsFeed: vi.fn() }));
vi.mock("@/data/restSummary", () => ({ loadRestSummary: vi.fn() }));
vi.mock("@/lib/planServer", () => ({ fetchInsightStatus: vi.fn(), fetchInsightSummary: vi.fn() }));

const asOf = "2026-09-18T08:00:00Z";
const exported = "2026-09-19T09:00:00Z";
const kickoff = "2026-09-20T14:00:00Z";
const window: TeamFormWindow = { matches_played: 2, goals_for: 4, goals_against: 1, clean_sheets: 1, wins: 1, draws: 1, losses: 0,
  team_xg: 2.4, team_xgc: null, goals_for_per_match: 2, goals_against_per_match: 0.5, team_xg_per_match: 1.2, team_xgc_per_match: null,
  observations: { fixture_ids: [1, 2], gw_from: 1, gw_to: 2, provisional_matches: 1, team_xg_matches: 2, team_xgc_matches: 0 } };
function forecast(fixture: number, gw: number, opponent: number, home: boolean, values: Partial<TeamFixture> = {}): TeamFixture {
  return { fixture, gw, kickoff_time: kickoff, opponent_team_code: opponent, opponent_short_name: `C${opponent}`, was_home: home,
    lambda_for: 1.25, lambda_against: 1.5, probability_clean_sheet: 0.2, attack_ease_index: 50, defence_ease_index: 50,
    overall_ease_index: 50, ease_index_formula_version: "v1", official_fdr: 3, stage_a_league_average_team: false, ...values };
}
function teams(): TeamRecord[] {
  return [
    { team_code: 1, team_name: "Alpha", short_name: "ALP", fixtures: [forecast(41, 5, 2, true, { lambda_for: 0 }), forecast(42, 5, 3, true, { lambda_for: 2.5 })] },
    { team_code: 2, team_name: "Beta", short_name: "BET", fixtures: [forecast(41, 5, 1, false, { lambda_for: null }), forecast(61, 7, 3, true)] },
    { team_code: 3, team_name: "Gamma", short_name: "GAM", fixtures: [forecast(42, 5, 1, false), forecast(61, 7, 2, false)] },
  ].map(team => ({ ...team, run_id: "preview-run", season: "2026-27", as_of: asOf,
    form: { source: "published_team_actuals", season: "2026-27", as_at_gw: 2,
      windows: { last_3: window, last_5: window, last_10: window, season_to_date: window } } }));
}
function players(): PlayerRecord[] {
  return teams().slice(0, 2).map(team => ({ run_id: team.run_id, season: team.season, as_of: asOf, team_code: team.team_code,
    code: 100 + team.team_code, web_name: `Player ${team.team_code}`, team_short_name: team.short_name, position: "MID", fixtures: team.fixtures,
  })) as unknown as PlayerRecord[];
}
function story(id: string, overrides: Partial<NewsStory> = {}): NewsStory {
  return { id: id.repeat(64), source_id: "fpl", source_name: "Official FPL", source_kind: "fpl", source_url: "https://www.arsenal.com/news/update",
    source_record_id: id, published_at: "2026-09-19T06:00:00Z", known_at: "2026-09-19T07:00:00Z", source_sha256: "c".repeat(64),
    season: "2026-27", team_code: 1, team_name: "Alpha", player_code: null, player_name: null, category: "injury",
    title: { en: "Fitness update", th: "ข่าวความพร้อม" }, summary: { en: "A return has not been confirmed.", th: "ยังไม่ยืนยันการกลับมาลงเล่น" },
    rendering: "source_text", ai_model: null, summarized_at: null, ...overrides };
}
const feed = (): PublicNewsFeed => ({ schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: exported,
  demo: false, sources: [], stories: [story("a"), story("b", { title: { en: "Translation pending", th: null }, summary: { en: "Reported uncertainty.", th: null } }),
    story("d", { team_code: null, team_name: null, title: { en: "Unlinked general news", th: null } })] });
const report = (): RestSummary => ({ schema_version: 1, semantics: "descriptive_observed_rest_not_forecast", season: "2026-27", as_of: exported,
  window_hours: 168, midweek_definition: "Monday_through_Thursday_UTC", duration_definition: "nominal_period_clock_intervals_v1_not_fpl_minutes", promotion_permitted: false,
  players: [{ code: 101, team_code: 1, verdict: "unknown", coverage_complete: false,
    last_appearance: { competition_id: 8, competition_name: "Premier League", provider_match_id: 900, kickoff: "2026-09-13T14:00:00Z", opponent_name: "Past club", nominal_minutes: 80, fpl_minutes: 79 },
    next_fixture: { fixture_id: 41, gw: 5, kickoff, opponent_name: "Beta", was_home: true }, rest_hours: 168, rest_days: 7,
    midweek_appearances: 0, midweek_nominal_minutes: null, international_window_overlap: false, unknown_reasons: ["roster_not_proven:900"] }] });

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(Date, "now").mockReturnValue(Date.parse("2026-09-19T10:00:00Z"));
  vi.stubGlobal("fetch", vi.fn());
  vi.mocked(loadPlayers).mockResolvedValue({ players: players(), manifest: null });
  vi.mocked(loadNewsFeed).mockRejectedValue(new Error("optional file absent"));
  vi.mocked(loadRestSummary).mockRejectedValue(new Error("optional file absent"));
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("selects published GW keys, exact DGW matches and club scope without claiming live timing or making AI calls", async () => {
  render(<MatchPreviews teams={teams()} exportCreatedAt={exported} />);
  const gw = screen.getByRole("combobox", { name: "Preview gameweek" });
  expect(gw).toHaveValue("5");
  expect(within(gw).getAllByRole("option").map(option => option.textContent)).toEqual(["GW5 · recorded forecast", "GW7 · recorded forecast"]);
  const first = screen.getByRole("button", { name: "Preview ALP v BET, fixture 41" });
  expect(within(first).getByText("0.00")).toBeInTheDocument();
  expect(within(first).getByText("Unavailable")).toBeInTheDocument();
  expect(within(first).getAllByText("20%")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Preview ALP v GAM, fixture 42" }));
  expect(screen.getByRole("heading", { name: "Alpha v Gamma" })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "Preview club" }), { target: { value: "3" } });
  expect(screen.queryByRole("button", { name: /fixture 41/ })).not.toBeInTheDocument();
  fireEvent.change(gw, { target: { value: "7" } });
  expect(screen.getByRole("heading", { name: "Beta v Gamma" })).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Reset preview" }));
  expect(gw).toHaveValue("5");
  expect(screen.getByRole("combobox", { name: "Preview club" })).toHaveValue("");
  expect(screen.getByRole("heading", { name: "Alpha v Beta" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Preview ALP v BET, fixture 41" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("Deterministic preview")).toBeInTheDocument();
  expect(screen.getByText(/expected goals are forecast means, not observed xG or predicted scorelines/)).toBeInTheDocument();
  await screen.findByText("News unavailable in this published generation.");
  expect(loadPlayers).toHaveBeenCalledTimes(1);
  expect(loadRestSummary).toHaveBeenCalledTimes(1);
  expect(loadNewsFeed).toHaveBeenCalledTimes(1);
  expect(fetchInsightStatus).not.toHaveBeenCalled();
  expect(fetchInsightSummary).not.toHaveBeenCalled();
  expect(fetch).not.toHaveBeenCalled();
});

it("keeps forecasts usable with failed optional loads and labels the selected vintage as a recorded forecast", async () => {
  vi.mocked(loadPlayers).mockRejectedValue(new Error("missing"));
  render(<MatchPreviews teams={teams()} exportCreatedAt={exported} />);
  expect(screen.getByRole("combobox", { name: "Preview gameweek" })).toHaveValue("5");
  expect(screen.queryByText(/upcoming/i)).not.toBeInTheDocument();
  await screen.findByText(/Published player identities unavailable/);
  expect(screen.getByText("Rest evidence unavailable in this published generation.")).toBeInTheDocument();
  expect(screen.getByText("News unavailable in this published generation.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Alpha v Beta" })).toBeInTheDocument();
  expect(screen.getByText(/Recorded forecast · 2026-27 · as of 2026-09-18 08:00 UTC/)).toBeInTheDocument();
  expect(screen.getAllByText(/2 fixtures, up to the latest five · 1 provisional/)).toHaveLength(2);
  expect(screen.getAllByText("FPL observed · 2026-27 · GW1–2")).toHaveLength(2);
  expect(screen.getAllByText(/0 measured fixtures/)).toHaveLength(2);
  expect(screen.getAllByText(/Observed form exported 2026-09-19 09:00 UTC/)).toHaveLength(2);
});

it("keeps news separately timed, translates only available text and links exact published sources and stories", async () => {
  vi.mocked(loadNewsFeed).mockResolvedValue(feed());
  render(<MatchPreviews teams={teams()} exportCreatedAt={exported} />);
  await screen.findByRole("heading", { name: "Fitness update" });
  expect(screen.queryByText("Unlinked general news")).not.toBeInTheDocument();
  expect(screen.getByText("Feed published 2026-09-19 09:00 UTC")).toBeInTheDocument();
  expect(screen.getAllByText(/Source published 2026-09-19 06:00 UTC · known 2026-09-19 07:00 UTC/)).toHaveLength(2);
  expect(screen.getByText(/reports may postdate the recorded forecast/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "ไทย" }));
  expect(screen.getByRole("heading", { name: "ข่าวความพร้อม" })).toHaveAttribute("lang", "th");
  expect(screen.getByRole("heading", { name: "Translation pending" })).toHaveAttribute("lang", "en");
  expect(screen.getByText("Thai translation pending · showing English")).toBeInTheDocument();
  expect(screen.getAllByRole("link", { name: "Original source" })[0]).toHaveAttribute("rel", "noopener noreferrer");
  expect(screen.getAllByRole("link", { name: "Open story" })[0]).toHaveAttribute("href", `#news?story=${"a".repeat(64)}&lang=th`);
  expect(screen.getByText(/Absence of a report does not establish fitness/)).toBeInTheDocument();
});

it("retains exact-fixture unknown workload, observed minutes and player evidence gaps", async () => {
  vi.mocked(loadRestSummary).mockResolvedValue(report());
  render(<MatchPreviews teams={teams()} exportCreatedAt={exported} />);
  await screen.findByText(/1 of 2 published players have a record matched to this exact fixture/);
  expect(screen.getByText(/roster_not_proven:900/)).toBeInTheDocument();
  expect(screen.getByText(/80 nominal min · 79 FPL min/)).toBeInTheDocument();
  expect(screen.getByText(/not FPL minutes or physical-load measurements/)).toBeInTheDocument();
  expect(screen.getAllByText("Unknown")).toHaveLength(2);
  expect(screen.queryByText("No witnessed midweek appearance")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Preview ALP v GAM, fixture 42" }));
  await waitFor(() => expect(screen.getByText(/0 of 1 published players have a record matched to this exact fixture/)).toBeInTheDocument());
  expect(screen.queryByText(/80 nominal min · 79 FPL min/)).not.toBeInTheDocument();
});

it("keeps a valid club report while exposing the rejection of a player's mismatched reported club", async () => {
  const data = feed();
  data.stories = [story("a"), story("b", { player_code: 102, player_name: "Player 2", team_code: 1, team_name: "Alpha",
    title: { en: "Former club report", th: null } })];
  vi.mocked(loadNewsFeed).mockResolvedValue(data);
  render(<MatchPreviews teams={teams()} exportCreatedAt={exported} />);
  await screen.findByRole("heading", { name: "Fitness update" });
  expect(screen.queryByRole("heading", { name: "Former club report" })).not.toBeInTheDocument();
  const rejection = screen.getByText("1 linked report(s) excluded because their evidence could not be matched");
  fireEvent.click(rejection);
  expect(screen.getByText("The reported player and club do not match this forecast vintage.")).toBeVisible();
  expect(screen.getByText(`Story ${"b".repeat(64)}`)).toBeVisible();
});

it("does not present archive or unproven form as current and exposes rejected reciprocal fixtures", async () => {
  const rows = teams();
  rows[0].form!.season = "2025-26";
  rows[1].form!.windows = { ...rows[1].form!.windows, last_5: { ...window, observations: undefined } };
  rows[2].fixtures = rows[2].fixtures.filter(row => row.fixture !== 42);
  render(<MatchPreviews teams={rows} exportCreatedAt={null} />);
  expect(screen.getAllByText("Same-season published form unavailable.")).toHaveLength(2);
  expect(screen.getByText(/1 fixture\(s\) unavailable because/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /fixture 42/ })).not.toBeInTheDocument();
  await screen.findByText("News unavailable in this published generation.");
});
