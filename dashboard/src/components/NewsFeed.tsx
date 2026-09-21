import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ArrowUpRight, Copy, ExternalLink, Newspaper, Search, Share2 } from "lucide-react";
import { loadNewsFeed, type NewsCategory, type NewsStory, type PublicNewsFeed } from "@/data/newsFeed";
import { newsShareLinks, newsStoryUrl, shareNews, type NewsLanguage } from "@/lib/newsShare";

const copy = {
  en: {
    title: "Premier League news", latest: "Team news to catch up on", eyebrow: "THE TEAM NEWS DESK",
    intro: "Injuries, squad updates and the manager’s own words. Catch up before choosing your XI.",
    all: "All news", search: "Search news", allTeams: "All clubs", club: "Club", reset: "Reset filters", source: "Original source", coverage: "Sources & coverage",
    loading: "Loading published news…", unavailable: "News has not been published in this dashboard generation. Other dashboard data remains available.",
    empty: "No news has been published yet.", noMatches: "No news matches these filters.", translation: "Thai translation pending · showing English", ai: "AI summary", original: "Source text",
    fpl: "FPL update · linked club article", fplOnly: "Official FPL update", publication: "Published by source", fplTime: "FPL news updated", captured: "First captured", generated: "Feed published",
    notTime: "Source publication time unavailable", bound: "Reported news is context only. It does not change xP, availability probabilities or optimizer recommendations.",
    limited: "Selected sources only. No news does not establish fitness or availability.", demo: "DEMO · Synthetic examples for interface testing. These are not current football news.",
    viewAll: "View all news", copy: "Copy link", share: "Share", copied: "Link copied", shared: "Opened sharing app", cancelled: "Sharing cancelled", copyFailed: "Could not copy. Open the story link to copy its address.",
    storyLink: "Story link", stale: "No successful capture", capturedAt: "Last successful capture", noStory: "This shared story is not in the current feed. It may be from an older publication.",
    checked: "Last checked", total: "stories", newest: "Newest captured first", showing: "Showing", clubs: "Browse by club", context: "Read the source, keep the context", contextText: "A manager’s hope is not a confirmed return. Check the date and original wording before deciding on your team.",
    sourceStatus: { ok: "Captured", disabled: "Disabled", pending_key: "Not connected", error: "Capture failed", budget_exhausted: "Monthly limit reached", not_configured: "Not configured" },
  },
  th: {
    title: "ข่าวพรีเมียร์ลีก", latest: "อัปเดตข่าวก่อนจัดทีม", eyebrow: "ข่าวความพร้อมของทีม",
    intro: "ข่าวบาดเจ็บ ความพร้อมทีม และคำสัมภาษณ์ผู้จัดการ อ่านให้ครบก่อนเลือก 11 ตัวจริง",
    all: "ข่าวทั้งหมด", search: "ค้นหาข่าว", allTeams: "ทุกสโมสร", club: "สโมสร", reset: "ล้างตัวกรอง", source: "อ่านต้นฉบับ", coverage: "แหล่งข่าวและความครอบคลุม",
    loading: "กำลังโหลดข่าวที่เผยแพร่…", unavailable: "ชุดข้อมูล Dashboard นี้ยังไม่มีข่าวเผยแพร่ ข้อมูลส่วนอื่นยังใช้งานได้ตามปกติ",
    empty: "ยังไม่มีข่าวเผยแพร่", noMatches: "ไม่พบข่าวที่ตรงกับตัวกรอง", translation: "รอคำแปลไทย · แสดงภาษาอังกฤษ", ai: "สรุปด้วย AI", original: "ข้อความจากแหล่งข่าว",
    fpl: "อัปเดตจาก FPL · ลิงก์บทความสโมสร", fplOnly: "อัปเดตทางการจาก FPL", publication: "แหล่งข่าวเผยแพร่", fplTime: "FPL อัปเดตข่าว", captured: "เก็บข้อมูลครั้งแรก", generated: "เผยแพร่ชุดข่าว",
    notTime: "ไม่ทราบเวลาเผยแพร่ต้นฉบับ", bound: "ข่าวเป็นข้อมูลประกอบเท่านั้น ไม่เปลี่ยน xP ความน่าจะเป็นลงเล่น หรือคำแนะนำจาก optimizer",
    limited: "ติดตามเฉพาะแหล่งข่าวที่เลือก การไม่มีข่าวไม่ได้ยืนยันว่านักเตะพร้อมลงเล่น", demo: "ตัวอย่างสาธิต · ข่าวสมมติสำหรับทดสอบหน้าจอ ไม่ใช่ข่าวฟุตบอลปัจจุบัน",
    viewAll: "ดูข่าวทั้งหมด", copy: "คัดลอกลิงก์", share: "แชร์", copied: "คัดลอกลิงก์แล้ว", shared: "เปิดแอปแชร์แล้ว", cancelled: "ยกเลิกการแชร์", copyFailed: "คัดลอกไม่ได้ กรุณาเปิดลิงก์ข่าวเพื่อคัดลอกที่อยู่",
    storyLink: "ลิงก์ข่าว", stale: "ยังไม่มีการดึงข่าวสำเร็จ", capturedAt: "ดึงข่าวสำเร็จล่าสุด", noStory: "ไม่พบข่าวที่แชร์ในชุดข้อมูลปัจจุบัน อาจเป็นข่าวจากชุดก่อนหน้า",
    checked: "ตรวจล่าสุด", total: "ข่าว", newest: "เรียงตามเวลาเก็บข่าวล่าสุด", showing: "แสดง", clubs: "เลือกข่าวตามสโมสร", context: "อ่านต้นฉบับให้ครบก่อนตัดสินใจ", contextText: "คำว่า ‘หวังว่าจะกลับมา’ ยังไม่ใช่การยืนยันว่าพร้อมลงเล่น ตรวจวันที่และคำพูดต้นฉบับก่อนจัดทีม",
    sourceStatus: { ok: "ดึงข้อมูลแล้ว", disabled: "ปิดใช้งาน", pending_key: "ยังไม่เชื่อมต่อ", error: "ดึงข้อมูลไม่สำเร็จ", budget_exhausted: "ถึงขีดจำกัดรายเดือน", not_configured: "ยังไม่ตั้งค่า" },
  },
};

