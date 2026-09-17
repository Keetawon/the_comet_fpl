import { useEffect, useState } from "react";
import { resolveDataUrl } from "@/data/publicData";

interface Status {
  schema: string;
  data_manifest_sha256: string;
  exported_at: string;
  source_known_at: string | null;
  latest_finalized_gw: number | null;
  awaiting_finality: { gw: number; fixtures_completed: number; fixtures_total: number }[];
  latest_forecast: { as_of: string; gw_from: number; gw_to: number } | null;
  current_platform_plan: boolean;
  forecast_rollover_required?: boolean;
  next_fixture_gw?: number | null;
}

/** Status only. No provisional observation is passed into accuracy scoring. */
export function PublicationStatus({ manifestHash }: { manifestHash: string }) {
  const [status, setStatus] = useState<Status | null>(null);
  useEffect(() => {
    let cancelled = false;
    resolveDataUrl("sdp/publication_status.json").then((url) => fetch(url))
      .then(async (response) => {
        if (!response.ok) return;
        const value: Status = await response.json();
        if (!cancelled && value.schema === "fpl.dashboard-publication-status/v1" &&
            value.data_manifest_sha256 === manifestHash && Array.isArray(value.awaiting_finality)) setStatus(value);
      }).catch(() => { /* Optional older packages remain readable. */ });
    return () => { cancelled = true; };
  }, [manifestHash]);
  if (!status || status.data_manifest_sha256 !== manifestHash) return null;
  return <aside aria-label="Dashboard publication status" className="rounded-lg border bg-muted/30 p-3 text-sm">
    <div className="flex flex-wrap gap-x-6 gap-y-2">
      <span><strong>Officially finalized:</strong> {status.latest_finalized_gw == null ? "Unavailable" : `through GW${status.latest_finalized_gw}`}</span>
      <span><strong>Latest forecast:</strong> {status.latest_forecast ? `GW${status.latest_forecast.gw_from}–${status.latest_forecast.gw_to}` : "Unavailable"}</span>
    </div>
    {status.awaiting_finality.map((gw) => <p key={gw.gw} className="mt-2 text-amber-800 dark:text-amber-300">
      <strong>GW{gw.gw}: {gw.fixtures_completed}/{gw.fixtures_total} matches ended.</strong> Awaiting official finality; prediction scores remain pending, including all double-gameweek legs.
    </p>)}
    {status.forecast_rollover_required && <p className="mt-2 text-amber-800 dark:text-amber-300">Next match scope is GW{status.next_fixture_gw}. A new pre-deadline forecast is required; this export has kept the original forecast vintage.</p>}
    {!status.current_platform_plan && <p className="mt-2 text-amber-800 dark:text-amber-300">Platform plan update required. Older plans retain their original forecast dates.</p>}
    <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">Refresh and forecast dates</summary>
      <p>FPL source: {status.source_known_at ?? "Unavailable"}</p><p>Dashboard exported: {status.exported_at}</p>
      <p>Latest forecast as of: {status.latest_forecast?.as_of ?? "Unavailable"}. Refreshing results does not regenerate forecasts.</p>
    </details>
  </aside>;
}
