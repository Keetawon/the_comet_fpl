/** Local UI fixture only. Not a capture, publication, source claim or model input. */
import { useState } from "react";
import { CalendarClock, Check, ChevronDown, Clock3, Radio } from "lucide-react";
import { NewsFeed, type NewsPreview } from "@/components/NewsFeed";
import type { NewsStory, PublicNewsFeed } from "@/data/newsFeed";
import type { NewsLanguage } from "@/lib/newsShare";

const simulatedAt = "2026-09-25T11:45:00Z";
const schedule = [
  { code: 3, club: "Arsenal", tag: "ARS", time: "2026-09-25T08:00:00Z", status: "received" },
  { code: 36, club: "Brighton", tag: "BHA", time: "2026-09-25T08:00:00Z", status: "received" },
  { code: 91, club: "Bournemouth", tag: "BOU", time: "2026-09-25T08:00:00Z", status: "received" },
  { code: 6, club: "Spurs", tag: "TOT", time: "2026-09-25T11:00:00Z", status: "waiting" },
  { code: 11, club: "Everton", tag: "EVE", time: "2026-09-25T12:30:00Z", status: "scheduled" },
  { code: 8, club: "Chelsea", tag: "CHE", time: "2026-09-25T14:30:00Z", status: "scheduled" },
] as const;

function story(index: number, code: number, club: string, category: NewsStory["category"], title: NewsStory["title"], summary: NewsStory["summary"]): NewsStory {
  return {
    id: String(index).repeat(64), source_id: "simulated_ffscout", source_name: "FFScout format · SIMULATION",
    source_kind: "x", source_record_id: String(index), source_url: `https://x.com/FFScout/status/${index}`,
    source_sha256: "0".repeat(64), published_at: `2026-09-25T09:${index}0:00Z`, known_at: simulatedAt,
    season: "2026-27", team_code: code, team_name: club, player_code: null, player_name: null,
    category, title, summary, rendering: "source_text", ai_model: null, summarized_at: null,
  };
}

const previewFeed: PublicNewsFeed = {
  schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", demo: true,
  generated_at: simulatedAt,
  sources: [{ source_id: "simulated_ffscout", source_name: "FFScout format · SIMULATION", source_kind: "x", status: "disabled", last_checked_at: null, last_success_at: null, message: "Local synthetic fixture. No X or GPT request was made. All displayed times and updates are invented for this preview." }],
  stories: [
    story(1, 36, "Brighton", "injury", {
      en: "BRIGHTON | A late fitness check, not a confirmed return",
      th: "ไบรท์ตัน | รอประเมินความพร้อม ยังไม่ยืนยันการกลับมา",
    }, {
      en: "Sample: a winger has returned to part of training but still needs a final assessment. The manager has not confirmed whether he will be in the squad.\n\nTreat this as a pending update, not a confirmed starter.\n#FPL | #BHAFC",
      th: "ตัวอย่าง: ปีกของทีมกลับมาซ้อมได้บางส่วน แต่ยังต้องประเมินอีกครั้ง ผู้จัดการทีมยังไม่ยืนยันว่าจะมีชื่อในทีมวันแข่ง\n\nยังเป็นข่าวที่ต้องติดตาม ไม่ใช่การยืนยันตัวจริง\n#FPL | #BHAFC",
    }),
    story(2, 3, "Arsenal", "squad", {
      en: "ARSENAL | Back in training; selection still open",
      th: "อาร์เซนอล | กลับมาซ้อมแล้ว แต่ยังไม่ยืนยันการลงสนาม",
    }, {
      en: "Sample: a defender has completed team training. The manager says he will assess the squad before choosing his XI; no starting place has been promised.\n#FPL | #ARS",
      th: "ตัวอย่าง: กองหลังกลับมาซ้อมกับทีมได้ครบ ผู้จัดการทีมจะประเมินขุมกำลังก่อนเลือก 11 ตัวจริง และยังไม่รับรองตำแหน่งตัวจริง\n#FPL | #ARS",
    }),
    story(3, 91, "Bournemouth", "press_conference", {
      en: "BOURNEMOUTH | Workload discussed, no XI announced",
      th: "บอร์นมัธ | พูดถึงภาระการลงเล่น ยังไม่ประกาศ 11 ตัวจริง",
    }, {
      en: "Sample: the manager says recovery after the midweek fixture will inform team selection. He has not named the players who may be rested.\n#FPL | #AFCB",
      th: "ตัวอย่าง: ผู้จัดการทีมจะพิจารณาการฟื้นตัวจากเกมกลางสัปดาห์ก่อนจัดทีม โดยยังไม่ได้ระบุว่าจะพักผู้เล่นคนใด\n#FPL | #AFCB",
    }),
  ],
};

