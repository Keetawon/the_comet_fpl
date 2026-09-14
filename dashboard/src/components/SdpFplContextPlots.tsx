import { Flame, Shield } from "lucide-react";
import { AnalyticsScatter, type AnalyticsScatterPoint } from "@/components/AnalyticsScatter";
import type { SdpMetric } from "@/data/sdpStats";
import { finite, metricAssumptions, metricCorrections, metricRaw, metricSourceLabel, metricSupplements, metricValue, shotShare } from "@/lib/sdpStats";
import type { SdpEntity, SdpFilters } from "@/lib/sdpStats";
import { sdpNumber as fmt, teamBenchmark } from "@/lib/sdpTeamAnalysis";

interface Props {
  teams: readonly SdpEntity[];
  league: readonly SdpEntity[];
  metrics: readonly SdpMetric[];
  filters: SdpFilters;
  asOf: string;
  selectedId: string | null;
  onSelectTeam: (id: string) => void;
}

const views = [
  { id: "attack", title: "Attack · Goal threat", icon: Flame, x: "shots_on_target", y: "expected_goals", xLabel: "SOT /match", yLabel: "xG /match", note: "Upper right: more chance value and more shots on target. Explore individual minutes and attacking shares before choosing a player." },
  { id: "defence", title: "Defence · Clean-sheet exposure", icon: Shield, x: "shots_on_target_allowed", y: "expected_goals_allowed", xLabel: "SOT conceded /match", yLabel: "xGA /match", note: "Lower left: less chance value and fewer shots on target conceded. More shots faced can mean more goalkeeper work, alongside clean-sheet risk." },
] as const;

function marks(team: SdpEntity, metric: SdpMetric) {
  return `${metricCorrections(team.rows, metric).length ? " ‡" : ""}${metricAssumptions(team.rows, metric).length ? " §" : ""}${metricSupplements(team.rows, metric).length ? " [FPL]" : ""}`;
}

export function SdpFplContextPlots({ teams, league, metrics, filters, asOf, selectedId, onSelectTeam }: Props) {
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
    const xgMetric = find(attack ? "expected_goals" : "expected_goals_allowed");
    const rows = [
      { label: `${attack ? "Goals" : "Goals conceded"} /match · FPL`, value: average(team, find(attack ? "goals_scored" : "goals_conceded", "fpl")) },
      { label: `${attack ? "Shots" : "Shots conceded"} /match · SDP`, value: average(team, shotMetric) },
      { label: `${attack ? "xG" : "xGA"} /shot · SDP / marked FPL`, value: perShot(team, xgMetric, shotMetric) },
    ];
    if (attack) {
      const sot = find("shots_on_target");
      const share = sot && shotMetric ? shotShare(team.rows, sot, shotMetric) : null;
      rows.push(
        { label: "SOT / all shots · SDP", value: share === null ? "—" : `${fmt(share, 1)}%${marks(team, sot!)}${marks(team, shotMetric!)}` },
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

  return <section className="sdp-context-plots space-y-4" aria-label="Attack and defence FPL context">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="sdp-eyebrow">Two sides of the game</p><h2 className="mt-1 text-xl font-semibold tracking-tight">Attack & defence</h2></div><p className="text-xs text-muted-foreground">Click a club to highlight it in both plots.</p></div>
    <div className="grid min-w-0 items-start gap-5 lg:grid-cols-2">
      {views.map(view => {
        const xMetric = find(view.x), yMetric = find(view.y);
        const coordinates = (team: SdpEntity) => {
          if (!xMetric || !yMetric) return null;
          const x = metricValue(team.rows, xMetric, "per_match").value;
          const y = metricValue(team.rows, yMetric, "per_match").value;
          return x !== null && y !== null && x >= 0 && y >= 0 ? { x, y } : null;
        };
        // Both medians use the same complete-pair league cohort, unaffected by club search.
        const eligibleLeague = league.filter(team => coordinates(team) !== null);
        const points: AnalyticsScatterPoint[] = teams.flatMap(team => {
          const pair = coordinates(team);
          if (!pair || !xMetric || !yMetric) return [];
          return [{ id: team.id, label: team.name, shortLabel: team.rows.at(-1)?.team_short_name,
            ...pair, xDisplay: average(team, xMetric), yDisplay: average(team, yMetric),
            groupLabel: `${team.rows.length} matched observations`, details: details(team, view.id === "attack"),
            color: "var(--sdp-plot-accent)", radius: 5,
          }];
        });
        return <article key={view.id} className={`sdp-panel sdp-${view.id}-plot min-w-0 p-4 sm:p-5`} aria-label={`${view.id === "attack" ? "Attack" : "Defence"} plot panel`}>
          <div className="sdp-plot-direction mb-3 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium"><view.icon className="size-4 shrink-0" aria-hidden="true" />{view.id === "attack" ? "Goal threat · look upper right ↗" : "Chance prevention · look lower left ↙"}</div>
          <AnalyticsScatter title={view.title} className="border-0 p-0 shadow-none"
            description={`${points.length}/${teams.length} visible clubs with complete paired coverage. League median: ${eligibleLeague.length} eligible clubs.`}
            readingNote={view.note} points={points}
            xAxis={{ label: `${xMetric ? metricSourceLabel(xMetric) : "SDP"} ${view.xLabel}`, displayLabel: view.xLabel, direction: "explanatory", bounds: { min: 0 } }}
            yAxis={{ label: `${yMetric ? metricSourceLabel(yMetric) : "SDP / marked FPL"} ${view.yLabel}`, displayLabel: view.yLabel, direction: "explanatory", bounds: { min: 0 } }}
            medianX={xMetric ? teamBenchmark(eligibleLeague, xMetric, "per_match", null).median : null}
            medianY={yMetric ? teamBenchmark(eligibleLeague, yMetric, "per_match", null).median : null}
            selectedPointId={selectedId} onSelectPoint={id => onSelectTeam(String(id))}
            vintageLabel={`Observed export ${asOf}`} vintageDisplayLabel="SDP / marked FPL" provenanceLabel="Observed"
            horizonLabel={`${filters.season} GW${filters.from}–${filters.to}; ${filters.recent}; ${filters.venue}`}
            horizonDisplayLabel={`GW${filters.from}–${filters.to} · ${filters.venue} · ${filters.recent === "all" ? "full range" : `up to ${filters.recent} matches`}`}
            emptyMessage={`No clubs have complete ${view.xLabel} and ${view.yLabel} in this range. Missing observations remain unavailable.`} />
        </article>;
      })}
    </div>
    <p className="text-xs leading-relaxed text-muted-foreground">‡ Owner-confirmed · § Assumed omitted zero · [FPL] Historical xG supplement. These are observed, unadjusted match statistics; recent opponents and sample size matter. Team clean sheets are match outcomes, not player clean-sheet points or future probabilities. Provider observation qualifiers remain in the metric table; model forecasts are unchanged.</p>
  </section>;
}
