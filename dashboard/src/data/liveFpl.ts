// Independent current reporting. Forecast files remain pinned to their immutable generation.
import type { CurrentPlayerAvailability, CurrentPlayerPrice, PlayerRecord, TeamRecord, FixtureScheduleOverlay } from "./types";

interface OfficialPlayer {
  season: string;
  code: number;
  current_availability: CurrentPlayerAvailability;
  current_price: CurrentPlayerPrice;
}
interface OfficialFixture {
  fixture: number;
  team_code: number;
  opponent_team_code: number;
  was_home: boolean;
  official_fdr: number | null;
}
export interface LiveFpl {
  schema: "fpl.current-official-reporting";
  schema_version: 1;
  season: string;
  captured_at: string;
  capture_id: string;
  sources: { "bootstrap-static": string; fixtures: string };
  players: OfficialPlayer[];
  fixtures: OfficialFixture[];
}
const SHA = /^[a-f0-9]{64}$/;
const instant = (value: unknown): value is string => typeof value === "string" &&
  /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) > 0;

export function validateLiveFpl(value: unknown): LiveFpl {
  if (!value || typeof value !== "object") throw new Error("Missing official reporting");
  const data = value as LiveFpl;
  if (data.schema !== "fpl.current-official-reporting" || data.schema_version !== 1 ||
      !/^\d{4}-\d{2}$/.test(data.season) || !instant(data.captured_at) ||
      Date.parse(data.captured_at) > Date.now() + 60_000 || !SHA.test(data.capture_id) ||
      !SHA.test(data.sources?.["bootstrap-static"]) || !SHA.test(data.sources?.fixtures) ||
      !Array.isArray(data.players) || data.players.length < 400 ||
      !Array.isArray(data.fixtures) || data.fixtures.length !== 760) throw new Error("Invalid official coverage");
  const codes = new Set<number>();
  for (const p of data.players) {
    if (!p || !positive(p.code) || codes.has(p.code) || p.season !== data.season) throw new Error("Invalid player identity");
    codes.add(p.code);
    const a = p.current_availability;
    const price = p.current_price;
    for (const report of [a, price]) {
      if (!report || report.source !== "FPL" || report.semantics !== "current_reported_not_forecast" ||
          report.season !== data.season || report.code !== p.code || report.captured_at !== data.captured_at ||
          report.capture_id !== data.capture_id || report.source_sha256 !== data.sources["bootstrap-static"]) {
        throw new Error("Official reporting provenance mismatch");
      }
    }
    if ((a.status !== null && !["a", "d", "i", "s", "u", "n", "x"].includes(a.status)) ||
        (a.chance_of_playing_next_round !== null && (!Number.isInteger(a.chance_of_playing_next_round) ||
          a.chance_of_playing_next_round < 0 || a.chance_of_playing_next_round > 100)) ||
        (a.next_gw !== null && (!positive(a.next_gw) || a.next_gw > 38)) ||
        (a.news !== null && typeof a.news !== "string") ||
        (a.news_added !== null && (!instant(a.news_added) || Date.parse(a.news_added) > Date.parse(data.captured_at))) ||
        (price.now_cost !== null && !positive(price.now_cost))) throw new Error("Invalid official player values");
  }
  const sides = new Map<string, OfficialFixture>();
  for (const f of data.fixtures) {
    if (!f || !positive(f.fixture) || !positive(f.team_code) || !positive(f.opponent_team_code) ||
        f.team_code === f.opponent_team_code || typeof f.was_home !== "boolean" ||
        (f.official_fdr !== null && (!Number.isInteger(f.official_fdr) || f.official_fdr < 1 || f.official_fdr > 5))) {
      throw new Error("Invalid official fixture");
    }
    const key = `${f.fixture}:${f.team_code}`;
    if (sides.has(key)) throw new Error("Duplicate official fixture");
    sides.set(key, f);
  }
  for (const f of data.fixtures) {
    const opponent = sides.get(`${f.fixture}:${f.opponent_team_code}`);
    if (!opponent || opponent.opponent_team_code !== f.team_code || opponent.was_home === f.was_home) {
      throw new Error("Contradictory official fixture sides");
    }
  }
  return data;
}

let pinned: Promise<LiveFpl | null> | undefined;
export function loadLiveFpl(): Promise<LiveFpl | null> {
  const pointer = import.meta.env.VITE_PUBLIC_DATA_POINTER?.trim();
  // Explicit existing production origin only; local/private tools never gain a new request.
  if (pointer !== "https://data.thecometfpl.com/current.json") return Promise.resolve(null);
  return pinned ??= (async () => {
    try {
      const response = await fetch("https://data.thecometfpl.com/live-fpl/current.json", {
        cache: "no-store", redirect: "error", signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) throw new Error("Official reporting unavailable");
      const text = await response.text();
      if (text.length > 4_000_000) throw new Error("Official reporting exceeds size bound");
      return validateLiveFpl(JSON.parse(text));
    } catch { return null; } // Last valid generation remains usable; the status bar labels the fallback.
  })();
}

function fixtureLookup(data: LiveFpl) {
  const sides = new Map(data.fixtures.map(f => [`${f.fixture}:${f.team_code}`, f]));
  return (season: string, team: number, fixture: { fixture: number; opponent_team_code: number; was_home: boolean | null }, fallback: number | null): number | null => {
  if (season !== data.season) return fallback;
  const match = sides.get(`${fixture.fixture}:${team}`);
  return match && match.opponent_team_code === fixture.opponent_team_code && match.was_home === fixture.was_home
    ? match.official_fdr : null;
  };
}

export function applyLivePlayers(players: PlayerRecord[], live: LiveFpl | null): PlayerRecord[] {
  if (!live) return players;
  const current = new Map(live.players.map(p => [p.code, p]));
  const fdr = fixtureLookup(live);
  return players.map(p => {
    if (p.season !== live.season) return p;
    const report = current.get(p.code);
    const newer = !p.current_availability || Date.parse(live.captured_at) >= Date.parse(p.current_availability.captured_at);
    return { ...p,
      ...(newer ? { current_availability: report?.current_availability ?? null, current_price: report?.current_price ?? null } : {}),
      fixtures: p.fixtures.map(f => ({ ...f, team_official_fdr: newer ? fdr(p.season, p.team_code, f, f.team_official_fdr) : f.team_official_fdr })),
    };
  });
}

export function applyLiveTeams(teams: TeamRecord[], live: LiveFpl | null, exportedAt?: string): TeamRecord[] {
  if (!live || (exportedAt && Date.parse(live.captured_at) < Date.parse(exportedAt))) return teams;
  const fdr = fixtureLookup(live);
  return teams.map(t => ({ ...t, fixtures: t.fixtures.map(f => ({ ...f,
    official_fdr: fdr(t.season, t.team_code, f, f.official_fdr),
  })) }));
}

export function applyLiveSchedule(schedule: FixtureScheduleOverlay, live: LiveFpl | null): FixtureScheduleOverlay {
  if (!live || Date.parse(live.captured_at) < Date.parse(schedule.export_created_at)) return schedule;
  const fdr = fixtureLookup(live);
  return { ...schedule, teams: schedule.teams.map(t => ({ ...t,
    fixtures: t.fixtures.map(f => ({ ...f, official_fdr: fdr(t.season, t.team_code, f, f.official_fdr ?? null) })),
  })) };
}
