// Vintage (run) selection. A read-model export carries EVERY recorded forecast
// vintage -- two architectures per recorded pack plus any older dev vintages -- so
// teams and players repeat once per run_id. These helpers pick and label ONE run for
// the exploratory pages, defaulting to the default architecture referenced by the
// default optimizer plan.

import {
  isDefaultArchitecture,
  resolvedPlanKind,
  type ComponentModes,
} from "@/lib/nextGw";
import type { PlanKind } from "@/data/types";

/** Minimal run shape both the manifest runs and page-derived runs satisfy. */
export interface RunLike {
  run_id: string;
  gw_from: number;
  gw_to: number;
}

export interface VintageOption {
  runId: string;
  /** Short human label, e.g. "Default · 881cbd54". */
  label: string;
  isDefault: boolean;
}

interface PlanLike {
  forecast_run_id: string;
  component_modes: ComponentModes | null;
  plan_kind?: PlanKind;
}

export function vintageOptions(runs: RunLike[], plans: PlanLike[]): VintageOption[] {
  const modesByRun = new Map(plans.map((p) => [p.forecast_run_id, p.component_modes]));
  return runs.map((run) => {
    const modes = modesByRun.get(run.run_id) ?? null;
    const isDefault = modes != null && isDefaultArchitecture(modes);
    const tag =
      modes == null ? "Vintage" : isDefault ? "Default" : "Diagnostic (V1/V1)";
    return {
      runId: run.run_id,
      label: `${tag} · ${run.run_id.slice(0, 8)} · GW${run.gw_from}-${run.gw_to}`,
      isDefault,
    };
  });
}

/**
 * The run the pages open on: the default-architecture run an optimizer plan references,
 * else the caller's fallback (e.g. summary.json's latest_run), else the first run.
 */
export function defaultVintageRunId(
  runs: RunLike[],
  plans: PlanLike[],
  fallback: string | null = null,
): string | null {
  const withPlan = plans.find((p) => resolvedPlanKind(p) === "platform_default");
  if (withPlan && runs.some((r) => r.run_id === withPlan.forecast_run_id)) {
    return withPlan.forecast_run_id;
  }
  if (fallback && runs.some((r) => r.run_id === fallback)) return fallback;
  return runs[0]?.run_id ?? null;
}
