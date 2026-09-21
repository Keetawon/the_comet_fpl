/** Local UI fixture only. Not a capture, publication, source claim or model input. */
import { useMemo, useState } from "react";
import { CalendarClock, Check, ChevronDown, Clock3 } from "lucide-react";
import { NewsFeed, type NewsPreview } from "@/components/NewsFeed";
import type { NewsStory, PublicNewsFeed } from "@/data/newsFeed";
import type { NewsLanguage } from "@/lib/newsShare";
import NewsRoundupPreview from "./NewsRoundupPreview";

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

function PressSchedule({ language, selectedTeam, asOf }: { language: NewsLanguage; selectedTeam: string; asOf: string }) {
  const [zone, setZone] = useState<"Europe/London" | "Asia/Bangkok">("Europe/London");
  const thai = language === "th";
  const rows = schedule.filter(row => !selectedTeam || String(row.code) === selectedTeam).map(row => ({ ...row,
    status: row.status === "received" ? "received" : Date.parse(row.time) <= Date.parse(asOf) ? "waiting" : "scheduled",
  } as const));
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

const scenarios = {
  collecting: { asOf: simulatedAt, completedAt: null },
  conferences: { asOf: "2026-09-25T15:05:00Z", completedAt: "2026-09-25T15:00:00Z" },
  deadline: { asOf: "2026-09-26T07:00:00Z", completedAt: null },
} as const;
type Scenario = keyof typeof scenarios;
const clubs = schedule.map(row => [row.code, row.club] as const);

export default function LocalNewsPreview() {
  const [scenario, setScenario] = useState<Scenario>("conferences");
  const preview = useMemo<NewsPreview>(() => {
    const { asOf, completedAt } = scenarios[scenario];
    const feed = { ...previewFeed, generated_at: asOf };
    return {
      feed, clubs,
      header: language => <>
        <label className="mt-4 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">{language === "th" ? "จำลองช่วงเวลา" : "Preview timing"}
          <select value={scenario} onChange={event => setScenario(event.target.value as Scenario)} className="min-h-11 max-w-full rounded-lg border bg-background px-3 text-sm text-foreground">
            <option value="collecting">{language === "th" ? "ระหว่างรอข่าว" : "Still collecting"}</option>
            <option value="conferences">{language === "th" ? "หลังแถลงครบทุกทีม" : "All conferences finished"}</option>
            <option value="deadline">{language === "th" ? "ก่อนเดดไลน์ 3 ชั่วโมง" : "Three hours before deadline"}</option>
          </select>
        </label>
        <NewsRoundupPreview key={scenario + language} language={language} feed={feed} clubs={clubs} asOf={asOf} deadline="2026-09-26T10:00:00Z" allConferencesEndedAt={completedAt} />
      </>,
      sidebar: (language, selectedTeam) => <PressSchedule language={language} selectedTeam={selectedTeam} asOf={asOf} />,
    };
  }, [scenario]);
  return <NewsFeed preview={preview} />;
}
