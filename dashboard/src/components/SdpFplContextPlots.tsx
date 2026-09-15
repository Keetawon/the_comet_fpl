import { useMemo, useState } from "react";
import { ChartNoAxesCombined, Flame, Shield, Target } from "lucide-react";
import { AnalyticsScatter, type AnalyticsScatterPoint } from "@/components/AnalyticsScatter";
import { DecisionTableFullscreen } from "@/components/DecisionTableFullscreen";
import type { SdpMatch, SdpMetric } from "@/data/sdpStats";
import { finite, metricAssumptions, metricCorrections, metricRaw, metricSourceLabel, metricSupplements, metricValue, shotShare } from "@/lib/sdpStats";
import type { SdpEntity, SdpFilters } from "@/lib/sdpStats";
import { sdpNumber as fmt, teamBenchmark } from "@/lib/sdpTeamAnalysis";

interface Props {
  teams: readonly SdpEntity[];
  league: readonly SdpEntity[];
  teamMatches: readonly SdpMatch[];
  metrics: readonly SdpMetric[];
  filters: SdpFilters;
  asOf: string;
  selectedId: string | null;
  onSelectTeam: (id: string) => void;
}

const views = [
  { id: "attack", panel: "Attack", title: "Attack · Goal threat", icon: Flame, x: "shots_on_target", y: "expected_goals", ySource: "sdp", xLabel: "SOT /match", yLabel: "xG /match", direction: "Goal threat · look upper right ↗", note: "Upper right: more chance value and more shots on target. Explore individual minutes and attacking shares before choosing a player." },
  { id: "defence", panel: "Defence", title: "Defence · Clean-sheet exposure", icon: Shield, x: "shots_on_target_allowed", y: "expected_goals_allowed", ySource: "sdp", xLabel: "SOT conceded /match", yLabel: "xGA /match", direction: "Chance prevention · look lower left ↙", note: "Lower left: less chance value and fewer shots on target conceded. More shots faced can mean more goalkeeper work, alongside clean-sheet risk." },
  { id: "finishing", panel: "Goals vs xG", title: "Goals vs xG · Observed finishing", icon: Target, x: "expected_goals", y: "goals_scored", ySource: "fpl", xLabel: "xG /match", yLabel: "Goals /match", direction: "Finishing · observed goals and chance value", note: "Compare goals with xG over the same matches. Team goals include opponent own goals. A difference describes this sample; it does not predict future finishing." },
] as const;

type ShotAxis = "share" | "volume" | "box";
const shotAxes = [
  { value: "share", attack: "SOT / all shots (%)", defence: "SOT conceded / all shots conceded (%)" },
  { value: "volume", attack: "SOT /match", defence: "SOT conceded /match" },
  { value: "box", attack: "Shots inside box /match", defence: "Shots inside box conceded /match" },
] as const;

// An opponent's observed box shots are this club's box shots conceded. Look up
// exact reciprocal match sides before applying venue/team display filters.
function opponentLookup(rows: readonly SdpMatch[]) {
  const key = (row: SdpMatch, team = row.team_code) => `${row.season}:${row.fixture}:${team}`;
  const index = new Map<string, SdpMatch | null>();
  for (const row of rows) index.set(key(row), index.has(key(row)) ? null : row);
  return (rows: readonly SdpMatch[]): SdpMatch[] | null => {
    const opponents: SdpMatch[] = [];
    for (const row of rows) {
      const other = index.get(key(row, row.opponent_team_code));
      if (!index.get(key(row)) || !other || other.opponent_team_code !== row.team_code ||
          other.was_home === row.was_home || other.gw !== row.gw ||
          Date.parse(other.kickoff_time) !== Date.parse(row.kickoff_time) ||
          other.provider_match_id !== row.provider_match_id) return null;
      opponents.push(other);
    }
    return opponents;
  };
}

function median(values: number[]) {
  values.sort((a, b) => a - b);
  return values.length ? (values[Math.floor((values.length - 1) / 2)] + values[Math.floor(values.length / 2)]) / 2 : null;
}

