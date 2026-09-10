import { ArrowUpRight, X } from "lucide-react";
import type { SdpMatch, SdpMetric } from "@/data/sdpStats";
import { Button } from "@/components/ui/button";
import { assumptionDescription, correctionDescription, finite, metricAssumptions, metricCorrections, metricId, metricRaw, metricValue } from "@/lib/sdpStats";
import type { SdpEntity, SdpMode } from "@/lib/sdpStats";
import { sdpNumber as fmt, teamBenchmark, teamMetricLabel } from "@/lib/sdpTeamAnalysis";

export function MetricCell({ rows, metric, mode, coverage = true }: { rows: SdpMatch[]; metric: SdpMetric; mode: SdpMode; coverage?: boolean }) {
  const value = metricValue(rows, metric, mode);
  const corrections = metricCorrections(rows, metric), assumptions = metricAssumptions(rows, metric);
  const title = [
    `${metric.source.toUpperCase()} · ${metric.provider_field ?? metric.key}. ${metric.description ?? "Recorded match statistic."}`,
    `${value.measured}/${value.matches} matches. ${metric.verified_semantics ? "" : "Provider observation; not independently reconciled."}`,
    ...corrections.map(correctionDescription), ...assumptions.map(assumptionDescription),
  ].join(" ");
  return <span title={title} className="tabular-nums">
    {value.value === null ? <span className="text-muted-foreground">Unavailable</span> : fmt(value.value)}
    {corrections.length > 0 && <sup className="ml-0.5 text-amber-700 dark:text-amber-300" aria-label="owner-confirmed display correction">‡</sup>}
    {assumptions.length > 0 && <sup className="ml-0.5 text-sky-700 dark:text-sky-300" aria-label="owner-directed omitted-count assumption">§</sup>}
    {coverage && <span className="ml-2 text-xs font-normal text-muted-foreground">{value.measured}/{value.matches}</span>}
  </span>;
}

export function TeamTrend({ entity, metric, compact = false }: { entity: SdpEntity; metric: SdpMetric; compact?: boolean }) {
  const values = entity.rows.map(row => metricRaw(row, metric));
  const measured = values.filter(finite);
  const width = 480, height = compact ? 68 : 155, pad = 14;
  const max = Math.max(1, ...measured), min = Math.min(0, ...measured);
  const x = (i: number) => pad + i * (width - pad * 2) / Math.max(1, values.length - 1);
  const y = (v: number) => height - pad - (v - min) / (max - min) * (height - pad * 2);
  const label = `${entity.name}: observed ${metric.label} by match`;
  if (!measured.length) return <p className="py-5 text-xs text-muted-foreground">No measured {metric.label.toLowerCase()} in this range.</p>;
  return <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={label} className="w-full text-[var(--sdp-accent)]">
    <title>{label}. Exact values and correction provenance are in the match log.</title>
    <line x1={pad} x2={width - pad} y1={y(0)} y2={y(0)} stroke="currentColor" opacity=".15" />
    {values.map((value, i) => value === null ? null : <g key={entity.rows[i].fixture}>
      {i > 0 && values[i - 1] !== null && <line x1={x(i - 1)} y1={y(values[i - 1]!)} x2={x(i)} y2={y(value)} stroke="currentColor" strokeWidth={compact ? 3 : 2} />}
      <circle cx={x(i)} cy={y(value)} r={compact ? 3 : 4} fill="currentColor">
        <title>GW{entity.rows[i].gw} · {entity.rows[i].opponent_short_name} ({entity.rows[i].was_home ? "H" : "A"}): {fmt(value)}{metricCorrections([entity.rows[i]], metric).length ? " · owner-confirmed" : ""}{metricAssumptions([entity.rows[i]], metric).length ? " · assumed zero" : ""}</title>
      </circle>
    </g>)}
  </svg>;
}

