import { useEffect, useRef, useState } from "react";
import { Copy, Share2 } from "lucide-react";
import type { PublicNewsFeed } from "@/data/newsFeed";
import { newsRoundupText, shareNewsRoundup, type NewsLanguage } from "@/lib/newsShare";

/** Show reviewed updates on publication; deadline metadata never gates news. */
export function NewsRoundup({ feed, language }: { feed: PublicNewsFeed; language: NewsLanguage }) {
  const [now, setNow] = useState(Date.now);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [feedback, setFeedback] = useState<{ text: string; action: "copied" | "shared" | "cancelled" | "manual" } | null>(null);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  const schedule = feed.roundup;
  const thai = language === "th";
  const format = (value: string) => new Intl.DateTimeFormat(thai ? "th-TH" : "en-GB", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
  }).format(new Date(value)) + " UTC";
  const fresh = now - Date.parse(feed.generated_at) <= 24 * 3600_000;
  const text = newsRoundupText(feed, language);
  const act = async (share: boolean) => {
    try {
      if (share) setFeedback({ text, action: await shareNewsRoundup(text) });
      else { await navigator.clipboard.writeText(text); setFeedback({ text, action: "copied" }); }
    } catch {
      textarea.current?.focus();
      textarea.current?.select();
      setFeedback({ text, action: "manual" });
    }
  };
  return <section aria-label={thai ? "สรุปข่าวล่าสุด" : "Latest news roundup"} className="comet-glass mt-5 rounded-2xl border p-5">
    <h2 className="text-lg font-semibold">{thai ? "สรุปข่าวล่าสุด" : "Latest news roundup"}</h2>
    <p className="mt-2 text-sm text-muted-foreground">{thai
      ? "สรุปข่าวที่ตรวจแล้วจากแหล่งข่าวที่เลือก ไม่ใช่การยืนยันว่าแถลงข่าวครบทุกทีม"
      : "Reviewed reports from selected sources. This does not establish that every club has completed its press conference."}</p>
    <p className="mt-2 text-sm">{thai ? "แสดงข่าวทันทีที่ตรวจและเผยแพร่แล้ว" : "Updates appear as soon as they are reviewed and published."}</p>
    <p className="mt-1 text-xs text-muted-foreground">{thai ? "เผยแพร่เมื่อ" : "Published"}: {format(feed.generated_at)}</p>
    {schedule && <p className="mt-1 text-xs text-muted-foreground">{schedule.season} GW{schedule.gw} · {thai ? "เดดไลน์" : "Deadline"}: {format(schedule.deadline_at)}</p>}
    {!fresh && <p role="status" className="mt-2 text-sm text-amber-700 dark:text-amber-300">{thai ? "ชุดข่าวเกิน 24 ชั่วโมงแล้ว รอข่าวที่ตรวจใหม่" : "This edition is over 24 hours old. Awaiting newly reviewed reports."}</p>}
    <div className="mt-4 grid gap-2 text-sm sm:grid-cols-3" aria-label={thai ? "ความหมายของสถานะ" : "Availability legend"}>
      <p className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-red-900 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">❌ {thai ? "ไม่พร้อมแน่นอน" : "Unavailable"}</p>
      <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200">🟨 {thai ? "ยังไม่แน่ชัด / รอเช็กฟิต" : "Doubtful / uncertain"}</p>
      <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-200">✅ {thai ? "ยืนยันว่าฟิต / พร้อม" : "Confirmed fit / available"}</p>
    </div>
    <label className="mt-4 block text-sm font-medium" htmlFor="all-team-roundup">{thai ? "อ่านสรุปข่าวที่ตรวจแล้ว" : "Read the reviewed roundup"} ({feed.stories.length})</label>
    <p id="roundup-scope" className="mt-1 text-xs text-muted-foreground">{thai ? "รวมทุกทีมในชุดข่าว ไม่เปลี่ยนตามตัวกรองด้านล่าง · ข่าวที่ไม่ระบุสถานะยังแสดงตามต้นฉบับ" : "Includes every published team report, regardless of the filters below. Reports without status labels retain their reviewed wording."}</p>
    <textarea id="all-team-roundup" ref={textarea} aria-label={thai ? "ข้อความสรุปข่าวทุกทีม" : "All-team roundup text"} aria-describedby="roundup-scope" value={text} readOnly rows={18} spellCheck={false} className="mt-3 block w-full resize-y rounded-xl border bg-background p-4 text-sm leading-7 text-foreground focus-visible:outline-2 focus-visible:outline-offset-2" />
    <div className="mt-3 flex flex-wrap items-center gap-3">
      <button type="button" disabled={!feed.stories.length} onClick={() => { void act(false); }} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2"><Copy className="size-4" aria-hidden="true" />{thai ? "คัดลอกสรุปทั้งหมด" : "Copy all teams"}</button>
      <button type="button" disabled={feed.demo || !feed.stories.length} onClick={() => { void act(true); }} className="inline-flex min-h-11 items-center gap-2 rounded-lg border bg-background px-4 py-2 text-sm font-semibold disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2"><Share2 className="size-4" aria-hidden="true" />{thai ? "แชร์สรุปทั้งหมด" : "Share all teams"}</button>
      <p className="text-xs text-muted-foreground">{thai ? "รวมชื่อ THE COMET FPL ลิงก์เว็บไซต์ และแหล่งข่าว" : "Includes THE COMET FPL, our website link and sources."}</p>
    </div>
    {feedback?.text === text && <p role="status" className="mt-3 text-sm text-muted-foreground">{feedback.action === "copied" ? thai ? "คัดลอกสรุปทุกทีมแล้ว" : "All-team roundup copied." : feedback.action === "shared" ? thai ? "แชร์สรุปแล้ว" : "Roundup shared." : feedback.action === "cancelled" ? thai ? "ยกเลิกการแชร์แล้ว" : "Sharing cancelled." : thai ? "เลือกข้อความทั้งหมดแล้ว กรุณาคัดลอกด้วยคำสั่งของอุปกรณ์" : "All text selected. Use your device’s copy command."}</p>}
  </section>;
}
