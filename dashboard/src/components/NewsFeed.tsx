import { useEffect, useMemo, useState } from "react";
import { ArrowUpRight, Copy, ExternalLink, Newspaper, Search, Share2 } from "lucide-react";
import { loadNewsFeed, type NewsCategory, type NewsStory, type PublicNewsFeed } from "@/data/newsFeed";
import { newsShareLinks, newsStoryUrl, shareNews, type NewsLanguage } from "@/lib/newsShare";

const copy = {
  en: {
    title: "Premier League news", latest: "Latest news", intro: "Injuries, squad updates and manager comments — with the source, not a predicted starting XI.",
    all: "All news", search: "Search news", allTeams: "All clubs", club: "Club", reset: "Reset filters", source: "Original source", coverage: "Sources & coverage",
    loading: "Loading published news…", unavailable: "News has not been published in this dashboard generation. Other dashboard data remains available.",
    empty: "No news has been published yet.", noMatches: "No news matches these filters.", translation: "Thai translation pending · showing English", ai: "AI summary", original: "Source text",
    fpl: "FPL update · linked club article", fplOnly: "Official FPL update", publication: "Published by source", fplTime: "FPL news updated", captured: "First captured", generated: "Feed published",
    notTime: "Source publication time unavailable", bound: "Reported news is context only. It does not change xP, availability probabilities or optimizer recommendations.",
    limited: "Selected sources only. No news does not establish fitness or availability.", demo: "DEMO · Synthetic examples for interface testing. These are not current football news.",
    viewAll: "View all news", copy: "Copy link", share: "Share", copied: "Link copied", shared: "Opened sharing app", cancelled: "Sharing cancelled", copyFailed: "Could not copy. Open the story link to copy its address.",
    storyLink: "Story link", stale: "No successful capture", capturedAt: "Last successful capture", noStory: "This shared story is not in the current feed. It may be from an older publication.",
    checked: "Last checked", total: "stories", sourceStatus: { ok: "Captured", disabled: "Disabled", pending_key: "Not connected", error: "Capture failed", budget_exhausted: "Monthly limit reached", not_configured: "Not configured" },
  },
  th: {
    title: "ข่าวพรีเมียร์ลีก", latest: "ข่าวล่าสุด", intro: "ข่าวบาดเจ็บ ความพร้อมของทีม และบทสัมภาษณ์ พร้อมแหล่งที่มา ไม่ใช่การทำนายตัวจริง",
    all: "ข่าวทั้งหมด", search: "ค้นหาข่าว", allTeams: "ทุกสโมสร", club: "สโมสร", reset: "ล้างตัวกรอง", source: "อ่านต้นฉบับ", coverage: "แหล่งข่าวและความครอบคลุม",
    loading: "กำลังโหลดข่าวที่เผยแพร่…", unavailable: "ชุดข้อมูล Dashboard นี้ยังไม่มีข่าวเผยแพร่ ข้อมูลส่วนอื่นยังใช้งานได้ตามปกติ",
    empty: "ยังไม่มีข่าวเผยแพร่", noMatches: "ไม่พบข่าวที่ตรงกับตัวกรอง", translation: "รอคำแปลไทย · แสดงภาษาอังกฤษ", ai: "สรุปด้วย AI", original: "ข้อความจากแหล่งข่าว",
    fpl: "อัปเดตจาก FPL · ลิงก์บทความสโมสร", fplOnly: "อัปเดตทางการจาก FPL", publication: "แหล่งข่าวเผยแพร่", fplTime: "FPL อัปเดตข่าว", captured: "เก็บข้อมูลครั้งแรก", generated: "เผยแพร่ชุดข่าว",
    notTime: "ไม่ทราบเวลาเผยแพร่ต้นฉบับ", bound: "ข่าวเป็นข้อมูลประกอบเท่านั้น ไม่เปลี่ยน xP ความน่าจะเป็นลงเล่น หรือคำแนะนำจาก optimizer",
    limited: "ติดตามเฉพาะแหล่งข่าวที่เลือก การไม่มีข่าวไม่ได้ยืนยันว่านักเตะพร้อมลงเล่น", demo: "ตัวอย่างสาธิต · ข่าวสมมติสำหรับทดสอบหน้าจอ ไม่ใช่ข่าวฟุตบอลปัจจุบัน",
    viewAll: "ดูข่าวทั้งหมด", copy: "คัดลอกลิงก์", share: "แชร์", copied: "คัดลอกลิงก์แล้ว", shared: "เปิดแอปแชร์แล้ว", cancelled: "ยกเลิกการแชร์", copyFailed: "คัดลอกไม่ได้ กรุณาเปิดลิงก์ข่าวเพื่อคัดลอกที่อยู่",
    storyLink: "ลิงก์ข่าว", stale: "ยังไม่มีการดึงข่าวสำเร็จ", capturedAt: "ดึงข่าวสำเร็จล่าสุด", noStory: "ไม่พบข่าวที่แชร์ในชุดข้อมูลปัจจุบัน อาจเป็นข่าวจากชุดก่อนหน้า",
    checked: "ตรวจล่าสุด", total: "ข่าว", sourceStatus: { ok: "ดึงข้อมูลแล้ว", disabled: "ปิดใช้งาน", pending_key: "ยังไม่เชื่อมต่อ", error: "ดึงข้อมูลไม่สำเร็จ", budget_exhausted: "ถึงขีดจำกัดรายเดือน", not_configured: "ยังไม่ตั้งค่า" },
  },
};

