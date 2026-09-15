import { useEffect, useMemo, useState } from "react";
import { Download } from "lucide-react";
import { loadCompetitiveSchedule, type CompetitiveSchedule } from "@/data/competitiveSchedule";
import type { FixtureScheduleOverlay, TeamRecord } from "@/data/types";
import { calendarColumns, calendarFixtures, calendarRange, leagueSlot, visibleCalendar, type CalendarFixture } from "@/lib/competitiveCalendar";
import { BUCKET_CLASSES, FDR_LEGEND, OPPONENT_LEGEND, NULL_BUCKET_CLASS, fdrBucket } from "@/lib/difficulty";
import { buildOpponentStrength, opponentStrengthBucket } from "@/lib/opponentStrength";
import { DecisionTableFullscreen } from "@/components/DecisionTableFullscreen";
import { MultiSelectFilter } from "@/components/MultiSelectFilter";
import { TeamBadge } from "@/components/Avatars";
import { Button } from "@/components/ui/button";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

const stamp = (value: string) => new Date(value).toLocaleString("en-GB", { timeZone: "Europe/London", dateStyle: "medium", timeStyle: "short" });
const cupClass = "bg-sky-100 text-sky-950 ring-1 ring-inset ring-sky-200 dark:bg-sky-950 dark:text-sky-100 dark:ring-sky-800";
const venue = (home: boolean | null) => home === null ? "venue TBC" : home ? "H" : "A";

