import { useEffect, useMemo, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { loadFixtureMatrix, loadSummary, type FixtureMatrixData } from "@/data/load";
import { loadSdpStats, type SdpStatsData } from "@/data/sdpStats";
import { buildMatchPreviews } from "@/lib/matchPreview";
import { buildGwBriefing } from "@/lib/gwBriefing";
import { copyGwBriefing, downloadGwBriefing, gwBriefingLineUrl, prepareGwBriefingFacebook, shareGwBriefing } from "@/lib/gwBriefingShare";

type Language = "en" | "th";
type PageState = { status: "loading" } | { status: "unavailable" } | { status: "ready"; data: FixtureMatrixData; latestRun: string | null };
type StatsState = { status: "loading" | "unavailable" } | { status: "ready"; data: SdpStatsData };
const fieldClass = "min-h-10 max-w-full rounded-md border bg-background px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2";
const utc = (value: string) => Number.isFinite(Date.parse(value)) ? `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC` : "Timestamp unavailable";

function BriefingDraft({ text, language, sourceContext }: { text: string; language: Language; sourceContext: string }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [editBase, setEditBase] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [editedAt, setEditedAt] = useState<string | null>(null);
  const [reviewedAt, setReviewedAt] = useState<string | null>(null);
  const [reviewSource, setReviewSource] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [facebook, setFacebook] = useState<{ url: string; instruction: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const version = useRef(0);
  useEffect(() => () => { version.current += 1; }, []);
  const changed = draft !== null && draft !== editBase;
  const reviewed = reviewedAt !== null && reviewSource === sourceContext;
  const disclosure = !changed ? "" : language === "th"
    ? `\n\n— ฉบับบรรณาธิการของเจ้าของ —\nเวลาแก้ไข: ${editedAt}\nเหตุผล: ${reason.trim()}\n${reviewed ? `เจ้าของตรวจทานแล้ว: ${reviewedAt}` : "รอเจ้าของตรวจทาน"}\nข้อความหรือสกอร์ที่เพิ่มเป็นความเห็นของเจ้าของ แยกจากผลคาดการณ์ของโมเดลที่เผยแพร่แล้ว\n${sourceContext}`
    : `\n\n— Owner editorial draft —\nEdited at: ${editedAt}\nReason: ${reason.trim()}\n${reviewed ? `Owner-reviewed at: ${reviewedAt}` : "Pending owner review"}\nThe owner edited this text; any added commentary or scoreline is editorial opinion, separate from the published model forecast.\n${sourceContext}`;
  const content = changed ? draft : text;
  const shareText = content + disclosure;
  const canShare = !!content.trim() && (!changed || (!!reason.trim() && reviewed)) && !busy;
  const lineUrl = shareText.trim() ? gwBriefingLineUrl(shareText) : null;
  const invalidateAction = () => { version.current += 1; setFeedback(""); setFacebook(null); setBusy(false); };
  const act = async (action: "copy" | "share" | "facebook" | "download") => {
    if (!canShare) return;
    const current = ++version.current;
    setBusy(true); setFeedback(""); setFacebook(null);
    try {
      let message = "";
      if (action === "copy") { await copyGwBriefing(shareText); message = "Full briefing copied."; }
      else if (action === "share") {
        const result = await shareGwBriefing(shareText);
        message = result === "shared" ? "Opened sharing app." : result === "copied" ? "Full briefing copied." : "Sharing cancelled.";
      } else if (action === "facebook") {
        const prepared = await prepareGwBriefingFacebook(shareText);
        if (current === version.current) setFacebook(prepared);
        message = prepared.instruction;
      } else { downloadGwBriefing(shareText); message = "Text download started."; }
      if (current === version.current) setFeedback(message);
    } catch (error) {
      if (current === version.current) setFeedback(error instanceof Error ? error.message : "Sharing is unavailable. Try copying or downloading the text.");
    } finally { if (current === version.current) setBusy(false); }
  };

  return <div className="space-y-4">
    <div className="flex flex-wrap gap-2" aria-label="Share briefing">
      <Button className="min-h-10" disabled={!canShare} onClick={() => { void act("copy"); }}>Copy</Button>
      <Button className="min-h-10" variant="outline" disabled={!canShare} onClick={() => { void act("share"); }}>Share</Button>
      {canShare && lineUrl ? <Button className="min-h-10" variant="outline" asChild><a href={lineUrl} target="_blank" rel="noopener noreferrer">LINE</a></Button> : <Button className="min-h-10" variant="outline" disabled>LINE</Button>}
      <Button className="min-h-10" variant="outline" disabled={!canShare} onClick={() => { void act("facebook"); }}>Copy for Facebook</Button>
      <Button className="min-h-10" variant="outline" disabled={!canShare} onClick={() => { void act("download"); }}>Download TXT</Button>
    </div>
    {!lineUrl && !!shareText.trim() && <p className="text-xs text-muted-foreground">This post is too long for the LINE link. Use Copy, Share or Download TXT for the complete text.</p>}
    <div className="space-y-2 text-sm" role="status" aria-live="polite">
      {feedback && <p>{feedback}</p>}
      {facebook && <a href={facebook.url} target="_blank" rel="noopener noreferrer" className="inline-block py-1 font-medium underline underline-offset-4">Open Facebook and paste</a>}
    </div>
    <div className="space-y-2">
      <p className="text-xs font-medium">{changed ? reviewed ? "Editorial analysis · owner-reviewed" : "Editorial analysis · pending owner review" : "Published fact draft"}</p>
      <div className="flex flex-wrap items-center gap-3"><label className="flex min-h-9 items-center gap-2 text-sm font-medium"><input type="checkbox" checked={editing} onChange={event => {
        setEditing(event.target.checked);
        if (event.target.checked && draft === null) { setDraft(text); setEditBase(text); }
      }} />Edit draft</label>{(editing || changed) && <Button variant="ghost" onClick={() => {
        setEditing(false); setDraft(null); setEditBase(null); setReason(""); setEditedAt(null); setReviewedAt(null); setReviewSource(null); invalidateAction();
      }}>Reset draft</Button>}</div>
      <p className="text-xs text-muted-foreground">Edits stay in this tab. Changing the forecast, GW or language resets them. Added commentary belongs to your editorial draft.</p>
      {editing && <p className="text-xs text-muted-foreground">Write or paste your proposed article and scorelines. Add a reason and review your editorial draft before sharing.</p>}
      {changed && <label className="flex flex-col gap-1 text-xs font-medium">Edit reason (required before sharing)
        <input className={fieldClass} value={reason} maxLength={200} onChange={event => { setReason(event.target.value); setReviewedAt(null); invalidateAction(); }} placeholder="For example: added my match commentary" />
      </label>}
      {changed && <label className="flex min-h-9 items-center gap-2 text-xs font-medium"><input type="checkbox" checked={reviewed} disabled={!reason.trim()} onChange={event => { setReviewedAt(event.target.checked ? new Date(Date.now()).toISOString() : null); setReviewSource(event.target.checked ? sourceContext : null); invalidateAction(); }} />I reviewed this editorial draft</label>}
    </div>
    {editing ? <div className="space-y-3">
      <label className="sr-only" htmlFor="gw-analysis-draft">Briefing draft text</label>
      <textarea id="gw-analysis-draft" className="min-h-[32rem] w-full resize-y rounded-xl border bg-white p-5 text-base leading-relaxed text-slate-900 focus-visible:outline-2 focus-visible:outline-offset-2 sm:p-7" value={draft ?? text} onChange={event => {
        if (editBase === null) setEditBase(text);
        setDraft(event.target.value); setEditedAt(new Date(Date.now()).toISOString()); setReviewedAt(null); invalidateAction();
      }} />
      {changed && <p className="whitespace-pre-wrap text-xs leading-relaxed text-muted-foreground" aria-label="Editorial disclosure">{disclosure.trim()}</p>}
    </div> : <article aria-label="Gameweek briefing text" lang={language} className="whitespace-pre-wrap break-words rounded-xl border bg-white p-5 text-base leading-relaxed text-slate-900 shadow-sm sm:p-7">{shareText}</article>}
  </div>;
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
    loadSdpStats().then(data => { if (active) setStats({ status: "ready", data }); })
      .catch(() => { if (active) setStats({ status: "unavailable" }); });
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
  const selectedSeason = runTeams[0]?.season;
  const scheduleTeams = state.status === "ready" ? state.data.schedule.teams.filter(team => team.season === selectedSeason) : [];
  const expectedFixtureIds = scheduleTeams.length ? [...new Set(scheduleTeams.flatMap(team => team.fixtures.filter(fixture => fixture.gw === selectedGw).map(fixture => fixture.fixture)))].sort((a, b) => a - b) : undefined;
  const briefing = selectedGw == null ? null : buildGwBriefing({ matches: built.matches.filter(match => match.gw === selectedGw), gw: selectedGw, language,
    stats: stats.status === "ready" ? stats.data : null,
    exportCreatedAt: state.status === "ready" ? state.data.manifest?.source.export_created_at ?? state.data.schedule.export_created_at : null,
    expectedFixtureIds });
  const sourceContext = language === "th"
    ? `บริบทแหล่งข้อมูล: ${selectedSeason} GW${selectedGw}\nชุดคาดการณ์: ${selectedRun} · ตัดข้อมูล ${utc(runTeams[0]?.as_of ?? "")}\nสถิติย้อนหลังเผยแพร่: ${stats.status === "ready" ? utc(stats.data.as_of) : "ไม่มีข้อมูล"}\nhttps://www.thecometfpl.com/`
    : `Source context: ${selectedSeason} GW${selectedGw}\nForecast record: ${selectedRun} · cutoff ${utc(runTeams[0]?.as_of ?? "")}\nObserved statistics publication: ${stats.status === "ready" ? utc(stats.data.as_of) : "Unavailable"}\nhttps://www.thecometfpl.com/`;

  return <div className="mx-auto w-full max-w-4xl space-y-5 p-4 pb-10 lg:p-6">
    <header className="space-y-2"><h1 className="text-xl font-semibold">GW Analysis</h1><p className="text-sm text-muted-foreground">A gameweek post to read, edit and share.</p><p className="text-xs text-muted-foreground">AI editorial writer is pending and not connected; published facts ready to copy.</p></header>
    {state.status === "loading" ? <p role="status" className="text-sm text-muted-foreground">Loading published forecasts…</p> : state.status === "unavailable" ? <p role="status" className="text-sm text-muted-foreground">Published forecasts are unavailable in this generation.</p> : <>
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex min-w-0 flex-col gap-1 text-xs font-medium">Forecast record
          <select className={fieldClass} value={selectedRun ?? ""} onChange={event => { setRunId(event.target.value); setGw(null); }}>
            {!runs.length && <option value="">Unavailable</option>}
            {runs.map(run => <option key={run.id} value={run.id}>{run.season} · {utc(run.asOf)} · {run.id.slice(0, 10)}</option>)}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs font-medium">Gameweek
          <select className={fieldClass} value={selectedGw ?? ""} disabled={!gameweeks.length} onChange={event => setGw(Number(event.target.value))}>
            {!gameweeks.length && <option value="">Unavailable</option>}{gameweeks.map(value => <option key={value} value={value}>GW{value}</option>)}
          </select>
        </label>
        <div className="flex gap-1" role="group" aria-label="Post language">{(["th", "en"] as const).map(value => <Button key={value} className="min-h-10" variant={language === value ? "secondary" : "ghost"} aria-pressed={language === value} onClick={() => setLanguage(value)}>{value === "th" ? "ไทย" : "English"}</Button>)}</div>
      </div>
      {stats.status === "loading" && <p className="text-xs text-muted-foreground">Loading optional observed statistics; the published forecast text is already available.</p>}
      {stats.status === "unavailable" && <p className="text-xs text-muted-foreground">Observed statistics unavailable; the post keeps the published forecast and labels the gap.</p>}
      {briefing?.text ? <BriefingDraft key={`${selectedRun}/${selectedGw}/${language}`} text={briefing.text} language={language} sourceContext={sourceContext} /> : <p role="status" className="rounded-xl border border-dashed p-5 text-sm text-muted-foreground">No complete published match evidence is available for this scope.</p>}
      <details className="rounded-lg border p-3 text-xs text-muted-foreground"><summary className="cursor-pointer font-medium focus-visible:outline-2">Sources and scope</summary><div className="mt-3 space-y-2 break-words">
        <p>Recorded forecast: {selectedRun ?? "Unavailable"}. Selecting a GW does not establish that it is the current upcoming gameweek.</p>
        {briefing && <p>{briefing.coverage}</p>}
        {briefing?.warnings.map(warning => <p key={warning}>{warning}</p>)}
        {!!built.rejected.length && <p>{built.rejected.length} fixture(s) excluded because their published sides could not be reconciled.</p>}
        <p>Current schedule fixtures identify coverage gaps only; they do not replace the recorded forecast fixtures. Editorial edits remain separate from model data.</p>
      </div></details>
    </>}
  </div>;
}
