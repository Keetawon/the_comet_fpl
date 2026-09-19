import { describe, expect, it } from "vitest";
import type { NewsStory, PublicNewsFeed } from "@/data/newsFeed";
import type { RestSummary } from "@/data/restSummary";
import type { PlayerRecord, TeamFixture, TeamRecord } from "@/data/types";
import { buildMatchPreviews, previewNews, previewRest } from "./matchPreview";

const cutoff = "2026-09-18T08:00:00Z";
const kickoff = "2026-09-20T14:00:00Z";
const now = Date.parse("2026-09-19T12:00:00Z");
function fixture(was_home = true, patch: Partial<TeamFixture> = {}): TeamFixture {
  return { gw: 5, fixture: 41, kickoff_time: kickoff, opponent_team_code: was_home ? 10 : 3, opponent_short_name: was_home ? "BET" : "ALP", was_home,
    lambda_for: was_home ? 2 : 1, lambda_against: was_home ? 1 : 2, probability_clean_sheet: 0.4,
    attack_ease_index: 120, defence_ease_index: 90, overall_ease_index: 100, ease_index_formula_version: "fixture-ease-v1",
    official_fdr: 3, stage_a_league_average_team: false, ...patch };
}
function teams(): TeamRecord[] {
  return [true, false].map(home => ({ run_id: "run-1", season: "2026-27", as_of: cutoff, team_code: home ? 3 : 10,
    team_name: home ? "Alpha" : "Beta", short_name: home ? "ALP" : "BET", form: null, fixtures: [fixture(home)] }));
}
function match() { return buildMatchPreviews(teams()).matches[0]; }
function player(code = 123, teamCode = 3): PlayerRecord {
  const f = fixture(teamCode === 3);
  return { run_id: "run-1", season: "2026-27", as_of: cutoff, code, team_code: teamCode, web_name: `P${code}`,
    position: "MID", team_short_name: teamCode === 3 ? "ALP" : "BET", now_cost: 50, selected_by_percent: null,
    availability_status: "a", chance_of_playing: 100, availability_multiplier: 1, cold_start_player: false, form: null, avg_minutes_last_5: null,
    fixtures: [{ gw: f.gw, fixture: f.fixture, kickoff_time: f.kickoff_time, opponent_team_code: f.opponent_team_code,
      opponent_short_name: f.opponent_short_name, was_home: f.was_home, expected_points: 4, probability_appears: null,
      probability_sixty_minutes: null, expected_goals: null, expected_assists: null, probability_clean_sheet: null,
      team_attack_ease_index: null, team_defence_ease_index: null, team_overall_ease_index: null, team_official_fdr: null,
      team_lambda_for: null, team_lambda_against: null, team_probability_clean_sheet: null }] };
}
function story(patch: Partial<NewsStory> = {}): NewsStory {
  return { id: "a".repeat(64), source_id: "fpl", source_name: "FPL", source_kind: "fpl", source_url: "https://www.arsenal.com/news/update",
    source_record_id: "code:123", published_at: null, known_at: "2026-09-19T10:00:00Z", source_sha256: "b".repeat(64), season: "2026-27",
    team_code: 3, team_name: "Alpha", player_code: 123, player_name: "P123", category: "injury", title: { en: "Update", th: null },
    summary: { en: "The manager hopes he can return.", th: null }, rendering: "source_text", ai_model: null, summarized_at: null, ...patch };
}
function feed(stories: NewsStory[] = [story()]): PublicNewsFeed {
  return { schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-19T11:00:00Z", demo: false,
    sources: [{ source_id: "fpl", source_name: "FPL", source_kind: "fpl", status: "ok", last_checked_at: "2026-09-19T10:00:00Z", last_success_at: "2026-09-19T10:00:00Z", message: "Selected coverage." }], stories };
}
function report(): RestSummary {
  return { schema_version: 1, semantics: "descriptive_observed_rest_not_forecast", season: "2026-27", as_of: "2026-09-19T08:00:00Z",
    window_hours: 168, midweek_definition: "Monday_through_Thursday_UTC", duration_definition: "nominal_period_clock_intervals_v1_not_fpl_minutes", promotion_permitted: false,
    players: [{ code: 123, team_code: 3, verdict: "midweek_played", coverage_complete: false,
      last_appearance: { competition_id: 5, competition_name: "Champions League", provider_match_id: 900, kickoff: "2026-09-16T18:00:00Z", observed_team_code: 99, opponent_name: "Opp", nominal_minutes: 90 },
      next_fixture: { gw: 5, fixture_id: 41, kickoff, opponent_name: "Beta", was_home: true }, rest_days: 4, rest_hours: 92,
      midweek_appearances: 1, midweek_nominal_minutes: 90, international_window_overlap: false, unknown_reasons: ["schedule_coverage_unproven"] }] };
}

