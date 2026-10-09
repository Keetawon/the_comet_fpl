import { useEffect, useState } from "react";
import type { PublicNewsFeed } from "@/data/newsFeed";
import type { NewsLanguage } from "@/lib/newsShare";

/** Show reviewed updates on publication; deadline metadata never gates news. */
export function NewsRoundup({ feed, language }: { feed: PublicNewsFeed; language: NewsLanguage }) {
  const [now, setNow] = useState(Date.now);
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
  return <section aria-label={thai ? "สรุปข่าวล่าสุด" : "Latest news roundup"} className="comet-glass mt-5 rounded-2xl border p-5">
    <h2 className="text-lg font-semibold">{thai ? "สรุปข่าวล่าสุด" : "Latest news roundup"}</h2>
    <p className="mt-2 text-sm text-muted-foreground">{thai
      ? "สรุปข่าวที่ตรวจแล้วจากแหล่งข่าวที่เลือก ไม่ใช่การยืนยันว่าแถลงข่าวครบทุกทีม"
      : "Reviewed reports from selected sources. This does not establish that every club has completed its press conference."}</p>
    <p className="mt-2 text-sm">{thai ? "แสดงข่าวทันทีที่ตรวจและเผยแพร่แล้ว" : "Updates appear as soon as they are reviewed and published."}</p>
    <p className="mt-1 text-xs text-muted-foreground">{thai ? "เผยแพร่เมื่อ" : "Published"}: {format(feed.generated_at)}</p>
    {schedule && <p className="mt-1 text-xs text-muted-foreground">{schedule.season} GW{schedule.gw} · {thai ? "เดดไลน์" : "Deadline"}: {format(schedule.deadline_at)}</p>}
    {!fresh && <p role="status" className="mt-2 text-sm text-amber-700 dark:text-amber-300">{thai ? "ชุดข่าวเกิน 24 ชั่วโมงแล้ว รอข่าวที่ตรวจใหม่" : "This edition is over 24 hours old. Awaiting newly reviewed reports."}</p>}
    <details className="mt-3" open>
      <summary className="min-h-11 cursor-pointer py-2 font-medium">{thai ? "อ่านสรุปข่าวที่ตรวจแล้ว" : "Read the reviewed roundup"} ({feed.stories.length})</summary>
      {feed.stories.length === 0 && <p>{thai ? "ยังไม่มีข่าวที่ตรวจแล้ว" : "No reviewed reports available."}</p>}
      <ul className="mt-2 space-y-4">{feed.stories.map(story => <li key={story.id}>
        <h3 className="font-semibold">{(thai && story.title.th) || story.title.en}</h3>
        <p className="mt-1 text-sm leading-relaxed">{(thai && story.summary.th) || story.summary.en}</p>
        {feed.demo ? <span className="text-sm">{story.source_name}</span> : <a className="inline-block min-h-11 py-2 text-sm underline" href={story.source_url} target="_blank" rel="noopener noreferrer">{story.source_name}</a>}
      </li>)}</ul>
    </details>
  </section>;
}
