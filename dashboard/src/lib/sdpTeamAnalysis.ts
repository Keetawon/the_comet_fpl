import type { SdpMetric } from "@/data/sdpStats";
import { finite, metricValue } from "./sdpStats";
import type { SdpEntity, SdpMode } from "./sdpStats";

// Descriptive presentation only. No forecast or model inputs are consumed here.
export function teamBenchmark(league: readonly SdpEntity[], metric: SdpMetric, mode: SdpMode, value: number | null) {
  const values = league.map(team => metricValue(team.rows, metric, mode).value).filter(finite).sort((a, b) => a - b);
  const n = values.length;
  const median = n ? (values[Math.floor((n - 1) / 2)] + values[Math.floor(n / 2)]) / 2 : null;
  // Midrank handles ties without declaring every tied club the leader. No quality score.
  const percentile = n < 2 || value === null ? null
    : (values.filter(v => v < value).length + values.filter(v => v === value).length / 2) / n * 100;
  return { median, percentile, count: n };
}

export const teamMetricGroups = [
  { id: "overview", label: "Overview", description: "The match picture, at a glance.", keys: ["goals", "expected_goals", "shots", "shots_on_target", "possession", "expected_goals_allowed"] },
  { id: "attack", label: "Attacking", description: "Shot volume, chance quality and activity around the box.", keys: ["goals", "expected_goals", "expected_goals_on_target", "shots", "shots_on_target", "shots_inside_box", "shots_outside_box", "shots_blocked", "big_chances_created", "big_chances_scored", "big_chances_missed", "touches_in_opposition_box"] },
  { id: "build-up", label: "Build-up", description: "Possession, passing direction and progression. These describe style, not a tactical label.", keys: ["possession", "passes", "accurate_passes", "forward_passes", "backward_passes", "long_passes", "accurate_long_passes", "final_third_entries", "penalty_area_entries", "crosses", "accurate_crosses"] },
  { id: "defence", label: "Defending", description: "Chances conceded and defensive workload. More actions do not automatically mean better defending.", keys: ["expected_goals_allowed", "shots_allowed", "shots_on_target_allowed", "tackles", "tackles_won", "interceptions", "clearances", "blocks", "recoveries", "saves", "possession_won_attacking_third", "possession_won_middle_third", "possession_won_defensive_third"] },
  { id: "duels", label: "Duels & discipline", description: "Ground and aerial contests, fouls, cards and corners.", keys: ["duels_won", "duels_lost", "aerial_duels_won", "aerial_duels_lost", "fouls", "yellow_cards", "red_cards", "offsides", "corners"] },
  { id: "all", label: "All metrics", description: "Every exported team metric, with its source and coverage.", keys: [] },
] as const;

export const sdpNumber = (value: number | null | undefined, digits = 2) => value == null ? "—"
  : new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value);

export function teamMetricLabel(metric: SdpMetric, mode: SdpMode) {
  return `${metric.source === "fpl" ? "FPL · " : ""}${metric.label}${metric.aggregation === "mean" ? metric.unit === "percent" ? " %" : " · mean" : mode === "per_match" ? " /match" : ""}`;
}
