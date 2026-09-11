import { afterEach, describe, expect, it, vi } from "vitest";
import { loadSdpStats, parseSdpStats } from "./sdpStats";
import { fplSupplement, sdpFixture } from "@/test/sdpFixture";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
describe("Observed SDP sidecar contract", () => {
  it("validates versioned FPL supplement provenance and fails closed on changed identity, dates or raw replacement", () => {
    const data = sdpFixture(); data.json_schema_version = 6;
    data.metrics.forEach(m => { m.omitted_zero_display = false; });
    data.team_matches.forEach(r => { r.display_assumptions = {}; r.display_supplements = {}; r.dashboard_status = "PROVIDER_VALID"; });
    const row = data.team_matches[0]; row.sdp.expected_goals = null;
    row.display_supplements = { expected_goals: fplSupplement(row) };
    const raw = JSON.stringify(data);
    expect(parseSdpStats(data)).toBe(data);
    expect(JSON.stringify(data)).toBe(raw);
    for (const [key, value] of Object.entries({ fixture: 999, subject_team_code: 999, source_known_at: "2027-01-01T00:00:00Z", player_rows: 10, starters: 10, value: -1, evidence_class: "strict_pit", records_sha256: "bad" })) {
      const broken = structuredClone(data);
      Object.assign(broken.team_matches[0].display_supplements!.expected_goals, { [key]: value });
      expect(() => parseSdpStats(broken)).toThrow();
    }
    const replaced = structuredClone(data); replaced.team_matches[0].sdp.expected_goals = 0;
    expect(() => parseSdpStats(replaced)).toThrow();
    data.json_schema_version = 5;
    expect(() => parseSdpStats(data)).toThrow();
  });
  it("preserves exact identities, nullable measurements and distinct FPL sources", () => {
    const source = sdpFixture(); source.team_matches[0].sdp.shots = null;
    const raw = JSON.stringify(source);
    expect(parseSdpStats(source)).toBe(source);
    expect(source.team_matches[0].sdp.shots).toBeNull();
    expect(source.player_matches[0].minutes_sdp).toBeNull();
    expect(source.player_matches[0].fpl?.expected_goals).toBe(0.2);
    expect(JSON.stringify(source)).toBe(raw);
  });
  it.each([2, 5] as const)("accepts mirrored owner-confirmed evidence in schema %s while raw SDP stays NULL", version => {
    const data = sdpFixture();
    const direct = data.team_matches[0];
    direct.status = "UNAVAILABLE";
    direct.sdp.shots_on_target = null;
    const shared = {
      correction_id: "2026-27-f1-team-3-sot",
      value: 0 as const,
      evidence_class: "owner_confirmed_display_correction" as const,
      owner_confirmation_recorded_at: "2026-09-08T07:00:00+00:00",
      source_known_at: "2026-09-07T07:00:00+00:00",
      provider_match_id: 123,
      provider_field: "ontargetScoringAtt" as const,
      provider_field_state: "omitted" as const,
      raw_payload_sha256: "a".repeat(64),
      corroboration: "shot_accounting_and_fpl_goalkeeper_proxy_zero" as const,
      subject_team_code: direct.team_code,
    };
    direct.display_corrections = { shots_on_target: { ...shared, relation: "direct" } };
    data.team_matches.push({
      ...direct,
      team_code: direct.opponent_team_code,
      team_name: direct.opponent_name,
      team_short_name: direct.opponent_short_name,
      opponent_team_code: direct.team_code,
      opponent_name: direct.team_name,
      opponent_short_name: direct.team_short_name,
      was_home: !direct.was_home,
      sdp: { ...direct.sdp, shots_on_target_allowed: null },
      display_corrections: { shots_on_target_allowed: { ...shared, relation: "opponent_mirror" } },
    });
    if (version === 5) {
      data.json_schema_version = 5;
      data.metrics.forEach(m => { m.omitted_zero_display = false; });
      data.team_matches.forEach(r => {
        r.display_assumptions = {};
        r.dashboard_status = r.status === "UNAVAILABLE" ? "OWNER_CONFIRMED_VALID" : "PROVIDER_VALID";
        Object.assign(r.sdp, { shots_inside_box: 3, touches_in_opposition_box: 5, passes: 300, accurate_passes: 250 });
      });
      data.team_matches.at(-1)!.sdp.shots_on_target = 2;
      direct.sdp.expected_goals = null;
      expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
      direct.sdp.expected_goals = 0.2;
      data.team_matches.at(-1)!.dashboard_status = "INCOMPLETE";
      expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
      data.team_matches.at(-1)!.dashboard_status = "OWNER_CONFIRMED_VALID";
      data.json_schema_version = 4;
      expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
      data.json_schema_version = 5;
    }
    expect(parseSdpStats(data)).toBe(data);
    expect(direct.sdp.shots_on_target).toBeNull();
    direct.sdp.shots_on_target = 0;
    expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
  });
  it.each(["future-known", "future-kickoff", "duplicate", "nonfinite", "identity", "denominator", "ambiguous-stat", "boolean-stat", "future-gameweek", "impossible-coverage", "unknown-status"])("fails closed on %s", defect => {
    const data = sdpFixture();
    if (defect === "future-known") data.team_matches[0].known_at = "2027-01-01T00:00:00Z";
    if (defect === "future-kickoff") data.team_matches[0].kickoff_time = "2027-01-01T00:00:00Z";
    if (defect === "duplicate") data.player_matches.push(data.player_matches[0]);
    if (defect === "nonfinite") data.team_matches[0].sdp.shots = Number.NaN;
    if (defect === "identity") data.player_matches[0] = { ...data.player_matches[0], code: null, provider_player_id: null };
    if (defect === "denominator") data.metrics[3].per90_denominator = "minutes_sdp";
    if (defect === "ambiguous-stat") data.metrics.push(data.metrics[0]);
    if (defect === "boolean-stat") (data.team_matches[0].sdp as unknown as Record<string, unknown>).shots = false;
    if (defect === "future-gameweek") data.gameweeks[0].source_known_at = "2027-01-01T00:00:00Z";
    if (defect === "impossible-coverage") data.coverage.unmapped_players = -1;
    if (defect === "unknown-status") data.team_matches[0].status = "GUESS";
    expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
  });
  it.each(["shots_blocked", "expected_goals_on_target"])("accepts direct %s correction without an invented opponent mirror", metric => {
    const data = sdpFixture();
    data.json_schema_version = 4;
    for (const m of data.metrics) m.omitted_zero_display = false;
    for (const row of data.team_matches) row.display_assumptions = {};
    const direct = data.team_matches[0];
    direct.status = "UNAVAILABLE";
    direct.sdp[metric] = null;
    const correction = {
      correction_id: "synthetic-blocked-zero", value: 0 as const,
      evidence_class: "owner_confirmed_display_correction" as const,
      provider_field: metric === "expected_goals_on_target" ? "expectedGoalsOnTarget" as const : "blockedScoringAtt" as const, provider_field_state: "omitted" as const,
      corroboration: metric === "expected_goals_on_target" ? "owner_confirmed_xgot_with_corroborated_zero_sot" as const : "shot_accounting_and_fpl_goalkeeper_proxy_zero" as const,
      relation: "direct" as "direct" | "opponent_mirror",
      subject_team_code: direct.team_code, provider_match_id: 123,
      raw_payload_sha256: "a".repeat(64),
      source_known_at: "2026-09-07T07:00:00+00:00",
      owner_confirmation_recorded_at: "2026-09-08T07:00:00+00:00",
    };
    direct.display_corrections = { [metric]: correction };
    expect(parseSdpStats(data)).toBe(data);
    expect(direct.sdp[metric]).toBeNull();
    if (metric === "expected_goals_on_target") {
      data.json_schema_version = 3;
      expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
      data.json_schema_version = 4;
    }
    correction.relation = "opponent_mirror";
    expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
    correction.relation = "direct";
    correction.owner_confirmation_recorded_at = "2027-01-01T00:00:00Z";
    expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
  });
  it("accepts only labelled sparse-count assumptions in schema v3", () => {
    const data = sdpFixture();
    data.json_schema_version = 3;
    data.as_of = "2026-09-10T00:00:00+00:00";
    for (const metric of data.metrics) metric.omitted_zero_display = false;
    for (const row of data.team_matches) row.display_assumptions = {};
    const row = data.team_matches[0];
    row.provider_match_id = 123;
    row.source_version = "b".repeat(64);
    row.sdp.shots_outside_box = null;
    data.metrics.push({
      ...data.metrics[0], key: "shots_outside_box", provider_field: "attemptsObox",
      omitted_zero_display: true,
    });
    row.display_assumptions!.shots_outside_box = {
      value: 0,
      evidence_class: "owner_directed_omitted_count_assumption",
      policy_recorded_at: "2026-09-09T02:47:16.006705+00:00",
      source_known_at: "2026-09-07T07:00:00+00:00",
      provider_match_id: 123,
      provider_field: "attemptsObox",
      provider_field_state: "omitted",
      raw_payload_sha256: "b".repeat(64),
    };
    expect(parseSdpStats(data)).toBe(data);
    row.sdp.shots_outside_box = 0;
    expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
    row.sdp.shots_outside_box = null;
    row.display_assumptions!.shots = row.display_assumptions!.shots_outside_box;
    expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
  });
  it("accepts unmapped stable provider identity and separate historical team membership", () => {
    const data = sdpFixture(); data.player_matches[0].code = null; data.player_matches[0].position = null;
    expect(parseSdpStats(data).player_matches[0].code).toBeNull();
  });
  it("rejects a kickoff exactly at cutoff while allowing evidence known exactly at cutoff", () => {
    const data = sdpFixture();
    data.team_matches[0].known_at = data.as_of;
    expect(parseSdpStats(data)).toBe(data);
    data.team_matches[0].kickoff_time = data.as_of;
    expect(() => parseSdpStats(data)).toThrow(/invalid or incompatible/);
  });
  it("loads the separate static SDP namespace without opening the forecast data", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => sdpFixture() });
    vi.stubGlobal("fetch", fetch);
    await loadSdpStats();
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/sdp/sdp_stats.json");
  });
  it("reports unpublished sidecar rather than fabricating rows", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    await expect(loadSdpStats()).rejects.toThrow(/have not been published/);
  });
  it("respects the existing Pages deployment base path", async () => {
    vi.stubEnv("BASE_URL", "/the_comet_fpl/");
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => sdpFixture() });
    vi.stubGlobal("fetch", fetch);
    await loadSdpStats();
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/the_comet_fpl/sdp/sdp_stats.json");
  });
});
