import { useEffect, useMemo, useState } from "react";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { loadPlayerForecastVsActual } from "@/data/load";
import type {
  ForecastAccuracyScoreBlock,
  PlayerForecastAccuracyRun,
  PlayerForecastObservation,
  PlayerForecastVsActualData,
} from "@/data/types";
import { compactInsightScope, insightFact, publishedInsightProvenance } from "@/lib/insights";
import { AccuracyScatter, AccuracyScoreKpis } from "./ForecastAccuracyParts";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: PlayerForecastVsActualData };

const fmt = (value: number | null | undefined, digits = 3) =>
  value == null ? "—" : value.toFixed(digits);
const signed = (value: number | null | undefined, digits = 3) =>
  value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
const pct = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

function newestRun(runs: readonly PlayerForecastAccuracyRun[]) {
  return [...runs].sort(
    (left, right) =>
      (right.created_at ?? right.as_of ?? "").localeCompare(left.created_at ?? left.as_of ?? "") ||
      right.run_id.localeCompare(left.run_id),
  )[0];
}

function observationOrder(left: PlayerForecastObservation, right: PlayerForecastObservation) {
  return left.gw - right.gw || left.web_name.localeCompare(right.web_name) || left.code - right.code;
}

interface NamedScore extends ForecastAccuracyScoreBlock {
  label: string;
}

function ScoreSplitTable({ title, rows }: { title: string; rows: readonly NamedScore[] }) {
  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="overflow-x-auto rounded-md border">
        <Table aria-label={title}>
          <TableHeader>
            <TableRow>
              <TableHead>Slice</TableHead>
              <TableHead>Rows / PMF</TableHead>
              <TableHead>Forecast mean</TableHead>
              <TableHead>Actual mean</TableHead>
              <TableHead>Bias</TableHead>
              <TableHead>MAE</TableHead>
              <TableHead>RMSE</TableHead>
              <TableHead>CRPS</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.label}>
                <TableCell>{row.label}</TableCell>
                <TableCell className="tabular-nums">{row.rows} / {row.distribution_rows}</TableCell>
                <TableCell className="tabular-nums">{fmt(row.forecast_mean)}</TableCell>
                <TableCell className="tabular-nums">{fmt(row.actual_mean)}</TableCell>
                <TableCell className="tabular-nums">{signed(row.bias)}</TableCell>
                <TableCell className="tabular-nums">{fmt(row.mae)}</TableCell>
                <TableCell className="tabular-nums">{fmt(row.rmse)}</TableCell>
                <TableCell className="tabular-nums">{fmt(row.crps)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}