const categoryNames: Record<NewsCategory, { en: string; th: string }> = {
  injury: { en: "Injury", th: "บาดเจ็บ" }, suspension: { en: "Suspension", th: "ติดโทษแบน" }, transfer: { en: "Transfer", th: "ย้ายทีม" },
  squad: { en: "Squad update", th: "ความพร้อมทีม" }, press_conference: { en: "Press conference", th: "สัมภาษณ์ผู้จัดการ" }, other: { en: "Other", th: "อื่น ๆ" },
};
const categoryTone: Record<NewsCategory, string> = {
  injury: "bg-rose-50 text-rose-800 dark:bg-rose-950/50 dark:text-rose-200",
  suspension: "bg-amber-50 text-amber-900 dark:bg-amber-950/50 dark:text-amber-200",
  transfer: "bg-sky-50 text-sky-800 dark:bg-sky-950/50 dark:text-sky-200",
  squad: "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200",
  press_conference: "bg-violet-50 text-violet-800 dark:bg-violet-950/50 dark:text-violet-200",
  other: "bg-muted text-muted-foreground",
};
const fieldClass = "min-h-11 rounded-lg border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2";
const actionClass = "inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors hover:bg-muted focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-40";
const utc = (value: string, language: NewsLanguage) => `${new Intl.DateTimeFormat(language === "th" ? "th-TH" : "en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }).format(new Date(value))} UTC`;
const routeQuery = () => new URLSearchParams(window.location.hash.split("?", 2)[1] ?? "");