export function TeamProfile({ team, league, fullRange, metrics, onLog }: { team: SdpEntity; league: SdpEntity[]; fullRange: SdpEntity | undefined; metrics: SdpMetric[]; onLog: () => void }) {
  return <section className="sdp-panel overflow-hidden" aria-label={`${team.name} profile`}>
    <div className="sdp-profile-heading flex flex-wrap items-center justify-between gap-4 border-b p-5 sm:p-6">
      <div className="flex items-center gap-4">
        <span className="sdp-club-mark text-base" aria-hidden="true">{team.rows.at(-1)?.team_short_name}</span>
        <div><p className="sdp-eyebrow">Club profile</p><h2 className="mt-1 text-xl font-semibold tracking-tight">{team.name}</h2><p className="mt-1 text-xs text-muted-foreground">{team.rows.length} observed matches · {team.rows[0]?.season} · GW{team.rows[0]?.gw}–GW{team.rows.at(-1)?.gw}</p></div>
      </div>
      <Button variant="outline" onClick={onLog}>Match log <ArrowUpRight aria-hidden="true" /></Button>
    </div>
    <div className="grid divide-y sm:grid-cols-2 sm:divide-y-0">
      {metrics.slice(0, 4).map(metric => {
        const value = metricValue(team.rows, metric, "per_match").value;
        const baseline = teamBenchmark(league, metric, "per_match", value);
        const long = fullRange ? metricValue(fullRange.rows, metric, "per_match").value : null;
        const same = fullRange?.rows.length === team.rows.length;
        return <div key={metricId(metric)} className="min-w-0 p-5 sm:p-6 sm:odd:border-r sm:[&:nth-child(n+3)]:border-t">
          <p className="text-xs font-medium text-muted-foreground">{teamMetricLabel(metric, "per_match")}</p>
          <div className="mt-2 text-3xl font-semibold tracking-tight"><MetricCell rows={team.rows} metric={metric} mode="per_match" coverage={false} /></div>
          <TeamTrend entity={team} metric={metric} compact />
          <div className="mb-2 flex justify-between gap-2 text-xs"><span className="text-muted-foreground">League median {fmt(baseline.median)}</span><span className="font-medium">{baseline.percentile === null ? "Percentile unavailable" : `P${fmt(baseline.percentile, 0)} · value percentile`}</span></div>
          <div className="relative h-1.5 rounded-full bg-muted" aria-hidden="true"><div className="h-full rounded-full bg-[var(--sdp-accent)]" style={{ width: `${baseline.percentile ?? 0}%` }} /><span className="absolute inset-y-[-3px] left-1/2 w-px bg-muted-foreground/60" /></div>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">{same ? "Selected window equals the full GW range." : `Full GW range: ${fmt(long)} (${fullRange?.rows.length ?? 0} matches). Difference: ${value === null || long === null ? "Unavailable" : `${value - long > 0 ? "+" : ""}${fmt(value - long)}`}.`}</p>
          <p className="mt-1 text-xs text-muted-foreground">Benchmark: {baseline.count} clubs with complete metric coverage.</p>
        </div>;
      })}
    </div>
    <p className="border-t px-5 py-3 text-xs leading-relaxed text-muted-foreground">Percentiles describe values, not team quality. Benchmarks use all clubs in the same season, GW range, venue and recent window, including marked display corrections and assumptions; searching or selecting a club does not change them. Recent changes are descriptive.</p>
  </section>;
}

export function TeamComparison({ teams, metrics, mode, onRemove }: { teams: SdpEntity[]; metrics: SdpMetric[]; mode: SdpMode; onRemove: (id: string) => void }) {
  if (!teams.length) return null;
  return <section className="sdp-panel p-5 sm:p-6" aria-label="Selected comparison">
    <div className="mb-5 flex flex-wrap items-center justify-between gap-3"><div><p className="sdp-eyebrow">Side by side</p><h2 className="mt-1 text-lg font-semibold">Compare observed profiles</h2></div><div className="flex flex-wrap gap-2">{teams.map((team, i) => <Button key={team.id} variant="outline" size="sm" onClick={() => onRemove(team.id)} aria-label={`Remove ${team.name} from comparison`}><span className="size-2 rounded-full" style={{ background: `var(--sdp-series-${i + 1})` }} />{team.name}<X className="size-3" aria-hidden="true" /></Button>)}</div></div>
    <div className="grid gap-x-8 gap-y-6 sm:grid-cols-2 xl:grid-cols-3">{metrics.slice(0, 6).map(metric => {
      const values = teams.map(team => metricValue(team.rows, metric, mode).value);
      const max = Math.max(1, ...values.filter(finite));
      return <div key={metricId(metric)}><h3 className="mb-3 text-xs font-medium text-muted-foreground">{teamMetricLabel(metric, mode)}</h3>{teams.map((team, i) => <div key={team.id} className="mt-3"><div className="mb-1.5 flex items-center justify-between gap-3 text-xs"><span>{team.name}</span><MetricCell rows={team.rows} metric={metric} mode={mode} /></div><div className="h-1.5 rounded-full bg-muted" aria-hidden="true">{values[i] !== null && <div className="h-full rounded-full" style={{ width: `${Math.max(0, values[i]!) / max * 100}%`, background: `var(--sdp-series-${i + 1})` }} />}</div></div>)}</div>;
    })}</div>
    <p className="mt-5 border-t pt-3 text-xs text-muted-foreground">Same filters and units for every club. Up to 3 clubs; each value includes its matched coverage. Missing values have no bar.</p>
  </section>;
}
