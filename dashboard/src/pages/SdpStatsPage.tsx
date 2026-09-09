import { useEffect, useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Download, RotateCcw, X } from "lucide-react";
import { AnalyticsScatter } from "@/components/AnalyticsScatter";
import { DecisionTableFullscreen } from "@/components/DecisionTableFullscreen";
import { FilterPanel } from "@/components/FilterPanel";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { loadSdpStats } from "@/data/sdpStats";
import type { SdpMatch, SdpMetric, SdpScope, SdpStatsData } from "@/data/sdpStats";
import { assumptionDescription, correctionDescription, dashboardTeamStatus, finite, metricAssumptions, metricCorrections, metricId, metricRaw, metricValue, sdpCsv, selectSdpEntities, sortSdpEntities } from "@/lib/sdpStats";
import type { SdpEntity, SdpFilters, SdpMode } from "@/lib/sdpStats";

const fmt = (value: number | null | undefined, digits = 2) => value == null ? "—" : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value);
const date = (value: string | null | undefined) => value ? new Intl.DateTimeFormat("en-GB", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(value)) : "Unavailable";
const inputClass = "h-9 min-w-0 w-full rounded-md border border-input bg-background px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const labelClass = "flex min-w-0 flex-col gap-1 text-xs font-medium text-muted-foreground";
const cardClass = "rounded-lg border bg-card p-4";
const colors = ["#2563eb", "#d97706", "#8b5cf6"];
const latestKnown = (rows: SdpMatch[]) => rows.reduce<string | undefined>((latest, row) => !latest || Date.parse(row.known_at) > Date.parse(latest) ? row.known_at : latest, undefined);
const exposureLabel = (minutes: number | null) => minutes === null ? "Exposure unknown" : minutes < 180 ? "Very low exposure" : minutes < 450 ? "Low exposure" : "Larger sample";

function Control({ label, value, options, onChange }: { label: string; value: string; options: [string, string][]; onChange: (value: string) => void }) {
  return <label className={labelClass}>{label}<select aria-label={label} value={value} onChange={e => onChange(e.target.value)} className={inputClass}>
    {options.map(([id, text]) => <option key={id} value={id}>{text}</option>)}
  </select></label>;
}

function initialFilters(rows: SdpMatch[]): SdpFilters {
  const season = [...new Set(rows.map(row => row.season))].sort().at(-1) ?? "";
  const weeks = rows.filter(row => row.season === season).map(row => row.gw);
  return { season, from: weeks.length ? Math.min(...weeks) : 1, to: weeks.length ? Math.max(...weeks) : 1, team: "all", venue: "all", recent: "5", search: "", position: "all", minMinutes: 0 };
}

function labelFor(metric: SdpMetric, mode: SdpMode) {
  const suffix = metric.aggregation === "mean" ? (metric.unit === "percent" ? " % · match mean" : " · match mean") : mode === "per90" ? " /90" : mode === "per_match" ? " /match" : mode === "per_appearance" ? " /app" : "";
  return `${metric.source === "fpl" ? "FPL · " : ""}${metric.label}${suffix}${metric.verified_semantics ? "" : " †"}`;
}

const sourceDescription = (metric: SdpMetric) => `${metric.source.toUpperCase()} ${metric.provider_field ?? metric.key}. ${metric.verified_semantics ? metric.description ?? "Recorded source value." : "Provider observation; not independently reconciled."}${metric.omitted_zero_display ? " An omitted value may be displayed as an owner-directed assumed zero and is marked §." : ""}`;

function CoverageValue({ rows, metric, mode }: { rows: SdpMatch[]; metric: SdpMetric; mode: SdpMode }) {
  const value = metricValue(rows, metric, mode);
  const unknownExposure = mode === "per_appearance" && rows.some(row => !finite(row.minutes_fpl));
  const corrections = metricCorrections(rows, metric);
  const assumptions = metricAssumptions(rows, metric);
  const exposure = mode === "per90" && metric.aggregation !== "mean" ? `; ${fmt(value.minutes)} matched actual minutes` : "";
  const provenance = [...corrections.map(correctionDescription), ...assumptions.map(assumptionDescription)].join(" ");
  return <span title={`${sourceDescription(metric)} ${unknownExposure ? "Appearance count unknown: missing FPL minutes" : `${value.measured}/${value.matches} ${mode === "per_appearance" ? "appearances" : "matches"} displayed`}; ${assumptions.length} assumed zero${exposure}. Missing observations outside the explicit sparse-count policy remain unavailable. ${provenance}`} className="tabular-nums">
    {value.value === null ? <span className="text-muted-foreground">Unavailable</span> : fmt(value.value)}{corrections.length > 0 && <sup className="ml-0.5" aria-label="owner-confirmed display correction">‡</sup>}{assumptions.length > 0 && <sup className="ml-0.5" aria-label="owner-directed omitted-count assumption">§</sup>}<span className="ml-1 text-[10px] text-muted-foreground">{unknownExposure ? "Exposure unknown" : `${value.measured}/${value.matches}`}</span>
  </span>;
}