const categoryNames: Record<NewsCategory, { en: string; th: string }> = {
  injury: { en: "Injury", th: "บาดเจ็บ" }, suspension: { en: "Suspension", th: "ติดโทษแบน" }, transfer: { en: "Transfer", th: "ย้ายทีม" },
  squad: { en: "Squad update", th: "ความพร้อมทีม" }, press_conference: { en: "Press conference", th: "สัมภาษณ์ผู้จัดการ" }, other: { en: "Other", th: "อื่น ๆ" },
};
const fieldClass = "min-h-10 rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2";
const actionClass = "inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-40";
const utc = (value: string, language: NewsLanguage) => `${new Intl.DateTimeFormat(language === "th" ? "th-TH" : "en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(new Date(value))} UTC`;
const routeQuery = () => new URLSearchParams(window.location.hash.split("?", 2)[1] ?? "");

function NewsCard({ story, language, demo, selected }: { story: NewsStory; language: NewsLanguage; demo: boolean; selected: boolean }) {
  const t = copy[language];
  const [feedback, setFeedback] = useState("");
  const translated = language === "th" && story.title.th !== null && story.summary.th !== null;
  const title = translated ? story.title.th! : story.title.en;
  const summary = translated ? story.summary.th! : story.summary.en;
  const links = newsShareLinks(story.id, language, `${title}\n${summary}\n${story.source_name}`);
  const share = async () => {
    try {
      const status = await shareNews(story.id, language, `${title}\n${summary}\n${story.source_name}`);
      setFeedback(status === "copied" ? t.copied : status === "cancelled" ? t.cancelled : t.shared);
    } catch { setFeedback(t.copyFailed); }
  };
  const copyLink = async () => {
    try { await navigator.clipboard.writeText(links.url); setFeedback(t.copied); }
    catch { setFeedback(t.copyFailed); }
  };

  return <article id={`news-${story.id}`} className={`flex min-w-0 scroll-mt-4 flex-col rounded-xl border bg-card p-4 sm:p-5 ${selected ? "ring-2 ring-sky-500" : ""}`} aria-labelledby={`title-${story.id}`}>
    <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px] font-medium">
      <span className="rounded-md bg-sky-100 px-2 py-1 text-sky-900 dark:bg-sky-950 dark:text-sky-200">{categoryNames[story.category][language]}</span>
      {story.team_name && <span className="rounded-md bg-muted px-2 py-1">{story.team_name}</span>}
      <span className="ml-auto text-muted-foreground">{story.rendering === "ai_summary" ? t.ai : t.original}</span>
    </div>
    <p className="mb-1.5 break-words text-xs font-medium text-muted-foreground">{story.source_name} · {story.source_kind === "x" ? "X" : new URL(story.source_url).hostname === "fantasy.premierleague.com" ? t.fplOnly : t.fpl}</p>
    <h3 id={`title-${story.id}`} lang={translated ? "th" : "en"} className="break-words text-base leading-snug font-semibold">{title}</h3>
    {language === "th" && !translated && <p className="mt-2 text-[11px] text-amber-700 dark:text-amber-300">{t.translation}</p>}
    <p lang={translated ? "th" : "en"} className="mt-3 whitespace-pre-line break-words text-sm leading-relaxed text-foreground/85">{summary}</p>
    <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">{story.published_at ? <>{story.source_kind === "fpl" ? t.fplTime : t.publication}: <time dateTime={story.published_at}>{utc(story.published_at, language)}</time></> : t.notTime}</p>
    <div className="mt-auto pt-4">
      <a href={story.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-9 items-center gap-1.5 text-xs font-semibold underline underline-offset-4">{t.source}<ExternalLink className="size-3" aria-hidden="true" /></a>
      <div className="mt-2 flex flex-wrap gap-1.5" aria-label={`${t.share}: ${title}`}>
        <button type="button" className={actionClass} disabled={demo} onClick={() => { void share(); }}><Share2 className="size-3.5" aria-hidden="true" />{t.share}</button>
        {demo ? <><button type="button" className={actionClass} disabled>LINE</button><button type="button" className={actionClass} disabled>Facebook</button></> : <><a className={actionClass} href={links.line} target="_blank" rel="noopener noreferrer">LINE</a><a className={actionClass} href={links.facebook} target="_blank" rel="noopener noreferrer">Facebook</a></>}
        <button type="button" className={actionClass} disabled={demo} onClick={() => { void copyLink(); }}><Copy className="size-3.5" aria-hidden="true" />{t.copy}</button>
      </div>
      {feedback && <p className="mt-2 text-xs text-muted-foreground" role="status">{feedback}</p>}
      <details className="mt-3 text-[11px] text-muted-foreground"><summary className="cursor-pointer focus-visible:outline-2">{t.coverage}</summary><div className="mt-2 space-y-1 break-words">
        <p>{t.captured}: {utc(story.known_at, language)}</p>
        {story.summarized_at && <p>{t.ai}: {utc(story.summarized_at, language)} · {story.ai_model}</p>}
        <p>{t.limited}</p>
        {!demo && <a className="inline-block underline underline-offset-2" href={newsStoryUrl(story.id, language)}>{t.storyLink}</a>}
      </div></details>
    </div>
  </article>;
}

