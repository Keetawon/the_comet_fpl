import { describe, expect, it } from "vitest";
import type { SdpStatsData } from "@/data/sdpStats";
import type { TeamFixture, TeamRecord } from "@/data/types";
import { fplSupplement, sdpFixture, sdpMatch, shooting, xg } from "@/test/sdpFixture";
import { buildGwBriefing, type GwBriefingInput } from "./gwBriefing";
import { buildMatchPreviews } from "./matchPreview";

const forecastAt = "2026-09-17T08:00:00Z";
const kickoff = "2026-09-20T14:00:00Z";
function matches() {
  const teams: TeamRecord[] = [3, 8].map(team_code => {
    const home = team_code === 3;
    const forecast: TeamFixture = { fixture: 41, gw: 5, kickoff_time: kickoff, was_home: home, opponent_team_code: home ? 8 : 3,
      opponent_short_name: home ? "BET" : "ALP", lambda_for: home ? 1.75 : 0.8, lambda_against: home ? 0.8 : 1.75,
      probability_clean_sheet: 0.4, attack_ease_index: 100, defence_ease_index: 100, overall_ease_index: 100,
      ease_index_formula_version: "v1", official_fdr: 3, stage_a_league_average_team: false };
    return { run_id: "frozen", as_of: forecastAt, season: "2026-27", team_code, team_name: home ? "Alpha" : "Beta", short_name: home ? "ALP" : "BET", form: null, fixtures: [forecast] };
  });
  return buildMatchPreviews(teams).matches;
}
function stats(): SdpStatsData {
  const base = sdpFixture();
  return { ...base, as_of: "2026-09-19T09:00:00Z", source_status: { ...base.source_status, latest_sdp_known_at: "2026-09-19T07:00:00Z" },
    metrics: [xg, { ...xg, key: "expected_goals_allowed", label: "xGA" }, { ...shooting, key: "shots_on_target", label: "SOT" }],
    gameweeks: [1, 2].map(gw => ({ season: "2026-27", gw, finished: true, fixtures_total: 1, fixtures_completed: 1, source_known_at: "2026-09-19T07:00:00Z" })),
    team_matches: [3, 8].flatMap(team_code => [1, 2].map(gw => sdpMatch({ team_code, opponent_team_code: team_code === 3 ? 8 : 3,
      team_name: team_code === 3 ? "Alpha" : "Beta", team_short_name: team_code === 3 ? "ALP" : "BET", fixture: gw, gw,
      kickoff_time: `2026-09-${gw === 1 ? "01" : "08"}T14:00:00Z`, known_at: "2026-09-19T07:00:00Z",
      sdp: { expected_goals: team_code === 3 ? gw : gw / 2, expected_goals_allowed: team_code === 3 ? gw / 2 : gw, shots_on_target: team_code === 3 ? gw * 2 : gw } }))),
  };
}
function input(patch: Partial<GwBriefingInput> = {}): GwBriefingInput {
  return { matches: matches(), gw: 5, language: "en", stats: stats(), exportCreatedAt: "2026-09-19T10:00:00Z", expectedFixtureIds: [41], ...patch };
}

