import { useEffect, useMemo, useState } from "react";
import { MessageSquareText } from "lucide-react";
import { loadPlayerActuals, loadPlayerProvisionalActuals } from "@/data/load";
import { loadNewsFeed, type PublicNewsFeed } from "@/data/newsFeed";
import { loadRestSummary, type RestSummary } from "@/data/restSummary";
import type { FixtureScheduleOverlay, PlayerObservedActualsRecord, PlayerRecord, TeamRecord } from "@/data/types";
import { mergePlayerActualRecords } from "@/lib/playerActuals";
import { buildSummaryBriefing, type BriefingLanguage } from "@/lib/summaryBriefing";
import { ShareBriefing } from "./ShareBriefing";
import { Button } from "./ui/button";

interface Props {
  teams: TeamRecord[];
  players: PlayerRecord[];
  schedule: FixtureScheduleOverlay;
  run: { run_id: string; season: string };
  gw: number | null;
}
type Reports = { status: "loading" } | { status: "ready"; news: PublicNewsFeed | null; rest: RestSummary | null; actuals: PlayerObservedActualsRecord[] | null };

/** Load public context and points history only when requested. No SDP bundle or AI request. */
export function SummaryGwBriefing(props: Props) {
  const [opened, setOpened] = useState(false);
  const [language, setLanguage] = useState<BriefingLanguage>("en");
  return <div className="min-w-0 space-y-3">
    <section aria-labelledby="summary-briefing-heading" className="comet-glass rounded-2xl border p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 id="summary-briefing-heading" className="flex items-center gap-2 text-base font-semibold"><MessageSquareText className="size-4" aria-hidden="true" />Next GW briefing{props.gw === null ? "" : ` · GW${props.gw}`}</h2>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">One message for LINE or Facebook: each match’s score outlook, then the home team’s @FFScout news and player rest days, followed by the away team’s news and rest days. Midweek minutes and every double-gameweek leg are included.</p></div>
        <Button className="min-h-11" disabled={props.gw === null} onClick={() => setOpened(!opened)}>{opened ? "Hide briefing" : "Create GW briefing"}</Button>
      </div>
      {props.gw === null && <p className="mt-2 text-sm text-muted-foreground">The next GW is not covered by this forecast.</p>}
      {opened && <div className="mt-4 flex flex-wrap items-center gap-2" role="group" aria-label="Briefing language">
        {(["en", "th"] as const).map(value => <Button key={value} variant={language === value ? "secondary" : "ghost"} aria-pressed={language === value} onClick={() => setLanguage(value)}>{value === "en" ? "English" : "ไทย"}</Button>)}
        <span className="text-xs text-muted-foreground">Top 5 per team by current-season points per appearance; matching rest days are grouped.</span>
      </div>}
    </section>
    {opened && props.gw !== null && <LoadedBriefing key={`${props.run.run_id}/${props.run.season}/${props.gw}`} {...props} gw={props.gw} language={language} />}
  </div>;
}

function LoadedBriefing({ language, ...props }: Props & { gw: number; language: BriefingLanguage }) {
  const { teams, players, schedule, run, gw } = props;
  const [reports, setReports] = useState<Reports>({ status: "loading" });
  const [revision, setRevision] = useState(0);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    let active = true;
    Promise.all([
      loadNewsFeed().catch(() => null), loadRestSummary().catch(() => null),
      loadPlayerActuals().catch(() => null), loadPlayerProvisionalActuals().catch(() => null),
    ]).then(([news, rest, finalized, provisional]) => {
      if (!active) return;
      let actuals: PlayerObservedActualsRecord[] | null = null;
      if (finalized && provisional && (provisional.captured_at === null || Date.parse(provisional.captured_at) <= Date.now())) {
        try {
          // Retain only this season after the standard, identity-checked display merge.
          actuals = mergePlayerActualRecords(finalized.players.filter(row => row.season === run.season), provisional.players.filter(row => row.season === run.season));
        } catch { /* Conflicting observations withhold ranking; score/news text remains usable. */ }
      }
      setReports({ status: "ready", news, rest, actuals }); setNow(Date.now());
    });
    return () => { active = false; };
  }, [revision, run.season]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const briefing = useMemo(() => reports.status === "ready" ? buildSummaryBriefing({ teams, players, schedule, run, gw, ...reports, language, now }) : null,
    [teams, players, schedule, run, gw, reports, language, now]);
  if (reports.status === "loading") return <p role="status" className="rounded-xl border p-4 text-sm text-muted-foreground">Preparing all fixtures, team news and rest reports…</p>;
  return <>
    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
      <p>{briefing?.fixtures ?? 0} fixtures · {briefing?.forecasts ?? 0} matching forecasts. {reports.news === null ? "News unavailable. " : ""}{reports.rest === null ? "Rest report unavailable. " : ""}{reports.actuals === null ? "Key-player ranking unavailable." : ""}</p>
      <Button variant="ghost" onClick={() => { setReports({ status: "loading" }); setRevision(value => value + 1); }}>Refresh reports</Button>
    </div>
    {briefing?.text ? <ShareBriefing key={`${language}/${briefing.text}`} text={briefing.text} language={language} title={language === "th" ? `สรุป GW${props.gw} พร้อมแชร์` : `GW${props.gw} · ready to share`} />
      : <p role="status" className="rounded-xl border p-4 text-sm text-muted-foreground">{briefing?.warnings.join(" ") ?? "The briefing is unavailable."}</p>}
  </>;
}