function MatchValue({ row, metric }: { row: SdpMatch; metric: SdpMetric }) {
  const corrections = metricCorrections([row], metric);
  const assumptions = metricAssumptions([row], metric);
  return <span className="tabular-nums" title={[...corrections.map(correctionDescription), ...assumptions.map(assumptionDescription)].join(" ") || sourceDescription(metric)}>{fmt(metricRaw(row, metric))}{corrections.length > 0 && <sup className="ml-0.5" aria-label="owner-confirmed display correction">‡</sup>}{assumptions.length > 0 && <sup className="ml-0.5" aria-label="owner-directed omitted-count assumption">§</sup>}</span>;
}

function ObservedTrend({ entity, metric, mode }: { entity: SdpEntity; metric: SdpMetric; mode: SdpMode }) {
  const points = entity.rows.map((row, index) => ({ row, index, value: metricValue([row], metric, mode).value }));
  const measured = points.filter(point => point.value !== null);
  const ceiling = Math.max(1, ...measured.map(point => point.value!));
  const floor = Math.min(0, ...measured.map(point => point.value!));
  const width = 640, height = 180, pad = 28;
  const x = (index: number) => pad + index * (width - pad * 2) / Math.max(1, points.length - 1);
  const y = (value: number) => height - pad - (value - floor) * (height - pad * 2) / (ceiling - floor);
  return <section className={cardClass} aria-label="Observed match trend">
    <h3 className="font-medium">{labelFor(metric, mode)} · match history</h3>
    <p className="mt-1 text-xs text-muted-foreground">Completed matches in the selected scope. Gaps remain missing; no fitted trend.</p>
    {measured.length === 0 ? <p className="py-8 text-sm text-muted-foreground">No measured values to chart in this scope.</p> : <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${entity.name}: observed ${labelFor(metric, mode)} by match. Exact values in the match log.`} className="mt-3 w-full">
      <line x1={pad} x2={width - pad} y1={y(0)} y2={y(0)} stroke="currentColor" opacity=".25" />
      <text x="0" y={pad} fill="currentColor" fontSize="11">{fmt(ceiling)}</text>
      <text x="8" y={height - pad} fill="currentColor" fontSize="11">{fmt(floor)}</text>
      {points.map((point, index) => {
        const previous = points[index - 1];
        return point.value === null ? null : <g key={point.row.fixture}>
          {previous?.value != null && <line x1={x(previous.index)} y1={y(previous.value)} x2={x(index)} y2={y(point.value)} stroke="currentColor" strokeWidth="2" opacity=".6" />}
          <circle cx={x(index)} cy={y(point.value)} r="4" fill="currentColor" tabIndex={0} role="img" aria-label={`GW${point.row.gw} ${point.row.opponent_short_name}: ${fmt(point.value)}`}>
            <title>{date(point.row.kickoff_time)} · GW{point.row.gw} · {point.row.opponent_short_name}: {fmt(point.value)}{metricCorrections([point.row], metric).length ? "; owner-confirmed display correction" : ""}{metricAssumptions([point.row], metric).length ? "; owner-directed omitted-count assumption" : ""}</title>
          </circle>
          {(points.length <= 12 || index === 0 || index === points.length - 1) && <text x={x(index)} y={height - 6} fill="currentColor" fontSize="10" textAnchor="middle">GW{point.row.gw}</text>}
        </g>;
      })}
    </svg>}
  </section>;
}

function Comparison({ entities, metrics, mode, onRemove }: { entities: SdpEntity[]; metrics: SdpMetric[]; mode: SdpMode; onRemove: (id: string) => void }) {
  if (!entities.length) return null;
  return <section className={cardClass} aria-label="Selected comparison">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-base font-semibold">Compare observed profiles</h2><p className="text-xs text-muted-foreground">Same filters · up to 3 · exact values, no normalized score</p></div>
    <div className="my-3 flex flex-wrap gap-2">{entities.map((entity, index) => <Button key={entity.id} variant="outline" size="sm" onClick={() => onRemove(entity.id)} aria-label={`Remove ${entity.name} from comparison`}><span className="size-2 rounded-full" style={{ backgroundColor: colors[index] }} />{entity.name}<X className="size-3" /></Button>)}</div>
    <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">{metrics.slice(0, 6).map(metric => {
      const values = entities.map(entity => metricValue(entity.rows, metric, mode).value);
      const max = Math.max(1, ...values.filter(finite));
      const min = Math.min(0, ...values.filter(finite));
      const span = max - min, zero = -min / span * 100;
      return <div key={metricId(metric)}><h3 className="mb-2 text-xs font-medium">{labelFor(metric, mode)}</h3>{entities.map((entity, index) => <div key={entity.id} className="mb-2 text-xs">
        <div className="mb-1 flex justify-between gap-3"><span className="truncate">{entity.name}</span><span className="tabular-nums">{fmt(values[index])}</span></div>
        <div className="relative h-2 overflow-hidden rounded-full bg-muted" aria-hidden="true">{min < 0 && <div className="absolute h-full w-px bg-foreground/50" style={{ left: `${zero}%` }} />}{values[index] !== null && <div className="absolute h-full rounded-full" style={{ left: `${(Math.min(0, values[index]!) - min) / span * 100}%`, width: `${Math.abs(values[index]!) / span * 100}%`, backgroundColor: colors[index] }} />}</div>
      </div>)}</div>;
    })}</div>
    <Table aria-label="Exact comparison values" className="mt-4"><TableHeader><TableRow><TableHead>Metric</TableHead>{entities.map(entity => <TableHead key={entity.id}>{entity.name}</TableHead>)}</TableRow></TableHeader><TableBody>{metrics.map(metric => <TableRow key={metricId(metric)}><TableCell>{labelFor(metric, mode)}</TableCell>{entities.map(entity => <TableCell key={entity.id}><CoverageValue rows={entity.rows} metric={metric} mode={mode} /></TableCell>)}</TableRow>)}</TableBody></Table>
  </section>;
}

function MatchDetail({ entity, scope, metrics, mode, trendMetric, onClose }: { entity: SdpEntity; scope: SdpScope; metrics: SdpMetric[]; mode: SdpMode; trendMetric: SdpMetric | null; onClose: () => void }) {
  return <section aria-label={`${entity.name} match detail`} className="space-y-3 rounded-lg border bg-muted/20 p-4">
    <div className="flex items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">{entity.name}</h2><p className="text-xs text-muted-foreground">{entity.clubs} · {entity.rows.length} fixture records · {date(entity.rows[0]?.kickoff_time)} – {date(entity.rows.at(-1)?.kickoff_time)}</p></div><Button variant="ghost" size="icon" onClick={onClose} aria-label="Close match detail"><X /></Button></div>
    {trendMetric && <ObservedTrend entity={entity} metric={trendMetric} mode={mode} />}
    <div className="rounded-lg border bg-background"><Table aria-label={`${entity.name} observed match log`} containerClassName="max-h-[440px]"><TableHeader className="sticky top-0 z-10 bg-background"><TableRow><TableHead>Match</TableHead><TableHead>Club</TableHead><TableHead>Opponent</TableHead>{scope === "player" && <><TableHead>SDP XI / bench</TableHead><TableHead>FPL min</TableHead><TableHead>Provider position</TableHead></>}{metrics.map(m => <TableHead key={metricId(m)}>{m.source.toUpperCase()} · {m.label}</TableHead>)}<TableHead>Source known (UTC)</TableHead><TableHead>Status</TableHead></TableRow></TableHeader><TableBody>{[...entity.rows].reverse().map(row => <TableRow key={row.fixture}>
      <TableCell><div className="font-medium">{row.season} · GW{row.gw}</div><div className="text-xs text-muted-foreground">{date(row.kickoff_time)}</div></TableCell><TableCell>{row.team_short_name}</TableCell><TableCell>{row.opponent_short_name} ({row.was_home ? "H" : "A"})</TableCell>
      {scope === "player" && <><TableCell>{row.started === true ? "Starting XI" : row.bench === true ? "Bench" : "Unknown"}</TableCell><TableCell>{fmt(row.minutes_fpl, 0)}</TableCell><TableCell>{row.provider_position ?? "—"}{row.provider_sub_position ? ` / ${row.provider_sub_position}` : ""}</TableCell></>}
      {metrics.map(m => <TableCell key={metricId(m)}><MatchValue row={row} metric={m} /></TableCell>)}<TableCell className="text-xs">{new Date(row.known_at).toISOString()}</TableCell><TableCell><Badge variant="outline" title={scope === "team" ? "Dashboard validation uses source observations plus owner-confirmed corrections. Original provider status is retained separately in provenance." : undefined}>{scope === "team" ? dashboardTeamStatus(row) === "OWNER_CONFIRMED_VALID" ? "Valid · owner-confirmed" : dashboardTeamStatus(row) === "PROVIDER_VALID" ? "Valid · SDP" : "Incomplete" : row.status.replaceAll("_", " ")}</Badge></TableCell>
    </TableRow>)}</TableBody></Table></div>
    <p className="text-xs text-muted-foreground">Match logs show observed source values plus explicitly marked display corrections and omitted-count assumptions. Nominal SDP event-clock intervals are not official minutes and never supply a per-90 denominator.</p>
  </section>;
}

function ReadyPage({ data, scope }: { data: SdpStatsData; scope: SdpScope }) {
  const rows = scope === "team" ? data.team_matches : data.player_matches;
  const relevant = data.metrics.filter(m => m.scope === scope || m.scope === "both");
  const defaultMetric = relevant.find(m => m.key === "expected_goals") ?? relevant[0];
  const defaults = initialFilters(rows);
  const [filters, setFilters] = useState(defaults);
  const defaultMode: SdpMode = scope === "team" ? "per_match" : "per_appearance";
  const [mode, setMode] = useState<SdpMode>(defaultMode);
  const [group, setGroup] = useState(scope === "team" ? "overview" : defaultMetric?.group ?? "all");
  const [sortKey, setSortKey] = useState(defaultMetric ? metricId(defaultMetric) : "name");
  const [ascending, setAscending] = useState(false);
  const [compared, setCompared] = useState<string[]>([]);
  const [detail, setDetail] = useState<string | null>(null);
  const [chartKey, setChartKey] = useState(defaultMetric ? metricId(defaultMetric) : "");
  const [page, setPage] = useState(0);
  const patchFilters = (patch: Partial<SdpFilters>) => { setFilters(current => ({ ...current, ...patch })); setPage(0); };
  const filtered = useMemo(() => selectSdpEntities(rows, scope, filters), [rows, scope, filters]);
  const overview = new Set(["goals", "shots", "shots_on_target", "expected_goals", "possession", "passes", "tackles", "fouls"]);
  const metrics = relevant.filter(m => group === "all" || (group === "overview" ? m.source === "sdp" && overview.has(m.key) : m.group === group));
  const ordered = sortSdpEntities(filtered, relevant.find(m => metricId(m) === sortKey) ?? null, mode, ascending);
  const pageCount = Math.max(1, Math.ceil(ordered.length / 25));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = ordered.slice(currentPage * 25, currentPage * 25 + 25);
  const comparisons = compared.flatMap(id => filtered.find(row => row.id === id) ?? []);
  const selectedDetail = filtered.find(row => row.id === detail);
  const chartMetric = relevant.find(m => metricId(m) === chartKey) ?? metrics[0] ?? null;
  const seasons = [...new Set(rows.map(row => row.season))].sort().reverse();
  const seasonRows = rows.filter(row => row.season === filters.season);
  const weeks = [...new Set(seasonRows.map(row => row.gw))].sort((a, b) => a - b);
  const completedWeeks = data.gameweeks.filter(row =>
    row.season === filters.season && row.fixtures_completed > 0,
  );
  const completedFixtureCount = completedWeeks.reduce(
    (total, row) => total + row.fixtures_completed,
    0,
  );
  const completedFixtureScope = completedWeeks.length
    ? `${completedFixtureCount} across GW${completedWeeks[0].gw}-GW${completedWeeks.at(-1)!.gw}`
    : "None witnessed";
  const fixtureRows = new Map<number, SdpMatch[]>();
  for (const row of seasonRows) fixtureRows.set(row.fixture, [...fixtureRows.get(row.fixture) ?? [], row]);
  const providerCoreValid = [...fixtureRows.values()].filter(fixture => fixture.length === 2 && fixture.every(row => row.status !== "UNAVAILABLE")).length;
  const dashboardValid = [...fixtureRows.values()].filter(fixture => fixture.length === 2 && fixture.every(row => dashboardTeamStatus(row) !== "INCOMPLETE")).length;
  const correctedFixtures = [...fixtureRows.values()].filter(fixture => fixture.length === 2 && fixture.every(row => dashboardTeamStatus(row) === "OWNER_CONFIRMED_VALID")).length;
  const displayCorrectionIds = new Set(seasonRows.flatMap(row => Object.values(row.display_corrections ?? {}).filter(correction => correction.relation === "direct").map(correction => correction.correction_id)));
  const displayAssumptionCount = seasonRows.reduce((count, row) => count + Object.keys(row.display_assumptions ?? {}).length, 0);
  const weekLabel = (gw: number) => {
    const official = data.gameweeks.find(row => row.season === filters.season && row.gw === gw);
    return `GW${gw}${official && !official.finished ? " · in progress" : ""}`;
  };
  const teams = [...new Map(seasonRows.map(row => [String(row.team_code), row.team_name])).entries()].sort((a, b) => a[1].localeCompare(b[1]));
  const selectedRows = filtered.flatMap(entity => entity.rows);
  const available = chartMetric ? filtered.filter(entity => metricValue(entity.rows, chartMetric, mode).value !== null).length : 0;
  const reset = () => { setFilters(defaults); setMode(defaultMode); setGroup(scope === "team" ? "overview" : defaultMetric?.group ?? "all"); setSortKey(defaultMetric ? metricId(defaultMetric) : "name"); setAscending(false); setCompared([]); setDetail(null); setPage(0); setChartKey(defaultMetric ? metricId(defaultMetric) : ""); };
  const chooseSeason = (season: string) => { const gws = rows.filter(row => row.season === season).map(row => row.gw); patchFilters({ season, from: Math.min(...gws), to: Math.max(...gws), team: "all" }); setCompared([]); setDetail(null); };
  const chooseComparison = (id: string) => setCompared(current => current.includes(id) ? current.filter(value => value !== id) : [...current.filter(value => filtered.some(row => row.id === value)), id].slice(0, 3));
  const exportCsv = () => { const url = URL.createObjectURL(new Blob([sdpCsv(ordered, metrics, mode)], { type: "text/csv;charset=utf-8" })); const link = document.createElement("a"); link.href = url; link.download = `${scope}-observed-${filters.season}-gw${filters.from}-${filters.to}.csv`; link.click(); URL.revokeObjectURL(url); };
  const metricOptions = relevant.map(m => [metricId(m), `${m.source.toUpperCase()} · ${m.label}`] as [string, string]);
  const xMetric = relevant.find(m => m.source === "sdp" && m.key === "expected_goals" && m.verified_semantics);
  const yMetric = relevant.find(m => m.source === "sdp" && m.key === "expected_goals_allowed" && m.verified_semantics);
  const scatterPoints = scope === "team" && xMetric && yMetric ? filtered.flatMap(entity => {
    const x = metricValue(entity.rows, xMetric, mode).value, y = metricValue(entity.rows, yMetric, mode).value;
    return x !== null && y !== null ? [{ id: entity.id, label: entity.name, x, y, groupLabel: `${entity.rows.length} complete observed matches`, color: colors[0] }] : [];
  }) : [];

  return <div className="space-y-4 p-4 lg:p-6">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><div className="mb-2 flex flex-wrap items-center gap-2"><Badge variant="secondary">Observed · Premier League</Badge><Badge variant="outline">SDP {scope === "team" ? "team statistics" : "lineups"}</Badge>{scope === "player" && <Badge variant="outline">FPL enrichment · labelled separately</Badge>}</div><h1 className="text-2xl font-semibold tracking-tight">{scope === "team" ? "Team stat from SDP" : "Players stat from SDP"}</h1><p className="mt-1 max-w-3xl text-sm text-muted-foreground">Explore recorded match performance, recent history and source coverage. These are observed statistics, not predictions.</p></div><Button variant="outline" onClick={exportCsv} disabled={!ordered.length}><Download />Export filtered CSV</Button></div>
    <div role="note" className="rounded-lg border bg-muted/35 p-3 text-sm text-muted-foreground"><strong className="text-foreground">Observed-data vintage:</strong> this tab was exported {date(data.as_of)}. Forecast and optimizer pages retain their own displayed publication vintages; refreshing these statistics does not refresh or relabel those predictions.</div>
    {scope === "team" && displayCorrectionIds.size > 0 && <div role="note" className="rounded-lg border border-amber-400/40 bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950/20 dark:text-amber-100"><strong>{displayCorrectionIds.size} owner-confirmed display correction{displayCorrectionIds.size === 1 ? " is" : "s are"} active.</strong> Confirmed zeros are accepted by dashboard validation. The original SDP payload is preserved for provenance. Corrected values are marked <span aria-hidden="true">‡</span> in tables and match logs. Charts and CSV use the same labelled display value.</div>}
    {scope === "team" && displayAssumptionCount > 0 && <div role="note" className="rounded-lg border border-sky-400/40 bg-sky-50 p-3 text-sm text-sky-950 dark:bg-sky-950/20 dark:text-sky-100"><strong>{displayAssumptionCount} omitted sparse-count cells are displayed as assumed zero.</strong> They are marked <span aria-hidden="true">§</span> and are not provider-verified zeros. Raw values remain NULL; core validity and predictions are unchanged. Other missing fields remain Unavailable unless separately owner-confirmed. Incomplete means required fields still lack acceptable evidence after confirmed corrections.</div>}
    {scope === "player" && data.source_status.player_stats === "UNAVAILABLE" && <div role="note" className="rounded-lg border border-amber-400/40 bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950/20 dark:text-amber-100"><strong>Detailed SDP player statistics are unavailable.</strong> SDP provides witnessed lineups and broad provider positions. Every detailed player statistic below is an explicitly labelled FPL observation. Player shots, SOT and box touches are not inferred from team totals.</div>}
    <div className={`grid grid-cols-2 gap-3 ${scope === "team" ? "xl:grid-cols-6" : "xl:grid-cols-5"}`}>{[[scope === "team" ? "Clubs in scope" : "Players in scope", filtered.length], ["Official completed fixtures", completedFixtureScope], ...(scope === "team" ? [["Dashboard-ready fixtures", `${dashboardValid} / ${fixtureRows.size}`]] : []), ["Observed fixture records", selectedRows.length], ["Complete chart metric", `${available} / ${filtered.length}`], ["Latest SDP known", date(data.source_status.latest_sdp_known_at)]].map(([label, value]) => <div key={label} className={cardClass}><p className="text-xs text-muted-foreground">{label}</p><p className="mt-1 text-xl font-semibold tabular-nums">{value}</p></div>)}</div>
    {scope === "team" && <p className="text-sm text-muted-foreground" aria-label="Dashboard validation breakdown">{dashboardValid} dashboard-ready fixtures: {providerCoreValid} from complete SDP + {correctedFixtures} validated with owner-confirmed zeros. {fixtureRows.size - dashboardValid} still incomplete.</p>}
    <FilterPanel><div className="grid grid-cols-2 items-end gap-3 md:grid-cols-4 xl:grid-cols-6">
      <Control label="Season" value={filters.season} options={seasons.map(s => [s, s])} onChange={chooseSeason} />
      <Control label="GW from" value={String(filters.from)} options={weeks.filter(gw => gw <= filters.to).map(gw => [String(gw), weekLabel(gw)])} onChange={value => patchFilters({ from: Number(value) })} />
      <Control label="GW to" value={String(filters.to)} options={weeks.filter(gw => gw >= filters.from).map(gw => [String(gw), weekLabel(gw)])} onChange={value => patchFilters({ to: Number(value) })} />
      <Control label="Recent history" value={filters.recent} options={[["3", "Last 3 matches"], ["5", "Last 5 matches"], ["all", "Full selected range"]]} onChange={value => patchFilters({ recent: value as SdpFilters["recent"] })} />
      <Control label="Venue" value={filters.venue} options={[["all", "Home + away"], ["home", "Home"], ["away", "Away"]]} onChange={value => patchFilters({ venue: value as SdpFilters["venue"] })} />
      <Control label="Team" value={filters.team} options={[["all", "All clubs"], ...teams]} onChange={value => patchFilters({ team: value })} />
      <label className={`${labelClass} col-span-2`}>Search {scope === "team" ? "clubs" : "players"}<input className={inputClass} aria-label={`Search ${scope === "team" ? "clubs" : "players"}`} placeholder={scope === "team" ? "Search a club…" : "Search player or club…"} value={filters.search} onChange={e => patchFilters({ search: e.target.value })} /></label>
      {scope === "player" && <><Control label="FPL position" value={filters.position} options={[["all", "All positions"], ...["GK", "DEF", "MID", "FWD"].map(p => [p, p] as [string, string])]} onChange={value => patchFilters({ position: value })} /><label className={labelClass}>Minimum FPL minutes<input className={inputClass} aria-label="Minimum FPL minutes" type="number" min="0" value={filters.minMinutes} onChange={e => patchFilters({ minMinutes: Math.max(0, Number(e.target.value) || 0) })} /></label></>}
      <Control label="Metric group" value={group} options={[...(scope === "team" ? [["overview", "Overview"] as [string, string]] : []), ["all", "All metrics"], ...[...new Set(relevant.map(m => m.group))].map(g => [g, g] as [string, string])]} onChange={setGroup} />
      <Control label="Display" value={mode} options={scope === "team" ? [["per_match", "Average per match"], ["total", "Totals"]] : [["per_appearance", "Average per appearance"], ["total", "Totals"], ["per90", "Per 90 actual minutes"]]} onChange={value => setMode(value as SdpMode)} />
      <Button variant="outline" onClick={reset}><RotateCcw />Reset filters</Button>
    </div><p className="mt-3 text-xs text-muted-foreground">Recent windows apply to each {scope === "team" ? "club" : "player"} after season, GW, team and venue filters. Both double-gameweek fixtures count. Sparse omitted counts can display an explicit assumed zero (§); all other missing values remain —. Percentage columns show a per-match mean, not a pooled percentage.</p>{scope === "player" && <p className="mt-1 text-xs text-muted-foreground">Average per appearance divides by matches with actual FPL minutes greater than zero; DNPs are excluded and unknown minutes keep the average unavailable. Match logs retain individual match values. Exposure uses selected FPL minutes: below 180 is very low; 180 to 449 is low; 450+ is a larger sample. These describe sample size, not model confidence.</p>}</FilterPanel>
    <div className="space-y-2" aria-label="Available statistic groups">
      <p className="text-sm font-medium">{scope === "team" ? `${relevant.filter(m => m.source === "sdp").length} SDP team metrics` : "Observed player metrics ? FPL source"}</p>
      <div className="flex flex-wrap gap-2">{[...(scope === "team" ? ["overview"] : []), ...new Set(relevant.map(m => m.group))].map(key => <Button key={key} size="sm" variant={group === key ? "default" : "outline"} aria-pressed={group === key} onClick={() => { setGroup(key); setPage(0); }}>{key === "overview" ? "Overview" : key.replaceAll("_", " ")}</Button>)}</div>
      {scope === "team" && <p className="text-xs text-muted-foreground">Shooting, possession, passing, territory, defensive actions and discipline are separate source observations. Passing direction, long passes and crosses describe play patterns; no inferred play-type label is assigned. Core-incomplete matches retain individually measured cells. Omitted sparse event counts may show assumed zero (§); other missing fields stay Unavailable.</p>}
    </div>
    {relevant.length > 0 && <div className="flex flex-wrap items-end justify-between gap-3"><Control label="Trend metric" value={chartMetric ? metricId(chartMetric) : ""} options={metricOptions} onChange={setChartKey} /><p className="text-xs text-muted-foreground">Each cell shows displayed / selected {mode === "per_appearance" ? "appearances" : "matches"}. Averages, totals and rates require complete display coverage. † Provider observation; not independently reconciled. ‡ Owner-confirmed correction. § Owner-directed assumed zero for an omitted sparse count. Hover for exact provenance.</p></div>}
    <DecisionTableFullscreen label={scope === "team" ? "SDP team statistics table" : "SDP player statistics table"}>
    {({ isFullscreen }) => <div className={isFullscreen ? "min-h-0 flex-1 space-y-4 overflow-y-auto" : "space-y-4"}>
    <Table aria-label={scope === "team" ? "Observed SDP team statistics" : "Observed player statistics by source"} containerClassName={isFullscreen ? "max-h-[calc(100dvh-9rem)]" : "max-h-[620px]"}><TableHeader className="sticky top-0 z-20 bg-background"><TableRow>
      <TableHead className="sticky left-0 z-30 bg-background"><button className="flex items-center gap-1" onClick={() => { setSortKey("name"); setAscending(sortKey === "name" ? !ascending : true); }}> {scope === "team" ? "Club" : "Player"}{sortKey === "name" && (ascending ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}</button></TableHead><TableHead>Compare</TableHead>{scope === "player" && <><TableHead>FPL position</TableHead><TableHead>Club(s)</TableHead><TableHead>FPL minutes / exposure</TableHead><TableHead>SDP starts</TableHead><TableHead title="Count of selected fixture rows with measured FPL minutes greater than zero. Unavailable if any selected minute field is missing.">FPL appearances</TableHead></>}<TableHead title="Selected fixture records, including recorded non-appearances.">Matches</TableHead>
      {metrics.map(metric => <TableHead key={metricId(metric)} aria-sort={sortKey === metricId(metric) ? ascending ? "ascending" : "descending" : "none"}><button className="flex items-center gap-1 text-left" onClick={() => { setSortKey(metricId(metric)); setAscending(sortKey === metricId(metric) ? !ascending : false); }} title={sourceDescription(metric)}>
        {labelFor(metric, mode)}{sortKey === metricId(metric) && (ascending ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}
      </button></TableHead>)}<TableHead>Latest source</TableHead>
    </TableRow></TableHeader><TableBody>{visible.map(entity => {
      const fplMinutes = entity.rows.every(r => finite(r.minutes_fpl)) ? entity.rows.reduce((sum, r) => sum + r.minutes_fpl!, 0) : null;
      const appearances = fplMinutes === null ? null : entity.rows.filter(r => r.minutes_fpl! > 0).length;
      const starts = entity.rows.every(r => r.started != null) ? entity.rows.filter(r => r.started).length : null;
      return <TableRow key={entity.id} data-state={detail === entity.id ? "selected" : undefined}><TableCell className="sticky left-0 z-10 bg-background"><button className="max-w-[190px] truncate text-left font-medium underline-offset-4 hover:underline focus-visible:underline" onClick={() => setDetail(entity.id)} aria-label={`View ${entity.name} match detail`}>{entity.name}</button>{scope === "player" && entity.code === null && <div className="text-[10px] text-muted-foreground">FPL identity unavailable</div>}</TableCell><TableCell><input type="checkbox" aria-label={`Compare ${entity.name}`} checked={compared.includes(entity.id)} disabled={!compared.includes(entity.id) && comparisons.length >= 3} onChange={() => chooseComparison(entity.id)} className="size-4 accent-current" /></TableCell>{scope === "player" && <><TableCell>{entity.position}</TableCell><TableCell>{entity.clubs}</TableCell><TableCell><span className="tabular-nums">{fmt(fplMinutes, 0)}</span><div className="mt-1 text-[10px] text-muted-foreground" title="Descriptive sample size only: very low below 180 minutes; low below 450; larger at 450+. This is not model confidence.">{exposureLabel(fplMinutes)}</div></TableCell><TableCell>{fmt(starts, 0)}</TableCell><TableCell>{fmt(appearances, 0)}</TableCell></>}<TableCell>{entity.rows.length}</TableCell>{metrics.map(metric => <TableCell key={metricId(metric)}><CoverageValue rows={entity.rows} metric={metric} mode={mode} /></TableCell>)}<TableCell className="text-xs text-muted-foreground" title={latestKnown(entity.rows)}>{date(latestKnown(entity.rows))}</TableCell></TableRow>;
    })}{!visible.length && <TableRow><TableCell colSpan={metrics.length + (scope === "player" ? 10 : 4)} className="py-12 text-center text-muted-foreground">No observed records match these filters. Reset filters or choose a season with coverage.</TableCell></TableRow>}</TableBody></Table>
    <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-muted-foreground"><p>{ordered.length ? currentPage * 25 + 1 : 0}–{Math.min((currentPage + 1) * 25, ordered.length)} of {ordered.length} · choose a name for the match log</p><div className="flex gap-2"><Button variant="outline" size="sm" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</Button><Button variant="outline" size="sm" disabled={currentPage + 1 >= pageCount} onClick={() => setPage(currentPage + 1)}>Next</Button></div></div>
    <Comparison entities={comparisons} metrics={metrics} mode={mode} onRemove={id => setCompared(current => current.filter(value => value !== id))} />
    {selectedDetail && <MatchDetail entity={selectedDetail} scope={scope} metrics={metrics} mode={mode} trendMetric={chartMetric} onClose={() => setDetail(null)} />}
    </div>}
    </DecisionTableFullscreen>
    {scope === "team" && xMetric && yMetric && <AnalyticsScatter title="Observed attack and defence" points={scatterPoints} xAxis={{ label: labelFor(xMetric, mode), direction: "explanatory", bounds: { min: 0 } }} yAxis={{ label: labelFor(yMetric, mode), direction: "explanatory", bounds: { min: 0 } }} vintageLabel={`SDP observed; export as of ${data.as_of}`} horizonLabel={`${filters.season} GW${filters.from}–${filters.to}; ${filters.recent === "all" ? "full selected range" : `last ${filters.recent} matches per club`}; ${filters.venue}`} description={`${scatterPoints.length} clubs plotted; ${filtered.length - scatterPoints.length} lack complete paired metrics.`} readingNote="Recorded team xG and exact opponent xG describe completed matches. Higher team xG and lower opponent xG indicate the stronger observed balance; neither forecasts the next fixture." />}
    <InsightSummaryPanel items={[{ id: "scope", statement: `${filtered.length} ${scope === "team" ? "clubs" : "players"} and ${selectedRows.length} observed fixture records match this scope.` }, { id: "coverage", statement: chartMetric ? `${available} have complete ${chartMetric.source.toUpperCase()} ${chartMetric.label} evidence for the selected display.` : "No observed metric is available in this source scope." }]} localOnlyReason="Observed source statistics remain a deterministic description. No AI or prediction model is called." />
    <details className={`${cardClass} text-xs`}>
      <summary className="cursor-pointer font-medium">Source coverage and freshness</summary>
      <p className="mt-2 text-muted-foreground">FINAL marks completed fixtures; provider observations may still be corrected in later captures.</p>
      <dl className="mt-3 grid gap-2 sm:grid-cols-2">
        <div><dt className="text-muted-foreground">SDP team stats</dt><dd>{data.source_status.team_stats}</dd></div>
        {scope === "team" && <div><dt className="text-muted-foreground">Provider core-valid / display corrections</dt><dd>{providerCoreValid} fixtures / {displayCorrectionIds.size} owner-confirmed values</dd></div>}
        <div><dt className="text-muted-foreground">SDP player stats / lineups</dt><dd>{data.source_status.player_stats} / {data.source_status.player_lineups}</dd></div>
        <div><dt className="text-muted-foreground">FPL enrichment</dt><dd>{data.source_status.fpl_enrichment}</dd></div>
        <div><dt className="text-muted-foreground">Export cutoff (UTC)</dt><dd>{new Date(data.as_of).toISOString()}</dd></div>
        <div><dt className="text-muted-foreground">Latest SDP known (UTC)</dt><dd>{data.source_status.latest_sdp_known_at ? new Date(data.source_status.latest_sdp_known_at).toISOString() : "Unavailable"}</dd></div>
        <div><dt className="text-muted-foreground">Latest FPL known (UTC)</dt><dd>{data.source_status.latest_fpl_known_at ? new Date(data.source_status.latest_fpl_known_at).toISOString() : "Unavailable"}</dd></div>
        <div><dt className="text-muted-foreground">Team source failures / unmapped players</dt><dd>{data.coverage.team_failures} / {data.coverage.unmapped_players}</dd></div>
      </dl>
      {data.source_status.notes.map(note => <p key={note} className="mt-2 text-muted-foreground">{note}</p>)}
    </details>
  </div>;
}

export function SdpStatsPage({ scope }: { scope: SdpScope }) {
  const [state, setState] = useState<{ data: SdpStatsData | null; error: string | null }>({ data: null, error: null });
  const [retry, setRetry] = useState(0);
  useEffect(() => { let alive = true; loadSdpStats().then(data => { if (alive) setState({ data, error: null }); }).catch((error: unknown) => { if (alive) setState({ data: null, error: error instanceof Error ? error.message : "Observed data is unavailable." }); }); return () => { alive = false; }; }, [retry]);
  if (state.error) return <div className="space-y-3 p-6"><h1 className="text-2xl font-semibold">{scope === "team" ? "Team stat from SDP" : "Players stat from SDP"}</h1><p role="alert" className="text-sm text-muted-foreground">{state.error}</p><p className="text-sm">No missing observations have been replaced with zeros.</p><Button variant="outline" onClick={() => { setState({ data: null, error: null }); setRetry(value => value + 1); }}>Retry source data</Button></div>;
  if (!state.data) return <p role="status" className="p-6 text-sm text-muted-foreground">Loading observed SDP statistics…</p>;
  return <ReadyPage key={scope} data={state.data} scope={scope} />;
}

export const TeamSdpStatsPage = () => <SdpStatsPage scope="team" />;
export const PlayerSdpStatsPage = () => <SdpStatsPage scope="player" />;
