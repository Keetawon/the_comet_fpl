import type { NewsStory, PublicNewsFeed } from "@/data/newsFeed";
import type { PlayerRest, RestSummary } from "@/data/restSummary";
import type { PlayerRecord, TeamFixture, TeamRecord } from "@/data/types";
import { matchingRest } from "./summaryRest";

export interface MatchPreviewSide { team: TeamRecord; forecast: TeamFixture }
export interface MatchPreview {
  run_id: string;
  season: string;
  as_of: string;
  fixture: number;
  gw: number;
  kickoff_time: string | null;
  home: MatchPreviewSide;
  away: MatchPreviewSide;
}
export interface RejectedPreview { season: string; run_id: string; fixture: number; reason: string }
export interface PreviewNews {
  stories: NewsStory[];
  reason: string | null;
  rejected: { id: string; reason: string }[];
}
export interface PreviewRestRow { player: PlayerRecord; rest: PlayerRest | null; reason: string | null }
export interface PreviewRest {
  rows: PreviewRestRow[];
  reason: string | null;
  /** Joined records, including unknown verdicts; never a count of rested players. */
  matched_count: number;
  total_players: number;
}

const positiveId = (value: number) => Number.isSafeInteger(value) && value > 0;
const timestamp = (value: string | null): number => value !== null && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
const sameTime = (a: string | null, b: string | null) => a === null && b === null || Number.isFinite(timestamp(a)) && timestamp(a) === timestamp(b);
const measured = (value: number | null, maximum = Infinity): number | null => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= maximum ? value : null;
const ordinaryPlayer = (player: PlayerRecord) => ["GK", "DEF", "MID", "FWD"].includes(player.position);

/** Copy presentation scalars only. Missing/invalid measurements never become zero. */
function displayFixture(fixture: TeamFixture): TeamFixture {
  return {
    ...fixture,
    lambda_for: measured(fixture.lambda_for),
    lambda_against: measured(fixture.lambda_against),
    probability_clean_sheet: measured(fixture.probability_clean_sheet, 1),
    attack_ease_index: measured(fixture.attack_ease_index),
    defence_ease_index: measured(fixture.defence_ease_index),
    overall_ease_index: measured(fixture.overall_ease_index),
    official_fdr: Number.isInteger(fixture.official_fdr) && fixture.official_fdr! >= 1 && fixture.official_fdr! <= 5 ? fixture.official_fdr : null,
  };
}

/** Pair only the two exact directed sides of a published fixture and vintage. */
export function buildMatchPreviews(teams: readonly TeamRecord[]): { matches: MatchPreview[]; rejected: RejectedPreview[] } {
  const groups = new Map<string, MatchPreviewSide[]>();
  const teamCounts = new Map<string, number>();
  const teamKey = (team: TeamRecord) => JSON.stringify([team.run_id, team.season, team.team_code]);
  for (const team of teams) {
    teamCounts.set(teamKey(team), (teamCounts.get(teamKey(team)) ?? 0) + 1);
    for (const forecast of team.fixtures) {
      const key = JSON.stringify([team.run_id, team.season, forecast.fixture]);
      const sides = groups.get(key) ?? [];
      sides.push({ team, forecast });
      groups.set(key, sides);
    }
  }
  const matches: MatchPreview[] = [];
  const rejected: RejectedPreview[] = [];
  for (const sides of groups.values()) {
    const first = sides[0];
    const reject = (reason: string) => rejected.push({ season: first.team.season, run_id: first.team.run_id, fixture: first.forecast.fixture, reason });
    if (sides.length !== 2 || sides.some(({ team }) => teamCounts.get(teamKey(team)) !== 1)) {
      reject("The fixture needs exactly two unique published club sides.");
      continue;
    }
    const [a, b] = sides;
    if (!positiveId(a.forecast.fixture) || sides.some(({ team, forecast }) =>
      !team.run_id || !/^\d{4}-\d{2}$/.test(team.season) || !positiveId(team.team_code) || !positiveId(forecast.opponent_team_code) ||
      !Number.isFinite(timestamp(team.as_of)) || !Number.isInteger(forecast.gw) || forecast.gw < 1 || forecast.gw > 38 ||
      (forecast.kickoff_time !== null && !Number.isFinite(timestamp(forecast.kickoff_time))))) {
      reject("The published fixture has an invalid identity or timestamp.");
      continue;
    }
    if (a.team.team_code === b.team.team_code || a.forecast.opponent_team_code !== b.team.team_code || b.forecast.opponent_team_code !== a.team.team_code ||
      typeof a.forecast.was_home !== "boolean" || typeof b.forecast.was_home !== "boolean" || a.forecast.was_home === b.forecast.was_home) {
      reject("The published clubs and home/away sides are not reciprocal.");
      continue;
    }
    if (!sameTime(a.team.as_of, b.team.as_of) || a.forecast.gw !== b.forecast.gw || !sameTime(a.forecast.kickoff_time, b.forecast.kickoff_time)) {
      reject("The published sides disagree on forecast cutoff, gameweek or kickoff.");
      continue;
    }
    const home = a.forecast.was_home ? a : b;
    const away = a.forecast.was_home ? b : a;
    matches.push({
      run_id: home.team.run_id, season: home.team.season, as_of: home.team.as_of,
      fixture: home.forecast.fixture, gw: home.forecast.gw, kickoff_time: home.forecast.kickoff_time,
      home: { team: home.team, forecast: displayFixture(home.forecast) },
      away: { team: away.team, forecast: displayFixture(away.forecast) },
    });
  }
  matches.sort((a, b) => a.season.localeCompare(b.season) || a.run_id.localeCompare(b.run_id) || a.gw - b.gw ||
    (a.kickoff_time === null ? Infinity : timestamp(a.kickoff_time)) - (b.kickoff_time === null ? Infinity : timestamp(b.kickoff_time)) || a.fixture - b.fixture);
  rejected.sort((a, b) => a.season.localeCompare(b.season) || a.run_id.localeCompare(b.run_id) || a.fixture - b.fixture);
  return { matches, rejected };
}

