import type { CompetitiveSchedule } from "@/data/competitiveSchedule";
import type { FixtureScheduleOverlay } from "@/data/types";

export interface CalendarFixture {
  key: string; teamCode: number; opponent: string; opponentName: string;
  opponentCode: number | null; home: boolean | null; kickoff: string | null;
  competition: string; competitionName: string; gw: number | null;
  fdr: number | null; status: string; source: "FPL" | "SDP"; knownAt: string;
}
const ABBR: Record<number, string> = { 1: "FAC", 2: "LC", 5: "UCL", 6: "UEL", 1125: "UECL" };

/** A fixed UK football calendar, independent of the browser's time zone. */
export function footballDate(instant: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(instant));
}

export function calendarFixtures(schedule: FixtureScheduleOverlay, cups: CompetitiveSchedule | null, season: string): CalendarFixture[] {
  const rows: CalendarFixture[] = [];
  const seen = new Set<string>();
  for (const team of schedule.teams.filter((t) => t.season === season)) {
    for (const f of team.fixtures) {
      const key = `fpl:${f.fixture}:${team.team_code}`;
      if (seen.has(key)) throw new Error("Duplicate official fixture side");
      seen.add(key);
      rows.push({ key, teamCode: team.team_code, opponent: f.opponent_short_name,
        opponentName: schedule.teams.find((t) => t.season === season && t.team_code === f.opponent_team_code)?.team_name ?? f.opponent_short_name,
        opponentCode: f.opponent_team_code, home: f.was_home, kickoff: f.kickoff_time,
        competition: "PL", competitionName: "Premier League", gw: f.gw, fdr: f.official_fdr ?? null,
        status: "Official schedule", source: "FPL", knownAt: schedule.export_created_at });
    }
  }
  if (cups?.season === season) for (const comp of cups.competitions) {
    for (const m of comp.matches) for (const home of [true, false]) {
      const teamCode = home ? m.home_team_code : m.away_team_code;
      if (teamCode === null) continue;
      const key = `sdp:${comp.competition_id}:${m.provider_match_id}:${teamCode}`;
      if (seen.has(key)) throw new Error("Duplicate competitive fixture side");
      seen.add(key);
      rows.push({ key, teamCode, opponent: home ? m.away_short : m.home_short,
        opponentName: home ? m.away_name : m.home_name, opponentCode: home ? m.away_team_code : m.home_team_code,
        home, kickoff: m.kickoff_time, competition: ABBR[comp.competition_id] ?? comp.name,
        competitionName: comp.name, gw: null, fdr: null, status: m.status, source: "SDP",
        knownAt: comp.sources.find((s) => s.payload_id === m.source_payload_id)!.known_at });
    }
  }
  return rows.sort((a, b) => (a.kickoff ?? "").localeCompare(b.kickoff ?? "") || a.key.localeCompare(b.key));
}

export function calendarRange(rows: CalendarFixture[], fromGw: number, toGw: number): [string, string] {
  const days = rows.filter((r) => r.gw !== null && r.gw >= fromGw && r.gw <= toGw && r.kickoff)
    .map((r) => footballDate(r.kickoff!)).sort();
  if (!days.length) return ["", ""];
  const first = new Date(`${days[0]}T12:00:00Z`);
  first.setUTCDate(first.getUTCDate() - (first.getUTCDay() + 6) % 7);
  return [first.toISOString().slice(0, 10), days.at(-1)!];
}

export function visibleCalendar(rows: CalendarFixture[], codes: number[], from: string, to: string) {
  const selected = rows.filter((r) => codes.includes(r.teamCode));
  const dated = selected.filter((r) => r.kickoff && footballDate(r.kickoff) >= from && footballDate(r.kickoff) <= to);
  return { rows: dated, dates: [...new Set(dated.map((r) => footballDate(r.kickoff!)))].sort(),
    undated: selected.filter((r) => r.kickoff === null) };
}

export interface CalendarColumn {
  key: string;
  heading: "Weekend" | "Midweek" | "Cup week";
  label: string;
  from: string;
  to: string;
  fixtures: CalendarFixture[];
}

/** Group PL by official GW (all DGW legs), cups by their UK calendar week.
 * Cup weekends stay separate and are labelled honestly, never forced into a GW.
 */
export function calendarColumns(rows: CalendarFixture[]): CalendarColumn[] {
  const groups = new Map<string, CalendarColumn>();
  for (const row of rows) {
    if (!row.kickoff && row.gw === null) continue;
    const day = row.kickoff ? footballDate(row.kickoff) : "";
    const monday = new Date(`${day || "2000-01-03"}T12:00:00Z`);
    const weekday = monday.getUTCDay();
    monday.setUTCDate(monday.getUTCDate() - (weekday + 6) % 7);
    const key = row.gw !== null ? `gw:${row.gw}` : `cups:${monday.toISOString().slice(0, 10)}`;
    const group: CalendarColumn = groups.get(key) ?? {key, heading: row.gw !== null ? "Weekend" : "Midweek",
      label: row.gw !== null ? `GW${row.gw}` : "", from: day, to: day, fixtures: []};
    if (row.gw === null && (weekday < 2 || weekday > 4)) group.heading = "Cup week";
    group.fixtures.push(row);
    group.from = group.from && (!day || group.from < day) ? group.from : day;
    group.to = group.to > day ? group.to : day;
    if (row.gw === null) group.label = [...new Set(group.fixtures.map((f) => f.competition))].sort().join(" · ");
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => (a.from || "9999").localeCompare(b.from || "9999") || a.key.localeCompare(b.key));
}

export function leagueSlot(schedule: FixtureScheduleOverlay, season: string, code: number, gw: number): "BGW" | "DGW" | "SINGLE" | "UNAVAILABLE" {
  // The published overlay contract is the complete scheduled season; a missing
  // team record is unavailable, never a blank gameweek. Unscheduled dates still
  // count as fixtures and therefore cannot create a false BGW.
  const team = schedule.teams.find((t) => t.season === season && t.team_code === code);
  if (!team || !schedule.teams.some((t) => t.season === season && t.fixtures.some((f) => f.gw === gw))) return "UNAVAILABLE";
  const count = team.fixtures.filter((f) => f.gw === gw).length;
  return count === 0 ? "BGW" : count > 1 ? "DGW" : "SINGLE";
}
