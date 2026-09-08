import type { SdpMatch, SdpMetric, SdpStatsData } from "@/data/sdpStats";

export const shooting: SdpMetric = { key: "shots", label: "Shots", group: "Attacking", source: "sdp", scope: "team", unit: "count", aggregation: "sum", per90_denominator: null, verified_semantics: true };
export const xg: SdpMetric = { ...shooting, key: "expected_goals", label: "xG", unit: "xg" };
export const possession: SdpMetric = { ...shooting, key: "possession", label: "Possession", group: "Possession", unit: "percent", aggregation: "mean" };
export const fplXg: SdpMetric = { ...xg, source: "fpl", scope: "player", per90_denominator: "minutes_fpl" };

export function sdpMatch(patch: Partial<SdpMatch> = {}): SdpMatch {
  return { season: "2026-27", gw: 1, fixture: 1, kickoff_time: "2026-08-22T14:00:00+00:00", team_code: 3, team_name: "Arsenal", team_short_name: "ARS", opponent_team_code: 8, opponent_name: "Chelsea", opponent_short_name: "CHE", was_home: true, status: "FINAL", known_at: "2026-09-07T08:00:00+00:00", sdp: { shots: 10, expected_goals: 1.5, possession: 60 }, ...patch };
}

export function sdpFixture(): SdpStatsData {
  const teamRows: SdpMatch[] = [], playerRows: SdpMatch[] = [];
  for (let team = 0; team < 4; team++) {
    for (let gw = 1; gw <= 6; gw++) {
      const row = sdpMatch({ team_code: team + 1, opponent_team_code: 10, team_name: ["Arsenal", "Brighton", "Chelsea", "Everton"][team], team_short_name: ["ARS", "BHA", "CHE", "EVE"][team], gw, fixture: team * 10 + gw, kickoff_time: new Date(Date.UTC(2026, 7, gw)).toISOString(), was_home: gw % 2 === 1, sdp: { shots: 10 + team + gw, expected_goals: (team + 1) * gw / 10, possession: 45 + team, expected_goals_allowed: (team + 1) * gw / 20 } });
      teamRows.push({ ...row, display_corrections: {} });
      playerRows.push({ ...row, code: 100 + team, provider_player_id: 1000 + team, web_name: `Player ${team + 1}`, position: team === 0 ? "DEF" : "MID", provider_position: "Midfielder", provider_sub_position: null, started: true, bench: false, appeared: true, minutes_sdp: null, nominal_minutes_sdp: 90, minutes_fpl: 60, sdp: {}, fpl: { expected_goals: 0.2 + team / 10 } });
    }
  }
  return { schema: "fpl.sdp-stats", json_schema_version: 2, as_of: "2026-09-08T08:00:00+00:00", source_status: { team_stats: "AVAILABLE", player_stats: "UNAVAILABLE", player_lineups: "AVAILABLE", fpl_enrichment: "AVAILABLE", latest_sdp_known_at: "2026-09-07T08:00:00+00:00", latest_fpl_known_at: "2026-09-07T09:00:00+00:00", latest_completed_kickoff: "2026-08-06T00:00:00Z", notes: ["Retained observed source versions. Missing values remain unavailable."] }, coverage: { team_matches: teamRows.length, player_matches: playerRows.length, sdp_lineup_player_matches: playerRows.length, fpl_player_matches: playerRows.length, team_failures: 0, unmapped_players: 0, seasons: ["2026-27"] }, gameweeks: [{ season: "2026-27", gw: 6, finished: false, fixtures_total: 10, fixtures_completed: 4, source_known_at: "2026-09-07T09:00:00+00:00" }], metrics: [shooting, xg, possession, fplXg, { ...xg, key: "expected_goals_allowed", label: "xG allowed" }].map(metric => ({ ...metric })), team_matches: teamRows, player_matches: playerRows };
}