describe("source-bound GW briefing text", () => {
  it.each([
    [0, "0"], [0.49, "0"], [0.5, "1"], [1.499, "1"], [1.5, "2"],
    [null, "—"], [NaN, "—"], [Infinity, "—"], [-1, "—"],
  ] as const)("rounds only valid goal averages for sharing: %s", (value, formatted) => {
    const source = input();
    source.matches[0].home.forecast.lambda_for = value;
    const before = structuredClone(source);
    const result = buildGwBriefing(source);
    expect(result.text).toContain(`Rounded goal averages: ALP ${formatted}–1 BET`);
    expect(result.text).toContain("ALP: xG 1.50, xGA 0.75, SOT 3.00");
    expect(source).toEqual(before);
  });

  it("publishes bilingual facts with separately named forecast/publication/capture times and no mutation", () => {
    const source = input();
    const before = structuredClone(source);
    const result = buildGwBriefing(source);
    expect(result.coverage).toBe("1/1 fixtures match the supplied GW inventory.");
    expect(result.text).toContain("https://www.thecometfpl.com");
    expect(result.warnings).toEqual([]);
    expect(result.text).toContain("Model forecast cutoff: 2026-09-17 08:00 UTC");
    expect(result.text).toContain("Dashboard export: 2026-09-19 10:00 UTC");
    expect(result.text).toContain("SDP statistics publication: 2026-09-19 09:00 UTC; latest retained SDP capture: 2026-09-19 07:00 UTC");
    expect(result.text).toContain("Rounded goal averages: ALP 2–1 BET");
    expect(result.text).toContain("ALP: xG 1.50, xGA 0.75, SOT 3.00 per match (2 recorded matches, GW1–2)");
    expect(result.text).toContain("not a historical pre-deadline snapshot");
    expect(result.text).toContain("not predicted scores or win probabilities");
    expect(result.text).not.toMatch(/winner:|prediction:|\d+%/i);
    expect(result.text).toContain("nearest integer (0.5 rounds up)");
    const thai = buildGwBriefing({ ...source, language: "th" });
    expect(thai.text).toContain("สรุป GW5 | THE COMET FPL");
    expect(thai.text).toContain("โมเดลตัดข้อมูล ณ 2026-09-17 08:00 UTC");
    expect(thai.text).toContain("เก็บข้อมูล SDP ล่าสุด: 2026-09-19 07:00 UTC");
    expect(thai.text).toContain("ไม่ใช่สกอร์ทายหรือโอกาสชนะ");
    expect(thai.text).toContain("ปัดค่าเฉลี่ยประตู: ALP 2–1 BET");
    expect(source).toEqual(before);
  });

  it.each([
    { run_id: "other" }, { season: "2025-26" }, { as_of: "2026-09-17T09:00:00Z" },
  ])("refuses mixed forecast identity %o", patch => {
    const original = matches()[0];
    const result = buildGwBriefing(input({ matches: [original, { ...original, fixture: 42, ...patch }] }));
    expect(result.text).toBe("");
    expect(result.warnings[0]).toMatch(/one forecast run, season and cutoff/);
  });

  it("refuses duplicate/absent target fixtures and invalid GW, without substituting another GW", () => {
    expect(buildGwBriefing(input({ matches: [matches()[0], matches()[0]] })).text).toBe("");
    expect(buildGwBriefing(input({ gw: 6 })).text).toBe("");
    expect(buildGwBriefing(input({ gw: NaN })).text).toBe("");
    expect(buildGwBriefing(input({ matches: [] })).coverage).toMatch(/No published fixtures/);
  });

  it("preserves all distinct target DGW legs while ignoring other forecast GWs", () => {
    const first = matches()[0];
    const second = { ...first, fixture: 42, kickoff_time: "2026-09-23T14:00:00Z" };
    const later = { ...first, fixture: 51, gw: 6, kickoff_time: "2026-09-27T14:00:00Z" };
    const result = buildGwBriefing(input({ matches: [later, second, first], expectedFixtureIds: [42, 41] }));
    expect(result.coverage).toMatch(/^2\/2/);
    expect(result.text.match(/Rounded goal averages/g)).toHaveLength(2);
    expect(result.text).toContain("2. Alpha v Beta");
    expect(result.text).not.toContain("3. Alpha");
  });

  it("never claims complete coverage without exact supplied fixture-set agreement", () => {
    expect(buildGwBriefing(input({ expectedFixtureIds: undefined })).coverage).toMatch(/not established/);
    const partial = buildGwBriefing(input({ expectedFixtureIds: [41, 42] }));
    expect(partial.coverage).toBe("1/2 fixtures match the supplied GW inventory; 1 missing, 0 unmatched.");
    expect(partial.text).toContain("not a complete GW briefing");
    const wrong = buildGwBriefing(input({ expectedFixtureIds: [42] }));
    expect(wrong.coverage).toMatch(/0\/1.*1 missing, 1 unmatched/);
    expect(buildGwBriefing(input({ expectedFixtureIds: [41, 41] })).text).toContain("fixture inventory is invalid");
    expect(buildGwBriefing(input({ expectedFixtureIds: [] })).coverage).toMatch(/1 unmatched/);
  });

  it("excludes target/partial-DGW, later-GW, late prior-GW, exact kickoff and cross-season statistics", () => {
    const source = stats();
    const high = { expected_goals: 999, expected_goals_allowed: 999, shots_on_target: 999 };
    const row = source.team_matches[0];
    source.team_matches.push(
      { ...row, fixture: 45, gw: 5, kickoff_time: "2026-09-18T14:00:00Z", sdp: high },
      { ...row, fixture: 51, gw: 6, kickoff_time: "2026-09-17T14:00:00Z", sdp: high },
      { ...row, fixture: 40, gw: 4, kickoff_time: "2026-09-21T14:00:00Z", sdp: high },
      { ...row, fixture: 39, gw: 4, kickoff_time: kickoff, sdp: high },
      { ...row, fixture: 38, season: "2025-26", sdp: high },
      { ...row, fixture: 41, gw: 4, sdp: high },
    );
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("ALP: xG 1.50, xGA 0.75, SOT 3.00 per match (2 recorded matches, GW1–2)");
    expect(result.text).not.toContain("999");
  });

  it("joins clubs only on permanent code and never fills a missing metric or short season", () => {
    const source = stats();
    source.team_matches = source.team_matches.filter(row => row.team_code === 3);
    source.team_matches[1].sdp.expected_goals = null;
    source.team_matches.push({ ...source.team_matches[0], team_code: 99, team_name: "Beta", team_short_name: "BET" });
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("ALP: xG —, xGA 0.75, SOT 3.00");
    expect(result.text).toContain("ALP xG: 1/2 matches measured; no partial average is shown.");
    expect(result.text).toContain("BET: no eligible earlier same-season matches.");
    expect(result.text).not.toContain("5 recorded matches");
  });

  it("preserves published zero means and observed zero measurements", () => {
    const source = input();
    source.matches[0].home.forecast.lambda_for = 0;
    source.matches[0].away.forecast.lambda_for = null;
    source.stats!.team_matches.forEach(row => { row.sdp.expected_goals = 0; });
    const result = buildGwBriefing(source);
    expect(result.text).toContain("Rounded goal averages: ALP 0–— BET");
    expect(result.text).toContain("ALP: xG 0.00");
  });

  it("omits corrected/SOT and FPL-supplemented/xG metrics with reasons in the shared text", () => {
    const source = stats();
    const row = source.team_matches[0];
    row.sdp.expected_goals = null;
    row.display_supplements = { expected_goals: fplSupplement(row, 3) };
    row.sdp.shots_on_target = null;
    row.display_corrections = { shots_on_target: { correction_id: "confirmed-sot", value: 0, evidence_class: "owner_confirmed_display_correction",
      owner_confirmation_recorded_at: source.as_of, source_known_at: row.known_at, provider_match_id: 900, provider_field: "ontargetScoringAtt",
      provider_field_state: "omitted", raw_payload_sha256: "a".repeat(64), corroboration: "shot_accounting_and_fpl_goalkeeper_proxy_zero", relation: "direct", subject_team_code: row.team_code } };
    const before = structuredClone(source);
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("ALP: xG —, xGA 0.75, SOT —");
    expect(result.text).toContain("ALP xG omitted: 0 display corrections, 0 assumptions, 1 FPL supplements.");
    expect(result.text).toContain("ALP SOT omitted: 1 display corrections, 0 assumptions, 0 FPL supplements.");
    expect(source).toEqual(before);
  });

  it("keeps forecast text usable when optional SDP is absent or an earliest kickoff cannot be proved", () => {
    const absent = buildGwBriefing(input({ stats: null }));
    expect(absent.text).toContain("Rounded goal averages: ALP 2–1 BET");
    expect(absent.text).toContain("Observed SDP statistics are unavailable");
    expect(absent.text).not.toContain("per match (");
    const unknown = matches(); unknown[0].kickoff_time = null;
    const result = buildGwBriefing(input({ matches: unknown }));
    expect(result.text).toContain("A selected kickoff is unknown");
    expect(result.text).not.toContain("ALP: xG");
  });

  it("preserves provisional/source uncertainty and rejects unverified catalog semantics", () => {
    const source = stats();
    source.team_matches[0].status = "PROVISIONAL";
    source.metrics[2].verified_semantics = false;
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("1 provisional");
    expect(result.text).toContain("SOT: no uniquely verified SDP metric");
    expect(result.text).toContain("SOT —");
  });

  it("rejects duplicated SDP fixture sides without changing the published forecasts", () => {
    const source = stats(); source.team_matches.push({ ...source.team_matches[0] });
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("Duplicate SDP club-fixture records");
    expect(result.text).toContain("Rounded goal averages: ALP 2–1 BET");
    expect(result.text).not.toContain("ALP: xG");
  });

  it("keeps ended rows usable when whole-GW completion is missing or unfinished", () => {
    const source = stats();
    source.gameweeks[0].finished = false;
    source.gameweeks = source.gameweeks.slice(0, 1);
    source.team_matches[0].status = "UNAVAILABLE";
    source.team_matches[1].status = "PROVISIONAL";
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("ALP: xG 1.50, xGA 0.75, SOT 3.00");
    expect(result.text).toContain("1 provisional");
    expect(result.text).toContain("Prior GW1 is not officially finished (1/1 fixtures ended)");
    expect(result.text).toContain("Official GW completion is not witnessed for GW2");
  });

  it.each(["missing status", "later knowledge", "future observed match"])("rejects malformed source %s without emitting a partial average", defect => {
    const source = stats();
    if (defect === "missing status") source.team_matches[0].status = "";
    else if (defect === "later knowledge") source.team_matches[0].known_at = "2026-09-20T00:00:00Z";
    else source.team_matches[0].kickoff_time = "2026-09-19T10:00:00Z";
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("invalid identity, status or source chronology");
    expect(result.text).not.toContain("ALP: xG");
  });

  it.each([-1, 0.5, NaN])("omits invalid raw shots-on-target %s", raw => {
    const source = stats(); source.team_matches[0].sdp.shots_on_target = raw;
    const result = buildGwBriefing(input({ stats: source }));
    expect(result.text).toContain("ALP: xG 1.50, xGA 0.75, SOT —");
    expect(result.text).toContain("ALP SOT: invalid raw SDP measurements");
  });

  it("retains synthetic provenance in copied demonstration text", () => {
    const source = stats(); source.source_status.notes.push("DEMO: synthetic local data only.");
    expect(buildGwBriefing(input({ stats: source })).text).toContain("DEMO: synthetic statistics for local interface review only");
  });
});