export function CompetitiveFixtureCalendar({ teams, schedule, fromGw, toGw }: {
  teams: TeamRecord[]; schedule: FixtureScheduleOverlay; fromGw: number; toGw: number;
}) {
  const [data, setData] = useState<CompetitiveSchedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<number[]>([]);
  const [range, setRange] = useState<[string, string] | null>(null);
  const [horizon, setHorizon] = useState(toGw - fromGw + 1);
  const [colour, setColour] = useState<"opponent" | "fdr">("opponent");
  useEffect(() => {
    let active = true;
    loadCompetitiveSchedule().then((value) => { if (active) setData(value); })
      .catch((e: unknown) => { if (active) setError(e instanceof Error ? e.message : "Schedule unavailable"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);
  const season = teams[0]?.season ?? "";
  const all = useMemo(() => calendarFixtures(schedule, data, season), [schedule, data, season]);
  const defaults = calendarRange(all, fromGw, fromGw + horizon - 1);
  const [from, to] = range ?? defaults;
  const invalidRange = !from || !to || from > to;
  const clubs = [...teams].filter((t) => !selected.length || selected.includes(t.team_code)).sort((a, b) => a.team_name.localeCompare(b.team_name));
  const eligible = range === null ? all.filter((f) => f.gw === null || (f.gw >= fromGw && f.gw < fromGw + horizon)) : all;
  const visible = visibleCalendar(eligible, clubs.map((t) => t.team_code), from, to);
  const globalRange = visibleCalendar(eligible, teams.map((t) => t.team_code), from, to);
  const selectedGws = new Set((range === null ? eligible : globalRange.rows).filter((f) => f.gw !== null).map((f) => f.gw));
  // Once a GW is selected, keep every leg, even an undated or later DGW leg.
  // Preserve its column when the selected club has a genuine blank.
  const columns = calendarColumns([...all.filter((f) => f.gw !== null && selectedGws.has(f.gw)), ...visible.rows.filter((f) => f.gw === null)]);
  const displayed = columns.flatMap((c) => c.fixtures).filter((f) => clubs.some((t) => t.team_code === f.teamCode));
  const cells = new Map<string, CalendarFixture[]>();
  for (const column of columns) for (const f of column.fixtures) {
    const key = `${f.teamCode}:${column.key}`;
    const entries = cells.get(key) ?? [];
    entries.push(f); cells.set(key, entries);
  }
  const cellFixtures = (code: number, day: string) => cells.get(`${code}:${day}`) ?? [];
  const slotLabel = (code: number, column: typeof columns[number]) => column.key.startsWith("gw:")
    ? leagueSlot(schedule, season, code, Number(column.key.slice(3))) : null;
  const strength = useMemo(() => buildOpponentStrength(teams), [teams]);
  const legend = colour === "opponent" ? OPPONENT_LEGEND : FDR_LEGEND;
  const description = (f: CalendarFixture) => `${f.opponent} (${venue(f.home)}) · ${f.gw === null ? f.competition : `GW${f.gw}`} · ${f.kickoff ? stamp(f.kickoff) : "Date TBC"}`;
  const exportCsv = () => {
    const cell = (s: string) => `"${(/^[=+@\-\t\r]/.test(s) ? "'" + s : s).replaceAll('"', '""')}"`;
    const lines = [["Team", ...columns.map((c) => `${c.heading} · ${c.label}`)], ...clubs.map((t) => [t.team_name, ...columns.map((c) => {
      const slot = slotLabel(t.team_code, c);
      const fixtures = cellFixtures(t.team_code, c.key).map(description).join(" | ");
      return slot === "BGW" || slot === "UNAVAILABLE" ? slot : slot === "DGW" ? `DGW | ${fixtures}` : fixtures;
    })])];
    const url = URL.createObjectURL(new Blob(["\uFEFF" + lines.map((r) => r.map(cell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `club-calendar-${season}-${from}-${to}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Keep the blob alive until the browser has started consuming the download.
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="space-y-3" aria-label="All-competition fixture calendar">
    <div className="rounded-lg border bg-card p-3 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="font-semibold">Club calendar · all competitions</h2><p className="text-xs text-muted-foreground">{season} · Weekends by GW, cup fixtures between them. Hover or tap a match for its date and UK kickoff time.</p></div>
        <Button variant="outline" size="sm" onClick={exportCsv} disabled={invalidRange || !columns.length}><Download className="size-3.5" /> CSV</Button>
      </div>
      <div className="flex flex-wrap gap-3 items-end text-sm">
        <MultiSelectFilter label="Team" ariaLabel="Calendar teams" allLabel="All teams" selected={selected} onChange={setSelected}
          options={[...teams].sort((a,b) => a.team_name.localeCompare(b.team_name)).map((t) => ({value: t.team_code, label: t.team_name}))} searchable searchLabel="Search calendar teams" />
        <ToggleGroup type="single" value={range === null ? String(horizon) : ""} onValueChange={(v) => { if (v) { setHorizon(Number(v)); setRange(null); } }} variant="outline" size="sm" aria-label="Calendar horizon">
          {[5, 10, 15].map((n) => <ToggleGroupItem key={n} value={String(n)}>{n} GWs</ToggleGroupItem>)}
        </ToggleGroup>
        <label className="grid gap-1 text-xs text-muted-foreground">From<input aria-label="Calendar from" type="date" className="rounded border bg-background px-2 py-1.5 text-foreground" value={from} onChange={(e) => setRange([e.target.value, to])} /></label>
        <label className="grid gap-1 text-xs text-muted-foreground">To<input aria-label="Calendar to" type="date" className="rounded border bg-background px-2 py-1.5 text-foreground" value={to} onChange={(e) => setRange([from, e.target.value])} /></label>
        <Button variant="ghost" size="sm" onClick={() => { setRange(null); setHorizon(toGw - fromGw + 1); setSelected([]); setColour("opponent"); }}>Reset calendar</Button>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <ToggleGroup type="single" value={colour} onValueChange={(v) => { if (v) setColour(v as typeof colour); }} variant="outline" size="sm" aria-label="Calendar difficulty source">
          <ToggleGroupItem value="opponent">Opponent strength</ToggleGroupItem><ToggleGroupItem value="fdr">Official FDR</ToggleGroupItem>
        </ToggleGroup>
        {legend.map((l) => <span key={l.bucket} className={`rounded px-2 py-1 ${BUCKET_CLASSES[l.bucket]}`}>{l.label}</span>)}
        <span className={`rounded px-2 py-1 ${cupClass}`}>Cup / Europe</span>
      </div>
      <p className="text-xs text-muted-foreground">PL colours use {colour === "opponent" ? `opponent strength from the selected forecast (${teams[0]?.as_of.slice(0, 10)})` : "current official FPL difficulty"}. Blue identifies cup and European matches, not difficulty. A blank cell means no listed fixture, not confirmed rest.</p>
    </div>
    {loading && <p role="status" className="text-sm text-muted-foreground">Loading retained cup and European schedules…</p>}
    {(error || (data && data.season !== season)) && <p role="alert" className="rounded border border-amber-400 bg-amber-50 p-3 text-sm text-amber-950">{error ?? `No competitive schedule for ${season}`}. Only official PL fixtures are shown; cup workload is unknown.</p>}
    {data?.season === season && <div className="space-y-1.5">
      <div className="flex flex-wrap gap-1.5 text-xs">{data.competitions.map((c) => <span key={c.competition_id} className="rounded border bg-muted/40 px-2 py-1">{c.name}: {c.status === "NOT_PUBLISHED" ? "not yet listed" : c.status === "AVAILABLE" ? `${c.matches.length} listed matches` : c.status.toLowerCase()}</span>)}</div>
      <p className="text-xs text-muted-foreground">Counts above cover the retained season catalogues. Retained schedules may change; future draws and competitions outside these six sources are not covered. {teams.filter((t) => !data.verified_team_codes.includes(t.team_code)).length > 0 && "Some clubs lack verified SDP identity; their cup schedule is unavailable."}</p>
    </div>}
    {invalidRange ? <p role="alert">Choose both dates, with the end date on or after the start date.</p> : <>
      <p className="text-xs text-muted-foreground">{clubs.length} clubs · {columns.length} periods · {new Set(displayed.map((r) => r.key.slice(0, r.key.lastIndexOf(":")))).size} listed fixtures. Weekend columns include all official GW legs, including weekday games. DGW = multiple PL fixtures; BGW = no PL fixture in the published schedule. Missing schedules stay unavailable.</p>
      <DecisionTableFullscreen label="Club calendar table">
        {({isFullscreen}) => <div className={`${isFullscreen ? "min-h-0 flex-1" : "max-h-[72vh]"} overflow-auto overscroll-contain`}>
          <TooltipProvider delayDuration={200}>
            <table aria-label="All competitions by period" className="table-fixed border-collapse text-xs tabular-nums" style={{width: 152 + columns.length * 84}}>
              <colgroup><col style={{width:152}} />{columns.map((c) => <col key={c.key} style={{width:84}} />)}</colgroup>
              <thead className="sticky top-0 z-20 bg-muted"><tr><th scope="col" className="sticky left-0 z-30 border-b border-r bg-muted px-3 py-2 text-left">Club</th>
                {columns.map((c) => <th key={c.key} scope="col" title={`${c.from} – ${c.to} · UK dates`} className={`border-b border-r px-1 py-2 text-center font-medium ${c.heading === "Weekend" ? "" : "bg-sky-50 text-sky-950 dark:bg-sky-950 dark:text-sky-100"}`}><span className="block text-[10px] text-muted-foreground">{c.heading}</span><span className="block text-[11px] leading-tight">{c.label}</span></th>)}</tr></thead>
              <tbody>{clubs.map((t) => <tr key={t.team_code}><th scope="row" className="sticky left-0 z-10 border-b border-r bg-card px-3 py-1.5 text-left font-medium"><span className="flex items-center gap-2 whitespace-nowrap"><TeamBadge teamCode={t.team_code} shortName={t.short_name} size="sm" />{t.team_name}</span></th>
                {columns.map((c) => <td key={c.key} className="border-b border-r p-0.5 align-middle text-center">
                  {slotLabel(t.team_code, c) === "BGW" && <span title="No Premier League fixture assigned in the current published schedule; subsequent amendments may change this." className="block rounded border border-dashed px-1 py-2 font-medium text-muted-foreground">BGW<span className="block text-[9px] font-normal">No PL fixture</span></span>}
                  {slotLabel(t.team_code, c) === "UNAVAILABLE" && <span className="text-[10px] text-muted-foreground">Unavailable</span>}
                  {slotLabel(t.team_code, c) === "DGW" && <span className="mb-0.5 block rounded bg-blue-50 text-[9px] font-semibold text-blue-800 dark:bg-blue-950 dark:text-blue-200">DGW · {cellFixtures(t.team_code, c.key).length} fixtures</span>}
                  {cellFixtures(t.team_code, c.key).map((f) => {
                  const value = colour === "fdr" ? f.fdr : strength.get(f.opponentCode ?? -1)?.index;
                  const bucket = colour === "fdr" ? fdrBucket(value ?? null) : opponentStrengthBucket(value);
                  return <Tooltip key={f.key}><TooltipTrigger asChild><button type="button" className={`block w-full rounded-sm px-2 py-1 leading-tight ${f.gw === null ? cupClass : bucket ? BUCKET_CLASSES[bucket] : NULL_BUCKET_CLASS}`} aria-label={`${t.team_name}: ${description(f)}`}><span className="block font-semibold">{f.opponent} <span className="font-normal">({venue(f.home)})</span></span><span className="text-[10px]">{f.gw === null ? f.competition : `GW${f.gw}`}</span></button></TooltipTrigger>
                    <TooltipContent side="top" className="max-w-72 space-y-1 p-3 text-xs"><p className="font-semibold">{t.team_name} · {f.opponentName} ({venue(f.home)})</p><p>{f.competitionName}{f.gw !== null ? ` · GW${f.gw}` : ""}</p><p>{f.kickoff ? `${stamp(f.kickoff)} UK` : "Date/time TBC"} · {f.status}</p>{f.gw !== null && <p>{colour === "fdr" ? "Official FDR" : "Opponent strength"}: {value == null ? "Unavailable" : value.toFixed(1)}</p>}<p>{f.source} {f.source === "FPL" ? "schedule export" : "source version"}: {stamp(f.knownAt)} UK</p></TooltipContent>
                  </Tooltip>;
                })}</td>)}</tr>)}</tbody>
            </table>
          </TooltipProvider>
          {!columns.length && <p className="p-6 text-sm text-muted-foreground">No listed fixtures in this range. Check schedule coverage above.</p>}
        </div>}
      </DecisionTableFullscreen>
    </>}
    {visible.undated.length > 0 && <details className="rounded border p-3 text-sm"><summary>Date/time to be confirmed · {visible.undated.length} club entries (not assigned to a day)</summary><ul className="mt-2 text-xs space-y-1">{visible.undated.map((f) => <li key={f.key}>{teams.find((t) => t.team_code === f.teamCode)?.team_name}: {description(f)}</li>)}</ul></details>}
    <details className="rounded border p-3 text-xs text-muted-foreground"><summary className="cursor-pointer">Sources & schedule coverage</summary><p className="mt-2">FPL schedule exported {stamp(schedule.export_created_at)} UK. This calendar is separate from immutable prediction vintages and does not change xP, optimizer inputs or player minutes.</p>
      {data?.season === season && <><p>SDP calendar exported {stamp(data.as_of)} UK. Source timestamps below are the retained payload version times; unchanged captures do not advance them. Coverage is the provider’s listed schedule, not proof that all future rounds are known.</p>{data.competitions.map((c) => <div className="mt-2" key={c.competition_id}><strong>{c.name}</strong> · {c.status}{c.issues.length ? ` · ${c.issues.join(", ")}` : ""}<ul>{c.sources.map((s) => <li key={s.payload_id}>{stamp(s.known_at)} UK · SHA256 <code className="break-all">{s.sha256}</code></li>)}</ul></div>)}</>}
    </details>
  </section>;
}
