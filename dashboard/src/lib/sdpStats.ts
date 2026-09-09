import type { SdpDisplayAssumption, SdpDisplayCorrection, SdpMatch, SdpMetric, SdpScope } from "@/data/sdpStats";

export type SdpMode = "total" | "per_match" | "per90";
export interface SdpFilters {
  season: string; from: number; to: number; team: string; venue: "all" | "home" | "away";
  recent: "all" | "3" | "5"; search: string; position: string; minMinutes: number;
}
export interface MetricValue { value: number | null; measured: number; matches: number; minutes: number | null }
export interface SdpEntity {
  id: string; name: string; clubs: string; position: string; code: number | null;
  teamCode: number; rows: SdpMatch[];
}

export const metricId = (m: SdpMetric) => `${m.scope}:${m.source}:${m.key}`;
export const entityId = (row: SdpMatch, scope: SdpScope) => scope === "team"
  ? `team:${row.team_code}` : row.code != null ? `fpl:${row.code}` : `sdp:${row.provider_player_id}`;
export const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export const metricCorrection = (row: SdpMatch, metric: SdpMetric): SdpDisplayCorrection | null =>
  metric.source === "sdp" ? row.display_corrections?.[metric.key] ?? null : null;
export const metricAssumption = (row: SdpMatch, metric: SdpMetric): SdpDisplayAssumption | null =>
  metric.source === "sdp" ? row.display_assumptions?.[metric.key] ?? null : null;
export const metricRaw = (row: SdpMatch, metric: SdpMetric): number | null => {
  const correction = metricCorrection(row, metric);
  if (correction) return correction.value;
  const assumption = metricAssumption(row, metric);
  if (assumption) return assumption.value;
  const value = row[metric.source]?.[metric.key];
  return finite(value) ? value : null;
};
export const correctionDescription = (correction: SdpDisplayCorrection) =>
  `Owner-confirmed display correction recorded ${correction.owner_confirmation_recorded_at}; raw SDP ${correction.provider_field} was omitted; corroborated by shot accounting and the official FPL goalkeeper proxy; raw payload SHA256 ${correction.raw_payload_sha256}. Provider core validity is unchanged.`;
export const assumptionDescription = (assumption: SdpDisplayAssumption) =>
  `Owner-directed display assumption recorded ${assumption.policy_recorded_at}; raw SDP ${assumption.provider_field} was omitted and is shown as zero for this sparse count. This is not a provider-verified zero; raw remains NULL. Raw payload SHA256 ${assumption.raw_payload_sha256}. Provider core validity is unchanged.`;
export function metricCorrections(rows: readonly SdpMatch[], metric: SdpMetric): SdpDisplayCorrection[] {
  const found = rows.flatMap(row => metricCorrection(row, metric) ?? []);
  return [...new Map(found.map(correction => [correction.correction_id, correction])).values()];
}
export function metricAssumptions(rows: readonly SdpMatch[], metric: SdpMetric): SdpDisplayAssumption[] {
  return rows.flatMap(row => metricAssumption(row, metric) ?? []);
}

export function metricValue(rows: readonly SdpMatch[], metric: SdpMetric, mode: SdpMode): MetricValue {
  const values = rows.map(row => metricRaw(row, metric));
  const measured = values.filter(finite).length;
  const result: MetricValue = { value: null, measured, matches: rows.length, minutes: null };
  if (!rows.length || measured !== rows.length) return result;
  const total = values.reduce<number>((sum, value) => sum + (value as number), 0);
  if (!finite(total)) return result;
  if (metric.aggregation === "mean") return { ...result, value: total / rows.length };
  if (mode === "per90") {
    if (metric.per90_denominator === null) return result;
    const minutes = rows.map(row => row[metric.per90_denominator!]);
    if (!minutes.every(finite)) return result;
    const exposure = minutes.reduce((sum, value) => sum + value, 0);
    const value = exposure > 0 ? total / exposure * 90 : null;
    return { ...result, minutes: finite(exposure) ? exposure : null, value: finite(value) && finite(exposure) ? value : null };
  }
  return { ...result, value: mode === "per_match" ? total / rows.length : total };
}