describe("published match identity", () => {
  it("pairs reciprocal sides once, keeps DGW legs and vintages separate, and sorts deterministically", () => {
    const input = teams();
    input[0].fixtures.push(fixture(true, { fixture: 42, kickoff_time: "2026-09-23T18:00:00Z" }));
    input[1].fixtures.push(fixture(false, { fixture: 42, kickoff_time: "2026-09-23T18:00:00Z" }));
    input.push(...teams().map(team => ({ ...team, run_id: "run-2", as_of: "2026-09-19T07:00:00Z" })));
    const before = structuredClone(input);
    const result = buildMatchPreviews(input.toReversed());
    expect(result.rejected).toEqual([]);
    expect(result.matches.map(row => [row.run_id, row.fixture, row.gw])).toEqual([["run-1", 41, 5], ["run-1", 42, 5], ["run-2", 41, 5]]);
    expect(result.matches[0].home.team.team_code).toBe(3);
    expect(result.matches[0].away.team.team_code).toBe(10);
    expect(input).toEqual(before);
  });

  it.each([
    ["opponent", (input: TeamRecord[]) => { input[1].fixtures[0].opponent_team_code = 44; }],
    ["venue", (input: TeamRecord[]) => { input[1].fixtures[0].was_home = true; }],
    ["unknown venue", (input: TeamRecord[]) => { input[1].fixtures[0].was_home = null; }],
    ["gameweek", (input: TeamRecord[]) => { input[1].fixtures[0].gw = 6; }],
    ["kickoff", (input: TeamRecord[]) => { input[1].fixtures[0].kickoff_time = null; }],
    ["cutoff", (input: TeamRecord[]) => { input[1].as_of = "2026-09-18T09:00:00Z"; }],
    ["duplicate leg", (input: TeamRecord[]) => { input[0].fixtures.push({ ...input[0].fixtures[0] }); }],
    ["duplicate club record", (input: TeamRecord[]) => { input.push({ ...input[0], fixtures: [] }); }],
    ["self fixture", (input: TeamRecord[]) => { input[1].team_code = 3; }],
    ["invalid timestamp", (input: TeamRecord[]) => { input[0].as_of = "2026-09-18T08:00:00"; }],
  ])("rejects %s without retaining a partial match", (_label, mutate) => {
    const input = teams(); mutate(input);
    const result = buildMatchPreviews(input);
    expect(result.matches).toEqual([]);
    expect(result.rejected).toEqual([expect.objectContaining({ fixture: 41, season: "2026-27", run_id: "run-1", reason: expect.any(String) })]);
  });

  it("does not cross season/run identities or fill a missing reciprocal side", () => {
    for (const patch of [{ season: "2025-26" }, { run_id: "another-run" }]) {
      const input = teams(); Object.assign(input[1], patch);
      expect(buildMatchPreviews(input).matches).toEqual([]);
      expect(buildMatchPreviews(input).rejected).toHaveLength(2);
    }
    expect(buildMatchPreviews(teams().slice(0, 1)).rejected).toHaveLength(1);
  });

  it("preserves zero, unavailable measurements and unknown kickoffs without mutating source forecasts", () => {
    const input = teams();
    input.forEach(team => { team.fixtures[0].kickoff_time = null; });
    Object.assign(input[0].fixtures[0], { lambda_for: 0, lambda_against: null, probability_clean_sheet: 0, attack_ease_index: NaN, defence_ease_index: Infinity, overall_ease_index: -1, official_fdr: 0 });
    const before = structuredClone(input);
    const preview = buildMatchPreviews(input).matches[0];
    expect(preview.kickoff_time).toBeNull();
    expect(preview.home.forecast).toMatchObject({ lambda_for: 0, lambda_against: null, probability_clean_sheet: 0, attack_ease_index: null, defence_ease_index: null, overall_ease_index: null, official_fdr: null });
    input[1].fixtures[0].probability_clean_sheet = 1.1;
    expect(buildMatchPreviews(input).matches[0].away.forecast.probability_clean_sheet).toBeNull();
    input[1].fixtures[0].probability_clean_sheet = before[1].fixtures[0].probability_clean_sheet;
    expect(input).toEqual(before);
  });
});

