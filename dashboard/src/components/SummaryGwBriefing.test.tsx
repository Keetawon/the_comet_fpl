import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadPlayerActuals, loadPlayerProvisionalActuals } from "@/data/load";
import { loadNewsFeed, type NewsStory, type PublicNewsFeed } from "@/data/newsFeed";
import { loadRestSummary, parseRestSummary, type RestSummary } from "@/data/restSummary";
import type { PlayerObservedActualsRecord, PlayerObservedFixture, PlayerRecord, TeamFixture, TeamRecord } from "@/data/types";
import { buildSummaryBriefing, type SummaryBriefingInput } from "@/lib/summaryBriefing";
import { SummaryGwBriefing } from "./SummaryGwBriefing";

vi.mock("@/data/newsFeed", async original => ({ ...await original<typeof import("@/data/newsFeed")>(), loadNewsFeed: vi.fn() }));
vi.mock("@/data/restSummary", async original => ({ ...await original<typeof import("@/data/restSummary")>(), loadRestSummary: vi.fn() }));
vi.mock("@/data/load", () => ({ loadPlayerActuals: vi.fn(), loadPlayerProvisionalActuals: vi.fn() }));
const asOf = "2026-10-16T08:00:00Z", kickoff = "2026-10-17T14:00:00Z", now = Date.parse("2026-10-16T12:00:00Z");
const run = { run_id: "primary", season: "2026-27" };
const leg = (home: boolean, fixture = 71, at = kickoff): TeamFixture => ({
  fixture, gw: 7, kickoff_time: at, was_home: home, opponent_team_code: home ? 10 : 3, opponent_short_name: home ? "BET" : "ALP",
  lambda_for: home ? 1.8 : 0.8, lambda_against: home ? 0.8 : 1.8, probability_clean_sheet: 0.4,
  attack_ease_index: 100, defence_ease_index: 100, overall_ease_index: 100, ease_index_formula_version: "fixture-ease-v1", official_fdr: 3, stage_a_league_average_team: false,
});
function history(code: number, points = [4]): PlayerObservedActualsRecord {
  return { season: run.season, code, actuals: points.map((value, index): PlayerObservedFixture => ({
    gw: 6, fixture: 60 + index, kickoff_time: `2026-10-${10 + index}T14:00:00Z`, team_code: 3, team_short_name: "ALP", opponent_team_code: 10, opponent_short_name: "BET", was_home: true,
    minutes: 90, starts: 1, goals_scored: null, assists: null, clean_sheets: null, goals_conceded: null, saves: null, bonus: null, bps: null,
    defensive_contribution: null, expected_goals: null, expected_assists: null, expected_goals_conceded: null,
    points_under_rules_2026_27: value, outcome_status: "finalized", total_points_as_recorded: null,
  })) };
}
function input(): SummaryBriefingInput & { teams: TeamRecord[]; players: PlayerRecord[]; actuals: PlayerObservedActualsRecord[] } {
  const teams: TeamRecord[] = [true, false].map(home => ({ ...run, as_of: asOf, team_code: home ? 3 : 10, team_name: home ? "Alpha" : "Beta", short_name: home ? "ALP" : "BET", form: null, fixtures: [leg(home)] }));
  const players: PlayerRecord[] = teams.map((team, i) => ({ ...run, as_of: asOf, code: i + 1, team_code: team.team_code, web_name: i ? "Away player" : "Home player", position: "MID", team_short_name: team.short_name,
    now_cost: 50, selected_by_percent: null, availability_status: "a", chance_of_playing: 100, availability_multiplier: 1, cold_start_player: false, form: null, avg_minutes_last_5: null,
    fixtures: team.fixtures.map(fixture => ({ ...fixture, expected_points: 4, probability_appears: null, probability_sixty_minutes: null, expected_goals: null, expected_assists: null, probability_clean_sheet: null,
      team_attack_ease_index: null, team_defence_ease_index: null, team_overall_ease_index: null, team_official_fdr: null, team_lambda_for: null, team_lambda_against: null, team_probability_clean_sheet: null })) }));
  const stories: NewsStory[] = teams.map((team, i) => ({ id: String(i).repeat(64), source_id: "scout", source_name: "Fantasy Football Scout", source_kind: "x", source_url: `https://x.com/FFScout/status/${100 + i}`, source_record_id: String(100 + i), published_at: "2026-10-16T09:00:00Z", known_at: "2026-10-16T09:10:00Z", source_sha256: "a".repeat(64), season: run.season, team_code: team.team_code, team_name: team.team_name, player_code: null, player_name: null, category: "press_conference", title: { en: "Update", th: null }, summary: { en: i ? "Away fitness remains uncertain." : "Home player has returned to training; availability unconfirmed.", th: i ? "ความฟิตทีมเยือนยังไม่ชัดเจน" : "กลับมาซ้อมแล้ว แต่ยังไม่ยืนยันว่าพร้อม" }, rendering: "source_text", ai_model: null, summarized_at: null }));
  const news: PublicNewsFeed = { schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-10-16T10:00:00Z", demo: false, sources: [{ source_id: "scout", source_name: "Fantasy Football Scout", source_kind: "x", status: "ok", last_checked_at: "2026-10-16T09:10:00Z", last_success_at: "2026-10-16T09:10:00Z", message: "" }], stories };
  const rest: RestSummary = { schema_version: 1, semantics: "descriptive_observed_rest_not_forecast", season: run.season, as_of: "2026-10-16T10:00:00Z", window_hours: 168, midweek_definition: "Tuesday_through_Thursday_UTC", duration_definition: "nominal_period_clock_intervals_v1_not_fpl_minutes", promotion_permitted: false,
    players: players.map(player => ({ code: player.code, team_code: player.team_code, verdict: "midweek_played", coverage_complete: false,
      last_appearance: { competition_id: 5, competition_name: "Champions League", provider_match_id: player.code + 900, kickoff: "2026-10-14T18:00:00Z", opponent_name: "Prior opponent", nominal_minutes: 90 },
      next_fixture: { fixture_id: 71, gw: 7, kickoff, was_home: player.team_code === 3, opponent_name: player.team_code === 3 ? "Beta" : "Alpha" }, rest_days: 3, rest_hours: 68, midweek_appearances: 1, midweek_nominal_minutes: 90, midweek_fixtures: 1, midweek_load: "heavy", international_window_overlap: false, unknown_reasons: ["schedule_coverage_unproven"] })) };
  return { run, gw: 7, teams, players, actuals: players.map(player => history(player.code)), schedule: { schema_version: 2, semantics: "current_at_export_not_forecast_vintage", export_created_at: asOf, database_sha256: "a".repeat(64), teams: structuredClone(teams) }, news, rest, now, language: "en" };
}
beforeEach(() => {
  vi.spyOn(Date, "now").mockReturnValue(now);
  vi.mocked(loadNewsFeed).mockResolvedValue(input().news!); vi.mocked(loadRestSummary).mockResolvedValue(input().rest!);
  vi.mocked(loadPlayerActuals).mockResolvedValue({ schema: "fpl.dashboard-player-actuals", json_schema_version: 9, players: input().actuals });
  vi.mocked(loadPlayerProvisionalActuals).mockResolvedValue({ schema: "fpl.dashboard-player-provisional-actuals", json_schema_version: 1, captured_at: null, players: [] });
});
afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); vi.unstubAllGlobals(); });