function vintagePlayers(players: readonly PlayerRecord[], match: MatchPreview): PlayerRecord[] {
  return players.filter(player => player.run_id === match.run_id && player.season === match.season && ordinaryPlayer(player));
}
function codeCounts(players: readonly { code: number }[]): Map<number, number> {
  const counts = new Map<number, number>();
  for (const player of players) counts.set(player.code, (counts.get(player.code) ?? 0) + 1);
  return counts;
}
const belongsToMatch = (teamCode: number | null, match: MatchPreview) => teamCode === match.home.team.team_code || teamCode === match.away.team.team_code;

/** Latest reported context, never evidence reconstructed at the forecast cutoff. */
export function previewNews(feed: PublicNewsFeed | null, match: MatchPreview, players: readonly PlayerRecord[], now: number): PreviewNews {
  if (!feed) return { stories: [], reason: "No news feed in this published generation.", rejected: [] };
  const generated = timestamp(feed.generated_at);
  if (!Number.isFinite(now) || !Number.isFinite(generated) || generated > now) return { stories: [], reason: "The news feed timestamp is invalid or in the future.", rejected: [] };
  const selected = vintagePlayers(players, match);
  const counts = codeCounts(selected);
  const rejected: PreviewNews["rejected"] = [];
  const stories = feed.stories.filter(story => {
    if (story.season !== match.season || !belongsToMatch(story.team_code, match)) return false;
    let reason: string | null = null;
    if (!Number.isFinite(timestamp(story.known_at)) || timestamp(story.known_at) > generated ||
      story.summarized_at !== null && (!Number.isFinite(timestamp(story.summarized_at)) || timestamp(story.summarized_at) > generated)) {
      reason = "News knowledge or summary time is invalid or later than its publication generation.";
    } else if (story.player_code !== null && (counts.get(story.player_code) !== 1 || !selected.some(player =>
      positiveId(player.code) && player.code === story.player_code && player.team_code === story.team_code && sameTime(player.as_of, match.as_of)))) {
      reason = "The reported player and club do not match this forecast vintage.";
    }
    if (reason) rejected.push({ id: story.id, reason });
    return reason === null;
  }).sort((a, b) => timestamp(b.known_at) - timestamp(a.known_at) || a.id.localeCompare(b.id));
  return { stories, reason: stories.length ? null : "No exactly matched news in this generation; selected sources do not establish complete coverage.", rejected };
}

/** Attach each player report only to its exact next fixture; retain every unavailable reason. */
export function previewRest(summary: RestSummary | null, match: MatchPreview, players: readonly PlayerRecord[], now: number): PreviewRest {
  const vintage = vintagePlayers(players, match);
  const counts = codeCounts(vintage);
  // One unavailable row per ambiguous player identity, never duplicate display keys.
  const selected = [...new Map(vintage.filter(player => belongsToMatch(player.team_code, match)).map(player => [player.code, player])).values()];
  const reportCounts = codeCounts(summary?.players ?? []);
  let reason: string | null = null;
  if (!summary) reason = "No rest report in this published generation.";
  else if (summary.season !== match.season) reason = "The rest report is for a different season.";
  else if (!Number.isFinite(now) || !Number.isFinite(timestamp(summary.as_of)) || timestamp(summary.as_of) > now) reason = "The rest report cutoff is invalid or in the future.";
  else if (!Number.isFinite(timestamp(match.kickoff_time))) reason = "The selected fixture has no confirmed kickoff.";
  else if (timestamp(match.kickoff_time) <= now) reason = "The selected fixture has started; next-fixture rest context is unavailable.";

  const rows = selected.map((player): PreviewRestRow => {
    const unavailable = (message: string): PreviewRestRow => ({ player, rest: null, reason: message });
    if (reason) return unavailable(reason);
    if (!positiveId(player.code) || counts.get(player.code) !== 1 || !sameTime(player.as_of, match.as_of)) return unavailable("The forecast player identity is duplicated or belongs to a different cutoff.");
    const side = player.team_code === match.home.team.team_code ? match.home : match.away;
    const fixtures = player.fixtures.filter(fixture => fixture.fixture === match.fixture);
    if (fixtures.length !== 1 || fixtures[0].gw !== match.gw || fixtures[0].opponent_team_code !== side.forecast.opponent_team_code ||
      fixtures[0].was_home !== side.forecast.was_home || !sameTime(fixtures[0].kickoff_time, match.kickoff_time)) return unavailable("The player forecast does not match this exact fixture, opponent and venue.");
    if (reportCounts.get(player.code) !== 1) return unavailable("The rest report has no unique record for this player.");
    const result = matchingRest(summary, player, match.gw, now);
    if (!result.rest) return unavailable(result.reason ?? "Rest evidence is unavailable.");
    const next = result.rest.next_fixture;
    if (next?.fixture_id !== match.fixture || next.was_home !== side.forecast.was_home || !sameTime(next.kickoff, match.kickoff_time)) return unavailable("The rest report next fixture or venue differs from this match.");
    return { player, rest: result.rest, reason: null };
  }).sort((a, b) => a.player.team_code - b.player.team_code || a.player.code - b.player.code);
  return { rows, reason: reason ?? (rows.length ? null : "No ordinary players in this forecast vintage match these clubs."), matched_count: rows.filter(row => row.rest !== null).length, total_players: rows.length };
}
