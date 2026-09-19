import type { SdpStatsData } from "@/data/sdpStats";
import type { MatchPreview } from "./matchPreview";
import { metricAssumptions, metricCorrections, metricSupplements, metricValue, selectSdpEntities } from "./sdpStats";

export interface GwBriefingInput {
  matches: readonly MatchPreview[];
  gw: number;
  language: "en" | "th";
  stats: SdpStatsData | null;
  exportCreatedAt: string | null;
  expectedFixtureIds?: readonly number[];
}
export interface GwBriefing { text: string; coverage: string; warnings: string[] }

const instant = (value: string | null) => value !== null && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? Date.parse(value) : NaN;
const stamp = (value: string | null) => Number.isFinite(instant(value)) ? new Date(value!).toISOString().slice(0, 16).replace("T", " ") + " UTC" : null;
const number = (value: number | null) => value !== null && Number.isFinite(value) && value >= 0 ? value.toFixed(2) : "—";

/** Deterministic source-bound prose. Never creates a scoreline, winner or probability. */
export function buildGwBriefing({ matches, gw, language, stats, exportCreatedAt, expectedFixtureIds }: GwBriefingInput): GwBriefing {
  const say = (en: string, th: string) => language === "th" ? th : en;
  const warnings: string[] = [];
  const unavailable = (reason: string): GwBriefing => ({ text: "", coverage: reason, warnings: [reason] });
  if (!Number.isInteger(gw) || gw < 1 || gw > 38) return unavailable(say("Invalid gameweek.", "เกมวีคไม่ถูกต้อง"));
  if (new Set(matches.map(match => JSON.stringify([match.run_id, match.season, instant(match.as_of)]))).size > 1 ||
    matches.some(match => !Number.isFinite(instant(match.as_of)))) return unavailable(say("Select one forecast run, season and cutoff.", "เลือกชุดคาดการณ์ ฤดูกาล และเวลาตัดข้อมูลเดียวกัน"));
  const selected = matches.filter(match => match.gw === gw).sort((a, b) =>
    (a.kickoff_time === null ? Infinity : instant(a.kickoff_time)) - (b.kickoff_time === null ? Infinity : instant(b.kickoff_time)) || a.fixture - b.fixture);
  if (!selected.length) return unavailable(say(`No published fixtures for GW${gw}.`, `ไม่มีคู่แข่งที่เผยแพร่สำหรับ GW${gw}`));
  const fixtureIds = new Set(selected.map(match => match.fixture));
  if (fixtureIds.size !== selected.length || selected.some(match => !Number.isSafeInteger(match.fixture) || match.fixture <= 0)) return unavailable(say("Published fixture identities are duplicated or invalid.", "รหัสคู่แข่งที่เผยแพร่ซ้ำหรือไม่ถูกต้อง"));
  const first = selected[0];
  let coverage = say(`${selected.length} published fixtures; full-GW coverage is not established.`, `${selected.length} คู่ที่เผยแพร่ ยังไม่ยืนยันว่าครบทั้งเกมวีค`);
  if (expectedFixtureIds !== undefined) {
    const expected = new Set(expectedFixtureIds);
    if (expected.size !== expectedFixtureIds.length || expectedFixtureIds.some(id => !Number.isSafeInteger(id) || id <= 0)) {
      warnings.push(say("The supplied fixture inventory is invalid; completeness is unavailable.", "รายการคู่แข่งสำหรับตรวจความครบถ้วนไม่ถูกต้อง จึงยืนยันความครบไม่ได้"));
    } else {
      const missing = [...expected].filter(id => !fixtureIds.has(id)).length;
      const extra = [...fixtureIds].filter(id => !expected.has(id)).length;
      coverage = missing === 0 && extra === 0
        ? say(`${selected.length}/${expected.size} fixtures match the supplied GW inventory.`, `ครอบคลุม ${selected.length}/${expected.size} คู่ ตรงกับรายการ GW ที่ใช้ตรวจสอบ`)
        : say(`${selected.length - extra}/${expected.size} fixtures match the supplied GW inventory; ${missing} missing, ${extra} unmatched.`, `ตรงกับรายการ GW ${selected.length - extra}/${expected.size} คู่ ขาด ${missing} คู่ และไม่ตรงรายการ ${extra} คู่`);
      if (missing || extra) warnings.push(say("The fixture sets differ; this is not a complete GW briefing.", "รายการคู่แข่งไม่ตรงกัน บทวิเคราะห์นี้จึงยังไม่ครบทั้งเกมวีค"));
    }
  }

  const earliestKickoff = Math.min(...selected.map(match => instant(match.kickoff_time)));
  let usableStats = stats;
  if (!stats) warnings.push(say("Observed SDP statistics are unavailable in this published generation.", "ไม่มีสถิติ SDP ที่สังเกตได้ในชุดข้อมูลเผยแพร่นี้"));
  else if (!Number.isFinite(instant(stats.as_of))) {
    usableStats = null;
    warnings.push(say("The statistics publication time is invalid; observed context is unavailable.", "เวลาเผยแพร่สถิติไม่ถูกต้อง จึงไม่แสดงข้อมูลย้อนหลัง"));
  } else if (!Number.isFinite(earliestKickoff)) {
    usableStats = null;
    warnings.push(say("A selected kickoff is unknown; an earlier-match statistics window cannot be established.", "ยังไม่ทราบเวลาเตะบางคู่ จึงกำหนดขอบเขตสถิติก่อนเกมไม่ได้"));
  }
  const teamCodes = new Set(selected.flatMap(match => [match.home.team.team_code, match.away.team.team_code]));
  let eligibleRows = usableStats?.team_matches.filter(row => row.season === first.season && row.gw >= 1 && row.gw < gw &&
    teamCodes.has(row.team_code) && !fixtureIds.has(row.fixture) &&
    (!Number.isFinite(instant(row.kickoff_time)) || instant(row.kickoff_time) < earliestKickoff)) ?? [];
  if (usableStats && eligibleRows.some(row => !Number.isSafeInteger(row.fixture) || row.fixture <= 0 || !Number.isInteger(row.gw) ||
    !["FINAL", "PROVISIONAL", "UNAVAILABLE"].includes(row.status) || !Number.isFinite(instant(row.kickoff_time)) ||
    !Number.isFinite(instant(row.known_at)) || instant(row.known_at) > instant(usableStats!.as_of) || instant(row.kickoff_time) >= instant(usableStats!.as_of))) {
    usableStats = null;
    warnings.push(say("Prior-match statistics have invalid identity, status or source chronology; observed context is unavailable.", "สถิติแมตช์ก่อนหน้ามีรหัส สถานะ หรือลำดับเวลาของแหล่งข้อมูลไม่ถูกต้อง จึงไม่แสดงข้อมูลย้อนหลัง"));
  }
  eligibleRows = usableStats ? eligibleRows.filter(row => instant(row.kickoff_time) < earliestKickoff) : [];
  if (new Set(eligibleRows.map(row => JSON.stringify([row.season, row.fixture, row.team_code]))).size !== eligibleRows.length) {
    usableStats = null;
    eligibleRows = [];
    warnings.push(say("Duplicate SDP club-fixture records prevent a reliable observed match count; observed context is unavailable.", "ระเบียน SDP ของสโมสรและแมตช์ซ้ำกัน จึงนับแมตช์ย้อนหลังอย่างถูกต้องไม่ได้และไม่แสดงข้อมูลย้อนหลัง"));
  }
  if (usableStats) {
    if (usableStats.source_status.notes.some(note => /^DEMO\b/i.test(note))) warnings.push(say("DEMO: synthetic statistics for local interface review only; not real football evidence.", "DEMO: สถิติสมมติสำหรับตรวจหน้าจอในเครื่องเท่านั้น ไม่ใช่หลักฐานการแข่งขันจริง"));
    const unwitnessed: number[] = [];
    for (const priorGw of [...new Set(eligibleRows.map(row => row.gw))].sort((a, b) => a - b)) {
      const receipts = usableStats.gameweeks.filter(row => row.season === first.season && row.gw === priorGw);
      if (receipts.length !== 1 || typeof receipts[0].finished !== "boolean") unwitnessed.push(priorGw);
      else if (!receipts[0].finished) warnings.push(say(`Prior GW${priorGw} is not officially finished (${receipts[0].fixtures_completed}/${receipts[0].fixtures_total} fixtures ended).`, `GW${priorGw} ก่อนหน้ายังไม่ปิดอย่างเป็นทางการ (จบแล้ว ${receipts[0].fixtures_completed}/${receipts[0].fixtures_total} คู่)`));
    }
    if (unwitnessed.length) warnings.push(say(`Official GW completion is not witnessed for ${unwitnessed.map(value => `GW${value}`).join(", ")}; ended match rows do not establish it.`, `ไม่มีหลักฐานยืนยันการปิดเกมวีคอย่างเป็นทางการสำหรับ ${unwitnessed.map(value => `GW${value}`).join(", ")} แมตช์ที่จบแล้วไม่ใช่หลักฐานว่าเกมวีคปิดครบ`));
  }
  const entities = selectSdpEntities(eligibleRows, "team", {
    season: first.season, from: 1, to: gw - 1, team: "all", venue: "all", recent: "all", search: "", position: "all", minMinutes: 0,
  });
  const observed = new Map<number, string>();
  const teamContext = (teamCode: number, teamName: string): string => {
    const cached = observed.get(teamCode);
    if (cached !== undefined) return cached;
    const rows = entities.find(entity => entity.teamCode === teamCode)?.rows ?? [];
    if (!rows.length) {
      const result = say(`${teamName}: no eligible earlier same-season matches.`, `${teamName}: ไม่มีข้อมูลแมตช์ก่อนหน้าในฤดูกาลเดียวกัน`);
      observed.set(teamCode, result);
      return result;
    }
    const values = ["expected_goals", "expected_goals_allowed", "shots_on_target"].map((key, index) => {
      const label = ["xG", "xGA", "SOT"][index];
      const catalog = usableStats!.metrics.filter(metric => metric.source === "sdp" && metric.scope === "team" && metric.key === key);
      if (catalog.length !== 1 || !catalog[0].verified_semantics) {
        warnings.push(say(`${teamName} ${label}: no uniquely verified SDP metric.`, `${teamName} ${label}: ไม่มีนิยามสถิติ SDP ที่ยืนยันได้เพียงรายการเดียว`));
        return `${label} —`;
      }
      const metric = catalog[0];
      const corrections = metricCorrections(rows, metric).length;
      const assumptions = metricAssumptions(rows, metric).length;
      const supplements = metricSupplements(rows, metric).length;
      if (corrections || assumptions || supplements) {
        warnings.push(say(`${teamName} ${label} omitted: ${corrections} display corrections, ${assumptions} assumptions, ${supplements} FPL supplements.`, `${teamName} งด ${label}: มีการแก้ค่าหน้าจอ ${corrections} รายการ ข้อสมมติ ${assumptions} รายการ และค่าเสริม FPL ${supplements} รายการ`));
        return `${label} —`;
      }
      if (rows.some(row => row.sdp[key] != null && (!Number.isFinite(row.sdp[key]) || row.sdp[key]! < 0 || key === "shots_on_target" && !Number.isSafeInteger(row.sdp[key])))) {
        warnings.push(say(`${teamName} ${label}: invalid raw SDP measurements; no average is shown.`, `${teamName} ${label}: ค่าสถิติ SDP ดิบไม่ถูกต้อง จึงไม่แสดงค่าเฉลี่ย`));
        return `${label} —`;
      }
      const value = metricValue(rows, metric, "per_match");
      if (value.value === null) warnings.push(say(`${teamName} ${label}: ${value.measured}/${value.matches} matches measured; no partial average is shown.`, `${teamName} ${label}: วัดได้ ${value.measured}/${value.matches} แมตช์ จึงไม่แสดงค่าเฉลี่ยที่ข้อมูลไม่ครบ`));
      return `${label} ${number(value.value)}`;
    });
    const provisional = rows.filter(row => row.status === "PROVISIONAL").length;
    const range = `GW${Math.min(...rows.map(row => row.gw))}–${Math.max(...rows.map(row => row.gw))}`;
    const result = say(`${teamName}: ${values.join(", ")} per match (${rows.length} recorded matches, ${range}${provisional ? `; ${provisional} provisional` : ""}).`, `${teamName}: ${values.join(", ")} ต่อแมตช์ (ข้อมูล ${rows.length} แมตช์ ${range}${provisional ? `; ${provisional} แมตช์ยังชั่วคราว` : ""})`);
    observed.set(teamCode, result);
    return result;
  };

  const lines = [say(`GW${gw} | THE COMET FPL`, `สรุป GW${gw} | THE COMET FPL`), "https://www.thecometfpl.com", `${first.season} · ${coverage}`,
    say(`Model forecast cutoff: ${stamp(first.as_of)}`, `โมเดลตัดข้อมูล ณ ${stamp(first.as_of)}`)];
  if (exportCreatedAt !== null) lines.push(say(`Dashboard export: ${stamp(exportCreatedAt) ?? "unavailable"}`, `ชุดข้อมูลแดชบอร์ด: ${stamp(exportCreatedAt) ?? "ไม่ทราบเวลา"}`));
  if (usableStats) lines.push(
    say(`SDP statistics publication: ${stamp(usableStats.as_of)}; latest retained SDP capture: ${stamp(usableStats.source_status.latest_sdp_known_at) ?? "unavailable"}.`, `เผยแพร่สถิติ SDP: ${stamp(usableStats.as_of)}; เก็บข้อมูล SDP ล่าสุด: ${stamp(usableStats.source_status.latest_sdp_known_at) ?? "ไม่ทราบเวลา"}`),
    say(`Observed context uses recorded ${first.season} matches in earlier GWs, before ${stamp(new Date(earliestKickoff).toISOString())}. These are current retained reports, not a historical pre-deadline snapshot.`, `สถิติย้อนหลังใช้แมตช์ที่บันทึกไว้ในฤดูกาล ${first.season} จาก GW ก่อนหน้า และเตะก่อน ${stamp(new Date(earliestKickoff).toISOString())} เป็นข้อมูลที่เก็บไว้ปัจจุบัน ไม่ใช่หลักฐานที่ตรึงก่อนเดดไลน์ในอดีต`),
  );
  for (const [index, match] of selected.entries()) {
    const home = match.home.team, away = match.away.team;
    lines.push("", `${index + 1}. ${home.team_name} v ${away.team_name}`, say(`Published model expected goals: ${home.short_name} ${number(match.home.forecast.lambda_for)}; ${away.short_name} ${number(match.away.forecast.lambda_for)}.`, `ค่าเฉลี่ยประตูที่โมเดลคาด: ${home.short_name} ${number(match.home.forecast.lambda_for)}; ${away.short_name} ${number(match.away.forecast.lambda_for)}`));
    if (usableStats) lines.push(`${teamContext(home.team_code, home.short_name)} ${teamContext(away.team_code, away.short_name)}`);
  }
  lines.push("", say("Model expected goals are means, not predicted scores or win probabilities. Observed xG/xGA describe chances created/conceded; SOT is shots on target. — means unavailable.", "ค่าเฉลี่ยประตูของโมเดลไม่ใช่สกอร์ทายหรือโอกาสชนะ สถิติ xG/xGA แสดงคุณภาพโอกาสที่สร้าง/เสีย ส่วน SOT คือยิงตรงกรอบ เครื่องหมาย — คือไม่มีข้อมูล"));
  const uniqueWarnings = [...new Set(warnings)];
  if (uniqueWarnings.length) lines.push("", say("Data notes:", "หมายเหตุข้อมูล:"), ...uniqueWarnings.map(warning => `• ${warning}`));
  return { text: lines.join("\n"), coverage, warnings: uniqueWarnings };
}