describe("combined public GW message", () => {
  it("orders the score, home news, home rest, away news and away rest without changing inputs", () => {
    const data = input(), before = structuredClone(data), result = buildSummaryBriefing(data);
    expect(result).toMatchObject({ fixtures: 1, forecasts: 1, warnings: [] });
    expect(result.text).toContain("1) Alpha (2) - (1) Beta");
    expect(result.text).toContain("Expected goals 1.80 – 0.80");
    const sections = ["1) Alpha (2) - (1) Beta", "ALP home team news", "ALP home rest", "BET away team news", "BET away rest"].map(s => result.text.indexOf(s));
    expect(sections.every(index => index >= 0)).toBe(true);
    expect(sections).toEqual([...sections].sort((a, b) => a - b));
    expect(result.text).toContain("3d (68.0h) gap: 🟠 Home player (90)");
    expect(result.text).toContain(data.news!.stories[0].summary.en);
    expect(result.text).toContain("@FFScout · 2026-10-16 09:00 UTC");
    expect(result.text).not.toContain("https://x.com/");
    expect(result.text).toContain("https://www.thecometfpl.com/#summary");
    expect(data).toEqual(before);
  });
  it("keeps every DGW leg in kickoff order without using first-leg rest for the later leg", () => {
    const data = input();
    data.teams.forEach(team => team.fixtures.unshift(leg(team.team_code === 3, 72, "2026-10-21T19:00:00Z")));
    data.schedule.teams = structuredClone(data.teams);
    const result = buildSummaryBriefing(data);
    expect(result.fixtures).toBe(2);
    expect(result.text).toContain("DGW · ALP 1/2 · BET 1/2");
    const later = result.text.split("2) Alpha")[1];
    expect(later).toContain("DGW · ALP 2/2 · BET 2/2");
    expect(later).toContain("rest unavailable for this fixture: Home player (—)");
    expect(later).not.toMatch(/[🟠🟡]/u);
    expect(later).not.toContain("3d (68.0h)");
    expect(later).toContain("Later DGW leg");
  });
  it("keeps five per club by average points, not totals, xP, position or available rest", () => {
    const data = input();
    const points = [[10], [8, 8], [7, 7, 7], [6, 6, 6, 6], [5], [4, 4, 4, 4, 4]];
    for (const [club, template] of [...data.players].entries()) for (const [rank, values] of points.entries()) {
      const code = 10 + club * 10 + rank;
      data.players.push({ ...template, code, web_name: `Ranked-${code}`, position: rank ? "DEF" : "FWD", fixtures: template.fixtures.map(f => ({ ...f, expected_points: rank * 10 })) });
      data.actuals.push(history(code, values));
    }
    const result = buildSummaryBriefing(data);
    for (const first of [10, 20]) {
      expect(result.text).toContain(Array.from({ length: 5 }, (_, i) => `Ranked-${first + i} (—)`).join(", "));
      expect(result.text).not.toContain(`Ranked-${first + 5}`);
    }
    expect(result.text).not.toContain("Home player (90)");
    expect(result.text).not.toContain("Away player (90)");
    expect(result.text).toContain("up to 5 per team by 2026-27 points per appearance before GW7");
    expect(result.text).not.toContain("(0)");
  });
  it("uses season-qualified, earlier appearances with status-correct points, excluding DNPs and missing values", () => {
    const data = input();
    data.actuals = [];
    for (const code of [1, 3, 4, 5, 6, 7, 8, 9]) {
      if (code !== 1) data.players.push({ ...data.players[0], code, web_name: `Candidate-${code}` });
      data.actuals.push(history(code, [code]));
    }
    data.actuals[0].actuals.push({ ...history(1, [100]).actuals[0], fixture: 90, minutes: 0 });
    data.actuals.push({ ...history(1, [1000]), season: "2025-26" });
    data.actuals[0].actuals.push({ ...history(1, [1000]).actuals[0], fixture: 91, gw: 7 });
    data.actuals[0].actuals.push({ ...history(1, [1000]).actuals[0], fixture: 92, kickoff_time: "2026-10-18T14:00:00Z" });
    // Candidate 3 outranks 6 using raw provisional points; the stale replay field is ignored.
    Object.assign(data.actuals[1].actuals[0], { outcome_status: "provisional", total_points_as_recorded: 9, points_under_rules_2026_27: -100 });
    data.actuals[5].actuals[0].points_under_rules_2026_27 = null;
    data.actuals[6].actuals[0].minutes = null;
    data.actuals[7].actuals[0].points_under_rules_2026_27 = 2;
    const text = buildSummaryBriefing(data).text;
    expect(text).toContain("Candidate-3 (—), Candidate-6 (—), Candidate-5 (—), Candidate-4 (—), Candidate-9 (—)");
    expect(text).not.toContain("Home player (90)");
    expect(text).not.toContain("Candidate-7");
    expect(text).not.toContain("Candidate-8");
    expect(text).toContain("Includes provisional points.");
  });
  it("breaks equal-average ties by stable player code and keeps the same cohort across DGW legs", () => {
    const data = input();
    for (const code of [8, 7, 6, 5, 4, 3]) {
      data.players.push({ ...data.players[0], code, web_name: `Tied-${code}` }); data.actuals.push(history(code));
    }
    data.teams.forEach(team => team.fixtures.push(leg(team.team_code === 3, 72, "2026-10-21T19:00:00Z")));
    data.schedule.teams = structuredClone(data.teams);
    const text = buildSummaryBriefing(data).text;
    expect(text.match(/Home player \(/g)).toHaveLength(2);
    for (const code of [3, 4, 5, 6]) expect(text.match(new RegExp(`Tied-${code} \\(`, "g"))).toHaveLength(2);
    for (const code of [7, 8]) expect(text).not.toContain(`Tied-${code}`);
  });
  it("does not fall back to a full roster or another season when ranking is unavailable", () => {
    const data = input();
    for (const actuals of [null, [], data.actuals.map(row => ({ ...row, season: "2025-26" }))]) {
      const text = buildSummaryBriefing({ ...data, actuals }).text;
      expect(text).toContain("Alpha (2) - (1) Beta");
      expect(text).toContain("Key-player ranking unavailable");
      expect(text).not.toContain("Home player (90)");
    }
  });
  it.each(["different account", "old", "wrong season", "unmapped", "other category", "future", "different GW", "demo"])("excludes %s news", kind => {
    const data = input(), story = data.news!.stories[0]; data.news!.stories = [story];
    if (kind === "different account") story.source_url = "https://x.com/OtherScout/status/100";
    if (kind === "old") story.published_at = "2026-10-01T09:00:00Z";
    if (kind === "wrong season") story.season = "2025-26";
    if (kind === "unmapped") story.team_code = null;
    if (kind === "other category") story.category = "transfer";
    if (kind === "future") story.known_at = "2026-10-18T09:00:00Z";
    if (kind === "demo") data.news!.demo = true;
    if (kind === "different GW") data.news!.roundup = { season: run.season, gw: 6, deadline_at: "2026-10-10T10:00:00Z", opens_at: "2026-10-10T05:00:00Z", schedule_captured_at: asOf, schedule_sha256: "a".repeat(64) };
    expect(buildSummaryBriefing(data).text).not.toContain(story.summary.en);
    expect(buildSummaryBriefing(data).text).toContain("No verified @FFScout update");
  });
  it("includes a scheduled fixture with missing or rescheduled forecast as unavailable", () => {
    const data = input(); data.teams[0].fixtures = [];
    let result = buildSummaryBriefing(data);
    expect(result).toMatchObject({ fixtures: 1, forecasts: 0 });
    expect(result.text).toContain("Alpha (—) - (—) Beta");
    const moved = input(); moved.schedule.teams.forEach(team => { team.fixtures[0].kickoff_time = "2026-10-18T14:00:00Z"; });
    result = buildSummaryBriefing(moved);
    expect(result.forecasts).toBe(0);
    expect(result.text).not.toContain("3d (68.0h)");
  });
  it("fails closed on conflicting schedule sides and mixed forecast cutoffs", () => {
    const data = input(); data.schedule.teams[1].fixtures[0].was_home = true;
    expect(buildSummaryBriefing(data).text).toBe("");
    const mixed = input(); mixed.players[0].as_of = "2026-10-15T00:00:00Z";
    expect(buildSummaryBriefing(mixed).text).toBe("");
  });
  it("preserves measured zero vs no fixture vs unknown, including legacy reports", () => {
    const data = input(), row = data.rest!.players[0];
    Object.assign(row, { verdict: "full_rest", coverage_complete: true, midweek_appearances: 0, midweek_nominal_minutes: 0, midweek_load: "none_not_selected" });
    expect(buildSummaryBriefing(data).text).toContain("gap: Home player (0)");
    Object.assign(row, { midweek_fixtures: 0, midweek_nominal_minutes: null, midweek_load: "none_no_fixture" });
    expect(buildSummaryBriefing(data).text).toContain("gap: Home player (—)");
    delete row.midweek_fixtures; delete row.midweek_load;
    expect(parseRestSummary(data.rest)).toBe(data.rest);
    expect(buildSummaryBriefing(data).text).toContain("gap: Home player (—)");
    row.midweek_load = "light";
    expect(() => parseRestSummary(data.rest)).toThrow(/midweek load/);
  });
  it.each([
    { minutes: 90, appearances: 1, marker: "🟠 " },
    { minutes: 46, appearances: 1, marker: "🟠 " },
    { minutes: 45, appearances: 1, marker: "🟡 " },
    { minutes: 1, appearances: 1, marker: "🟡 " },
    { minutes: 0, appearances: 1, marker: "" },
    { minutes: 0, appearances: 0, marker: "" },
    { minutes: null, appearances: 1, marker: "" },
    { minutes: null, appearances: 0, marker: "" },
  ])("marks recorded midweek minutes $minutes with $appearances appearances in both languages", ({ minutes, appearances, marker }) => {
    const data = input();
    Object.assign(data.rest!.players[0], { midweek_nominal_minutes: minutes, midweek_appearances: appearances, midweek_load: "unknown" });
    for (const language of ["en", "th"] as const) {
      const text = buildSummaryBriefing({ ...data, language }).text;
      const entry = text.split("\n").find(line => line.includes("Home player ("));
      expect(entry?.split(": ")[1]).toBe(`${marker}Home player (${minutes ?? "—"})`);
      if (minutes === null && appearances === 0) {
        expect(text).toContain(language === "en" ? "midweek minutes unknown or did not play" : "ไม่ทราบนาทีกลางสัปดาห์ หรือไม่ได้ลงเล่น");
      }
    }
  });
  it("marks each player in a grouped row without marking players with no rest report", () => {
    const data = input();
    data.players.push({ ...data.players[0], code: 3, web_name: "Teammate" }, { ...data.players[0], code: 4, web_name: "Unmeasured" });
    data.actuals.push(history(3), history(4));
    data.rest!.players.push({ ...data.rest!.players[0], code: 3 });
    const text = buildSummaryBriefing(data).text;
    expect(text).toContain("• 3d (68.0h) gap: 🟠 Home player (90), 🟠 Teammate (90)");
    expect(text).toContain("• rest unavailable for this fixture: Unmeasured (—)");
  });
  it("withholds rest after kickoff and uses reviewed Thai text without reclassifying fitness", () => {
    const data = input(); data.language = "th";
    expect(buildSummaryBriefing(data).text).toContain("กลับมาซ้อมแล้ว แต่ยังไม่ยืนยันว่าพร้อม");
    data.language = "en"; data.now = Date.parse(kickoff);
    const text = buildSummaryBriefing(data).text;
    expect(text).toContain("Kickoff has passed");
    expect(text).not.toContain("3d (68.0h)");
  });
  it("renders the report's actual midweek convention and leaves Monday-only minutes unmarked", () => {
    const data = input();
    Object.assign(data.rest!.players[0], { verdict: "unknown", midweek_appearances: 0, midweek_fixtures: 0, midweek_nominal_minutes: null, midweek_load: "unknown" });
    data.rest!.players[0].last_appearance!.kickoff = "2026-10-12T18:00:00Z";
    expect(parseRestSummary(data.rest)).toBe(data.rest);
    const text = buildSummaryBriefing(data).text;
    expect(text).toContain("gap: Home player (—)");
    expect(text).toContain("Midweek = Tue–Thu UTC");
    expect(buildSummaryBriefing({ ...data, language: "th" }).text).toContain("กลางสัปดาห์คือ อ.–พฤ. UTC");
    data.rest!.midweek_definition = "Monday_through_Thursday_UTC";
    expect(parseRestSummary(data.rest)).toBe(data.rest);
    expect(buildSummaryBriefing(data).text).toContain("Midweek = Mon–Thu UTC");
    expect(() => parseRestSummary({ ...data.rest, midweek_definition: "all_week" })).toThrow(/rest summary/);
  });
});

it("loads context on demand, copies the complete message and switches languages", async () => {
  const data = input(), writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  render(<SummaryGwBriefing {...data} teams={[...data.teams]} players={[...data.players]} />);
  expect(loadNewsFeed).not.toHaveBeenCalled();
  expect(loadRestSummary).not.toHaveBeenCalled();
  expect(loadPlayerActuals).not.toHaveBeenCalled();
  expect(loadPlayerProvisionalActuals).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Create GW briefing" }));
  const area = await screen.findByRole("textbox", { name: "Analysis message" });
  expect(area).toHaveValue(buildSummaryBriefing(data).text);
  expect((area as HTMLTextAreaElement).value).not.toContain("https://x.com/");
  fireEvent.click(screen.getByRole("button", { name: "Copy text" }));
  await screen.findByRole("button", { name: "Copied" });
  expect(writeText).toHaveBeenCalledWith(buildSummaryBriefing(data).text);
  fireEvent.click(screen.getByRole("button", { name: "ไทย" }));
  expect(screen.getByRole("textbox")).toHaveValue(buildSummaryBriefing({ ...data, language: "th" }).text);
  expect((area as HTMLTextAreaElement).value).not.toContain("https://x.com/");
  expect((area as HTMLTextAreaElement).value).toContain("https://www.thecometfpl.com/#summary");
});
it.each(["finalized failed", "provisional failed", "future capture", "conflicting identity"])("keeps score/news text but withholds ranking when %s", async kind => {
  const data = input();
  if (kind === "finalized failed") vi.mocked(loadPlayerActuals).mockRejectedValue(new Error("Offline"));
  if (kind === "provisional failed") vi.mocked(loadPlayerProvisionalActuals).mockRejectedValue(new Error("Offline"));
  if (kind === "future capture" || kind === "conflicting identity") vi.mocked(loadPlayerProvisionalActuals).mockResolvedValue({
    schema: "fpl.dashboard-player-provisional-actuals", json_schema_version: 1, captured_at: kind === "future capture" ? "2026-10-18T00:00:00Z" : asOf,
    players: [{ ...data.actuals[0], actuals: [{ ...data.actuals[0].actuals[0], team_code: 11 }] }],
  });
  render(<SummaryGwBriefing {...data} />);
  fireEvent.click(screen.getByRole("button", { name: "Create GW briefing" }));
  expect(await screen.findByRole("textbox")).toHaveValue(buildSummaryBriefing({ ...data, actuals: null }).text);
});
it("still offers score text when both context sources fail", async () => {
  vi.mocked(loadNewsFeed).mockRejectedValue(new Error("Offline")); vi.mocked(loadRestSummary).mockRejectedValue(new Error("Missing"));
  const data = input(); render(<SummaryGwBriefing {...data} teams={[...data.teams]} players={[...data.players]} />);
  fireEvent.click(screen.getByRole("button", { name: "Create GW briefing" }));
  const area = await screen.findByRole("textbox");
  expect(area).toHaveValue(buildSummaryBriefing({ ...data, news: null, rest: null }).text);
});
