import type { PublicNewsFeed } from "@/data/newsFeed";
import type { PlayerRest, RestSummary } from "@/data/restSummary";
import type { FixtureScheduleOverlay, PlayerObservedActualsRecord, PlayerRecord, TeamRecord } from "@/data/types";
import { buildMatchPreviews, previewNews, previewRest, type MatchPreview } from "./matchPreview";
import { averageObservedPointsPerAppearance } from "./playerActuals";

export type BriefingLanguage = "en" | "th";
export interface SummaryBriefingInput {
  teams: readonly TeamRecord[];
  players: readonly PlayerRecord[];
  schedule: FixtureScheduleOverlay;
  run: { run_id: string; season: string };
  gw: number;
  news: PublicNewsFeed | null;
  rest: RestSummary | null;
  actuals: readonly PlayerObservedActualsRecord[] | null;
  now: number;
  language: BriefingLanguage;
}
export interface SummaryBriefing { text: string; fixtures: number; forecasts: number; warnings: string[] }

const stamp = (value: string | null | undefined) => value && Number.isFinite(Date.parse(value))
  ? `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC` : "—";
const rounded = (value: number | null) => value === null ? "—" : String(Math.round(value));
const decimal = (value: number | null) => value === null ? "—" : value.toFixed(2);
const sameKickoff = (a: string | null, b: string | null) => a === b || a !== null && b !== null && Date.parse(a) === Date.parse(b);
const SCOUT_POST = /^https:\/\/(?:www\.)?(?:x\.com|twitter\.com)\/FFScout\/status\/\d+$/i;
const NEWS_WINDOW = 7 * 86400_000;

