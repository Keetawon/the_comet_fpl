/** Synthetic design preview; no scheduler, provider call or public publication. */
import { useRef, useState } from "react";
import { ClipboardCheck, Copy, FileText, Share2 } from "lucide-react";
import type { PublicNewsFeed } from "@/data/newsFeed";
import type { NewsLanguage } from "@/lib/newsShare";

interface Props {
  language: NewsLanguage;
  feed: PublicNewsFeed;
  clubs: readonly (readonly [number, string])[];
  asOf: string;
  deadline: string;
}

const dateTime = (value: string, language: NewsLanguage) => new Intl.DateTimeFormat(language === "th" ? "th-TH" : "en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: language === "th" ? "Asia/Bangkok" : "Europe/London",
}).format(new Date(value)) + (language === "th" ? " ICT" : " UK");

export default function NewsRoundupPreview({ language, feed, clubs, asOf, deadline }: Props) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [feedback, setFeedback] = useState<"copied" | "manual" | null>(null);
  const thai = language === "th";
  const now = Date.parse(asOf);
  const stories = feed.stories.filter(story => Date.parse(story.known_at) <= now &&
    (story.published_at === null || Date.parse(story.published_at) <= now) &&
    (story.summarized_at === null || Date.parse(story.summarized_at) <= now));
  const orderedClubs = [...clubs].sort((a, b) => a[1].localeCompare(b[1], "en"));
  const received = orderedClubs.filter(([code]) => stories.some(story => story.team_code === code)).length;
  const sourceText = (value: string) => value.replace(/^\s*#FPL\s*\|[^\n]*$/gm, "").trim();
  const text = [
    thai ? "🧪 ตัวอย่างสรุปข่าวสมมติ — ไม่ใช่ข่าวจริง" : "🧪 SIMULATED NEWS ROUNDUP — NOT REAL NEWS",
    thai ? "THE COMET · สรุปข่าวก่อนเดดไลน์" : "THE COMET · Pre-deadline team news",
    `${thai ? "เดดไลน์สมมติ" : "Example deadline"}: ${dateTime(deadline, language)}`,
    `${thai ? "ข้อมูลถึง" : "As of"}: ${dateTime(asOf, language)}`,
    `${thai ? "มีสรุป" : "Recaps available"}: ${received}/${orderedClubs.length} ${thai ? "ทีมในตัวอย่าง" : "sample clubs"}`,
    "",
    ...orderedClubs.map(([code, name]) => {
      const updates = stories.filter(story => story.team_code === code).sort((a, b) => Date.parse(b.known_at) - Date.parse(a.known_at) || a.id.localeCompare(b.id));
      if (!updates.length) return `${name.toUpperCase()} | ${thai ? "ยังไม่มีสรุปข่าวที่ยืนยันได้ ไม่ได้แปลว่านักเตะทุกคนพร้อมลงสนาม" : "No verified recap yet. This does not establish player availability."}\n`;
      return `${name.toUpperCase()} | ${updates.map(story => {
        const summary = thai && story.summary.th !== null ? story.summary.th : story.summary.en;
        const fallback = thai && story.summary.th === null ? "[รอคำแปลไทย] " : "";
        return `${fallback}${sourceText(summary)}\n${thai ? "ที่มา" : "Source"}: ${story.source_name}`;
      }).join("\n\n")}\n`;
    }),
    thai ? "📌 ข่าวเป็นข้อมูลประกอบ ไม่ใช่การยืนยัน 11 ตัวจริงหรือคำแนะนำซื้อขาย" : "📌 Reported context, not a confirmed XI or transfer recommendation.",
    "THE COMET FPL · www.thecometfpl.com",
  ].join("\n");
  const copyText = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setFeedback("copied");
    } catch {
      textarea.current?.focus();
      textarea.current?.select();
      setFeedback("manual");
    }
  };

  if (!import.meta.env.DEV || !feed.demo) return null;
  return <section className="comet-glass mt-4 rounded-2xl border border-cyan-200 p-4 sm:p-6 dark:border-cyan-800" aria-labelledby="news-roundup-heading">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="flex items-center gap-2 text-xs font-semibold tracking-wide text-cyan-800 dark:text-cyan-200"><FileText className="size-4" aria-hidden="true" />{thai ? "ข่าวทุกทีมในข้อความเดียว" : "ALL YOUR TEAM NEWS, ONE MESSAGE"}</p>
        <h2 id="news-roundup-heading" className="mt-2 text-xl font-semibold">{thai ? "สรุปข่าวก่อนเดดไลน์" : "Your pre-deadline roundup"}</h2></div>
      <span className="rounded-full bg-cyan-100 px-3 py-1.5 text-xs font-medium text-cyan-900 dark:bg-cyan-950 dark:text-cyan-200">{thai ? `มีข่าว ${received}/${clubs.length} ทีมตัวอย่าง` : `${received}/${clubs.length} sample clubs covered`}</span>
    </div>
    <p id="news-roundup-scope" className="mt-2 text-sm text-muted-foreground">{thai ? "รวมทุกทีมเสมอ ไม่เปลี่ยนตามตัวกรองข่าวด้านล่าง" : "Always includes every club; filters below only affect individual news cards."}</p>
    <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{thai ? "แสดงข่าวทันทีที่ตรวจและเผยแพร่แล้ว ไม่ต้องรอข่าวครบทุกทีม" : "Updates appear as soon as they are reviewed and published, without waiting for every club."}</p>
    <p className="mt-1 text-xs text-muted-foreground">{thai ? "เดดไลน์สมมติ" : "Example deadline"}: {dateTime(deadline, language)}</p>
      <div className="mt-4 text-xs text-muted-foreground">{thai ? "ข้อมูลถึง" : "As of"}: {dateTime(asOf, language)}</div>
      <textarea key={`${language}-${asOf}`} ref={textarea} aria-label={thai ? "ข้อความสรุปข่าวทุกทีม" : "All-team roundup text"} aria-describedby="news-roundup-scope" value={text} readOnly rows={11} className="mt-2 block w-full resize-y rounded-xl border bg-background/90 p-4 text-sm leading-relaxed focus-visible:outline-2 focus-visible:outline-offset-2" />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => { void copyText(); }} className="inline-flex min-h-11 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2"><Copy className="size-4" aria-hidden="true" />{thai ? "คัดลอกข้อความทั้งหมด" : "Copy full roundup"}</button>
        <button type="button" disabled className="inline-flex min-h-11 cursor-not-allowed items-center gap-2 rounded-lg border px-4 py-2 text-sm opacity-45"><Share2 className="size-4" aria-hidden="true" />{thai ? "แชร์" : "Share"}</button>
        <span className="text-xs text-muted-foreground">{thai ? "ปิดแชร์ข่าวสมมติ · ข้อความที่คัดลอกมีป้ายตัวอย่าง" : "Sharing disabled for synthetic news · copied text includes the demo label"}</span>
      </div>
      {feedback && <p role="status" className="mt-3 flex items-center gap-2 text-sm text-muted-foreground"><ClipboardCheck className="size-4" aria-hidden="true" />{feedback === "copied" ? thai ? "คัดลอกข้อความทั้งหมดแล้ว" : "Full roundup copied" : thai ? "เลือกข้อความไว้แล้ว กรุณาคัดลอกด้วยคำสั่งของอุปกรณ์" : "Text selected. Use your device’s copy command."}</p>}
  </section>;
}
