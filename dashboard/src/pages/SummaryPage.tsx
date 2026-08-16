// Summary landing page: the latest recorded vintage in one glance -- run provenance, roster
// coverage, the next gameweek's first kickoff (deadlines are not sourced, never fabricated),
// headline EV and availability risk, fixture-ease extremes, and the optimizer plans present.
// It reads only summary.json; every number links back to a page that exposes its primitives.

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { loadSummary } from "@/data/load";
import type { SummaryData, SummaryFixture, SummaryPlayer } from "@/data/types";
import { isDefaultArchitecture } from "@/lib/nextGw";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; summary: SummaryData };

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

function PlayerList({ rows }: { rows: SummaryPlayer[] }) {
  if (!rows.length) return <p className="text-xs text-muted-foreground">none</p>;
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((row) => (
        <li key={row.code} className="flex items-baseline justify-between gap-2">
          <span className="truncate">
            <span className="font-medium">{row.web_name ?? `code ${row.code}`}</span>
            <span className="ml-1 text-xs text-muted-foreground">
              {row.position ?? "–"} · {row.team_short_name ?? "–"}
            </span>
          </span>
          <span className="tabular-nums">{fmt(row.expected_points)}</span>
        </li>
      ))}
    </ul>
  );
}

function EaseList({ rows }: { rows: SummaryFixture[] }) {
  if (!rows.length) return <p className="text-xs text-muted-foreground">none</p>;
  return (
    <ul className="space-y-1 text-sm">
      {rows.map((row, index) => (
        <li key={index} className="flex items-baseline justify-between gap-2">
          <span className="truncate">
            {row.team_short_name ?? "–"}{" "}
            <span className="text-xs text-muted-foreground">
              vs {row.opponent_short_name ?? "–"} {row.was_home == null ? "" : row.was_home ? "(H)" : "(A)"}
            </span>
          </span>
          <span className="tabular-nums text-xs">
            ease {fmt(row.overall_ease_index, 0)} · FDR {fmt(row.official_fdr, 0)}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function SummaryPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadSummary()
      .then((summary) => {
        if (!cancelled) setState({ status: "ready", summary });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Summary</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }

  const { summary } = state;
  const run = summary.latest_run;
  if (!run) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Summary</h1>
        <p className="text-sm text-muted-foreground">
          No recorded forecast runs in this export. Generate a vintage first (see
          dashboard/README.md).
        </p>
      </div>
    );
  }

  const modes = run.component_modes ?? {};

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Summary</h1>
        <p className="text-xs text-muted-foreground">
          run {run.run_id.slice(0, 12)}… · as of {run.as_of?.replace("T", " ").slice(0, 16)} UTC ·
          status {run.status ?? "–"}
        </p>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-md border p-3">
          <p className="text-xs font-medium text-muted-foreground">Latest vintage</p>
          <p className="mt-1 text-sm">
            {run.season} · GW{run.gw_from}-{run.gw_to}
          </p>
          <div className="mt-1 flex flex-wrap gap-1">
            {Object.entries(modes).map(([key, value]) => (
              <Badge key={key} variant="outline" className="text-[10px]">
                {key}={value ?? "?"}
              </Badge>
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            Roster: {summary.roster.players} players · {summary.roster.teams} clubs
          </p>
        </div>
        <div className="rounded-md border p-3">
          <p className="text-xs font-medium text-muted-foreground">Next gameweek</p>
          {summary.next_gameweek ? (
            <>
              <p className="mt-1 text-sm">GW{summary.next_gameweek.gw}</p>
              <p className="text-xs text-muted-foreground">
                first kickoff{" "}
                {summary.next_gameweek.first_kickoff
                  ?.replace("T", " ")
                  .slice(0, 16)} UTC
              </p>
              <p className="text-xs text-muted-foreground">
                {summary.next_gameweek.fixture_count ?? "–"} fixtures · deadlines are not
                sourced, so none is shown
              </p>
            </>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">no scheduled fixtures</p>
          )}
        </div>
        <div className="rounded-md border p-3">
          <p className="text-xs font-medium text-muted-foreground">Optimizer plans</p>
          {summary.optimizer_plans.length ? (
            <ul className="mt-1 space-y-1 text-xs">
              {summary.optimizer_plans.map((plan) => (
                <li key={plan.optimizer_run_id} className="truncate">
                  <span className="font-medium">{plan.optimizer_run_id.slice(0, 10)}…</span>{" "}
                  {isDefaultArchitecture(plan.component_modes) ? "(default)" : "(diagnostic)"} ·
                  decision {plan.decision_sha256.slice(0, 8)}…
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-xs text-muted-foreground">
              none in this export -- rebuild it with --optimizer-plan inputs
            </p>
          )}
          <p className="mt-2 text-[10px] text-muted-foreground">
            Development-only optimizer output; see the Next GW suggestion page.
          </p>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <div className="rounded-md border p-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Top GW{run.gw_from} xP
          </p>
          <PlayerList rows={summary.top_xp} />
        </div>
        <div className="rounded-md border p-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Top GW{run.gw_from}-{run.gw_to} xP
          </p>
          <PlayerList rows={summary.horizon_top_xp} />
        </div>
        <div className="rounded-md border p-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Availability flags (reported overlay)
          </p>
          <PlayerList rows={summary.flagged_top_xp} />
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div className="rounded-md border p-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">
            Easiest GW{run.gw_from} fixtures (ease: 100 = league average, higher = easier)
          </p>
          <EaseList rows={summary.easiest_fixtures} />
        </div>
        <div className="rounded-md border p-3">
          <p className="mb-1 text-xs font-medium text-muted-foreground">Hardest GW{run.gw_from} fixtures</p>
          <EaseList rows={summary.hardest_fixtures} />
        </div>
      </div>

      <Separator className="my-1" />
      <p className="text-xs text-muted-foreground">
        Headline numbers only -- the Fixture matrix and Players pages expose the raw lambdas,
        ease indices, and per-fixture xP behind every figure. Availability is a reported
        overlay valid for the next gameweek, never folded into xP.
      </p>
    </div>
  );
}