/** Join current schedule, one saved forecast and separately dated public context. No model arithmetic. */
export function buildSummaryBriefing(input: SummaryBriefingInput): SummaryBriefing {
  const { run, gw, schedule, players, rest, now, language } = input;
  const say = (en: string, th: string) => language === "th" ? th : en;
  const warnings: string[] = [];
  const unavailable = (reason: string): SummaryBriefing => ({ text: "", fixtures: 0, forecasts: 0, warnings: [reason] });
  if (!Number.isInteger(gw) || gw < 1 || gw > 38 || !Number.isFinite(now)) return unavailable(say("Next gameweek unavailable.", "ยังไม่มีข้อมูลเกมวีคถัดไป"));
  const teams = input.teams.filter(team => team.run_id === run.run_id && team.season === run.season);
  const roster = players.filter(player => player.run_id === run.run_id && player.season === run.season);
  const cutoffs = new Set([...teams, ...roster].map(row => Date.parse(row.as_of)));
  if (cutoffs.size !== 1 || !Number.isFinite([...cutoffs][0]) || [...cutoffs][0] > now ||
      [...teams, ...roster].some(row => !/(?:Z|[+-]\d{2}:\d{2})$/.test(row.as_of))) return unavailable(say("A single forecast cutoff could not be verified.", "ยังยืนยันเวลาตัดข้อมูลคาดการณ์ชุดเดียวกันไม่ได้"));
  const asOf = new Date([...cutoffs][0]).toISOString();
  const published = buildMatchPreviews(teams).matches.filter(match => match.gw === gw);
  // Null scalars are explicit placeholders for current fixtures without a usable saved forecast.
  const scheduled = buildMatchPreviews(schedule.teams.filter(team => team.season === run.season).map(team => ({
    ...team, run_id: run.run_id, as_of: asOf, form: null,
    fixtures: team.fixtures.filter(fixture => fixture.gw === gw).map(fixture => ({
      ...fixture, lambda_for: null, lambda_against: null, probability_clean_sheet: null,
      attack_ease_index: null, defence_ease_index: null, overall_ease_index: null,
      ease_index_formula_version: "unavailable", official_fdr: fixture.official_fdr ?? null, stage_a_league_average_team: false,
    })),
  })));
  if (scheduled.rejected.length) return unavailable(say("The current fixture schedule has conflicting or missing sides. A complete briefing is unavailable.", "ตารางแข่งขันมีคู่แข่งที่ข้อมูลขัดแย้งหรือไม่ครบ จึงยังสร้างสรุปครบทุกคู่ไม่ได้"));
  if (!scheduled.matches.length) return unavailable(say(`No scheduled fixtures for GW${gw}.`, `ไม่มีคู่แข่งขันใน GW${gw}`));
  let forecasts = 0;
  const matches = scheduled.matches.map(current => {
    const forecast = published.find(match => match.fixture === current.fixture && match.gw === current.gw &&
      match.home.team.team_code === current.home.team.team_code && match.away.team.team_code === current.away.team.team_code &&
      sameKickoff(match.kickoff_time, current.kickoff_time));
    if (forecast) { forecasts += 1; return forecast; }
    return current;
  });
  const clubFixtures = new Map<number, number[]>();
  for (const match of matches) for (const side of [match.home, match.away]) {
    const ids = clubFixtures.get(side.team.team_code) ?? [];
    ids.push(match.fixture); clubFixtures.set(side.team.team_code, ids);
  }
  let news = input.news;
  if (news?.demo) { news = null; warnings.push(say("Demo news excluded.", "ไม่ใช้ข่าวสมมติ")); }
  if (news?.roundup && (news.roundup.season !== run.season || news.roundup.gw !== gw)) {
    news = null;
    warnings.push(say("The news edition belongs to another gameweek; awaiting this GW's update.", "ชุดข่าวเป็นของเกมวีคอื่น รออัปเดตสำหรับ GW นี้"));
  }
  if (news && (!Number.isFinite(Date.parse(news.generated_at)) || Date.parse(news.generated_at) > now)) news = null;
  const freshRest = rest && rest.season === run.season && Number.isFinite(Date.parse(rest.as_of)) && Date.parse(rest.as_of) <= now ? rest : null;
  if (forecasts < matches.length) warnings.push(say(`${matches.length - forecasts} fixture(s) have no matching saved forecast; shown as —.`, `${matches.length - forecasts} คู่ไม่มีคาดการณ์ที่ตรงกับตารางปัจจุบัน แสดงเป็น —`));

  // One current-season cohort for the whole GW, including every DGW leg. Never
  // substitute forecast xP, archived form or rest-report availability for observed points.
  const historyBefore = Math.min(now, ...matches.flatMap(match => match.kickoff_time === null ? [] : [Date.parse(match.kickoff_time)]));
  const averages = new Map((input.actuals ?? []).filter(record => record.season === run.season).map(record => [record.code,
    averageObservedPointsPerAppearance(record.actuals.filter(row => row.gw < gw && Date.parse(row.kickoff_time) < historyBefore)),
  ]));
  const includesProvisional = [...averages.values()].some(value => value.includesProvisional);

  const restLabel = (row: PlayerRest | null): string => {
    if (!row) return say("rest unavailable for this fixture", "ยังไม่มีวันพักที่ตรงกับคู่นี้");
    const gap = row.rest_days === null || row.rest_hours === null ? say("rest unknown", "ไม่ทราบวันพัก")
      : say(`${row.rest_days}d (${row.rest_hours.toFixed(1)}h) gap`, `ห่าง ${row.rest_days} วัน (${row.rest_hours.toFixed(1)} ชม.)`);
    return `${gap}${row.last_appearance?.observed_team_code != null && row.last_appearance.observed_team_code !== row.team_code
      ? say("; last appearance for a previous club", "; นัดล่าสุดเป็นการเล่นให้สโมสรเดิม") : ""}`;
  };
  const newsLines = (match: MatchPreview, teamCode: number): string[] => {
    const stories = previewNews(news, match, roster, now).stories.filter(story => story.team_code === teamCode &&
      story.source_kind === "x" && SCOUT_POST.test(story.source_url) &&
      ["injury", "suspension", "squad", "press_conference"].includes(story.category) && story.published_at !== null &&
      Date.parse(story.published_at) >= now - NEWS_WINDOW && Date.parse(story.published_at) <= now &&
      (match.kickoff_time === null || Date.parse(story.published_at) < Date.parse(match.kickoff_time)));
    if (!stories.length) return [say("• No verified @FFScout update for this team in the last 7 days. Fitness unconfirmed.", "• ไม่มีอัปเดต @FFScout ที่ยืนยันตัวตนทีมได้ใน 7 วันล่าสุด ยังสรุปความฟิตไม่ได้")];
    return stories.flatMap(story => [
      // Preserve reviewed uncertainty/status lines. The browser neither classifies nor rewrites news.
      language === "th" && story.summary.th ? story.summary.th : `${language === "th" ? "[รอคำแปลไทย] " : ""}${story.summary.en}`,
      `@FFScout · ${stamp(story.published_at)}`,
    ]);
  };
  const lines = [say(`GW${gw} MATCHWEEK BRIEFING | THE COMET FPL`, `สรุปก่อนเกม GW${gw} | THE COMET FPL`),
    `${run.season} · ${matches.length} ${say("fixtures", "คู่")}`,
    say(`Forecast: ${stamp(asOf)}`, `คาดการณ์: ${stamp(asOf)}`),
    say(`News edition: ${stamp(news?.generated_at)} | Rest report: ${stamp(freshRest?.as_of)}`, `ชุดข่าว: ${stamp(news?.generated_at)} | ข้อมูลพัก: ${stamp(freshRest?.as_of)}`),
    say("Scores below are rounded goal averages, not exact-score picks.", "ตัวเลขสกอร์คือค่าเฉลี่ยประตูปัดเศษ ไม่ใช่คำทายสกอร์ที่แน่นอน"),
    say(`Key players: up to 5 per team by ${run.season} points per appearance before GW${gw}; fewer if history is unavailable.${includesProvisional ? " Includes provisional points." : ""}`,
      `นักเตะหลัก: สูงสุดทีมละ 5 คน ตามแต้มเฉลี่ยต่อนัดที่ลงเล่นในฤดูกาล ${run.season} ก่อน GW${gw} อาจน้อยกว่า 5 หากไม่มีประวัติ${includesProvisional ? " รวมแต้มที่ยังไม่ยืนยันผลสุดท้าย" : ""}`),
    say("Player (midweek minutes): 🟠 more than 45 · 🟡 1–45 · no symbol = zero or unknown minutes. (—) = midweek minutes unknown or did not play.",
      "นักเตะ (นาทีกลางสัปดาห์): 🟠 มากกว่า 45 · 🟡 1–45 · ไม่มีสัญลักษณ์ = 0 นาทีหรือไม่ทราบนาที (—) = ไม่ทราบนาทีกลางสัปดาห์ หรือไม่ได้ลงเล่น")];
  if (run.run_id.startsWith("DEMO-")) lines.unshift(say("DEMO — synthetic forecasts, not current predictions.", "DEMO — ข้อมูลคาดการณ์สมมติ ไม่ใช่ผลปัจจุบัน"));
  for (const [index, match] of matches.entries()) {
    lines.push("", `${index + 1}) ${match.home.team.team_name} (${rounded(match.home.forecast.lambda_for)}) - (${rounded(match.away.forecast.lambda_for)}) ${match.away.team.team_name}`,
      `${stamp(match.kickoff_time)} · ${say("Expected goals", "ค่าเฉลี่ยประตู")} ${decimal(match.home.forecast.lambda_for)} – ${decimal(match.away.forecast.lambda_for)}`);
    const doubleLegs = [match.home, match.away].flatMap(side => {
      const fixtures = clubFixtures.get(side.team.team_code)!;
      return fixtures.length > 1 ? [`${side.team.short_name} ${fixtures.indexOf(match.fixture) + 1}/${fixtures.length}`] : [];
    });
    if (doubleLegs.length) lines.push(`DGW · ${doubleLegs.join(" · ")}`);
    if (match.kickoff_time !== null && Date.parse(match.kickoff_time) <= now) lines.push(say("Kickoff has passed; this remains the saved pre-match forecast.", "ผ่านเวลาเตะแล้ว ตัวเลขนี้ยังเป็นคาดการณ์ก่อนเกมที่บันทึกไว้"));
    for (const [index, side] of [match.home, match.away].entries()) lines.push(
      "", `${side.team.short_name} ${say(`${index ? "away" : "home"} team news / press conference`, `${index ? "ทีมเยือน" : "เจ้าบ้าน"}: ข่าวทีม / แถลงข่าว`)}`,
      ...newsLines(match, side.team.team_code));
    const report = previewRest(freshRest, match, roster, now);
    for (const [sideIndex, side] of [match.home, match.away].entries()) {
      lines.push("", `${side.team.short_name} ${say(`${sideIndex ? "away" : "home"} rest & midweek minutes`, `${sideIndex ? "ทีมเยือน" : "เจ้าบ้าน"}: วันพักและนาทีกลางสัปดาห์`)}`);
      const rows = report.rows.filter(row => row.player.team_code === side.team.team_code && averages.get(row.player.code)?.pointsPerAppearance != null)
        .sort((a, b) => averages.get(b.player.code)!.pointsPerAppearance! - averages.get(a.player.code)!.pointsPerAppearance! || a.player.code - b.player.code)
        .slice(0, 5);
      const groups = new Map<string, string[]>();
      for (const row of rows) {
        const label = restLabel(row.rest), names = groups.get(label) ?? [];
        const minutes = row.rest?.midweek_nominal_minutes;
        const marker = row.rest && row.rest.midweek_appearances > 0 && typeof minutes === "number" && Number.isFinite(minutes) && minutes > 0
          ? minutes > 45 ? "🟠 " : "🟡 " : "";
        names.push(`${marker}${row.player.web_name} (${minutes == null ? "—" : minutes.toFixed(0)})`); groups.set(label, names);
      }
      if (!rows.length) lines.push(say("• Key-player ranking unavailable: no usable current-season points per appearance.", "• ยังจัดอันดับนักเตะหลักไม่ได้: ไม่มีแต้มเฉลี่ยต่อนัดที่ใช้ได้ในฤดูกาลนี้"));
      for (const [label, names] of groups) lines.push(`• ${label}: ${names.join(", ")}`);
      if (clubFixtures.get(side.team.team_code)!.indexOf(match.fixture) > 0 && rows.some(row => row.rest === null)) lines.push(
        say("Later DGW leg: rest will be updated after the earlier appearance is known; no assumed minutes or recovery.", "นัดหลังใน DGW: รอข้อมูลการลงเล่นนัดก่อนเพื่ออัปเดตวันพัก ไม่สมมตินาทีหรือการฟื้นตัว"));
    }
  }
  lines.push("", say(`Rest = UK calendar days and hours between witnessed kickoffs. Midweek = Mon–Thu UTC within the report's ${freshRest?.window_hours ?? "—"}h window; nominal club minutes, not FPL minutes. Coverage may be incomplete; unknown does not mean rested. National-team minutes are not captured.`,
    `วันพักนับตามวันที่อังกฤษและชั่วโมงระหว่างเวลาเตะที่มีหลักฐาน กลางสัปดาห์คือ จ.–พฤ. UTC ในช่วง ${freshRest?.window_hours ?? "—"} ชม. ของรายงาน นาทีสโมสรเป็นเวลาตามนาฬิกาเกม ไม่ใช่นาที FPL ข้อมูลอาจไม่ครบ ไม่ทราบไม่ได้แปลว่าได้พัก และยังไม่มีนาทีทีมชาติ`),
    say("News comes from selected @FFScout reports, not confirmed lineups or proof every conference is complete. Reports may be newer than the saved forecast.", "ข่าวมาจากรายงาน @FFScout ที่เลือก ไม่ใช่การยืนยันตัวจริงหรือยืนยันว่าแถลงครบทุกทีม ข่าวอาจใหม่กว่าชุดคาดการณ์"),
    ...warnings, "https://www.thecometfpl.com/#summary");
  return { text: lines.join("\n"), fixtures: matches.length, forecasts, warnings };
}
