import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowUpRight, Check, Copy, Download, MessageSquareText, ShieldCheck, Share2, Target } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TeamBadge } from "@/components/Avatars";
import { loadFixtureMatrix, loadSummary, type FixtureMatrixData } from "@/data/load";
import { loadSdpStats, type SdpStatsData } from "@/data/sdpStats";
import { buildMatchPreviews, type MatchPreview } from "@/lib/matchPreview";
import { buildGwBriefing } from "@/lib/gwBriefing";
import { copyGwBriefing, downloadGwBriefing, gwBriefingLineUrl, prepareGwBriefingFacebook, shareGwBriefing } from "@/lib/gwBriefingShare";

type Language = "en" | "th";
type PageState = { status: "loading" } | { status: "unavailable" } | { status: "ready"; data: FixtureMatrixData; latestRun: string | null };
type StatsState = { status: "loading" | "unavailable" } | { status: "ready"; data: SdpStatsData };
const fieldClass = "min-h-11 max-w-full rounded-lg border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2";
const utc = (value: string) => Number.isFinite(Date.parse(value)) ? `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC` : "Unavailable";
const goal = (value: number | null) => value === null ? "—" : value.toFixed(2);
const chance = (value: number | null) => value === null ? "—" : `${Math.round(value * 100)}%`;