export function PlayerForecastVsActualPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState("");
  const [gwFilter, setGwFilter] = useState("all");

  useEffect(() => {
    let cancelled = false;
    loadPlayerForecastVsActual()
      .then((data) => {
        if (cancelled) return;
        setState({ status: "ready", data });
        setRunId(newestRun(data.runs)?.run_id ?? "");
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

  const run =
    state.status === "ready"
      ? state.data.runs.find((candidate) => candidate.run_id === runId) ?? newestRun(state.data.runs)
      : undefined;
  const completedGws = useMemo(
    () => (run ? [...run.by_gw].sort((a, b) => a.gw - b.gw).map(({ gw }) => gw) : []),
    [run],
  );
  const observations = useMemo(
    () =>
      run
        ? run.observations
            .filter((observation) => gwFilter === "all" || observation.gw === Number(gwFilter))
            .sort(observationOrder)
        : [],
    [gwFilter, run],
  );
  const scoreBlock =
    !run || gwFilter === "all"
      ? run?.overall
      : run.by_gw.find(({ gw }) => gw === Number(gwFilter));
  const residualOrder = useMemo(
    () =>
      [...observations].sort(
        (left, right) => right.residual - left.residual || observationOrder(left, right),
      ),
    [observations],
  );

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading player prediction accuracy…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">Player prediction vs actual</h1>
        <p role="alert" className="mt-2 max-w-2xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!run) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold">Player prediction vs actual</h1>
        <p className="mt-3 text-sm text-muted-foreground">No recorded player forecast runs are published yet.</p>
      </div>
    );
  }

  const topUnder = residualOrder[0];
  const topOver = residualOrder.at(-1);
  const coverage = run.coverage;
  const scopeLabel = gwFilter === "all" ? "all scored gameweeks" : `GW${gwFilter}`;
  const positionRows: NamedScore[] = run.by_position.map((row) => ({ ...row, label: row.position }));
  const gwRows: NamedScore[] = run.by_gw.map((row) => ({ ...row, label: `GW${row.gw}` }));
  const teamRows: NamedScore[] = run.by_team.map((row) => ({
    ...row,
    label: `${row.team_name} (${row.team_short_name})`,
  }));
  const insightFacts = [
    insightFact(
      "coverage.visible_rows",
      "coverage",
      `${observations.length} scored player-gameweek row${observations.length === 1 ? " is" : "s are"} visible for ${scopeLabel}.`,
      ["player_forecast_vs_actual.json"],
    ),
    ...(scoreBlock?.bias == null ? [] : [
      insightFact(
        "score.bias",
        "published_scalar",
        `Published bias is ${signed(scoreBlock.bias)} points; positive means actual points exceeded forecast xP.`,
        ["player_forecast_vs_actual.json"],
      ),
    ]),
    ...(topUnder ? [
      insightFact(
        "rank.largest_positive_residual",
        "rank",
        `Largest under-prediction: ${topUnder.web_name} GW${topUnder.gw} (${signed(topUnder.residual)}).`,
        ["player_forecast_vs_actual.json"],
      ),
    ] : []),
    ...(topOver ? [
      insightFact(
        "rank.smallest_residual",
        "rank",
        `${topOver.web_name} in GW${topOver.gw} has the smallest visible residual at ${signed(topOver.residual)} points.`,
        ["player_forecast_vs_actual.json"],
      ),
    ] : []),
  ];
  const insightCaveats = [
    "Only authoritatively finalized observations are scored.",
    "Residual equals actual points minus forecast xP.",
    "Probabilities and CRPS are published values; the browser does not reconstruct them.",
  ];
  const firstCompletedGw = completedGws[0] ?? run.gw_from;
  const lastCompletedGw = completedGws.at(-1) ?? run.gw_to;

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold">Player prediction vs actual</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Diagnose one immutable player forecast against finalized 2026/27-rule replay outcomes.
            Residuals describe this vintage only and never become future buy or avoid signals.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <label className="text-xs text-muted-foreground">
            Forecast vintage
            <select
              aria-label="Player forecast vintage"
              className="ml-2 h-8 rounded-md border bg-background px-2 text-sm text-foreground"
              value={run.run_id}
              onChange={(event) => {
                setRunId(event.target.value);
                setGwFilter("all");
              }}
            >
              {state.data.runs.map((candidate) => (
                <option key={candidate.run_id} value={candidate.run_id}>
                  {candidate.run_id.slice(0, 12)} · {candidate.season} GW{candidate.gw_from}-{candidate.gw_to}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-muted-foreground">
            Finalized scope
            <select
              aria-label="Completed player gameweek"
              className="ml-2 h-8 rounded-md border bg-background px-2 text-sm text-foreground"
              value={gwFilter}
              onChange={(event) => setGwFilter(event.target.value)}
            >
              <option value="all">All scored GWs</option>
              {completedGws.map((gw) => <option key={gw} value={gw}>GW{gw}</option>)}
            </select>
          </label>
        </div>
      </div>

      <section className="rounded-lg border bg-card p-4" aria-labelledby="player-coverage-heading">
        <h2 id="player-coverage-heading" className="text-sm font-semibold">Coverage and finality</h2>
        <p className="mt-1 text-sm">
          {coverage.scored_rows} of {coverage.forecast_rows} forecast player-gameweeks scored; {coverage.pending_rows} pending, {coverage.missing_outcome_rows} missing immutable outcomes, {coverage.legacy_unavailable_rows} legacy-unavailable.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          {coverage.final_eligible_rows} rows belong to authoritatively final gameweeks; {coverage.distribution_scored_rows} have valid stored distributions. A partial double gameweek scores nothing until every leg is final and attached.
        </p>
      </section>

      {!state.data.has_outcomes && (
        <p role="status" className="rounded-md border p-4 text-sm">No finalized player outcomes are available in any published run. Pending and missing rows are never read as zero.</p>
      )}

      {scoreBlock ? <AccuracyScoreKpis block={scoreBlock} /> : (
        <p role="status" className="rounded-md border p-4 text-sm text-muted-foreground">No published score block exists for {scopeLabel}.</p>
      )}

      <AccuracyScatter
        title={`Player expected vs actual · ${scopeLabel}`}
        description="Each point is one published player-gameweek observation. Signed residual is actual points minus forecast xP."
        predictedLabel="Forecast xP"
        actualLabel="Actual replayed points"
        points={observations.map((observation) => ({
          id: `${observation.gw}-${observation.code}`,
          label: `${observation.web_name} · GW${observation.gw}`,
          predicted: observation.forecast_xp,
          actual: observation.actual_points,
          detail: `residual ${signed(observation.residual)}; ${observation.position} · ${observation.team_short_name}`,
        }))}
        emptyMessage="No fully finalized player-gameweek observations exist in this scope."
      />

      <InsightSummaryPanel
        items={insightFacts}
        caveats={insightCaveats}
        remote={{
          page: "player_forecast_vs_actual",
          provenance: publishedInsightProvenance(state.data.manifest, run),
          scope: compactInsightScope({
            gw_from: gwFilter === "all" ? firstCompletedGw : Number(gwFilter),
            gw_to: gwFilter === "all" ? lastCompletedGw : Number(gwFilter),
            view: "overall",
          }),
          localScopeKey: JSON.stringify({ runId: run.run_id, gwFilter }),
        }}
      />

      <section className="space-y-2" aria-labelledby="player-observations-heading">
        <h2 id="player-observations-heading" className="text-sm font-semibold">Exact player observations</h2>
        <div className="overflow-x-auto rounded-md border">
          <Table aria-label="Exact player prediction observations">
            <TableHeader>
              <TableRow>
                <TableHead>GW</TableHead><TableHead>Player</TableHead><TableHead>Position</TableHead><TableHead>Team</TableHead>
                <TableHead>Forecast xP</TableHead><TableHead>Actual</TableHead><TableHead>Residual (actual − forecast)</TableHead><TableHead>Absolute error</TableHead><TableHead>CRPS</TableHead>
                <TableHead>P(total ≤ 2)</TableHead><TableHead>P(total ≥ 2)</TableHead><TableHead>P(total ≥ 6)</TableHead><TableHead>P(total ≥ 10)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {observations.map((observation) => (
                <TableRow key={`${observation.gw}-${observation.code}`}>
                  <TableCell>GW{observation.gw}</TableCell><TableCell className="font-medium">{observation.web_name}</TableCell><TableCell>{observation.position}</TableCell><TableCell>{observation.team_short_name}</TableCell>
                  <TableCell className="tabular-nums">{fmt(observation.forecast_xp, 2)}</TableCell><TableCell className="tabular-nums">{fmt(observation.actual_points, 0)}</TableCell><TableCell className="tabular-nums">{signed(observation.residual)}</TableCell><TableCell className="tabular-nums">{fmt(observation.absolute_error)}</TableCell><TableCell className="tabular-nums">{fmt(observation.crps)}</TableCell>
                  <TableCell className="tabular-nums">{pct(observation.p_le_2)}</TableCell><TableCell className="tabular-nums">{pct(observation.p_ge_2)}</TableCell><TableCell className="tabular-nums">{pct(observation.p_ge_6)}</TableCell><TableCell className="tabular-nums">{pct(observation.p_ge_10)}</TableCell>
                </TableRow>
              ))}
              {!observations.length && <TableRow><TableCell colSpan={13} className="text-muted-foreground">No scored observations in this scope; missing is not zero.</TableCell></TableRow>}
            </TableBody>
          </Table>
        </div>
      </section>

      <section className="space-y-2" aria-labelledby="player-calibration-heading">
        <h2 id="player-calibration-heading" className="text-sm font-semibold">Published threshold reliability · full run</h2>
        <p className="text-xs text-muted-foreground">Inclusive events only. These probabilities and buckets were computed by the static Python emitter; the browser does not reconstruct or recalibrate them.</p>
        <div className="overflow-x-auto rounded-md border">
          <Table aria-label="Player threshold calibration">
            <TableHeader><TableRow><TableHead>Event</TableHead><TableHead>Bucket</TableHead><TableHead>Rows</TableHead><TableHead>Predicted mean</TableHead><TableHead>Observed rate</TableHead></TableRow></TableHeader>
            <TableBody>{run.calibration.map((row, index) => (
              <TableRow key={`${row.event}-${row.threshold}-${row.bucket}-${index}`}>
                <TableCell>{row.event === "points_le" ? `P(total ≤ ${row.threshold})` : `P(total ≥ ${row.threshold})`}</TableCell><TableCell>{row.bucket}</TableCell><TableCell>{row.rows}</TableCell><TableCell>{pct(row.predicted_mean)}</TableCell><TableCell>{pct(row.observed_rate)}</TableCell>
              </TableRow>
            ))}</TableBody>
          </Table>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        <ScoreSplitTable title="Scores by position" rows={positionRows} />
        <ScoreSplitTable title="Scores by finalized gameweek" rows={gwRows} />
        <ScoreSplitTable title="Scores by forecast-time team" rows={teamRows} />
      </div>

      <p className="text-xs text-muted-foreground">
        Run {run.run_id} · as of {run.as_of ?? "unknown"} · created {run.created_at ?? "unknown"}. Cross-vintage differences diagnose calibration only; compare every vintage against its own attached outcomes.
      </p>
    </div>
  );
}
