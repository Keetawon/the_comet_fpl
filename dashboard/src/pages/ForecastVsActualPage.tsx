// Forecast versus actual: each recorded vintage scored against its own season's finalised
// outcomes at player-gameweek grain, under the points-under-2026/27-rules measure. With no
// finalised outcomes inside any vintage's horizon (the 2026-27 GW1 state) the page shows the
// framework and says why -- never zero-filled numbers.

import { useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { loadForecastVsActual } from "@/data/load";
import type { ForecastVsActualData, ScoreBlock } from "@/data/types";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: ForecastVsActualData };

const fmt = (value: number | null | undefined, digits = 2) =>
  value == null ? "–" : value.toFixed(digits);

const signed = (value: number | null | undefined, digits = 2) =>
  value == null ? "–" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;

function ScoreCells({ block }: { block: ScoreBlock }) {
  return (
    <>
      <TableCell className="tabular-nums">{block.rows}</TableCell>
      <TableCell className="tabular-nums">{fmt(block.mean_ev)}</TableCell>
      <TableCell className="tabular-nums">{fmt(block.mean_actual)}</TableCell>
      <TableCell className="tabular-nums">{signed(block.bias)}</TableCell>
      <TableCell className="tabular-nums">{fmt(block.mae)}</TableCell>
      <TableCell className="tabular-nums">{fmt(block.crps, 3)}</TableCell>
    </>
  );
}

const SCORE_HEADERS = (
  <>
    <TableHead>Rows</TableHead>
    <TableHead>Mean EV</TableHead>
    <TableHead>Mean actual</TableHead>
    <TableHead>Bias (actual − EV)</TableHead>
    <TableHead>MAE</TableHead>
    <TableHead>CRPS</TableHead>
  </>
);

export function ForecastVsActualPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadForecastVsActual()
      .then((data) => {
        if (!cancelled) setState({ status: "ready", data });
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

  if (state.status === "loading") return <p className="p-6 text-muted-foreground">Loading read models…</p>;
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Forecast vs actual</h1>
        <p className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }

  const { data } = state;

  return (
    <div className="flex flex-col gap-4 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Forecast vs actual</h1>
        <p className="text-xs text-muted-foreground">
          measure: points under 2026/27 rules · join at (season, gw, code), read-time only
        </p>
      </div>

      {!data.has_outcomes ? (
        <div className="rounded-md border p-4">
          <p className="font-medium">No finalised outcomes inside any recorded vintage yet.</p>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            The recorded vintages forecast 2026-27, whose matches have not played, and no
            historical vintage is recorded -- so there is nothing to score. This page fills in
            as gameweeks finalise and outcomes are attached; unfinalised player-fixture rows
            are excluded, never read as zero.
          </p>
        </div>
      ) : (
        data.runs.map((run) => (
          <div key={run.run_id} className="space-y-3">
            <p className="text-sm">
              <span className="font-medium">run {run.run_id.slice(0, 12)}…</span>{" "}
              <span className="text-muted-foreground">
                {run.season} GW{run.gw_from}-{run.gw_to} · {run.rows} scored player-gameweeks
              </span>
            </p>
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Position</TableHead>
                      {SCORE_HEADERS}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {run.by_position.map((block) => (
                      <TableRow key={block.position}>
                        <TableCell>{block.position}</TableCell>
                        <ScoreCells block={block} />
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
              <div className="overflow-x-auto rounded-md border">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Gameweek</TableHead>
                      {SCORE_HEADERS}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {run.by_gw.map((block) => (
                      <TableRow key={block.gw}>
                        <TableCell>GW{block.gw}</TableCell>
                        <ScoreCells block={block} />
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
            <div className="overflow-x-auto rounded-md border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>P(≥ {run.calibration[0]?.threshold_points ?? 2} pts) bucket</TableHead>
                    <TableHead>Rows</TableHead>
                    <TableHead>Predicted mean</TableHead>
                    <TableHead>Observed rate</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {run.calibration.map((bucket) => (
                    <TableRow key={bucket.bucket}>
                      <TableCell>{bucket.bucket}</TableCell>
                      <TableCell className="tabular-nums">{bucket.rows}</TableCell>
                      <TableCell className="tabular-nums">
                        {fmt(bucket.predicted_mean, 3)}
                      </TableCell>
                      <TableCell className="tabular-nums">
                        {fmt(bucket.observed_rate, 3)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        ))
      )}

      <p className="text-xs text-muted-foreground">
        Bias is actual minus EV (positive = the model under-predicted). CRPS uses the stored
        full-points distribution; calibration buckets predicted P(≥ 2 points) against the
        observed rate. Cross-vintage EV differences measure calibration, not squad quality --
        compare a run only against its own outcomes.
      </p>
    </div>
  );
}