/** Read-only public text. Users edit their copy in their own app, never this page. */
function ShareBriefing({ text, language }: { text: string; language: Language }) {
  const [feedback, setFeedback] = useState("");
  const [copied, setCopied] = useState(false);
  const [facebook, setFacebook] = useState<{ url: string; instruction: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const version = useRef(0);
  useEffect(() => () => { version.current += 1; }, []);
  const lineUrl = text.trim() ? gwBriefingLineUrl(text) : null;
  const act = async (action: "copy" | "share" | "facebook" | "download") => {
    if (!text.trim() || busy) return;
    const current = ++version.current;
    setBusy(true); setFeedback(""); setFacebook(null); setCopied(false);
    try {
      let message = "";
      if (action === "copy") { await copyGwBriefing(text); message = language === "th" ? "คัดลอกแล้ว นำไปวางและแก้ไขในแอปที่คุณใช้ได้เลย" : "Copied. Paste and edit in your favourite app."; }
      else if (action === "share") {
        const result = await shareGwBriefing(text);
        message = result === "shared" ? "Opened sharing app." : result === "copied" ? "Copied. Paste in your favourite app." : "Sharing cancelled.";
      } else if (action === "facebook") {
        const prepared = await prepareGwBriefingFacebook(text);
        if (current === version.current) setFacebook(prepared);
        message = prepared.instruction;
      } else { downloadGwBriefing(text); message = "Text download started."; }
      if (current === version.current) { setFeedback(message); setCopied(action === "copy"); }
    } catch (error) {
      if (current === version.current) setFeedback(error instanceof Error ? error.message : "Sharing is unavailable. Download the text instead.");
    } finally { if (current === version.current) setBusy(false); }
  };
  return <section id="matchweek-analysis" aria-labelledby="analysis-heading" className="comet-glass overflow-hidden rounded-2xl border shadow-sm">
    <div className="border-b p-5 sm:p-6">
      <div className="mb-3 flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground"><MessageSquareText className="size-4" aria-hidden="true" />The Comet briefing</div>
      <h2 id="analysis-heading" className="text-xl font-semibold tracking-tight">{language === "th" ? "บทสรุปพร้อมแชร์" : "Your matchweek, in words"}</h2>
      <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{language === "th" ? "คัดลอกทั้งข้อความ แล้วเพิ่มมุมมองของคุณใน LINE, Facebook หรือแอปที่ใช้ได้เลย" : "Copy the full post. Add your own take in LINE, Facebook or your notes app."}</p>
    </div>
    <div className="p-5 sm:p-6">
      <label htmlFor="score-analysis-text" className="sr-only">Analysis message</label>
      <textarea id="score-analysis-text" readOnly lang={language} value={text} className="min-h-80 w-full resize-y rounded-xl border bg-muted/30 p-4 text-sm leading-7 focus-visible:outline-2 focus-visible:outline-offset-2 sm:min-h-[26rem]" />
      <div className="mt-4 flex flex-wrap gap-2" aria-label="Share analysis">
        <Button className="min-h-11 gap-2" disabled={busy || !text} onClick={() => { void act("copy"); }}>{copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}{copied ? "Copied" : "Copy text"}</Button>
        <Button className="min-h-11 gap-2" variant="outline" disabled={busy || !text} onClick={() => { void act("share"); }}><Share2 className="size-4" aria-hidden="true" />Share</Button>
        {lineUrl && <Button className="min-h-11" variant="outline" asChild><a href={lineUrl} target="_blank" rel="noopener noreferrer">LINE</a></Button>}
        <Button className="min-h-11" variant="ghost" disabled={busy || !text} onClick={() => { void act("facebook"); }}>Copy for Facebook</Button>
        <Button className="min-h-11 gap-2" variant="ghost" disabled={busy || !text} onClick={() => { void act("download"); }}><Download className="size-4" aria-hidden="true" />TXT</Button>
      </div>
      {!lineUrl && <p className="mt-2 text-xs text-muted-foreground">For this longer post, use Copy text or Share to send the full message to LINE.</p>}
      <div className="mt-2 text-sm" role="status" aria-live="polite">{feedback}{facebook && <a href={facebook.url} target="_blank" rel="noopener noreferrer" className="mt-2 block font-medium underline underline-offset-4">Open Facebook and paste</a>}</div>
    </div>
  </section>;
}

function MatchOutlook({ match }: { match: MatchPreview }) {
  return <article aria-label={`${match.home.team.team_name} v ${match.away.team.team_name}`} className="comet-glass min-w-0 rounded-2xl border p-3 shadow-sm">
    <div className="mb-3 flex items-start justify-between gap-2 text-xs text-muted-foreground"><span className="font-medium">GW{match.gw}</span><time className="text-right" dateTime={match.kickoff_time ?? undefined}>{match.kickoff_time ? <><span className="block">{utc(match.kickoff_time).slice(0, 10)}</span><span className="block">{utc(match.kickoff_time).slice(11)}</span></> : "Kickoff to be confirmed"}</time></div>
    <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-1">
      {[match.home, match.away].map((side, index) => <div key={side.team.team_code} className={`row-start-1 min-w-0 text-center ${index === 0 ? "col-start-1" : "col-start-3"}`}>
        <div className="mb-2 flex flex-col items-center gap-1"><TeamBadge teamCode={side.team.team_code} shortName={side.team.short_name} size="md" /><span className="text-[10px] font-semibold tracking-wide text-muted-foreground">{index ? "AWAY" : "HOME"}</span></div>
        <h3 className="flex min-h-8 items-center justify-center text-xs font-semibold leading-4">{side.team.team_name}</h3>
        <div className="mt-2 tabular-nums" role="group" aria-label={`${side.team.team_name} goal outlook`}>
          <p className="text-4xl font-semibold leading-none tracking-tight"><span className="sr-only">Rounded expected goals: </span><span>{side.forecast.lambda_for === null ? "—" : Math.round(side.forecast.lambda_for)}</span></p>
          {side.forecast.lambda_for !== null && <p className="mt-1 text-xs font-normal text-muted-foreground"><span className="sr-only">Published expected goals: </span><span>({goal(side.forecast.lambda_for)})</span></p>}
        </div>
      </div>)}
      <span className="col-start-2 row-start-1 text-[10px] font-medium text-muted-foreground">vs</span>
    </div>
    <div className="mt-3 rounded-lg bg-emerald-50 px-2 py-2 text-center dark:bg-emerald-950/30">
      <p className="text-xs text-emerald-900 dark:text-emerald-200">Clean-sheet chance</p>
      <div className="mt-1 grid grid-cols-2 gap-4 text-sm font-semibold tabular-nums"><span>{chance(match.home.forecast.probability_clean_sheet)}</span><span>{chance(match.away.forecast.probability_clean_sheet)}</span></div>
    </div>
  </article>;
}

export function GwAnalysisPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [stats, setStats] = useState<StatsState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [gw, setGw] = useState<number | null>(null);
  const [language, setLanguage] = useState<Language>("th");
  useEffect(() => {
    let active = true;
    Promise.all([loadFixtureMatrix(), loadSummary().catch(() => null)]).then(([data, summary]) => {
      if (active) setState({ status: "ready", data, latestRun: summary?.latest_run?.run_id ?? null });
    }).catch(() => { if (active) setState({ status: "unavailable" }); });
    loadSdpStats().then(data => { if (active) setStats({ status: "ready", data }); }).catch(() => { if (active) setStats({ status: "unavailable" }); });
    return () => { active = false; };
  }, []);
  const teams = useMemo(() => state.status === "ready" ? state.data.teams : [], [state]);
  const runs = [...new Map(teams.map(team => [team.run_id, { id: team.run_id, season: team.season, asOf: team.as_of }])).values()];
  const defaultRun = state.status === "ready" && runs.some(run => run.id === state.latestRun) ? state.latestRun : runs.at(-1)?.id;
  const selectedRun = runs.some(run => run.id === runId) ? runId : defaultRun;
  const runTeams = useMemo(() => teams.filter(team => team.run_id === selectedRun), [teams, selectedRun]);
  const built = useMemo(() => buildMatchPreviews(runTeams), [runTeams]);
  const gameweeks = [...new Set(runTeams.flatMap(team => team.fixtures.map(fixture => fixture.gw)))].filter(value => Number.isInteger(value) && value >= 1 && value <= 38).sort((a, b) => a - b);
  const selectedGw = gw != null && gameweeks.includes(gw) ? gw : gameweeks[0];
  const matches = built.matches.filter(match => match.gw === selectedGw);
  const selectedSeason = runTeams[0]?.season;
  const scheduleTeams = state.status === "ready" ? state.data.schedule.teams.filter(team => team.season === selectedSeason) : [];
  const expectedFixtureIds = scheduleTeams.length ? [...new Set(scheduleTeams.flatMap(team => team.fixtures.filter(fixture => fixture.gw === selectedGw).map(fixture => fixture.fixture)))].sort((a, b) => a - b) : undefined;
  const briefing = selectedGw == null ? null : buildGwBriefing({ matches, gw: selectedGw, language, stats: stats.status === "ready" ? stats.data : null,
    exportCreatedAt: state.status === "ready" ? state.data.manifest?.source.export_created_at ?? state.data.schedule.export_created_at : null, expectedFixtureIds });
  const sharedText = briefing?.text ? `${selectedRun?.startsWith("DEMO-") ? "DEMO · Synthetic preview only. Not current football forecasts.\n\n" : ""}${briefing.text}` : "";
  const sides = matches.flatMap(match => [match.home, match.away]);
  const attack = [...sides].filter(side => side.forecast.lambda_for !== null).sort((a, b) => b.forecast.lambda_for! - a.forecast.lambda_for!)[0];
  const defence = [...sides].filter(side => side.forecast.probability_clean_sheet !== null).sort((a, b) => b.forecast.probability_clean_sheet! - a.forecast.probability_clean_sheet!)[0];

  return <div className="mx-auto w-full max-w-7xl space-y-6 p-4 pb-12 lg:p-6">
    <header className="comet-hero relative overflow-hidden rounded-2xl border p-5 text-foreground sm:p-7">
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div className="max-w-xl"><p className="mb-3 text-xs font-semibold uppercase tracking-[0.2em] text-sidebar-accent-foreground">The Comet · matchweek outlook</p><h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">Score Prediction</h1><p className="mt-3 text-sm leading-relaxed text-muted-foreground">The games, the goal outlook, and a take you can share. A little context before you pick your XI.</p></div>
        {selectedGw != null && <div className="rounded-xl border border-border px-5 py-3"><p className="text-xs text-muted-foreground">{selectedSeason}</p><p className="mt-1 text-3xl font-semibold tracking-tight">GW{selectedGw}</p></div>}
      </div>
      <a href="#matchweek-analysis" onClick={event => { event.preventDefault(); document.getElementById("matchweek-analysis")?.scrollIntoView({ block: "start" }); }} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-lg bg-secondary/70 px-4 text-sm font-medium hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2">Read & share the briefing<ArrowDown className="size-4" aria-hidden="true" /></a>
    </header>
    {selectedRun?.startsWith("DEMO-") && <p role="note" className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100">DEMO · Synthetic preview data. These are not current football forecasts.</p>}
    {state.status === "loading" ? <p role="status" className="rounded-xl border p-6 text-sm text-muted-foreground">Loading the matchweek outlook…</p> : state.status === "unavailable" ? <div role="status" className="rounded-xl border border-dashed p-6"><h2 className="font-semibold">This matchweek is not available yet</h2><p className="mt-2 text-sm text-muted-foreground">The forecast could not be loaded. Please try again later.</p></div> : <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-wrap items-end gap-4"><label className="flex flex-col gap-1.5 text-xs font-medium">Gameweek<select className={fieldClass} value={selectedGw ?? ""} disabled={!gameweeks.length} onChange={event => setGw(Number(event.target.value))}>{!gameweeks.length && <option value="">Unavailable</option>}{gameweeks.map(value => <option key={value} value={value}>GW{value}</option>)}</select></label><p className="pb-3 text-xs text-muted-foreground">Forecast dated {utc(runTeams[0]?.as_of ?? "")}</p></div>
        <div className="flex gap-1 rounded-lg border p-1" role="group" aria-label="Post language">{(["th", "en"] as const).map(value => <Button key={value} className="min-h-11 px-4" variant={language === value ? "secondary" : "ghost"} aria-pressed={language === value} onClick={() => setLanguage(value)}>{value === "th" ? "ไทย" : "English"}</Button>)}</div>
      </div>
      {matches.length > 0 && <div className="grid gap-3 sm:grid-cols-3">
        <section className="rounded-xl border bg-card p-4"><p className="text-xs font-medium text-muted-foreground">Games in this view</p><p className="mt-2 text-2xl font-semibold tabular-nums">{matches.length}{expectedFixtureIds && <span className="text-sm font-normal text-muted-foreground"> / {expectedFixtureIds.length} scheduled</span>}</p><p className="mt-1 text-xs text-muted-foreground">{selectedSeason} · GW{selectedGw}</p></section>
        <section className="rounded-xl border bg-amber-50/50 p-4 dark:bg-amber-950/20"><p className="flex items-center gap-2 text-xs font-medium text-amber-950 dark:text-amber-200"><Target className="size-4" aria-hidden="true" />Highest goal estimate</p><p className="mt-2 text-xl font-semibold">{attack?.team.team_name ?? "Unavailable"}</p><p className="mt-1 text-sm text-muted-foreground">{attack ? `${goal(attack.forecast.lambda_for)} expected goals · ${attack.forecast.was_home ? "home" : "away"} vs ${attack.forecast.opponent_short_name}` : "No measured estimate"}</p></section>
        <section className="rounded-xl border bg-emerald-50/50 p-4 dark:bg-emerald-950/20"><p className="flex items-center gap-2 text-xs font-medium text-emerald-950 dark:text-emerald-200"><ShieldCheck className="size-4" aria-hidden="true" />Highest clean-sheet chance</p><p className="mt-2 text-xl font-semibold">{defence?.team.team_name ?? "Unavailable"}</p><p className="mt-1 text-sm text-muted-foreground">{defence ? `${chance(defence.forecast.probability_clean_sheet)} · ${defence.forecast.was_home ? "home" : "away"} vs ${defence.forecast.opponent_short_name}` : "No measured estimate"}</p></section>
      </div>}
      <section aria-labelledby="fixtures-heading" className="@container"><div className="mb-2 flex flex-wrap items-baseline justify-between gap-2"><h2 id="fixtures-heading" className="text-xl font-semibold tracking-tight">The fixture outlook</h2><a href="#fixtures" className="inline-flex min-h-11 items-center gap-1 text-sm font-medium underline-offset-4 hover:underline">Fixture calendar<ArrowUpRight className="size-4" aria-hidden="true" /></a></div><p className="mb-3 text-sm text-muted-foreground">Rounded goal averages, with the original estimates underneath in parentheses. These are not exact-score picks.</p><div className="grid grid-cols-1 gap-3 @min-[440px]:grid-cols-2 @min-[700px]:grid-cols-3 @min-[960px]:grid-cols-5">{matches.map(match => <MatchOutlook key={match.fixture} match={match} />)}</div>{!matches.length && <p className="rounded-xl border border-dashed p-6 text-sm text-muted-foreground">No complete match forecasts are available for this gameweek.</p>}</section>
      {stats.status === "unavailable" && <p className="text-sm text-muted-foreground">Recent team statistics are unavailable. The briefing still includes the published goal outlook.</p>}
      {stats.status === "loading" ? <p role="status" className="rounded-xl border p-4 text-sm text-muted-foreground">Loading team statistics for the briefing… Sharing will be ready when this finishes.</p> : sharedText && <ShareBriefing key={`${selectedRun}/${selectedGw}/${language}/${sharedText}`} text={sharedText} language={language} />}
      <details className="rounded-xl border bg-muted/20 p-4 text-xs text-muted-foreground"><summary className="min-h-6 cursor-pointer font-medium focus-visible:outline-2">Sources & how to read this</summary><div className="mt-4 space-y-3 break-words leading-relaxed"><p>Goal estimates are averages, not scoreline picks or guaranteed outcomes. Clean-sheet chances are team probabilities, not an individual player's chance of earning clean-sheet points. Availability is not folded into these estimates.</p><label className="flex max-w-xl flex-col gap-1.5 font-medium">Forecast record<select className={fieldClass} value={selectedRun ?? ""} onChange={event => { setRunId(event.target.value); setGw(null); }}>{!runs.length && <option value="">Unavailable</option>}{runs.map(run => <option key={run.id} value={run.id}>{run.season} · {utc(run.asOf)} · {run.id.slice(0, 10)}</option>)}</select></label><p>Record: {selectedRun ?? "Unavailable"}. A selected GW may be historical; selection does not establish that it is the next deadline.</p><p>Observed statistics updated: {stats.status === "ready" ? utc(stats.data.as_of) : "Unavailable"}. They may be newer than the forecast.</p><p>{briefing?.coverage}</p>{briefing?.warnings.map(warning => <p key={warning}>{warning}</p>)}{!!built.rejected.length && <p>{built.rejected.length} match(es) omitted because their published sides could not be reconciled.</p>}<p>The current schedule identifies coverage gaps; it does not replace saved forecasts. AI-authored editorial analysis is not connected. The copyable briefing contains published facts only.</p></div></details>
    </>}
  </div>;
}
