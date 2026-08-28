import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { loadPlanServerToken } from "@/lib/planServerToken";
import {
  fetchInsightStatus,
  fetchInsightSummary,
  type InsightDisplayScope,
  type InsightPage,
  type InsightSummaryRequest,
  type InsightSummaryResponse,
} from "@/lib/planServer";
import type { InsightProvenance } from "@/lib/insights";

export interface DeterministicInsightItem {
  id: string;
  statement: string;
}

export interface RemoteInsightConfig {
  page: InsightPage;
  provenance: InsightProvenance | null;
  scope: InsightDisplayScope;
  /** Full UI scope for stale-response invalidation; never transported to the server. */
  localScopeKey?: string;
  unavailableReason?: string;
}

interface InsightSummaryPanelProps {
  items?: readonly DeterministicInsightItem[];
  caveats?: readonly string[];
  remote?: RemoteInsightConfig;
  localOnlyReason?: string;
  className?: string;
}

function hostedStatic(): boolean {
  return import.meta.env.VITE_HOSTED_STATIC === "true";
}

function requestFor(remote: RemoteInsightConfig): InsightSummaryRequest | null {
  const provenance = remote.provenance;
  if (provenance == null) return null;
  return {
    schema: "fpl.insight-summary-request",
    schema_version: 4,
    page: remote.page,
    manifest_sha256: provenance.manifestSha256,
    run_id: provenance.runId,
    season: provenance.season,
    as_of: provenance.asOf,
    scope: remote.scope,
  };
}

export function InsightSummaryPanel({
  items,
  caveats,
  remote,
  localOnlyReason,
  className,
}: InsightSummaryPanelProps) {
  const displayItems = items ?? [];
  const displayCaveats = caveats ?? [];
  const request = remote ? requestFor(remote) : null;
  const requestFingerprint = JSON.stringify({
    request: request ?? { page: remote?.page ?? null, items: displayItems },
    localScopeKey: remote?.localScopeKey ?? null,
  });
  const generation = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InsightSummaryResponse | null>(null);

  useEffect(() => {
    generation.current += 1;
    setBusy(false);
    setError(null);
    setResult(null);
  }, [requestFingerprint]);

  const isHosted = hostedStatic();
  const disabledReason = remote == null
    ? localOnlyReason ?? "AI explanation is not available for this deterministic page."
    : isHosted
      ? "AI explanation is disabled in the hosted static dashboard."
      : remote.unavailableReason
        ? remote.unavailableReason
        : request == null
          ? "AI explanation requires a published manifest hash for this exact vintage."
          : null;

  const explain = async () => {
    if (request == null || disabledReason != null || busy) return;
    const requestGeneration = ++generation.current;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const token = loadPlanServerToken();
      const status = await fetchInsightStatus(token);
      if (requestGeneration !== generation.current) return;
      if (!status.enabled) {
        throw new Error("AI explanation is not configured on the local server.");
      }
      const response = await fetchInsightSummary(request, token);
      if (requestGeneration !== generation.current) return;
      setResult(response);
    } catch (caught: unknown) {
      if (requestGeneration !== generation.current) return;
      setError(caught instanceof Error ? caught.message : "AI explanation failed.");
    } finally {
      if (requestGeneration === generation.current) setBusy(false);
    }
  };

  return (
    <section
      className={`min-w-0 rounded-lg border bg-card p-4 ${className ?? ""}`}
      aria-labelledby="insight-summary-heading"
      data-testid="insight-summary-panel"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="insight-summary-heading" className="text-sm font-semibold">
            Insight summary
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Facts from the selected filters.
          </p>
        </div>
        {remote && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={disabledReason != null || busy}
            onClick={() => void explain()}
          >
            {busy ? "Explaining…" : "Explain with AI"}
          </Button>
        )}
      </div>

      {displayItems.length ? (
        <ul className="mt-3 grid min-w-0 gap-2 text-sm md:grid-cols-2">
          {displayItems.map((item) => (
            <li key={item.id} className="min-w-0 [overflow-wrap:anywhere]">
              {item.statement}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-3 text-sm text-muted-foreground">
          No published evidence is available in this scope; missing values are not zero.
        </p>
      )}
      {displayCaveats.length > 0 && (
        <div className="mt-3 space-y-1 border-t pt-3 text-xs text-muted-foreground">
          {displayCaveats.map((caveat) => <p key={caveat}>{caveat}</p>)}
        </div>
      )}

      {disabledReason && <p className="mt-3 text-xs text-muted-foreground">{disabledReason}</p>}
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error}</p>}
      {result && (
        <div
          className="mt-4 min-w-0 border-t pt-3 [overflow-wrap:anywhere]"
          aria-label="AI-selected explanation"
        >
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            AI-selected - verify cited metrics
          </p>
          <p className="mt-1 min-w-0 text-sm font-semibold [overflow-wrap:anywhere]">
            {result.headline}
          </p>
          <ul className="mt-2 space-y-2 text-sm">
            {result.items.map((item, index) => (
              <li
                key={`${index}-${item.citations.join(".")}`}
                className="min-w-0 [overflow-wrap:anywhere]"
              >
                <span>{item.text}</span>{" "}
                <span className="text-xs text-muted-foreground [overflow-wrap:anywhere]">
                  [{item.citations.join(", ")}]
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-2 min-w-0 text-[11px] text-muted-foreground [overflow-wrap:anywhere]">
            {result.provider} · {result.model} · {result.source}
          </p>
        </div>
      )}
    </section>
  );
}