const goalPatterns = [
  { key: "open_play_goals", label: "Open play", color: "var(--sdp-pattern-open)" },
  { key: "confirmed_set_piece_goals", label: "Set piece (confirmed)", color: "var(--sdp-pattern-set)" },
  { key: "own_goals_received", label: "Opponent own goal", color: "var(--sdp-pattern-own)" },
  { key: "unclassified_goals", label: "Unclassified", color: "var(--sdp-pattern-unknown)" },
] as const;

function patternTotals(team: SdpEntity) {
  const receipts = team.rows.flatMap(row => row.goal_patterns ? [row.goal_patterns] : []);
  if (!receipts.length || receipts.length !== team.rows.length) return { measured: receipts.length, totals: null };
  const totals = { open_play_goals: 0, confirmed_set_piece_goals: 0, own_goals_received: 0, unclassified_goals: 0, total_goals: 0 };
  for (const receipt of receipts) {
    for (const { key } of goalPatterns) totals[key] += receipt[key];
    totals.total_goals += receipt.total_goals;
  }
  return { measured: receipts.length, totals };
}

function marks(team: SdpEntity, metric: SdpMetric) {
  return `${metricCorrections(team.rows, metric).length ? " ‡" : ""}${metricAssumptions(team.rows, metric).length ? " §" : ""}${metricSupplements(team.rows, metric).length ? " [FPL]" : ""}`;
}

