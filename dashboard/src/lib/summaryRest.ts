import type { PlayerRecord, SummaryData } from "@/data/types";
import type { PlayerRest, RestSummary } from "@/data/restSummary";
import { rawPlayerGameweekXp } from "@/lib/userDraft";

export interface RankedNextPlayer { player: PlayerRecord; xp: number }

/** The published upcoming GW is authoritative; never substitute an older horizon. */
export function summaryNextGw(summary: SummaryData, run: { season: string; gw_from: number; gw_to: number }): number | null {
  const gw = summary.next_gameweek?.gw;
  return summary.latest_run?.season === run.season && gw != null && Number.isInteger(gw) && gw >= run.gw_from && gw <= run.gw_to ? gw : null;
}

export function topNextPlayers(players: readonly PlayerRecord[], gw: number | null): RankedNextPlayer[] {
  if (gw === null) return [];
  const seen = new Set<number>();
  const duplicate = new Set<number>();
  for (const p of players) { if (seen.has(p.code)) duplicate.add(p.code); seen.add(p.code); }
  return players.filter((p) => ["GK", "DEF", "MID", "FWD"].includes(p.position) && !duplicate.has(p.code))
    .map((player) => ({ player, xp: rawPlayerGameweekXp(player, gw) }))
    .filter((row): row is RankedNextPlayer => row.xp !== null && Number.isFinite(row.xp))
    .sort((a, b) => b.xp - a.xp || a.player.code - b.player.code).slice(0, 15);
}

export function matchingRest(summary: RestSummary | null, player: PlayerRecord, gw: number, now: number): { rest: PlayerRest | null; reason: string | null } {
  if (!summary) return { rest: null, reason: "No rest report in this published generation." };
  if (summary.season !== player.season) return { rest: null, reason: "Rest report is for a different season." };
  if (Date.parse(summary.as_of) > now) return { rest: null, reason: "Rest report cutoff is in the future." };
  const rest = summary.players.find((p) => p.code === player.code);
  if (!rest || rest.team_code !== player.team_code) return { rest: null, reason: "Current player/club identity is not matched to this forecast." };
  const next = rest.next_fixture;
  if (!next || next.gw !== gw || next.kickoff === null) return { rest: null, reason: "Rest report does not cover this next GW fixture." };
  if (Date.parse(next.kickoff) <= now) return { rest: null, reason: "Rest report is stale: its next fixture has started." };
  if (!player.fixtures.some((f) => f.gw === gw && f.kickoff_time !== null && Date.parse(f.kickoff_time) === Date.parse(next.kickoff!) &&
      (next.fixture_id == null || next.fixture_id === f.fixture))) return { rest: null, reason: "Published rest schedule differs from this forecast fixture." };
  if (rest.verdict === "full_rest" && rest.coverage_complete !== true) return { rest: null, reason: "Complete midweek schedule evidence is not established." };
  return { rest, reason: null };
}