function NewsCard({ story, language, demo, selected, compact }: { story: NewsStory; language: NewsLanguage; demo: boolean; selected: boolean; compact: boolean }) {
  const t = copy[language];
  const [feedback, setFeedback] = useState("");
  const translated = language === "th" && story.title.th !== null && story.summary.th !== null;
  const title = translated ? story.title.th! : story.title.en;
  const summary = translated ? story.summary.th! : story.summary.en;
  const links = newsShareLinks(story.id, language, `${title}\n${summary}\n${story.source_name}`);
  const Heading = compact ? "h3" : "h2";
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

  return <article id={`news-${story.id}`} className={`min-w-0 scroll-mt-4 ${compact ? "py-4 first:pt-0 last:pb-0" : "comet-glass rounded-2xl border p-4 sm:p-6"} ${selected ? "ring-2 ring-sky-500" : ""}`} aria-labelledby={`title-${story.id}`}>
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs font-medium">
      <span className={`rounded-md px-2 py-1 ${categoryTone[story.category]}`}>{categoryNames[story.category][language]}</span>
      {story.team_name && <span className="text-muted-foreground">{story.team_name}</span>}
    </div>
    <Heading id={`title-${story.id}`} lang={translated ? "th" : "en"} className={`break-words font-semibold tracking-tight ${compact ? "text-base leading-snug" : "text-xl leading-snug sm:text-2xl"}`}>
      {compact ? <a href={`#news?${new URLSearchParams({ story: story.id, lang: language })}`} className="rounded-sm hover:underline focus-visible:outline-2">{title}</a> : title}
    </Heading>
    {language === "th" && !translated && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">{t.translation}</p>}
    <p lang={translated ? "th" : "en"} className={`mt-3 whitespace-pre-line break-words leading-relaxed text-foreground/85 ${compact ? "text-sm" : "text-base"}`}>{summary}</p>
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span className="font-medium">{story.source_name}</span>
      <span>{story.rendering === "ai_summary" ? t.ai : t.original}</span>
      <p>{story.published_at ? <>{story.source_kind === "fpl" ? t.fplTime : t.publication}: <time dateTime={story.published_at}>{utc(story.published_at, language)}</time></> : t.notTime}</p>
    </div>
    {!compact && <>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t pt-4">
        {demo ? <span className="text-xs text-muted-foreground">{language === "th" ? "ข่าวสมมติ · ปิดลิงก์และการแชร์" : "Synthetic story · links and sharing disabled"}</span> : <a href={story.source_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold underline underline-offset-4">{t.source}<ExternalLink className="size-3.5" aria-hidden="true" /></a>}
        <div className="flex flex-wrap gap-2" aria-label={`${t.share}: ${title}`}>
          <button type="button" className={actionClass} disabled={demo} onClick={() => { void share(); }}><Share2 className="size-3.5" aria-hidden="true" />{t.share}</button>
          {demo ? <><button type="button" className={actionClass} disabled>LINE</button><button type="button" className={actionClass} disabled>Facebook</button></> : <><a className={actionClass} href={links.line} target="_blank" rel="noopener noreferrer">LINE</a><a className={actionClass} href={links.facebook} target="_blank" rel="noopener noreferrer">Facebook</a></>}
          <button type="button" className={actionClass} disabled={demo} onClick={() => { void copyLink(); }}><Copy className="size-3.5" aria-hidden="true" />{t.copy}</button>
        </div>
      </div>
      {feedback && <p className="mt-2 text-xs text-muted-foreground" role="status">{feedback}</p>}
      <details className="mt-3 text-xs text-muted-foreground"><summary className="w-fit cursor-pointer py-2 focus-visible:outline-2">{t.coverage}</summary><div className="mt-1 space-y-2 break-words">
        <p>{story.source_kind === "x" ? "X" : new URL(story.source_url).hostname === "fantasy.premierleague.com" ? t.fplOnly : t.fpl}</p>
        <p>{t.captured}: {utc(story.known_at, language)}</p>
        {story.summarized_at && <p>{t.ai}: {utc(story.summarized_at, language)} · {story.ai_model}</p>}
        {!demo && <a className="inline-block underline underline-offset-2" href={newsStoryUrl(story.id, language)}>{t.storyLink}</a>}
      </div></details>
    </>}
  </article>;
}

/** The browser only reads a published feed. It never contacts X or an AI provider. */
export interface NewsPreview {
  feed: PublicNewsFeed;
  clubs: readonly (readonly [number, string])[];
  header: (language: NewsLanguage) => ReactNode;
  sidebar: (language: NewsLanguage, selectedTeam: string) => ReactNode;
}

export function NewsFeed({ compact = false, preview }: { compact?: boolean; preview?: NewsPreview }) {
  const demoPreview = import.meta.env.DEV && preview?.feed.demo ? preview : undefined;
  const [state, setState] = useState<{ status: "loading" | "unavailable" } | { status: "ready"; data: PublicNewsFeed }>({ status: "loading" });
  const [language, setLanguage] = useState<NewsLanguage>(() => routeQuery().get("lang") === "th" ? "th" : "en");
  const [sharedId, setSharedId] = useState<string | null>(() => compact ? null : routeQuery().get("story"));
  const [query, setQuery] = useState("");
  const [team, setTeam] = useState("");
  const [category, setCategory] = useState<NewsCategory | "">("");
  useEffect(() => {
    if (demoPreview) {
      setState({ status: "ready", data: demoPreview.feed });
      return;
    }
    let active = true;
    loadNewsFeed().then(data => { if (active) setState({ status: "ready", data }); }).catch(() => { if (active) setState({ status: "unavailable" }); });
    return () => { active = false; };
  }, [demoPreview]);
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
    const result = new Map<number, string>(demoPreview?.clubs);
    for (const story of feed?.stories ?? []) if (story.team_code !== null && story.team_name !== null) result.set(story.team_code, story.team_name);
    return [...result].sort((a, b) => a[1].localeCompare(b[1]));
  }, [feed, demoPreview]);
  const searched = useMemo(() => (feed?.stories ?? []).filter(story =>
    (!team || String(story.team_code) === team) &&
    (!query.trim() || [story.title.en, story.title.th, story.summary.en, story.summary.th, story.player_name, story.team_name, story.source_name].filter(Boolean).join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())))
    .sort((a, b) => Date.parse(b.known_at) - Date.parse(a.known_at) || a.id.localeCompare(b.id)), [feed, query, team]);
  const filtered = searched.filter(story => !category || story.category === category);
  const stories = compact ? filtered.slice(0, 3) : filtered;
  const changeLanguage = (next: NewsLanguage) => {
    setLanguage(next);
    if (!compact) {
      const params = routeQuery();
      params.set("lang", next);
      window.history.replaceState(null, "", `#news?${params}`);
    }
  };
  const reset = () => { setQuery(""); setTeam(""); setCategory(""); };

  return <section className={compact ? "min-w-0 comet-glass rounded-2xl border p-4 sm:p-6" : "min-w-0"} aria-label={t.title}>
    <header className={`flex flex-wrap items-start justify-between gap-4 ${compact ? "" : "comet-glass rounded-2xl border p-4 sm:p-6"}`}>
      <div className="max-w-2xl">
        {!compact && <p className="mb-3 flex items-center gap-2 text-xs font-bold tracking-[0.14em] text-sidebar-accent-foreground"><Newspaper className="size-4" aria-hidden="true" />{t.eyebrow}</p>}
        {compact ? <h2 className="text-lg font-semibold tracking-tight">{t.latest}</h2> : <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">{t.title}</h1>}
        {!compact && <p className="mt-3 max-w-xl text-base leading-relaxed text-muted-foreground">{t.intro}</p>}
        {feed && <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{t.generated}: <time dateTime={feed.generated_at}>{utc(feed.generated_at, language)}</time></p>}
      </div>
      <div className="flex shrink-0 rounded-lg border bg-background p-1" aria-label="News language">{(["en", "th"] as const).map(lang => <button type="button" key={lang} lang={lang} aria-pressed={language === lang} onClick={() => changeLanguage(lang)} className={`min-h-11 rounded-md px-4 py-2 text-sm font-semibold focus-visible:outline-2 ${language === lang ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-muted"}`}>{lang === "en" ? "English" : "ไทย"}</button>)}</div>
    </header>
    {feed?.demo && <p role="note" className="mt-4 rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm font-medium text-amber-900 dark:border-amber-700 dark:bg-amber-950 dark:text-amber-200">{t.demo}</p>}
    {!compact && demoPreview?.header(language)}
    {!compact && feed && feed.stories.length > 0 && <div className="mt-6 space-y-4">
      <div className="grid grid-cols-2 gap-2 sm:flex sm:flex-row"><label className="relative col-span-2 min-w-0 flex-1"><Search className="pointer-events-none absolute top-3.5 left-3 size-4 text-muted-foreground" aria-hidden="true" /><span className="sr-only">{t.search}</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder={t.search} className={`${fieldClass} w-full pl-9`} /></label><label><span className="sr-only">{t.club}</span><select value={team} onChange={event => setTeam(event.target.value)} className={`${fieldClass} w-full sm:max-w-56`}><option value="">{t.allTeams}</option>{clubs.map(([code, name]) => <option value={code} key={code}>{name}</option>)}</select></label><button type="button" className={fieldClass} onClick={reset}>{t.reset}</button></div>
      <div className="comet-news-topics flex max-w-full gap-2 overflow-x-auto pb-2 sm:flex-wrap" role="group" aria-label={language === "th" ? "ประเภทข่าว" : "News category"}>{(["", ...Object.keys(categoryNames)] as (NewsCategory | "")[]).map(key => <button type="button" key={key} aria-pressed={category === key} onClick={() => setCategory(key)} className={`inline-flex min-h-11 shrink-0 items-center gap-2 whitespace-nowrap rounded-full border px-3.5 py-2 text-sm font-medium focus-visible:outline-2 ${category === key ? "border-primary bg-primary text-primary-foreground" : "bg-card hover:bg-muted"}`}>
        {key ? categoryNames[key][language] : t.all}<span aria-hidden="true" className="tabular-nums opacity-60">{key ? searched.filter(story => story.category === key).length : searched.length}</span>
      </button>)}</div>
    </div>}
    {sharedId && feed && !feed.stories.some(story => story.id === sharedId) && <p role="status" className="mt-4 text-sm text-muted-foreground">{t.noStory}</p>}
    <div className={compact ? "mt-5" : "mt-5 grid gap-6 xl:grid-cols-[minmax(0,1fr)_17rem]"}>
      <div className="min-w-0">
        {!compact && feed && feed.stories.length > 0 && <div className="mb-3 flex flex-wrap justify-between gap-2 text-xs text-muted-foreground" aria-live="polite"><p>{t.showing} {stories.length} / {feed.stories.length} {t.total}</p><p>{t.newest}</p></div>}
        {state.status !== "ready" || stories.length === 0 ? <div className="rounded-xl border border-dashed bg-muted/20 px-5 py-10 text-center text-sm text-muted-foreground" role="status"><Newspaper className="mx-auto mb-3 size-6" aria-hidden="true" />{state.status === "loading" ? t.loading : state.status === "unavailable" ? t.unavailable : feed?.stories.length ? t.noMatches : t.empty}</div> : <div className={compact ? "divide-y" : "space-y-4"}>{stories.map(story => <NewsCard story={story} language={language} demo={feed!.demo} selected={story.id === sharedId} compact={compact} key={story.id} />)}</div>}
      </div>
      {!compact && <aside className="space-y-4 self-start">
        {demoPreview?.sidebar(language, team)}
        {!demoPreview && clubs.length > 0 && <div className="comet-glass rounded-2xl border p-5"><h2 className="text-sm font-semibold">{t.clubs}</h2><div className="mt-3 flex flex-wrap gap-2">{clubs.map(([code, name]) => <button type="button" key={code} aria-pressed={team === String(code)} onClick={() => setTeam(team === String(code) ? "" : String(code))} className={`min-h-11 rounded-lg border px-3 py-2 text-xs font-medium focus-visible:outline-2 ${team === String(code) ? "bg-primary text-primary-foreground" : "hover:bg-muted"}`}>{name}</button>)}</div></div>}
        <div className="rounded-2xl border border-amber-200 bg-amber-50/60 p-5 dark:border-amber-900 dark:bg-amber-950/20"><h2 className="text-sm font-semibold">{t.context}</h2><p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t.contextText}</p><p className="mt-3 text-xs leading-relaxed text-muted-foreground">{t.limited}</p></div>
      </aside>}
    </div>
    <footer className="mt-5 border-t pt-4">
      {compact && <a href={`#news?lang=${language}`} className="inline-flex min-h-11 items-center gap-2 text-sm font-semibold underline underline-offset-4">{t.viewAll}<ArrowUpRight className="size-4" aria-hidden="true" /></a>}
      <details className="text-xs text-muted-foreground"><summary className="w-fit cursor-pointer py-2 font-medium focus-visible:outline-2">{t.coverage}</summary><div className="mt-2 space-y-3 leading-relaxed"><p>{t.bound}</p><p>{t.limited}</p>{feed?.sources.map(source => <div key={source.source_id} className="rounded-lg border bg-muted/20 p-3"><p className="font-medium text-foreground">{source.source_name} · {t.sourceStatus[source.status]}</p><p>{source.last_success_at ? `${t.capturedAt}: ${utc(source.last_success_at, language)}` : t.stale}</p>{source.last_checked_at && <p>{t.checked}: {utc(source.last_checked_at, language)}</p>}{source.message && <p>{source.message}</p>}</div>)}</div></details>
    </footer>
  </section>;
}