export function selectSdpEntities(rows: readonly SdpMatch[], scope: SdpScope, filters: SdpFilters): SdpEntity[] {
  const grouped = new Map<string, SdpMatch[]>();
  for (const row of rows) {
    if (row.season !== filters.season || row.gw < filters.from || row.gw > filters.to ||
        (filters.team !== "all" && String(row.team_code) !== filters.team) ||
        (filters.venue !== "all" && row.was_home !== (filters.venue === "home")) ||
        (scope === "player" && filters.position !== "all" && row.position !== filters.position)) continue;
    const id = entityId(row, scope);
    grouped.set(id, [...grouped.get(id) ?? [], row]);
  }
  const entities: SdpEntity[] = [];
  for (const [id, allRows] of grouped) {
    const ordered = allRows.sort((a, b) => Date.parse(a.kickoff_time) - Date.parse(b.kickoff_time) || a.fixture - b.fixture);
    const selected = filters.recent === "all" ? ordered : ordered.slice(-Number(filters.recent));
    const latest = selected.at(-1)!;
    const name = scope === "team" ? latest.team_name : latest.web_name ?? `SDP player ${latest.provider_player_id}`;
    const clubs = [...new Set(selected.map(row => row.team_short_name))].join(" / ");
    if (!`${name} ${clubs}`.toLocaleLowerCase().includes(filters.search.trim().toLocaleLowerCase())) continue;
    if (scope === "player" && filters.minMinutes > 0) {
      const minutes = selected.map(row => row.minutes_fpl);
      if (!minutes.every(finite) || minutes.reduce((sum, value) => sum + value, 0) < filters.minMinutes) continue;
    }
    entities.push({ id, name, clubs, position: [...new Set(selected.map(r => r.position).filter(Boolean))].join(" / ") || "—", code: latest.code ?? null, teamCode: latest.team_code, rows: selected });
  }
  return entities.sort((a, b) => a.name.localeCompare(b.name) || a.id.localeCompare(b.id));
}

export function sortSdpEntities(rows: readonly SdpEntity[], metric: SdpMetric | null, mode: SdpMode, ascending: boolean): SdpEntity[] {
  return [...rows].sort((a, b) => {
    if (metric === null) return (ascending ? 1 : -1) * a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
    const x = metricValue(a.rows, metric, mode).value, y = metricValue(b.rows, metric, mode).value;
    if (x === null || y === null) return x === y ? a.id.localeCompare(b.id) : x === null ? 1 : -1;
    return (ascending ? x - y : y - x) || a.id.localeCompare(b.id);
  });
}

const csvCell = (value: unknown) => {
  let text = value == null ? "" : String(value);
  if (typeof value === "string" && /^[=+\-@\t\r]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
};
export function sdpCsv(rows: readonly SdpEntity[], metrics: readonly SdpMetric[], mode: SdpMode): string {
  const label = (m: SdpMetric) => `${m.source.toUpperCase()} ${m.label}${m.aggregation === "mean" ? " [per-match mean]" : ""}${m.verified_semantics ? "" : ` [provider observation; not independently reconciled; ${m.provider_field ?? m.key}]`}`;
  const header = ["Name", "Stable identity", "Clubs in selected scope", "Season", "First kickoff", "Last kickoff", "Match rows", "Display mode", ...metrics.flatMap(m => [label(m), `${label(m)} displayed matches`, `${label(m)} display provenance`])];
  const records = rows.map(row => [row.name, row.id, row.clubs, row.rows[0]?.season, row.rows[0]?.kickoff_time, row.rows.at(-1)?.kickoff_time, row.rows.length, mode, ...metrics.flatMap(m => { const value = metricValue(row.rows, m, mode); const corrections = metricCorrections(row.rows, m); const assumptions = metricAssumptions(row.rows, m); return [value.value, `${value.measured}/${value.matches}${assumptions.length ? ` (${assumptions.length} assumed zero)` : ""}`, [...corrections.map(correctionDescription), ...assumptions.map(assumptionDescription)].join(" | ")]; })]);
  return [header, ...records].map(row => row.map(csvCell).join(",")).join("\r\n") + "\r\n";
}
