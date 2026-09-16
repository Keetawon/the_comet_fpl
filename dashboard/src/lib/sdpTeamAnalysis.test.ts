import { describe, expect, it } from "vitest";
import { sdpFixture, xg } from "@/test/sdpFixture";
import { selectSdpEntities } from "./sdpStats";
import { teamBenchmark } from "./sdpTeamAnalysis";

describe("descriptive team benchmarks", () => {
  const teams = () => selectSdpEntities(sdpFixture().team_matches, "team", { season: "2026-27", from: 1, to: 6, recent: "all", team: "all", search: "", venue: "all", position: "all", minMinutes: 0 });
  it("uses club averages and midrank ties rather than treating a selected club as the league", () => {
    const rows = teams();
    for (let i = 0; i < rows.length; i++) for (const row of rows[i].rows) row.sdp.expected_goals = [0, 1, 1, 2][i];
    expect(teamBenchmark(rows, xg, "per_match", 1)).toEqual({ median: 1, percentile: 50, count: 4 });
    expect(teamBenchmark(rows, xg, "per_match", 0).percentile).toBe(12.5);
    expect(teamBenchmark(rows, xg, "per_match", 2).percentile).toBe(87.5);
  });
  it("excludes incomplete metrics and withholds percentiles for missing values or a single club", () => {
    const rows = teams(); rows[0].rows[0].sdp.expected_goals = null;
    expect(teamBenchmark(rows, xg, "per_match", null)).toMatchObject({ count: 3, percentile: null });
    expect(teamBenchmark([rows[1]], xg, "per_match", 1).percentile).toBeNull();
    expect(teamBenchmark([], xg, "per_match", 1)).toEqual({ median: null, percentile: null, count: 0 });
  });
});
