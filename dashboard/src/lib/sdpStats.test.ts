import { describe, expect, it } from "vitest";
import { metricAssumptions, metricCorrections, metricRaw, metricValue, sdpCsv, selectSdpEntities, sortSdpEntities } from "./sdpStats";
import { fplSupplement, fplXg, possession, sdpFixture, sdpMatch, shooting, xg } from "@/test/sdpFixture";
import type { SdpFilters } from "./sdpStats";

const filters: SdpFilters = { season: "2026-27", from: 1, to: 6, team: "all", venue: "all", recent: "all", search: "", position: "all", minMinutes: 0 };
describe("SDP observed descriptive arithmetic", () => {
  it("uses labelled FPL supplements consistently for mixed-source averages, sort and CSV without replacing SDP", () => {
    const a = sdpMatch({ sdp: { expected_goals: null }, status: "UNAVAILABLE", dashboard_status: "INCOMPLETE" });
    a.display_supplements = { expected_goals: fplSupplement(a, 2) };
    const b = sdpMatch({ fixture: 2, sdp: { expected_goals: 1 } });
    const before = JSON.stringify([a, b]);
    expect(metricRaw(a, xg)).toBe(2);
    expect(metricValue([a, b], xg, "per_match").value).toBe(1.5);
    const entity = { id: "team:3", name: "Arsenal", clubs: "ARS", position: "", code: null, teamCode: 3, rows: [a, b] };
    const csv = sdpCsv([entity], [xg], "per_match");
    expect(csv).toContain("SDP / marked FPL xG");
    expect(csv).toContain('"1.5","2/2"');
    expect(csv).toContain("FPL archive player-sum xG");
    expect(csv).toContain("Actual archive capture");
    expect(sdpCsv([entity], [xg], "per_match")).toBe(csv);
    expect(sortSdpEntities([entity, { ...entity, id: "team:2", rows: [b] }], xg, "per_match", false)[0].id).toBe("team:3");
    expect(metricValue([a, sdpMatch({ sdp: { expected_goals: null } })], xg, "per_match").value).toBeNull();
    expect(JSON.stringify([a, b])).toBe(before);
    a.sdp.expected_goals = 0;
    expect(metricRaw(a, xg)).toBe(0);
  });
  it("does not turn a missing match metric into zero or a complete aggregate", () => {
    const value = metricValue([sdpMatch(), sdpMatch({ sdp: { shots: null } })], shooting, "total");
    expect(value).toEqual({ value: null, measured: 1, matches: 2, minutes: null });
    expect(metricValue([sdpMatch({ sdp: { shots: 0 } })], shooting, "total").value).toBe(0);
    expect(metricValue([], shooting, "total").value).toBeNull();
  });
  it.each(["ontargetScoringAtt", "blockedScoringAtt", "expectedGoalsOnTarget"] as const)("uses the labelled %s display correction consistently without changing raw SDP", providerField => {
    const key = providerField === "expectedGoalsOnTarget" ? "expected_goals_on_target" : providerField === "blockedScoringAtt" ? "shots_blocked" : "shots_on_target";
    const metric = { ...shooting, key, label: key };
    const row = sdpMatch({
      status: "UNAVAILABLE",
      sdp: { [key]: null },
      display_corrections: {
        [key]: {
          correction_id: "2026-27-f7-team-7-sot",
          value: 0,
          evidence_class: "owner_confirmed_display_correction",
          owner_confirmation_recorded_at: "2026-09-08T07:00:00+00:00",
          source_known_at: "2026-09-07T07:00:00+00:00",
          provider_match_id: 123,
          provider_field: providerField,
          provider_field_state: "omitted",
          raw_payload_sha256: "a".repeat(64),
          corroboration: providerField === "expectedGoalsOnTarget" ? "owner_confirmed_xgot_with_corroborated_zero_sot" : "shot_accounting_and_fpl_goalkeeper_proxy_zero",
          relation: "direct",
          subject_team_code: 3,
        },
      },
    });
    expect(row.sdp[key]).toBeNull();
    expect(metricRaw(row, metric)).toBe(0);
    expect(metricValue([row], metric, "total")).toEqual({ value: 0, measured: 1, matches: 1, minutes: null });
    expect(metricCorrections([row], metric)).toHaveLength(1);
    const csv = sdpCsv([{ id: "team:3", name: "Arsenal", clubs: "ARS", position: "—", code: null, teamCode: 3, rows: [row] }], [metric], "total");
    expect(csv).toContain("Owner-confirmed display correction");
    expect(csv).toContain(`${providerField} was omitted`);
    expect(metricValue([row], metric, "per_match").value).toBe(0);
    expect(sdpCsv([{ id: "team:3", name: "Arsenal", clubs: "ARS", position: "", code: null, teamCode: 3, rows: [row] }], [metric], "per_match")).toContain("average per match");
  });
  it("averages player stats over witnessed appearances, excluding DNPs without treating unknown minutes as zero", () => {
    const rows = [
      sdpMatch({ minutes_fpl: 30, fpl: { expected_goals: 0.1 } }),
      sdpMatch({ minutes_fpl: 90, fpl: { expected_goals: 0.5 } }),
      sdpMatch({ minutes_fpl: 0, fpl: { expected_goals: null } }),
    ];
    expect(metricValue(rows, fplXg, "per_appearance")).toEqual({ value: 0.3, measured: 2, matches: 2, minutes: null });
    expect(metricValue([rows[2]], fplXg, "per_appearance").value).toBeNull();
    expect(metricValue([...rows, sdpMatch({ minutes_fpl: null })], fplXg, "per_appearance").value).toBeNull();
    expect(metricValue([...rows, sdpMatch({ minutes_fpl: 90, fpl: { expected_goals: null } })], fplXg, "per_appearance").value).toBeNull();
    const entity = { id: "fpl:1", name: "Player", clubs: "ARS", position: "DEF", code: 1, teamCode: 3, rows };
    const csv = sdpCsv([entity], [fplXg], "per_appearance");
    expect(csv).toContain('"0.3","2/2"');
    expect(csv).toContain("average per appearance; FPL minutes > 0");
    expect(sdpCsv([entity], [fplXg], "per_appearance")).toBe(csv);
    expect(sdpCsv([{ ...entity, rows: [sdpMatch({ minutes_fpl: null })] }], [fplXg], "per_appearance")).toContain("unknown appearances (missing FPL minutes)");
    const other = { ...entity, id: "fpl:2", rows: [sdpMatch({ minutes_fpl: 60, fpl: { expected_goals: 0.4 } })] };
    expect(sortSdpEntities([entity, other], fplXg, "per_appearance", false)[0].id).toBe("fpl:2");
  });
  it("shows a raw omitted sparse count as an explicitly labelled assumed zero", () => {
    const metric = { ...shooting, key: "shots_outside_box", provider_field: "attemptsObox", omitted_zero_display: true };
    const row = sdpMatch({
      provider_match_id: 123,
      source_version: "b".repeat(64),
      sdp: { shots_outside_box: null },
      display_assumptions: {
        shots_outside_box: {
          value: 0,
          evidence_class: "owner_directed_omitted_count_assumption",
          policy_recorded_at: "2026-09-09T02:47:16.006705+00:00",
          source_known_at: "2026-09-07T07:00:00+00:00",
          provider_match_id: 123,
          provider_field: "attemptsObox",
          provider_field_state: "omitted",
          raw_payload_sha256: "b".repeat(64),
        },
      },
    });
    expect(row.sdp.shots_outside_box).toBeNull();
    expect(metricRaw(row, metric)).toBe(0);
    expect(metricAssumptions([row], metric)).toHaveLength(1);
    const csv = sdpCsv([{ id: "team:3", name: "Arsenal", clubs: "ARS", position: "—", code: null, teamCode: 3, rows: [row] }], [metric], "total");
    expect(csv).toContain("1/1 (1 assumed zero)");
    expect(csv).toContain("not a provider-verified zero");
  });
  it("uses matched actual FPL minutes for FPL per90 and never nominal SDP time", () => {
    const row = sdpMatch({ fpl: { expected_goals: 0.5 }, minutes_fpl: 45, minutes_sdp: null, nominal_minutes_sdp: 90 });
    expect(metricValue([row], fplXg, "per90").value).toBe(1);
    expect(metricValue([{ ...row, minutes_fpl: null }], fplXg, "per90").value).toBeNull();
    expect(metricValue([{ ...row, minutes_fpl: 0 }], fplXg, "per90").value).toBeNull();
    expect(metricValue([row], { ...fplXg, source: "sdp", per90_denominator: "minutes_sdp" }, "per90").value).toBeNull();
  });
  it("computes exposure-weighted rate rather than averaging fixture per90 rates", () => {
    const rows = [sdpMatch({ minutes_fpl: 10, fpl: { expected_goals: 1 } }), sdpMatch({ minutes_fpl: 80, fpl: { expected_goals: 1 } })];
    expect(metricValue(rows, fplXg, "per90").value).toBe(2);
  });
  it("preserves percentage means and per-match count denominators", () => {
    const rows = [sdpMatch(), sdpMatch({ sdp: { possession: 40, shots: 20 } })];
    expect(metricValue(rows, possession, "total").value).toBe(50);
    expect(metricValue(rows, shooting, "per_match").value).toBe(15);
    expect(metricValue(rows, { ...shooting, verified_semantics: false }, "total").value).toBe(30);
    expect(metricValue([sdpMatch({ sdp: { shots: null } })], { ...shooting, verified_semantics: false }, "total").value).toBeNull();
  });
  it("selects each entity's last3/5 matches with exact season, team and venue filters", () => {
    const data = sdpFixture();
    expect(selectSdpEntities(data.team_matches, "team", { ...filters, recent: "3" }).every(r => r.rows.length === 3)).toBe(true);
    const away = selectSdpEntities(data.team_matches, "team", { ...filters, team: "1", venue: "away", recent: "3" });
    expect(away[0].rows.map(r => r.gw)).toEqual([2, 4, 6]);
    expect(selectSdpEntities(data.team_matches, "team", { ...filters, season: "2025-26" })).toEqual([]);
  });
  it("keeps DGW legs and temporal transfer clubs without reassigning old matches", () => {
    const source = sdpFixture().player_matches.filter(r => r.code === 100);
    const rows = [source[0], { ...source[1], gw: 1, team_code: 6, team_name: "Other", team_short_name: "OTH" }];
    const selected = selectSdpEntities(rows, "player", filters);
    expect(selected).toHaveLength(1);
    expect(selected[0].clubs).toBe("ARS / OTH");
    expect(selected[0].rows).toHaveLength(2);
    expect(selectSdpEntities(rows, "player", { ...filters, team: "1" })[0].rows).toHaveLength(1);
  });
  it("sorts NULL last in both directions and keeps deterministic ties", () => {
    const rows = selectSdpEntities(sdpFixture().team_matches, "team", filters);
    rows[0].rows[0].sdp.shots = null;
    for (const ascending of [true, false]) expect(sortSdpEntities(rows, shooting, "total", ascending).at(-1)?.name).toBe("Arsenal");
    expect(sortSdpEntities(rows, shooting, "total", true)).toEqual(sortSdpEntities(rows, shooting, "total", true));
  });
  it("minimum minutes never substitutes unknown exposure", () => {
    const source = sdpFixture().player_matches; source[0].minutes_fpl = null;
    const selected = selectSdpEntities(source, "player", { ...filters, minMinutes: 1 });
    expect(selected.map(row => row.name)).not.toContain("Player 1");
  });
  it("exports source labels, exact selected range, coverage, NULL blanks and safe CSV names", () => {
    const selected = selectSdpEntities(sdpFixture().player_matches, "player", filters);
    selected[0].name = '=SUM(1,2)'; selected[0].rows[0].fpl!.expected_goals = null;
    const csv = sdpCsv(selected, [fplXg], "total");
    expect(csv).toContain('"FPL xG"');
    expect(csv).toContain('"\'=SUM(1,2)"');
    expect(csv).toContain('"","5/6"');
    expect(csv).not.toContain("undefined");
  });
  it("keeps provider reconciliation and per-match percentage-mean qualifiers in CSV headers", () => {
    const selected = selectSdpEntities(sdpFixture().team_matches, "team", filters);
    const csv = sdpCsv(selected, [{ ...shooting, verified_semantics: false, provider_field: "totalScoringAtt" }, possession], "total");
    expect(csv).toContain('SDP Shots [provider observation; not independently reconciled; totalScoringAtt]');
    expect(csv).toContain('SDP Possession [per-match mean]');
    expect(csv).toContain('"81","6/6"');
  });
});
