import { describe, expect, it } from "vitest";
import { parseSdpStats } from "@/data/sdpStats";
import { sdpFixture, shooting } from "@/test/sdpFixture";
import { goalPatternDescriptions, goalPatternDisplay, metricRaw, metricSourceLabel, metricValue, sdpCsv } from "./sdpStats";

const metric = { ...shooting, key: "set_piece_goals", label: "Set-piece goals", provider_field: null };
function fixture() {
  const data = sdpFixture(); data.json_schema_version = 7;
  data.metrics.forEach(m => { m.omitted_zero_display = false; });
  data.team_matches.forEach(row => {
    Object.assign(row, { dashboard_status: "PROVIDER_VALID", display_supplements: {}, display_assumptions: {}, goal_patterns: null });
  });
  const row = data.team_matches[0];
  row.source_version = "a".repeat(64); row.sdp.open_play_goals = 0; row.sdp.set_piece_goals = null;
  row.fpl = { goals_scored: 3 };
  row.goal_patterns = { open_play_goals: 0, set_piece_goals: null, confirmed_set_piece_goals: 1, own_goals_received: 1, unclassified_goals: 1, total_goals: 3, source_version: row.source_version, raw_payload_sha256: "b".repeat(64), source_known_at: row.known_at, audited_at: "2026-09-14T16:00:00Z", evidence_urls: ["https://www.chelseafc.com/en/news/article/match-report-chelsea-4-3-brighton"], method: "audited_goal_accounting_v1" };
  return data;
}

describe("audited goal accounting", () => {
  it("keeps source cutoff separate from interpretation time and preserves incomplete totals", () => {
    const data = fixture(); const before = JSON.stringify(data);
    expect(parseSdpStats(data)).toBe(data);
    const row = data.team_matches[0];
    expect(metricRaw(row, metric)).toBeNull();
    expect(metricValue([row], metric, "per_match").value).toBeNull();
    const csv = sdpCsv([{ id: "team:1", name: "Test club", clubs: "TST", position: "", code: null, teamCode: 1, rows: [row] }], [metric], "per_match");
    expect(csv).toContain("1 confirmed set-piece"); expect(csv).toContain("1 unclassified");
    expect(csv).toContain("1 opponent own goals"); expect(csv).toContain("SDP + audit");
    expect(JSON.stringify(data)).toBe(before);
    row.goal_patterns!.set_piece_goals = 2;
    expect(() => parseSdpStats(data)).toThrow();
  });

  it("uses complete audited counts consistently, including measured zeros", () => {
    const data = fixture(); const row = data.team_matches[0];
    Object.assign(row.goal_patterns!, { set_piece_goals: 2, confirmed_set_piece_goals: 2, unclassified_goals: 0 });
    expect(parseSdpStats(data)).toBe(data);
    expect(metricRaw(row, metric)).toBe(2);
    const zero = structuredClone(row);
    zero.fpl!.goals_scored = 0;
    Object.assign(zero.goal_patterns!, { set_piece_goals: 0, confirmed_set_piece_goals: 0, own_goals_received: 0, total_goals: 0 });
    expect(metricValue([row, zero], metric, "per_match")).toMatchObject({ value: 1, measured: 2, matches: 2 });
    zero.goal_patterns = null;
    expect(metricValue([row, zero], metric, "per_match").value).toBeNull();
  });

  it.each(["hash", "timestamp", "own goal", "missing receipt"])("rejects contradictory %s evidence", kind => {
    const data = fixture(), row = data.team_matches[0];
    if (kind === "hash") row.goal_patterns!.source_version = "";
    if (kind === "timestamp") row.goal_patterns!.audited_at = "2026-01-01T00:00:00Z";
    if (kind === "own goal") row.goal_patterns!.own_goals_received = 0;
    if (kind === "missing receipt") delete row.goal_patterns;
    expect(() => parseSdpStats(data)).toThrow();
  });

  it("accepts separately timed source accounting only in schema 8 and labels its provenance", () => {
    const data = fixture(); const row = data.team_matches[0];
    const { audited_at, ...counts } = row.goal_patterns!;
    row.goal_patterns = { ...counts, method: "source_goal_accounting_v1", interpreted_at: audited_at! };
    expect(() => parseSdpStats(data)).toThrow();
    data.json_schema_version = 8;
    expect(() => parseSdpStats(data)).toThrow(); // New interpretations cannot predate this export.
    data.as_of = "2026-09-15T00:00:00Z";
    const before = JSON.stringify(data);
    expect(parseSdpStats(data)).toBe(data);
    expect(metricSourceLabel(metric, [row])).toBe("SDP accounting");
    expect(goalPatternDescriptions([row], metric)[0]).toContain("SDP accounting interpreted");
    expect(goalPatternDescriptions([row], metric)[0]).not.toContain("Display audit");
    expect(metricRaw(row, metric)).toBeNull();
    expect(JSON.stringify(data)).toBe(before);
    row.goal_patterns.interpreted_at = "2026-01-01T00:00:00Z";
    expect(() => parseSdpStats(data)).toThrow();
    row.goal_patterns.interpreted_at = audited_at!;
    Object.assign(row.goal_patterns, { audited_at });
    expect(() => parseSdpStats(data)).toThrow();
  });

  it("keeps missing origins separate from known official goals and complete set-piece totals", () => {
    const row = fixture().team_matches[0]; row.goal_patterns = null;
    const before = JSON.stringify(row);
    expect(goalPatternDisplay(row)).toMatchObject({ open_play_goals: 0, unclassified_goals: 3, total_goals: 3 });
    expect(metricRaw(row, metric)).toBeNull();
    const csv = sdpCsv([{ id: "team:1", name: "Test club", clubs: "TST", position: "", code: null, teamCode: 1, rows: [row] }], [metric], "per_match");
    expect(csv).toContain("complete goal-origin classification unavailable");
    expect(csv).toContain("3 official FPL goals; 3 unclassified");
    expect(JSON.stringify(row)).toBe(before);
    row.sdp.open_play_goals = 2;
    expect(goalPatternDisplay(row)).toMatchObject({ open_play_goals: 2, unclassified_goals: 1, total_goals: 3 });
    for (const missingOrConflicting of [null, -1, 4, .5]) {
      row.sdp.open_play_goals = missingOrConflicting;
      expect(goalPatternDisplay(row)).toMatchObject({ open_play_goals: 0, unclassified_goals: 3, total_goals: 3 });
    }
    row.fpl!.goals_scored = 0;
    expect(goalPatternDisplay(row)?.total_goals).toBe(0);
    row.fpl!.goals_scored = null;
    expect(goalPatternDisplay(row)).toBeNull();
  });
});