export function SdpFplContextPlots({ teams, league, teamMatches, metrics, filters, asOf, selectedId, onSelectTeam }: Props) {
  const [attackAxis, setAttackAxis] = useState<ShotAxis>("share");
  const [defenceAxis, setDefenceAxis] = useState<ShotAxis>("share");
  const opponents = useMemo(() => opponentLookup(teamMatches), [teamMatches]);
  const find = (key: string, source: "sdp" | "fpl" = "sdp") => metrics.find(metric => metric.key === key && metric.source === source);
  const average = (team: SdpEntity, metric: SdpMetric | undefined) => metric ? `${fmt(metricValue(team.rows, metric, "per_match").value)}${marks(team, metric)}` : "—";
  const perShot = (team: SdpEntity, chance: SdpMetric | undefined, shots: SdpMetric | undefined) => {
    if (!chance || !shots) return "—";
    const numerator = metricValue(team.rows, chance, "total").value;
    const denominator = metricValue(team.rows, shots, "total").value;
    return numerator !== null && denominator !== null && denominator > 0
      ? `${fmt(numerator / denominator, 3)}${marks(team, chance)}${marks(team, shots)}` : "—";
  };
  const details = (team: SdpEntity, attack: boolean): AnalyticsScatterPoint["details"] => {
    const shotMetric = find(attack ? "shots" : "shots_allowed");
    const sot = find(attack ? "shots_on_target" : "shots_on_target_allowed");
    const share = sot && shotMetric ? shotShare(team.rows, sot, shotMetric) : null;
    const xgMetric = find(attack ? "expected_goals" : "expected_goals_allowed");
    const rows = [
      { label: `${attack ? "Goals" : "Goals conceded"} /match · FPL`, value: average(team, find(attack ? "goals_scored" : "goals_conceded", "fpl")) },
      { label: `${attack ? "Shots" : "Shots conceded"} /match · SDP`, value: average(team, shotMetric) },
      { label: `${attack ? "SOT" : "SOT conceded"} /match · SDP`, value: average(team, sot) },
      { label: `${attack ? "SOT / all shots" : "SOT conceded / all shots conceded"} · SDP`, value: share === null ? "—" : `${fmt(share, 1)}%${marks(team, sot!)}${marks(team, shotMetric!)}` },
      { label: `${attack ? "xG" : "xGA"} /shot · SDP / marked FPL`, value: perShot(team, xgMetric, shotMetric) },
    ];
    if (attack) {
      rows.push(
        { label: "Box touches /match · SDP", value: average(team, find("touches_in_opposition_box")) },
        { label: "xGOT /match · SDP", value: average(team, find("expected_goals_on_target")) },
      );
    } else {
      const conceded = find("goals_conceded", "fpl");
      const goals = conceded ? team.rows.map(row => metricRaw(row, conceded)) : [];
      const complete = goals.length > 0 && goals.every(value => finite(value) && value >= 0);
      rows.push(
        { label: "Team clean sheets / matches · FPL", value: complete ? `${goals.filter(value => value === 0).length}/${goals.length}` : "—" },
        { label: "Saves /match · SDP", value: average(team, find("saves")) },
      );
    }
    return rows;
  };
  const finishingDetails = (team: SdpEntity): AnalyticsScatterPoint["details"] => {
    const xgMetric = find("expected_goals"), goalsMetric = find("goals_scored", "fpl");
    const xg = xgMetric ? metricValue(team.rows, xgMetric, "total").value : null;
    const goals = goalsMetric ? metricValue(team.rows, goalsMetric, "total").value : null;
    return [
      { label: "xG total · SDP / marked FPL", value: `${fmt(xg)}${xgMetric ? marks(team, xgMetric) : ""}` },
      { label: "Goals total · FPL", value: fmt(goals) },
      { label: "Goals minus xG · observed total", value: fmt(goals !== null && xg !== null ? goals - xg : null) },
    ];
  };
  const patterns = teams.map(team => ({ team, ...patternTotals(team) })).sort((a, b) =>
    (b.totals?.total_goals ?? -1) - (a.totals?.total_goals ?? -1) ||
    a.team.name.localeCompare(b.team.name) || a.team.id.localeCompare(b.team.id));
  const maxGoals = Math.max(1, ...patterns.flatMap(row => row.totals ? [row.totals.total_goals] : []));
  const selectedPattern = patterns.find(row => row.team.id === selectedId);
  const horizonLabel = `${filters.season} GW${filters.from}–${filters.to}; ${filters.recent}; ${filters.venue}`;
  const horizonDisplayLabel = `GW${filters.from}–${filters.to} · ${filters.venue} · ${filters.recent === "all" ? "full range" : `up to ${filters.recent} matches`}`;

  return <section className="sdp-context-plots space-y-4" aria-label="Attack and defence FPL context">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="sdp-eyebrow">Four views of the game</p><h2 className="mt-1 text-xl font-semibold tracking-tight">Attack, defence & goals</h2></div><p className="text-xs text-muted-foreground">Click a club to highlight it across all four charts.</p></div>
    <div className="grid min-w-0 items-start gap-5 lg:grid-cols-2">
      {views.map(view => {
        const axis = view.id === "attack" ? attackAxis : view.id === "defence" ? defenceAxis : "volume";
        const percentage = axis === "share";
        const xLabel = view.id === "finishing" ? view.xLabel : shotAxes.find(option => option.value === axis)![view.id];
        const xMetric = find(axis === "box" ? "shots_inside_box" : view.x), yMetric = find(view.y, view.ySource);
        const shotMetric = find(view.id === "defence" ? "shots_allowed" : "shots");
        const xRows = (team: SdpEntity) => view.id === "defence" && axis === "box" ? opponents(team.rows) : team.rows;
        const coordinates = (team: SdpEntity) => {
          if (!xMetric || !yMetric) return null;
          const rows = xRows(team);
          if (!rows) return null;
          const x = percentage ? shotMetric ? shotShare(rows, xMetric, shotMetric) : null : metricValue(rows, xMetric, "per_match").value;
          const y = metricValue(team.rows, yMetric, "per_match").value;
          return x !== null && y !== null && x >= 0 && y >= 0 ? { x, y } : null;
        };
        // Both medians use the same complete-pair league cohort, unaffected by club search.
        const eligibleLeague = league.filter(team => coordinates(team) !== null);
        const points: AnalyticsScatterPoint[] = teams.flatMap(team => {
          const pair = coordinates(team);
          if (!pair || !xMetric || !yMetric) return [];
          return [{ id: team.id, label: team.name, shortLabel: team.rows.at(-1)?.team_short_name,
            ...pair, xDisplay: `${fmt(pair.x, percentage ? 1 : 2)}${percentage ? "%" : ""}${marks({ ...team, rows: xRows(team)! }, xMetric)}${percentage && shotMetric ? marks(team, shotMetric) : ""}`, yDisplay: average(team, yMetric),
            groupLabel: `${team.rows.length} matched observations`, details: view.id === "finishing" ? finishingDetails(team) : details(team, view.id === "attack"),
            color: "var(--sdp-plot-accent)", radius: 5,
          }];
        });
        return <article key={view.id} className={`sdp-panel sdp-${view.id}-plot min-w-0 p-4 sm:p-5`} aria-label={`${view.panel} plot panel`}>
          <div className="sdp-plot-direction mb-3 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium"><view.icon className="size-4 shrink-0" aria-hidden="true" />{view.direction}</div>
          {view.id !== "finishing" && <label className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            X-axis
            <select className="sdp-control min-w-0 max-w-full flex-1" aria-label={`${view.panel} X-axis`} value={axis}
              onChange={event => (view.id === "attack" ? setAttackAxis : setDefenceAxis)(event.target.value as ShotAxis)}>
              {shotAxes.map(option => <option key={option.value} value={option.value} title={option[view.id as "attack" | "defence"]}>{view.id === "defence" && option.value === "share" ? "SOT conceded (%)" : view.id === "defence" && option.value === "box" ? "Box shots conceded /match" : option[view.id as "attack" | "defence"]}</option>)}
            </select>
          </label>}
          <AnalyticsScatter title={view.title} className="border-0 p-0 shadow-none"
            description={`${points.length}/${teams.length} visible clubs with complete paired coverage. League median: ${eligibleLeague.length} eligible clubs.`}
            readingNote={percentage ? `${view.id === "attack" ? "Upper right: higher xG and a larger share of shots on target." : "Lower left: lower xGA and a smaller share of opposing shots on target."} SOT % = total SOT / total shots across the same matches. Check shot volume in the tooltip; this is accuracy, not shot location.` : axis === "box" ? `${view.id === "attack" ? "Upper right: higher xG and more shots from inside the box." : "Lower left: lower xGA and fewer opponent shots from inside the box. Conceded counts use the exact opponent's SDP match row."} Shot location is separate from shots on target.` : view.note} points={points}
            xAxis={{ label: `${xMetric ? metricSourceLabel(xMetric) : "SDP"} ${xLabel}`, displayLabel: xLabel, direction: "explanatory", bounds: { min: 0, ...percentage ? { max: 100 } : {} }, ...percentage ? { format: (value: number) => `${fmt(value, 1)}%` } : {} }}
            yAxis={{ label: `${yMetric ? metricSourceLabel(yMetric) : view.ySource === "fpl" ? "FPL" : "SDP / marked FPL"} ${view.yLabel}`, displayLabel: view.yLabel, direction: "explanatory", bounds: { min: 0 } }}
            medianX={median(eligibleLeague.map(team => coordinates(team)!.x))}
            medianY={yMetric ? teamBenchmark(eligibleLeague, yMetric, "per_match", null).median : null}
            selectedPointId={selectedId} onSelectPoint={id => onSelectTeam(String(id))}
            vintageLabel={`Observed export ${asOf}`} vintageDisplayLabel="SDP / marked FPL" provenanceLabel="Observed"
            horizonLabel={horizonLabel} horizonDisplayLabel={horizonDisplayLabel}
            emptyMessage={`No clubs have complete ${xLabel} and ${view.yLabel} in this range${percentage ? " with a positive shot denominator" : ""}. Missing observations remain unavailable.`} />
        </article>;
      })}
      <article className="sdp-panel sdp-pattern-plot min-w-0 p-4 sm:p-5" aria-label="Goal patterns plot panel">
        <DecisionTableFullscreen label="Goal patterns chart" className="rounded-none border-0" contentClassName="overflow-y-auto">
          {({ isFullscreen }) => <div className={isFullscreen ? "p-4 sm:p-6" : ""}>
            <div className="sdp-plot-direction mb-3 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium"><ChartNoAxesCombined className="size-4 shrink-0" aria-hidden="true" />Goal patterns · how the goals were scored</div>
            <h2 className="text-sm font-semibold">Goal patterns · Observed goals</h2>
            <p className="mt-1 text-xs text-muted-foreground">{patterns.filter(row => row.totals !== null).length}/{teams.length} visible clubs with receipts for every selected match.</p>
            <p role="note" className="mt-2 rounded-md bg-muted/60 px-2.5 py-2 text-xs text-muted-foreground"><span className="font-medium text-foreground">How to read: </span>Bar length is total goals in the selected matches, sorted highest first. Set piece includes penalties and shows confirmed goals only; unclassified goals remain separate. Compare match counts alongside totals.</p>
            <p className="mt-1 text-[11px] text-muted-foreground" title={`Observed export ${asOf}; ${horizonLabel}`}>Observed audited receipts · {horizonDisplayLabel}</p>
            <ul className="my-4 flex flex-wrap gap-x-4 gap-y-2 text-[11px] text-muted-foreground" aria-label="Goal pattern legend">{goalPatterns.map(pattern => <li key={pattern.key} className="flex items-center gap-1.5"><span className="size-2.5 rounded-sm" style={{ background: pattern.color }} aria-hidden="true" />{pattern.label}</li>)}</ul>
            {!patterns.length && <p role="status" className="mt-4 text-sm text-muted-foreground">No clubs in this range.</p>}
            <div className={`sdp-pattern-rows space-y-1${isFullscreen ? "" : " max-h-80 overflow-y-auto"}`} role="group" aria-label={`Observed goal-pattern totals; export ${asOf}; ${horizonLabel}`}>
              {patterns.map(({ team, measured, totals }) => {
                const summary = totals ? `${goalPatterns.map(pattern => `${pattern.label}: ${totals[pattern.key]}`).join("; ")}; Total goals: ${totals.total_goals}` : `Unavailable: ${measured}/${team.rows.length} match receipts`;
                return <button type="button" key={team.id} className="sdp-pattern-row w-full rounded-lg px-2 py-2 text-left" aria-pressed={selectedId === team.id}
                  onClick={() => onSelectTeam(team.id)} aria-label={`${team.name}; ${team.rows.length} matched observations; ${summary}; observed export ${asOf}; ${horizonLabel}`} title={`${team.name} · ${team.rows.length} matches · ${summary}`}>
                  <span className="truncate text-xs font-semibold">{team.rows.at(-1)?.team_short_name ?? team.name}</span>
                  <span className="min-w-0">{totals ? <span className="sdp-pattern-track flex h-4 w-full overflow-hidden rounded-sm bg-muted/60" aria-hidden="true">{goalPatterns.map(pattern => <span key={pattern.key} data-pattern={pattern.key} data-count={totals[pattern.key]} style={{ width: `${totals[pattern.key] / maxGoals * 100}%`, backgroundColor: pattern.color }} />)}</span> : <span className="text-[11px] text-muted-foreground">Unavailable · {measured}/{team.rows.length} match receipts</span>}</span>
                  <span className="text-right text-xs tabular-nums">{totals ? totals.total_goals : "—"}<span className="block text-[10px] text-muted-foreground">{team.rows.length} matches</span></span>
                </button>;
              })}
            </div>
            {selectedPattern?.totals && <div className="mt-4 rounded-lg border bg-muted/30 p-3" aria-label={`${selectedPattern.team.name} goal-pattern detail`}>
              <p className="text-xs font-semibold">{selectedPattern.team.name} · {selectedPattern.team.rows.length} matches · {selectedPattern.totals.total_goals} goals</p>
              <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 text-[11px]">{goalPatterns.map(pattern => <div key={pattern.key}><dt className="text-muted-foreground">{pattern.label}</dt><dd className="font-medium tabular-nums">{selectedPattern.totals![pattern.key]}</dd></div>)}</dl>
            </div>}
            <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground">Missing match receipts leave a club unavailable. Categories come from published audit receipts and describe past goals only.</p>
          </div>}
        </DecisionTableFullscreen>
      </article>
    </div>
    <p className="text-xs leading-relaxed text-muted-foreground">‡ Owner-confirmed · § Assumed omitted zero · [FPL] Historical xG supplement. These are observed, unadjusted match statistics; recent opponents and sample size matter. Team clean sheets are match outcomes, not player clean-sheet points or future probabilities. Provider observation qualifiers remain in the metric table; model forecasts are unchanged.</p>
  </section>;
}
