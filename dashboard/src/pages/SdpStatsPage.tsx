import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowDown, ArrowRight, ArrowUp, ArrowUpRight, Check, Download, Info, RotateCcw, Search, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import { AnalyticsScatter } from "@/components/AnalyticsScatter";
import { DecisionTableFullscreen } from "@/components/DecisionTableFullscreen";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import { MetricCell, TeamComparison, TeamProfile, TeamTrend } from "@/components/SdpTeamProfile";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { loadSdpStats } from "@/data/sdpStats";
import type { SdpMatch, SdpStatsData } from "@/data/sdpStats";
import { dashboardTeamStatus, metricId, metricValue, sdpCsv, selectSdpEntities, sortSdpEntities } from "@/lib/sdpStats";
import type { SdpFilters, SdpMode } from "@/lib/sdpStats";
import { teamBenchmark, teamMetricGroups, teamMetricLabel } from "@/lib/sdpTeamAnalysis";
import "./SdpStatsPage.css";

const date = (value: string | null | undefined) => value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value)) : "Unavailable";
const stamp = (value: string | null) => value ? `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC` : "Unavailable";

function Control({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (value: string) => void }) {
  return <label className="sdp-control"><span>{label}</span><select aria-label={label} value={value} onChange={e => onChange(e.target.value)}>{options.map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></label>;
}

function initialFilters(rows: SdpMatch[]): SdpFilters {
  const season = [...new Set(rows.map(row => row.season))].sort().at(-1) ?? "";
  const gws = rows.filter(row => row.season === season).map(row => row.gw);
  return { season, from: gws.length ? Math.min(...gws) : 1, to: gws.length ? Math.max(...gws) : 1, recent: "5", venue: "all", team: "all", search: "", position: "all", minMinutes: 0 };
}

function ReadyPage({ data }: { data: SdpStatsData }) {
  const defaults = initialFilters(data.team_matches);
  const [filters, setFilters] = useState(defaults);
  const [group, setGroup] = useState("overview");
  const [mode, setMode] = useState<SdpMode>("per_match");
  const [sortKey, setSortKey] = useState("expected_goals");
  const [ascending, setAscending] = useState(false);
  const [compared, setCompared] = useState<string[]>([]);
  const [detail, setDetail] = useState<string | null>(null);
  const [showLog, setShowLog] = useState(false);
  const [chartKey, setChartKey] = useState("expected_goals");
  const logRef = useRef<HTMLElement>(null);
  const relevant = useMemo(() => data.metrics.filter(m => m.scope === "team" || m.scope === "both"), [data]);
  // Display selection never shrinks the benchmark population.
  const league = useMemo(() => selectSdpEntities(data.team_matches, "team", { ...filters, team: "all", search: "" }), [data, filters]);
  const fullRange = useMemo(() => selectSdpEntities(data.team_matches, "team", { ...filters, team: "all", search: "", recent: "all" }), [data, filters]);
  const filtered = league.filter(team => (filters.team === "all" || String(team.teamCode) === filters.team) && `${team.name} ${team.clubs}`.toLocaleLowerCase().includes(filters.search.trim().toLocaleLowerCase()));
  const category = teamMetricGroups.find(g => g.id === group) ?? teamMetricGroups[0];
  const metrics = relevant.filter(m => group === "all" || m.source === "sdp" && (category.keys as readonly string[]).includes(m.key));
  const sortMetric = relevant.find(m => metricId(m) === sortKey || m.key === sortKey) ?? null;
  const ordered = sortSdpEntities(filtered, sortMetric, mode, ascending);
  const selected = filtered.find(team => team.id === detail) ?? filtered[0];
  const comparisons = compared.flatMap(id => filtered.find(team => team.id === id) ?? []);
  const profileMetrics = ["expected_goals", "shots", "possession", "expected_goals_allowed"].flatMap(key => relevant.find(m => m.source === "sdp" && m.key === key) ?? []);
  const xMetric = profileMetrics.find(m => m.key === "expected_goals" && m.verified_semantics);
  const yMetric = profileMetrics.find(m => m.key === "expected_goals_allowed" && m.verified_semantics);
  const chartMetric = relevant.find(m => metricId(m) === chartKey || m.key === chartKey) ?? metrics[0];
  const scatterPoints = xMetric && yMetric ? filtered.flatMap(team => {
    const x = metricValue(team.rows, xMetric, "per_match").value, y = metricValue(team.rows, yMetric, "per_match").value;
    return x !== null && y !== null ? [{ id: team.id, label: team.name, shortLabel: team.rows.at(-1)?.team_short_name, x, y, groupLabel: `${team.rows.length} matches · displayed values, including marked corrections`, color: team.id === selected?.id ? "var(--sdp-accent)" : "var(--sdp-series-2)" }] : [];
  }) : [];
  const seasons = [...new Set(data.team_matches.map(row => row.season))].sort().reverse();
  const seasonRows = data.team_matches.filter(row => row.season === filters.season);
  const weeks = [...new Set(seasonRows.map(row => row.gw))].sort((a, b) => a - b);
  const seasonTeams = [...new Map(seasonRows.map(row => [String(row.team_code), row.team_name])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const fixtureRows = new Map<number, SdpMatch[]>();
  for (const row of seasonRows) fixtureRows.set(row.fixture, [...fixtureRows.get(row.fixture) ?? [], row]);
  const completePairs = [...fixtureRows.values()].filter(rows => rows.length === 2);
  const providerValid = completePairs.filter(rows => rows.every(row => dashboardTeamStatus(row) === "PROVIDER_VALID")).length;
  const corrected = completePairs.filter(rows => rows.every(row => dashboardTeamStatus(row) !== "INCOMPLETE") && rows.some(row => dashboardTeamStatus(row) === "OWNER_CONFIRMED_VALID")).length;
  const correctionIds = new Set(seasonRows.flatMap(row => Object.values(row.display_corrections ?? {}).filter(c => c.relation === "direct").map(c => c.correction_id)));
  const assumptions = seasonRows.reduce((sum, row) => sum + Object.keys(row.display_assumptions ?? {}).length, 0);
  const completed = data.gameweeks.filter(gw => gw.season === filters.season && gw.fixtures_completed > 0);
  const latestCovered = [...seasonRows].sort((a, b) => Date.parse(b.kickoff_time) - Date.parse(a.kickoff_time))[0];
  const completedText = completed.length ? `${completed.reduce((sum, gw) => sum + gw.fixtures_completed, 0)} across GW${completed[0].gw}–GW${completed.at(-1)!.gw}` : "Official GW finality unavailable";
  const officialIncomplete = completed.some(gw => !gw.finished);
  const patch = (value: Partial<SdpFilters>) => { setFilters(current => ({ ...current, ...value })); setShowLog(false); };
  const chooseSeason = (season: string) => {
    const gws = data.team_matches.filter(row => row.season === season).map(row => row.gw);
    patch({ season, from: Math.min(...gws), to: Math.max(...gws), team: "all", search: "" });
    setCompared([]); setDetail(null);
  };
  const reset = () => { setFilters(defaults); setGroup("overview"); setMode("per_match"); setSortKey("expected_goals"); setAscending(false); setCompared([]); setDetail(null); setShowLog(false); setChartKey("expected_goals"); };
  const weekLabel = (gw: number) => `GW${gw}${data.gameweeks.some(row => row.season === filters.season && row.gw === gw && !row.finished) ? " · in progress" : ""}`;
  const chooseComparison = (id: string) => setCompared(current => current.includes(id) ? current.filter(value => value !== id) : [...current.filter(value => filtered.some(row => row.id === value)), id].slice(0, 3));
  const exportCsv = () => {
    const url = URL.createObjectURL(new Blob([sdpCsv(ordered, metrics, mode)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = `team-observed-${filters.season}-gw${filters.from}-${filters.to}.csv`; link.click(); URL.revokeObjectURL(url);
  };
  useEffect(() => { if (showLog) logRef.current?.scrollIntoView?.({ block: "nearest" }); }, [showLog, detail]);

  return <div className="sdp-workspace mx-auto max-w-[1600px] space-y-6 p-4 sm:p-6 xl:p-8">
    <header className="sdp-hero relative overflow-hidden rounded-2xl border px-5 py-6 sm:p-8">
      <div className="relative flex flex-wrap items-start justify-between gap-5">
        <div><p className="sdp-eyebrow flex items-center gap-2"><span className="size-1.5 rounded-full bg-[var(--sdp-accent)]" />The Comet / Football observatory</p>
          <h1 className="mt-3 text-2xl font-semibold tracking-tight sm:text-4xl">Team stat from SDP</h1>
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">See how teams create, build and defend.<br className="hidden sm:block" /> Explore the numbers behind each match, in the context of the league.</p>
          <div className="mt-5 flex flex-wrap gap-2 text-xs"><span className="sdp-chip">Premier League · {filters.season}</span><span className="sdp-chip">Observed football</span><span className="sdp-chip">{officialIncomplete ? "Partial GW included" : "Completed-match data"}</span></div>
        </div>
        <div className="text-left sm:text-right"><p className="sdp-eyebrow">Dashboard refreshed</p><p className="mt-2 text-sm font-medium">{stamp(data.as_of)}</p><p className="mt-1 text-xs text-muted-foreground">Latest match: {date(latestCovered?.kickoff_time)}</p><a href="#players" className="mt-5 inline-flex min-h-10 items-center gap-2 text-sm font-medium underline-offset-4 hover:underline">Player statistics <ArrowUpRight className="size-4" aria-hidden="true" /></a></div>
      </div>
      <div className="relative mt-7 grid grid-cols-2 gap-y-5 border-t pt-5 lg:grid-cols-4">
        {[["Clubs", seasonTeams.length, "in this season's export"], ["Matches covered", fixtureRows.size, completedText], ["Dashboard-ready fixtures", `${providerValid + corrected} / ${fixtureRows.size}`, `${providerValid} SDP · ${corrected} owner-confirmed`], ["Latest covered GW", latestCovered ? `GW${latestCovered.gw}` : "—", "Season snapshot · filters below"]].map(([label, value, note]) => <div key={label} className="min-w-0 pr-3 lg:border-r lg:pl-5 lg:first:pl-0 lg:last:border-0"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</p><p className="mt-1 text-xs text-muted-foreground">{note}</p></div>)}
      </div>
    </header>
    <section className="sdp-panel p-4 sm:p-5" aria-label="Analysis filters">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2 text-sm font-medium"><SlidersHorizontal className="size-4 text-[var(--sdp-accent)]" aria-hidden="true" />Set your view</div><Button variant="ghost" size="sm" onClick={reset}><RotateCcw className="size-3.5" aria-hidden="true" />Reset filters</Button></div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Control label="Season" value={filters.season} options={seasons.map(s => [s, s])} onChange={chooseSeason} />
        <Control label="GW from" value={String(filters.from)} options={weeks.filter(gw => gw <= filters.to).map(gw => [String(gw), weekLabel(gw)])} onChange={value => patch({ from: Number(value) })} />
        <Control label="GW to" value={String(filters.to)} options={weeks.filter(gw => gw >= filters.from).map(gw => [String(gw), weekLabel(gw)])} onChange={value => patch({ to: Number(value) })} />
        <Control label="Recent history" value={filters.recent} options={[["all", "Full selected range"], ["3", "Last 3 matches"], ["5", "Last 5 matches"]]} onChange={value => patch({ recent: value as SdpFilters["recent"] })} />
        <Control label="Venue" value={filters.venue} options={[["all", "Home + away"], ["home", "Home"], ["away", "Away"]]} onChange={value => patch({ venue: value as SdpFilters["venue"] })} />
        <Control label="Team" value={filters.team} options={[["all", "All clubs"], ...seasonTeams]} onChange={value => patch({ team: value })} />
      </div>
      <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{filters.season} · GW{filters.from}–GW{filters.to} · {filters.recent === "all" ? "Full selected range" : `Up to ${filters.recent} completed matches per club`}. Shorter histories stay shorter; every double-gameweek leg counts.</p>
    </section>
    {fixtureRows.size > providerValid + corrected && <p role="note" className="rounded-lg border bg-muted/40 px-4 py-3 text-xs leading-relaxed text-muted-foreground">Some matches lack required SDP fields. Available statistics are still shown independently; an incomplete core does not mean the whole match is missing. Cells report measured / selected matches. An average stays unavailable if that metric is missing from any selected match; missing xG is never treated as zero.</p>}
    <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="sdp-eyebrow">Explore the league</p><h2 className="mt-1 text-xl font-semibold tracking-tight">The bigger picture</h2></div><p className="text-xs text-muted-foreground">Profiles and charts use per-match averages.</p></div>
    <div className="grid min-w-0 gap-5 xl:grid-cols-2">
      <section className="sdp-panel min-w-0 p-4 sm:p-5" aria-label="League comparison">
        {xMetric && yMetric ? <AnalyticsScatter title="Attack meets defence" className="border-0 p-0 shadow-none" description={`${scatterPoints.length} of ${filtered.length} visible clubs have complete paired xG coverage.`} readingNote="Further right: more xG created. Lower: less xG conceded. Dashed lines mark league medians. Tap a point for exact values; select a club below to explore its profile." points={scatterPoints} xAxis={{ label: "SDP xG created /match", displayLabel: "xG created /match →", direction: "explanatory", bounds: { min: 0 } }} yAxis={{ label: "SDP xG conceded /match", displayLabel: "xG conceded /match", direction: "explanatory", bounds: { min: 0 } }} medianX={teamBenchmark(league, xMetric, "per_match", null).median} medianY={teamBenchmark(league, yMetric, "per_match", null).median} vintageLabel={`Observed export ${data.as_of}`} provenanceLabel="Observed" vintageDisplayLabel="SDP statistics" emptyMessage="No clubs have complete xG and opponent xG in this range. Other available statistics are shown below; missing xG is not zero." horizonLabel={`${filters.season} GW${filters.from}–${filters.to}; ${filters.recent}; ${filters.venue}`} horizonDisplayLabel={`GW${filters.from}–${filters.to} · ${filters.venue}`} /> : <div className="p-5 text-sm text-muted-foreground">The attack/defence chart needs independently reconciled xG and opponent xG fields. Other measured statistics remain available below.</div>}
        <div className="mt-4 border-t pt-4"><Control label="Explore club profile" value={selected?.id ?? ""} options={filtered.map(team => [team.id, team.name])} onChange={value => { setDetail(value); setShowLog(false); }} /></div>
      </section>
      {selected ? <TeamProfile team={selected} league={league} fullRange={fullRange.find(team => team.id === selected.id)} metrics={profileMetrics} onLog={() => setShowLog(true)} /> : <div className="sdp-panel flex items-center justify-center p-8 text-sm text-muted-foreground">No clubs match this view. Reset filters to explore the league.</div>}
    </div>
    <section className="space-y-4" aria-label="Team statistics explorer">
      <div className="flex flex-wrap items-end justify-between gap-4"><div><p className="sdp-eyebrow">The detail behind the picture</p><h2 className="mt-1 text-xl font-semibold tracking-tight">Club comparison</h2></div><Button variant="outline" onClick={exportCsv} disabled={!ordered.length}><Download className="size-4" aria-hidden="true" />Export filtered CSV</Button></div>
      <div className="sdp-panel overflow-hidden">
        <div className="flex flex-wrap gap-1 border-b p-2" aria-label="Metric groups">{teamMetricGroups.map(g => <button key={g.id} type="button" className="sdp-group" aria-pressed={group === g.id} onClick={() => setGroup(g.id)}>{g.label}</button>)}</div>
        <div className="flex flex-wrap items-end justify-between gap-4 p-4">
          <label className="sdp-control min-w-0 flex-1 sm:max-w-xs"><span>Search clubs</span><span className="relative"><Search className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" aria-hidden="true" /><input aria-label="Search clubs" placeholder="Find a club…" value={filters.search} onChange={e => patch({ search: e.target.value })} className="pl-9!" /></span></label>
          <Control label="Display" value={mode} options={[["per_match", "Average per match"], ["total", "Totals"]]} onChange={value => setMode(value as SdpMode)} />
          <p className="max-w-md text-xs leading-relaxed text-muted-foreground">{category.description} Select up to 3 clubs to compare.</p>
        </div>
        <DecisionTableFullscreen label="SDP team statistics table" className="rounded-none border-x-0 border-b-0">
          {({ isFullscreen }) => <div className={isFullscreen ? "sdp-table-body sdp-table-body-fullscreen" : "sdp-table-body space-y-4"}>
            <Table aria-label="Observed SDP team statistics" className="sdp-team-table" containerClassName={isFullscreen ? "min-h-0 flex-1 overflow-auto" : "max-h-[680px]"}>
              <TableHeader className="sticky top-0 z-20 bg-muted"><TableRow>
                <TableHead className="sticky left-0 z-30 min-w-[160px] bg-muted"><button className="sdp-sort" onClick={() => { setSortKey("name"); setAscending(sortKey === "name" ? !ascending : true); }}>Club {sortKey === "name" && (ascending ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}</button></TableHead>
                <TableHead>Compare</TableHead><TableHead>Matches</TableHead>
                {metrics.map(metric => <TableHead key={metricId(metric)} aria-sort={sortMetric === metric ? ascending ? "ascending" : "descending" : "none"}><button className="sdp-sort" title={`${metric.source.toUpperCase()} · ${metric.provider_field ?? metric.key}. ${metric.verified_semantics ? metric.description ?? "Recorded statistic." : "Provider observation; not independently reconciled."}`} onClick={() => { setSortKey(metricId(metric)); setAscending(sortMetric === metric ? !ascending : false); }}>{teamMetricLabel(metric, mode)}{sortMetric === metric && (ascending ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}</button></TableHead>)}
                <TableHead>xG by match</TableHead>
              </TableRow></TableHeader>
              <TableBody>{ordered.map(team => <TableRow key={team.id} data-state={selected?.id === team.id ? "selected" : undefined}>
                <TableCell className="sticky left-0 z-10 bg-card"><button className="sdp-table-club flex items-center gap-2 text-left font-medium" onClick={() => { setDetail(team.id); setShowLog(true); }} aria-label={`View ${team.name} match detail`}><span className="sdp-club-mark" aria-hidden="true">{team.clubs}</span><span>{team.name}</span></button></TableCell>
                <TableCell><label className="sdp-table-compare inline-flex cursor-pointer items-center justify-center"><input className="size-4 accent-[var(--sdp-accent)]" type="checkbox" aria-label={`Compare ${team.name}`} checked={comparisons.some(t => t.id === team.id)} disabled={!comparisons.some(t => t.id === team.id) && comparisons.length >= 3} onChange={() => chooseComparison(team.id)} /></label></TableCell>
                <TableCell className="text-muted-foreground tabular-nums">{team.rows.length}</TableCell>
                {metrics.map(metric => <TableCell key={metricId(metric)}><MetricCell rows={team.rows} metric={metric} mode={mode} /></TableCell>)}
                <TableCell className="min-w-28">{xMetric ? <TeamTrend entity={team} metric={xMetric} compact /> : "Unavailable"}</TableCell>
              </TableRow>)}{!ordered.length && <TableRow><TableCell colSpan={metrics.length + 4} className="py-12 text-center text-muted-foreground">No observed records match these filters. Reset filters to explore the league.</TableCell></TableRow>}</TableBody>
            </Table>
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 px-3 py-2 text-xs text-muted-foreground"><span>{ordered.length} clubs · {metrics.length} metrics · click a name for its match log</span><span>Cells show measured / selected matches</span></div>
            <div className="sdp-table-details">
            <TeamComparison teams={comparisons} metrics={metrics} mode={mode} onRemove={id => setCompared(current => current.filter(value => value !== id))} />
            {selected && showLog && <section ref={logRef} className="sdp-panel m-3 p-4 sm:p-5" aria-label={`${selected.name} match detail`}>
              <div className="mb-4 flex items-start justify-between gap-3"><div><p className="sdp-eyebrow">Match notebook</p><h2 className="mt-1 text-lg font-semibold">{selected.name}</h2><p className="mt-1 text-xs text-muted-foreground">{selected.rows.length} matches · {filters.season} · individual match values</p></div><Button variant="ghost" size="icon" aria-label="Close match detail" onClick={() => setShowLog(false)}><X aria-hidden="true" /></Button></div>
              <div className="mb-4 grid gap-4 md:grid-cols-[1fr_2fr]"><div className="space-y-3"><Control label="Trend metric" value={chartMetric ? metricId(chartMetric) : ""} options={relevant.map(m => [metricId(m), `${m.source.toUpperCase()} · ${m.label}`])} onChange={setChartKey} /><p className="text-xs leading-relaxed text-muted-foreground">Chronological observations. Missing values break the line. Corrections and assumed zeros retain their source marks.</p></div>{chartMetric && <TeamTrend entity={selected} metric={chartMetric} />}</div>
              <Table aria-label={`${selected.name} observed match log`} containerClassName="max-h-[440px]"><TableHeader className="sticky top-0 z-10 bg-muted"><TableRow><TableHead>Match</TableHead><TableHead>Opponent</TableHead><TableHead>Score · FPL</TableHead>{metrics.map(m => <TableHead key={metricId(m)}>{m.source.toUpperCase()} · {m.label}</TableHead>)}<TableHead>Evidence</TableHead></TableRow></TableHeader><TableBody>{[...selected.rows].reverse().map(row => <TableRow key={row.fixture}><TableCell><p className="font-medium">{row.season} · GW{row.gw}</p><p className="mt-1 text-xs text-muted-foreground">{date(row.kickoff_time)}</p></TableCell><TableCell>{row.opponent_short_name} <span className="text-muted-foreground">({row.was_home ? "H" : "A"})</span></TableCell><TableCell>{row.fpl?.goals_scored != null && row.fpl?.goals_conceded != null ? `${row.fpl.goals_scored}–${row.fpl.goals_conceded}` : "Unavailable"}</TableCell>{metrics.map(metric => <TableCell key={metricId(metric)}><MetricCell rows={[row]} metric={metric} mode="total" coverage={false} /></TableCell>)}<TableCell><span className="sdp-chip" title={`Actual source known_at: ${row.known_at}; provider core status: ${row.status}`}>{dashboardTeamStatus(row) === "OWNER_CONFIRMED_VALID" ? "Valid · owner-confirmed" : dashboardTeamStatus(row) === "PROVIDER_VALID" ? "Valid · SDP" : "Incomplete"}</span></TableCell></TableRow>)}</TableBody></Table>
            </section>}
            </div>
          </div>}
        </DecisionTableFullscreen>
      </div>
      <p className="flex items-start gap-2 text-xs leading-relaxed text-muted-foreground"><Info className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" /><span>‡ Owner-confirmed value · § Assumed zero for an omitted sparse count. Tables, charts and CSV share these display values. Other missing observations stay unavailable. Percentages are per-match means; counts default to per-match averages.</span></p>
    </section>
    <details className="sdp-panel p-5 text-sm">
      <summary className="flex cursor-pointer items-center gap-2 font-medium"><ShieldCheck className="size-4 text-[var(--sdp-accent)]" aria-hidden="true" />Data coverage & methodology <span className="ml-auto text-xs font-normal text-muted-foreground">Sources, corrections, freshness</span></summary>
      <div className="mt-5 space-y-4 border-t pt-4 text-xs leading-relaxed text-muted-foreground">
        <p aria-label="Dashboard validation breakdown"><strong className="text-foreground">{providerValid + corrected} dashboard-ready fixtures:</strong> {providerValid} from complete SDP + {corrected} validated with owner-confirmed zeros. {fixtureRows.size - providerValid - corrected} still incomplete. Counts describe the selected season.</p>
        <p>{correctionIds.size} owner-confirmed display corrections and {assumptions} omitted sparse-count assumptions in this season. Original raw SDP payloads remain unchanged. Confirmed corrections count toward dashboard readiness; assumed omissions do not establish provider core validity.</p>
        <div className="grid gap-4 sm:grid-cols-2"><p>Latest SDP capture<br /><strong className="font-medium text-foreground">{stamp(data.source_status.latest_sdp_known_at)}</strong></p><p>Latest FPL enrichment<br /><strong className="font-medium text-foreground">{stamp(data.source_status.latest_fpl_known_at)}</strong></p></div>
        <p>SDP supplies team process statistics; FPL supplies explicitly labelled official scores. A provider field may be observed without independent semantic reconciliation: column tooltips retain that qualifier. xG describes provider-estimated chance quality for completed matches, not a future THE COMET forecast.</p>
        <p>League benchmarks are equal-weighted club averages over the selected match window. Only clubs with complete metric coverage participate; fewer than two clubs means no percentile. Higher value percentiles do not imply better football. Recent versus full-range comparisons can overlap and do not test persistence.</p>
        <p><strong className="text-foreground">Observed-data vintage:</strong> {stamp(data.as_of)}. Forecast and optimizer pages retain their own publication vintages; refreshing these statistics does not refresh or relabel those predictions.</p>
        <p>Detailed SDP player statistics are unavailable in retained captures. Their FPL-based duplicate tab has been consolidated into <a className="underline" href="#players">Players</a>. SDP participation evidence remains retained; no player-level shots, passing or box touches are allocated from team totals.</p>
      </div>
    </details>
    <InsightSummaryPanel items={[{ id: "scope", statement: `${filtered.length} clubs match ${filters.season} GW${filters.from}–GW${filters.to}. The recent window uses up to ${filters.recent === "all" ? "all selected" : filters.recent} matches per club.` }, { id: "coverage", statement: `${providerValid} season fixtures have complete SDP evidence; ${corrected} more are dashboard-ready with owner-confirmed corrections.` }]} localOnlyReason="Observed descriptive statistics. No AI, forecast or optimizer calculation is called." />
    <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4 text-xs text-muted-foreground"><span className="flex items-center gap-1.5"><Check className="size-3.5" aria-hidden="true" />Observed data · model independent</span><a href="#players" className="inline-flex min-h-10 items-center gap-2 hover:text-foreground">Explore individual players <ArrowRight className="size-3.5" aria-hidden="true" /></a></div>
  </div>;
}

export function TeamSdpStatsPage() {
  const [state, setState] = useState<{ data: SdpStatsData | null; error: string | null }>({ data: null, error: null });
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let alive = true;
    loadSdpStats().then(data => { if (alive) setState({ data, error: null }); }).catch((error: unknown) => { if (alive) setState({ data: null, error: error instanceof Error ? error.message : "Observed data is unavailable." }); });
    return () => { alive = false; };
  }, [retry]);
  if (state.error) return <div className="sdp-workspace p-6"><div className="sdp-panel space-y-4 p-6"><p className="sdp-eyebrow">Football observatory</p><h1 className="text-2xl font-semibold">Team stat from SDP</h1><p role="alert">{state.error}</p><p className="text-sm text-muted-foreground">The retained source could not be loaded. Missing observations have not been replaced with zeros.</p><Button variant="outline" onClick={() => { setState({ data: null, error: null }); setRetry(value => value + 1); }}>Retry source data</Button></div></div>;
  if (!state.data) return <div className="sdp-workspace space-y-5 p-6" role="status" aria-label="Loading observed SDP statistics"><div className="h-52 rounded-2xl bg-muted motion-safe:animate-pulse" /><p className="text-sm text-muted-foreground">Loading the football picture…</p><div className="grid gap-5 md:grid-cols-2"><div className="h-80 rounded-2xl bg-muted motion-safe:animate-pulse" /><div className="h-80 rounded-2xl bg-muted motion-safe:animate-pulse" /></div></div>;
  return <ReadyPage data={state.data} />;
}