/** The browser only reads a published feed. It never contacts X or an AI provider. */
export function NewsFeed({ compact = false }: { compact?: boolean }) {
  const [state, setState] = useState<{ status: "loading" | "unavailable" } | { status: "ready"; data: PublicNewsFeed }>({ status: "loading" });
  const [language, setLanguage] = useState<NewsLanguage>(() => routeQuery().get("lang") === "th" ? "th" : "en");
  const [sharedId, setSharedId] = useState<string | null>(() => compact ? null : routeQuery().get("story"));
  const [query, setQuery] = useState("");
  const [team, setTeam] = useState("");
  const [category, setCategory] = useState("");
  useEffect(() => {
    let active = true;
    loadNewsFeed().then(data => { if (active) setState({ status: "ready", data }); }).catch(() => { if (active) setState({ status: "unavailable" }); });
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (compact) return;
    const changed = () => { setSharedId(routeQuery().get("story")); setLanguage(routeQuery().get("lang") === "th" ? "th" : "en"); };
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, [compact]);
  useEffect(() => {
    if (sharedId && state.status === "ready") document.getElementById(`news-${sharedId}`)?.scrollIntoView?.({ block: "start" });
  }, [sharedId, state]);
  const t = copy[language];
  const feed = state.status === "ready" ? state.data : null;
  const clubs = useMemo(() => {
    const result = new Map<number, string>();
    for (const story of feed?.stories ?? []) if (story.team_code !== null && story.team_name !== null) result.set(story.team_code, story.team_name);
    return [...result].sort((a, b) => a[1].localeCompare(b[1]));
  }, [feed]);
  const filtered = useMemo(() => (feed?.stories ?? []).filter(story =>
    (!team || String(story.team_code) === team) && (!category || story.category === category) &&
    (!query.trim() || [story.title.en, story.title.th, story.summary.en, story.summary.th, story.player_name, story.team_name, story.source_name].filter(Boolean).join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())))
    .sort((a, b) => Date.parse(b.known_at) - Date.parse(a.known_at) || a.id.localeCompare(b.id)), [feed, query, team, category]);
  const stories = compact ? filtered.slice(0, 3) : filtered;
  const changeLanguage = (next: NewsLanguage) => { setLanguage(next); if (!compact) window.history.replaceState(null, "", `#news?${new URLSearchParams({ ...(sharedId ? { story: sharedId } : {}), lang: next })}`); };

  return <section className={compact ? "min-w-0 rounded-xl border bg-card p-4 sm:p-5" : "min-w-0"} aria-label={t.title}>
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-2xl"><div className="flex items-center gap-2"><Newspaper className="size-5 text-sky-600 dark:text-sky-400" aria-hidden="true" />{compact ? <h2 className="text-base font-semibold">{t.latest}</h2> : <h1 className="text-2xl font-semibold tracking-tight">{t.title}</h1>}</div><p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t.intro}</p></div>
      <div className="flex shrink-0 rounded-md border p-1" aria-label="News language">{(["en", "th"] as const).map(lang => <button type="button" key={lang} lang={lang} aria-pressed={language === lang} onClick={() => changeLanguage(lang)} className={`min-h-8 rounded px-3 py-1 text-xs font-semibold focus-visible:outline-2 ${language === lang ? "bg-foreground text-background" : "text-muted-foreground hover:bg-muted"}`}>{lang === "en" ? "English" : "ไทย"}</button>)}</div>
    </div>
    {feed?.demo && <p role="note" className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm font-medium text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">{t.demo}</p>}
    {feed && <div className="mt-4 rounded-lg border bg-muted/20 px-3 py-2.5 text-xs text-muted-foreground"><p>{t.generated}: {utc(feed.generated_at, language)} · {feed.stories.length} {t.total}</p><div className="mt-2 flex flex-wrap gap-1.5">{feed.sources.map(source => <span key={source.source_id} className={`rounded border px-2 py-1 ${source.status === "ok" ? "text-foreground" : "border-amber-300 text-amber-800 dark:border-amber-800 dark:text-amber-300"}`}>{source.source_name} · {t.sourceStatus[source.status]}</span>)}</div><details className="mt-2"><summary className="cursor-pointer font-medium focus-visible:outline-2">{t.coverage}</summary><div className="mt-2 space-y-2">{feed.sources.map(source => <div key={source.source_id}><p className="font-medium text-foreground">{source.source_name}</p><p>{source.last_success_at ? `${t.capturedAt}: ${utc(source.last_success_at, language)}` : t.stale}</p>{source.last_checked_at && <p>{t.checked}: {utc(source.last_checked_at, language)}</p>}{source.message && <p>{source.message}</p>}</div>)}<p>{t.limited}</p></div></details></div>}
    {!compact && feed && feed.stories.length > 0 && <div className="mt-5 space-y-3">
      <div className="flex flex-wrap gap-1.5" role="group" aria-label={language === "th" ? "ประเภทข่าว" : "News category"}>{["", ...Object.keys(categoryNames)].map(key => <button type="button" key={key} aria-pressed={category === key} onClick={() => setCategory(key)} className={`min-h-9 rounded-full border px-3 py-1.5 text-xs font-medium focus-visible:outline-2 ${category === key ? "border-foreground bg-foreground text-background" : "hover:bg-muted"}`}>{key ? categoryNames[key as NewsCategory][language] : t.all}</button>)}</div>
      <div className="flex flex-col gap-2 sm:flex-row"><label className="relative min-w-0 flex-1"><Search className="pointer-events-none absolute top-3 left-3 size-4 text-muted-foreground" aria-hidden="true" /><span className="sr-only">{t.search}</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder={t.search} className={`${fieldClass} w-full pl-9`} /></label><label><span className="sr-only">{t.club}</span><select value={team} onChange={event => setTeam(event.target.value)} className={`${fieldClass} w-full sm:max-w-56`}><option value="">{t.allTeams}</option>{clubs.map(([code, name]) => <option value={code} key={code}>{name}</option>)}</select></label><button type="button" className={fieldClass} onClick={() => { setQuery(""); setTeam(""); setCategory(""); }}>{t.reset}</button></div>
    </div>}
    {sharedId && feed && !feed.stories.some(story => story.id === sharedId) && <p role="status" className="mt-4 text-sm text-muted-foreground">{t.noStory}</p>}
    {state.status !== "ready" || stories.length === 0 ? <div className="mt-5 rounded-xl border border-dashed bg-muted/20 px-5 py-10 text-center text-sm text-muted-foreground" role="status">{state.status === "loading" ? t.loading : state.status === "unavailable" ? t.unavailable : feed?.stories.length ? t.noMatches : t.empty}</div> : <div className={`mt-5 grid gap-3 ${compact ? "xl:grid-cols-3" : "lg:grid-cols-2 2xl:grid-cols-3"}`}>{stories.map(story => <NewsCard story={story} language={language} demo={feed!.demo} selected={story.id === sharedId} key={story.id} />)}</div>}
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p className="max-w-3xl text-xs leading-relaxed text-muted-foreground">{t.bound}</p>{compact && <a href={`#news?lang=${language}`} className="inline-flex min-h-9 items-center gap-1 whitespace-nowrap text-xs font-semibold underline underline-offset-4">{t.viewAll}<ArrowUpRight className="size-3.5" aria-hidden="true" /></a>}</div>
  </section>;
}