function Briefing({ language }: { language: NewsLanguage }) {
  const thai = language === "th";
  return <div className="mt-4 flex flex-col gap-4 rounded-2xl border border-cyan-200 bg-cyan-50/80 p-5 sm:flex-row sm:items-center sm:justify-between dark:border-cyan-900 dark:bg-cyan-950/40">
    <div><p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-cyan-800 dark:text-cyan-200"><Radio className="size-4" aria-hidden="true" />{thai ? "จำลองรอบข่าวก่อนเดดไลน์" : "Pre-deadline briefing · simulation"}</p>
      <h2 className="mt-2 text-lg font-semibold">{thai ? "วันศุกร์: ตามข่าวให้ครบก่อนจัดทีม" : "Friday: catch up before picking your XI"}</h2>
      <p className="mt-1 text-sm text-muted-foreground">{thai ? "ตัวอย่างเวลา 25 ก.ย. 2026 · 12:45 อังกฤษ / 18:45 ไทย" : "Example clock: 25 Sep 2026 · 12:45 UK / 18:45 Thailand"}</p></div>
    <div className="flex shrink-0 items-center gap-4 border-t border-cyan-200 pt-3 sm:border-t-0 sm:border-l sm:pt-0 sm:pl-5 dark:border-cyan-900">
      <p className="text-3xl font-semibold tabular-nums">3<span className="text-lg font-normal text-muted-foreground"> / 6</span></p>
      <div><p className="text-sm font-medium">{thai ? "ทีมที่มีสรุปแล้ว" : "Club summaries received"}</p><p className="mt-1 text-xs text-muted-foreground">{thai ? "1 รอสรุป · 2 ยังไม่ถึงเวลา" : "1 awaiting recap · 2 scheduled"}</p></div>
    </div>
  </div>;
}

function PressSchedule({ language, selectedTeam }: { language: NewsLanguage; selectedTeam: string }) {
  const [zone, setZone] = useState<"Europe/London" | "Asia/Bangkok">("Europe/London");
  const thai = language === "th";
  const rows = schedule.filter(row => !selectedTeam || String(row.code) === selectedTeam);
  const statuses = thai ? { received: "มีสรุปแล้ว", waiting: "รอสรุป", scheduled: "ยังไม่ถึงเวลา" } : { received: "Recap received", waiting: "Awaiting recap", scheduled: "Scheduled" };
  return <section className="comet-glass rounded-2xl border p-4 sm:p-5" aria-label={thai ? "ตารางแถลงข่าวจำลอง" : "Simulated press-conference schedule"}>
    <div className="flex items-center gap-2"><CalendarClock className="size-4 text-cyan-700 dark:text-cyan-300" aria-hidden="true" /><h2 className="text-sm font-semibold">{thai ? "ตารางแถลงข่าว" : "Press-conference schedule"}</h2></div>
    <p className="mt-2 text-xs text-muted-foreground">{thai ? "ศุกร์ 25 ก.ย. · เวลาและสถานะสมมติ" : "Fri 25 Sep · invented times & statuses"}</p>
    <details className="group mt-3" open>
      <summary className="flex min-h-11 cursor-pointer items-center justify-between gap-3 text-xs font-medium">{thai ? "ดู / ย่อตาราง" : "Show / hide schedule"}<ChevronDown className="size-4 transition-transform group-open:rotate-180" aria-hidden="true" /></summary>
      <label className="mt-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">{thai ? "เขตเวลา" : "Time zone"}<select className="min-h-11 rounded-lg border bg-background px-2 text-foreground" value={zone} onChange={event => setZone(event.target.value as typeof zone)}><option value="Europe/London">UK · BST</option><option value="Asia/Bangkok">ไทย · ICT</option></select></label>
      <ol className="mt-3 divide-y">{rows.map(row => <li key={row.code} className="flex items-center gap-3 py-3">
        <time dateTime={row.time} className="w-11 shrink-0 text-sm font-medium tabular-nums">{new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: zone }).format(new Date(row.time))}</time>
        <div className="min-w-0 flex-1"><p className="text-sm font-semibold">{row.club}</p><p className={`mt-1 flex items-center gap-1.5 text-xs ${row.status === "received" ? "text-teal-700 dark:text-teal-300" : row.status === "waiting" ? "text-amber-700 dark:text-amber-300" : "text-muted-foreground"}`}>{row.status === "received" ? <Check className="size-3" aria-hidden="true" /> : <Clock3 className="size-3" aria-hidden="true" />}{statuses[row.status]}</p></div>
        <span className="text-[10px] font-semibold text-muted-foreground">{row.tag}</span>
      </li>)}</ol>
    </details>
    <p className="mt-3 border-t pt-3 text-xs leading-relaxed text-muted-foreground">{thai ? "ตารางเวลาไม่ใช่ข่าวความพร้อมทีม การยังไม่มีสรุปไม่ได้แปลว่านักเตะทุกคนพร้อมลงสนาม" : "A timetable is not a squad update. No recap does not mean every player is available."}</p>
  </section>;
}

const preview: NewsPreview = {
  feed: previewFeed,
  clubs: schedule.map(row => [row.code, row.club]),
  header: language => <Briefing language={language} />,
  sidebar: (language, selectedTeam) => <PressSchedule language={language} selectedTeam={selectedTeam} />,
};

export default function LocalNewsPreview() {
  return <NewsFeed preview={preview} />;
}