describe("related published news", () => {
  it("accepts current context after the forecast cutoff, preserves prose and sorts ties by identity", () => {
    const input = feed([story({ id: "z" }), story({ id: "a", player_code: null, player_name: null }), story({ id: "old", known_at: "2026-09-19T09:00:00Z" })]);
    const before = structuredClone(input);
    const result = previewNews(input, match(), [player()], now);
    expect(result.stories.map(row => row.id)).toEqual(["a", "z", "old"]);
    expect(result.rejected).toEqual([]);
    expect(input).toEqual(before);
  });

  it("requires exact season/club and player identity, never a matching name or current transferred club", () => {
    const input = feed([story(), story({ id: "seasonless", season: null }), story({ id: "old-season", season: "2025-26" }),
      story({ id: "unknown-club", team_code: null }), story({ id: "wrong-player", player_code: 999, player_name: "P123" }),
      story({ id: "transfer", team_code: 10, team_name: "Beta" }), story({ id: "club", team_code: 10, player_code: null, player_name: null })]);
    const result = previewNews(input, match(), [player()], now);
    expect(result.stories.map(row => row.id)).toEqual(["a".repeat(64), "club"]);
    expect(result.rejected.map(row => row.id)).toEqual(["wrong-player", "transfer"]);
    for (const roster of [[player(), player()], [{ ...player(), run_id: "other" }], [{ ...player(), as_of: "2026-09-19T01:00:00Z" }], [{ ...player(), position: "AM" }]]) {
      expect(previewNews(feed(), match(), roster, now).stories).toEqual([]);
    }
  });

  it("keeps missing/future news unavailable and rejects later knowledge or summaries", () => {
    expect(previewNews(null, match(), [player()], now).reason).toMatch(/No news/);
    expect(previewNews({ ...feed(), generated_at: "2026-09-20T12:00:00Z" }, match(), [player()], now).stories).toEqual([]);
    const bad = feed([story({ known_at: "2026-09-20T00:00:00Z" }), story({ id: "translated", summarized_at: "2026-09-20T00:00:00Z" })]);
    expect(previewNews(bad, match(), [player()], now)).toMatchObject({ stories: [], rejected: [{ id: "a".repeat(64), reason: expect.any(String) }, { id: "translated", reason: expect.any(String) }] });
    expect(previewNews(feed([]), match(), [player()], now).reason).toMatch(/coverage/);
  });
});

describe("exact next-fixture workload context", () => {
  it("joins current report to selected-vintage players, retains prior-club appearances and reports unmatched coverage", () => {
    const input = report();
    const roster = [player(456, 10), player(), { ...player(789), position: "AM" }, { ...player(999), run_id: "other" }];
    const before = structuredClone({ input, roster });
    const result = previewRest(input, match(), roster, now);
    expect(result).toMatchObject({ total_players: 2, matched_count: 1, reason: null });
    expect(result.rows[0].rest?.last_appearance?.observed_team_code).toBe(99);
    expect(result.rows[1]).toMatchObject({ rest: null, reason: expect.any(String) });
    expect({ input, roster }).toEqual(before);
  });

  it.each([
    ["missing exact fixture", (input: RestSummary) => { delete input.players[0].next_fixture!.fixture_id; }],
    ["other DGW leg", (input: RestSummary) => { input.players[0].next_fixture!.fixture_id = 42; }],
    ["opposite venue", (input: RestSummary) => { input.players[0].next_fixture!.was_home = false; }],
    ["unknown venue", (input: RestSummary) => { input.players[0].next_fixture!.was_home = null; }],
    ["transferred current club", (input: RestSummary) => { input.players[0].team_code = 10; }],
    ["duplicate report", (input: RestSummary) => { input.players.push({ ...input.players[0] }); }],
  ])("rejects %s with a visible unavailable reason", (_label, mutate) => {
    const input = report(); mutate(input);
    const result = previewRest(input, match(), [player()], now);
    expect(result.matched_count).toBe(0);
    expect(result.rows[0]).toMatchObject({ rest: null, reason: expect.any(String) });
  });

  it("rejects contradictory or duplicate player-fixture identities and duplicated player registry rows", () => {
    for (const patch of [{ opponent_team_code: 99 }, { was_home: false }, { gw: 6 }, { kickoff_time: "2026-09-21T14:00:00Z" }]) {
      const p = player(); Object.assign(p.fixtures[0], patch);
      expect(previewRest(report(), match(), [p], now).matched_count).toBe(0);
    }
    const duplicate = player(); duplicate.fixtures.push({ ...duplicate.fixtures[0] });
    expect(previewRest(report(), match(), [duplicate], now).rows[0].reason).toMatch(/exact fixture/);
    expect(previewRest(report(), match(), [player(), player()], now)).toMatchObject({ matched_count: 0, total_players: 1, rows: [{ reason: expect.stringMatching(/duplicated/) }] });
  });

  it("never turns unknown/absent into rest and rejects stale/future reports", () => {
    const unknown = report(); Object.assign(unknown.players[0], { verdict: "unknown", midweek_appearances: 0, midweek_nominal_minutes: null, rest_hours: null, rest_days: null });
    expect(previewRest(unknown, match(), [player()], now).rows[0].rest).toMatchObject({ verdict: "unknown", rest_days: null });
    const unproven = report(); Object.assign(unproven.players[0], { verdict: "full_rest", midweek_appearances: 0, coverage_complete: false });
    expect(previewRest(unproven, match(), [player()], now).rows[0].reason).toMatch(/Complete/);
    for (const input of [null, { ...report(), season: "2025-26" }, { ...report(), as_of: "2026-09-20T00:00:00Z" }]) {
      expect(previewRest(input, match(), [player()], now)).toMatchObject({ matched_count: 0, reason: expect.any(String) });
    }
    expect(previewRest(report(), match(), [player()], Date.parse(kickoff)).reason).toMatch(/started/);
    expect(previewRest(report(), { ...match(), kickoff_time: null }, [player()], now).reason).toMatch(/confirmed kickoff/);
  });
});
