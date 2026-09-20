import { PublicationStatus } from "@/components/PublicationStatus";
import { AccuracyObservationTable, AccuracyDelta } from "@/components/AccuracyObservationTable";
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
import { loadTeamForecastVsActual } from "@/data/load";
import type {
  CleanSheetScoreBlock,
  ForecastAccuracyScoreBlock,
  TeamAccuracyScoreSet,
  TeamForecastObservation,
  TeamForecastVsActualData,
} from "@/data/types";
import {
  accuracyComponentLabel,
  accuracyRunLabel,
  accuracyRunRole,
  accuracyRunRoleLabel,
  defaultAccuracyRun,
  orderedAccuracyRuns,
} from "@/lib/forecastAccuracyRuns";
import { compactInsightScope, insightFact, publishedInsightProvenance } from "@/lib/insights";
import { AccuracyKpis, AccuracyScatter, AccuracyScoreKpis, type AccuracyKpi } from "./ForecastAccuracyParts";

type TeamAccuracyView = "attack" | "defence" | "clean_sheet";
type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: TeamForecastVsActualData };

const fmt = (value: number | null | undefined, digits = 3) =>
  value == null ? "—" : value.toFixed(digits);
const signed = (value: number | null | undefined, digits = 3) =>
  value == null ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}`;
const pct = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

function observationOrder(left: TeamForecastObservation, right: TeamForecastObservation) {
  return left.gw - right.gw || left.fixture - right.fixture || left.team_id - right.team_id;
}

interface TeamSlice extends TeamAccuracyScoreSet {
  label: string;
}

function SliceTable({ title, rows, view }: { title: string; rows: readonly TeamSlice[]; view: TeamAccuracyView }) {
  return (
    <section className="space-y-2" aria-label={title}>
      <h3 className="text-sm font-semibold">{title}</h3>
      <div className="overflow-x-auto rounded-md border">
        <Table aria-label={`${title} · ${view}`}>
          <TableHeader><TableRow>
            <TableHead>Slice</TableHead><TableHead>Rows</TableHead>
            {view === "clean_sheet" ? <><TableHead>Predicted mean</TableHead><TableHead>Observed rate</TableHead><TableHead>Brier</TableHead></> : <><TableHead>Forecast mean</TableHead><TableHead>Actual mean</TableHead><TableHead>Bias</TableHead><TableHead>MAE</TableHead><TableHead>RMSE</TableHead><TableHead>CRPS</TableHead></>}
          </TableRow></TableHeader>
          <TableBody>{rows.map((row) => {
            if (view === "clean_sheet") {
              const score = row.clean_sheet;
              return <TableRow key={row.label}>
                <TableCell>{row.label}</TableCell><TableCell>{score.rows}</TableCell>
                <TableCell>{pct(score.predicted_mean)}</TableCell><TableCell>{pct(score.observed_rate)}</TableCell><TableCell>{fmt(score.brier)}</TableCell>
              </TableRow>;
            }
            const score = row[view];
            return <TableRow key={row.label}>
              <TableCell>{row.label}</TableCell><TableCell>{score.rows}</TableCell>
              <TableCell>{fmt(score.forecast_mean)}</TableCell><TableCell>{fmt(score.actual_mean)}</TableCell><TableCell>{signed(score.bias)}</TableCell><TableCell>{fmt(score.mae)}</TableCell><TableCell>{fmt(score.rmse)}</TableCell><TableCell>{fmt(score.crps)}</TableCell>
            </TableRow>;
          })}</TableBody>
        </Table>
      </div>
    </section>
  );
}

interface ClubAggregate {
  teamId: number;
  teamName: string;
  shortName: string;
  rows: number;
  attackForecast: number;
  attackActual: number;
  attackResidual: number;
  defenceForecast: number;
  defenceActual: number;
  defenceResidual: number;
  expectedCleanSheets: number;
  actualCleanSheets: number;
}

function clubAggregates(observations: readonly TeamForecastObservation[]): ClubAggregate[] {
  const grouped = new Map<number, ClubAggregate>();
  for (const observation of observations) {
    const row = grouped.get(observation.team_id) ?? {
      teamId: observation.team_id,
      teamName: observation.team_name,
      shortName: observation.team_short_name,
      rows: 0,
      attackForecast: 0,
      attackActual: 0,
      attackResidual: 0,
      defenceForecast: 0,
      defenceActual: 0,
      defenceResidual: 0,
      expectedCleanSheets: 0,
      actualCleanSheets: 0,
    };
    row.rows += 1;
    row.attackForecast += observation.lambda_for;
    row.attackActual += observation.actual_goals_for;
    row.attackResidual += observation.attack_residual;
    row.defenceForecast += observation.lambda_against;
    row.defenceActual += observation.actual_goals_against;
    row.defenceResidual += observation.defence_residual;
    row.expectedCleanSheets += observation.probability_clean_sheet;
    row.actualCleanSheets += observation.actual_clean_sheet ? 1 : 0;
    grouped.set(observation.team_id, row);
  }
  return [...grouped.values()].sort((left, right) => left.teamName.localeCompare(right.teamName));
}

function cleanSheetKpis(score: CleanSheetScoreBlock): AccuracyKpi[] {
  return [
    { label: "Scored rows", value: score.rows },
    { label: "Predicted mean", value: pct(score.predicted_mean), note: "Mean published P(clean sheet)" },
    { label: "Observed rate", value: pct(score.observed_rate) },
    { label: "Brier score", value: fmt(score.brier), note: "Published by the static emitter" },
  ];
}

export function TeamForecastVsActualPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState("");
  const [gwFilter, setGwFilter] = useState("all");
  const [view, setView] = useState<TeamAccuracyView>("attack");

  useEffect(() => {
    let cancelled = false;
    loadTeamForecastVsActual()
      .then((data) => {
        if (cancelled) return;
        setState({ status: "ready", data });
        setRunId(defaultAccuracyRun(data.runs)?.run_id ?? "");
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => { cancelled = true; };
  }, []);

  const runOptions = useMemo(
    () => state.status === "ready" ? orderedAccuracyRuns(state.data.runs) : [],
    [state],
  );
  const run = state.status === "ready"
    ? runOptions.find((candidate) => candidate.run_id === runId) ?? defaultAccuracyRun(runOptions)
    : undefined;
  const completedGws = useMemo(
    () => (run ? [...run.by_gw].sort((a, b) => a.gw - b.gw).map(({ gw }) => gw) : []),
    [run],
  );
  const observations = useMemo(
    () => run ? run.observations.filter((row) => gwFilter === "all" || row.gw === Number(gwFilter)).sort(observationOrder) : [],
    [gwFilter, run],
  );
  const scopeScores: TeamAccuracyScoreSet | undefined = !run
    ? undefined
    : gwFilter === "all"
      ? run
      : run.by_gw.find(({ gw }) => gw === Number(gwFilter));
  const clubs = useMemo(() => clubAggregates(observations), [observations]);

  if (state.status === "loading") return <p role="status" className="p-6 text-muted-foreground">Loading team prediction accuracy…</p>;
  if (state.status === "error") return <div className="p-6"><h1 className="text-lg font-semibold">Team prediction vs actual</h1><p role="alert" className="mt-2 max-w-2xl text-sm text-destructive">{state.message}</p></div>;
  if (!run) return <div className="p-6"><h1 className="text-lg font-semibold">Team prediction vs actual</h1><p className="mt-3 text-sm text-muted-foreground">No recorded team forecast runs are published yet.</p></div>;

  const coverage = run.coverage;
  const scopeLabel = gwFilter === "all" ? "all scored fixtures" : `GW${gwFilter}`;
  const selectedScore = scopeScores?.[view];
  const insightValue = (row: TeamForecastObservation) => view === "attack"
    ? row.attack_residual
    : view === "defence"
      ? row.defence_residual
      : row.clean_sheet_brier;
  const ranked = [...observations].sort((left, right) => insightValue(right) - insightValue(left) || observationOrder(left, right));
  const highInsight = ranked[0];
  const lowInsight = ranked.at(-1);
  const plotPoints = observations.map((row) => ({
    id: `${row.fixture}-${row.team_id}`,
    label: `${row.team_name} vs ${row.opponent_team_short_name} · GW${row.gw}`,
    predicted: view === "attack" ? row.lambda_for : view === "defence" ? row.lambda_against : row.probability_clean_sheet,
    actual: view === "attack" ? row.actual_goals_for : view === "defence" ? row.actual_goals_against : Number(row.actual_clean_sheet),
    detail: view === "attack"
      ? `attack residual ${signed(row.attack_residual)} (actual goals − λ for)`
      : view === "defence"
        ? `defence residual ${signed(row.defence_residual)} (actual conceded − λ against; positive is worse)`
        : `clean sheet ${row.actual_clean_sheet ? "yes" : "no"}; Brier ${fmt(row.clean_sheet_brier)}`,
    color: row.stage_a_league_average_team ? "#f97316" : "#2563eb",
  }));
  const sliceGw: TeamSlice[] = run.by_gw.map((row) => ({ ...row, label: `GW${row.gw}` }));
  const sliceTeam: TeamSlice[] = run.by_team.map((row) => ({ ...row, label: `${row.team_name} (${row.team_short_name})` }));
  const sliceVenue: TeamSlice[] = run.by_venue.map((row) => ({ ...row, label: row.venue === "home" ? "Home" : "Away" }));
  const sliceFallback: TeamSlice[] = run.by_fallback.map((row) => ({ ...row, label: row.stage_a_league_average_team ? "Stage A fallback" : "No fallback" }));
  const insightFacts = [
    insightFact(
      "coverage.visible_sides",
      "coverage",
      `${observations.length} finalized team-fixture side${observations.length === 1 ? " is" : "s are"} visible for ${scopeLabel}.`,
      ["team_forecast_vs_actual.json"],
    ),
    ...(selectedScore == null ? [] : [
      insightFact(
        view === "clean_sheet" ? "score.clean_sheet_brier" : `score.${view}_bias`,
        "published_scalar",
        view === "clean_sheet"
          ? `Published clean-sheet Brier score is ${fmt((selectedScore as CleanSheetScoreBlock).brier)}.`
          : `Published ${view} bias is ${signed((selectedScore as ForecastAccuracyScoreBlock).bias)}; residual is actual minus forecast.`,
        ["team_forecast_vs_actual.json"],
      ),
    ]),
    ...(highInsight ? [
      insightFact(
        "rank.largest_selected_error",
        "rank",
        `${highInsight.team_name} in GW${highInsight.gw} has the largest visible ${view === "clean_sheet" ? "clean-sheet Brier score" : `${view} residual`} at ${view === "clean_sheet" ? fmt(insightValue(highInsight)) : signed(insightValue(highInsight))}.`,
        ["team_forecast_vs_actual.json"],
      ),
    ] : []),
    ...(lowInsight ? [
      insightFact(
        "rank.smallest_selected_error",
        "rank",
        `${lowInsight.team_name} in GW${lowInsight.gw} has the smallest visible ${view === "clean_sheet" ? "clean-sheet Brier score" : `${view} residual`} at ${view === "clean_sheet" ? fmt(insightValue(lowInsight)) : signed(insightValue(lowInsight))}.`,
        ["team_forecast_vs_actual.json"],
      ),
    ] : []),
  ];
  const insightCaveats = [
    "Only finalized reciprocal fixture sides are scored.",
    view === "defence"
      ? "A positive defence residual means more goals were conceded than forecast and is worse."
      : "Residual equals actual goals minus the published forecast.",
    "CRPS, Brier scores, and calibration are published values; the browser does not reconstruct them.",
  ];
  const firstCompletedGw = completedGws[0] ?? run.gw_from;
  const lastCompletedGw = completedGws.at(-1) ?? run.gw_to;
  const selectedRole = accuracyRunRole(run.component_modes);

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h1 className="text-lg font-semibold">Team prediction vs actual</h1><p className="mt-1 max-w-3xl text-sm text-muted-foreground">Diagnose recorded team attack, defence, and clean-sheet forecasts against immutable reciprocal fixture outcomes. Historical residuals never become future club-selection signals.</p></div>
        <div className="flex flex-wrap gap-2">
          <label className="text-xs text-muted-foreground">Forecast vintage<select aria-label="Team forecast vintage" className="mt-1 block h-9 w-full max-w-[min(32rem,75vw)] rounded-md border bg-background px-2 text-sm text-foreground" value={run.run_id} onChange={(event) => { setRunId(event.target.value); setGwFilter("all"); }}>
            {runOptions.map((candidate) => <option key={candidate.run_id} value={candidate.run_id}>{accuracyRunLabel(candidate)}</option>)}
          </select></label>
          <label className="text-xs text-muted-foreground">Finalized scope<select aria-label="Completed team gameweek" className="mt-1 block h-9 w-full max-w-[min(32rem,75vw)] rounded-md border bg-background px-2 text-sm text-foreground" value={gwFilter} onChange={(event) => setGwFilter(event.target.value)}>
            <option value="all">All scored fixtures</option>{completedGws.map((gw) => <option key={gw} value={gw}>GW{gw}</option>)}
          </select></label>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-sm" aria-label="Monitoring vintage shortcuts">
        <button className="rounded-md border px-3 py-2" onClick={() => { setRunId(defaultAccuracyRun(runOptions)?.run_id ?? ""); setGwFilter("all"); }}>Latest scored forecast</button>
        <button className="rounded-md border px-3 py-2" onClick={() => { const latest = runOptions.find((r) => r.component_modes?.["football_environment.primary"] === "sdp_v2") ?? runOptions[0]; if (latest) setRunId(latest.run_id); setGwFilter("all"); }}>Latest published forecast · may be pending</button>
      </div>
      <PublicationStatus manifestHash={state.data.manifest?.content_sha256 ?? ""} />

      <div
        aria-label="Selected team forecast provenance"
        className="rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground"
      >
        <p>Viewing <span className="font-medium text-foreground">{accuracyRunRoleLabel(selectedRole)}</span>
        {" · "}as of {run.as_of ?? "unknown"}
        {" · "}{run.coverage.scored_rows} scored
        {" · "}development-only monitoring</p>
        <details className="mt-2"><summary className="cursor-pointer">Forecast components</summary>
          <p className="mt-1">{accuracyComponentLabel(run.component_modes)}</p>
        </details>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Team accuracy view">
        {(["attack", "defence", "clean_sheet"] as const).map((value) => <button key={value} type="button" aria-pressed={view === value} onClick={() => setView(value)} className={`rounded-md border px-3 py-1.5 text-sm ${view === value ? "bg-primary text-primary-foreground" : "bg-background"}`}>{value === "clean_sheet" ? "Clean sheet" : value[0].toUpperCase() + value.slice(1)}</button>)}
      </div>

      <section className="rounded-lg border bg-card p-4" aria-labelledby="team-coverage-heading">
        <h2 id="team-coverage-heading" className="text-sm font-semibold">Coverage and finality</h2>
        <p className="mt-1 text-sm">{coverage.scored_rows} of {coverage.forecast_rows} forecast team-fixture sides scored; {coverage.pending_rows} pending, {coverage.missing_outcome_rows} missing outcomes, {coverage.invalid_fixture_rows} invalid reciprocal fixtures.</p>
        <p className="mt-1 text-xs text-muted-foreground">PMF coverage: attack {coverage.attack_distribution_scored_rows}, defence {coverage.defence_distribution_scored_rows}; clean-sheet scored rows {coverage.clean_sheet_scored_rows}. A fixture scores only after two immutable reciprocal outcome sides agree.</p>
      </section>

      {!state.data.has_outcomes && <p role="status" className="rounded-md border p-4 text-sm">No finalized team outcomes are available in any published run. Pending and missing fixtures are never read as zero.</p>}

      {selectedScore
        ? view === "clean_sheet"
          ? <AccuracyKpis items={cleanSheetKpis(selectedScore as CleanSheetScoreBlock)} />
          : <AccuracyScoreKpis
              block={selectedScore as ForecastAccuracyScoreBlock}
              biasNote={view === "defence" ? "Positive = more goals conceded than forecast (worse)" : undefined}
            />
        : <p role="status" className="rounded-md border p-4 text-sm text-muted-foreground">No published {view.replace("_", " ")} score block exists for {scopeLabel}.</p>}

      {view === "defence" && <p className="rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100"><strong>Defence residual direction:</strong> positive means more goals were conceded than forecast and is worse; negative means fewer were conceded.</p>}

      <AccuracyScatter
        title={`${view === "clean_sheet" ? "Clean-sheet" : view[0].toUpperCase() + view.slice(1)} predicted vs actual · ${scopeLabel}`}
        description={view === "clean_sheet" ? "Published clean-sheet probability against a finalized binary outcome." : `Each point is one finalized team-fixture side. ${view === "defence" ? "Positive residual means more conceded than forecast (worse)." : "Positive residual means more goals than forecast."}`}
        predictedLabel={view === "attack" ? "Forecast λ for" : view === "defence" ? "Forecast λ against" : "Forecast P(clean sheet)"}
        actualLabel={view === "attack" ? "Actual goals for" : view === "defence" ? "Actual goals against" : "Actual clean sheet (0/1)"}
        points={plotPoints}
        emptyMessage="No finalized team-fixture observations exist in this scope."
      />


      <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">Cumulative club totals · selected scope</summary>      <section className="space-y-2" aria-labelledby="club-residuals-heading"><h2 id="club-residuals-heading" className="text-sm font-semibold">Cumulative club residuals in selected scope</h2><p className="text-xs text-muted-foreground">Expected clean sheets is the sum of published per-fixture probabilities, an expected count—not P(at least one clean sheet).</p><div className="overflow-x-auto rounded-md border"><Table aria-label="Cumulative club prediction residuals"><TableHeader><TableRow><TableHead>Club</TableHead><TableHead>Rows</TableHead><TableHead>Attack forecast / actual / residual</TableHead><TableHead>Defence forecast / actual / residual</TableHead><TableHead>Expected / actual clean sheets</TableHead></TableRow></TableHeader><TableBody>{clubs.map((club) => <TableRow key={club.teamId}><TableCell>{club.teamName} ({club.shortName})</TableCell><TableCell>{club.rows}</TableCell><TableCell className="tabular-nums">{fmt(club.attackForecast)} / {fmt(club.attackActual, 0)} / {signed(club.attackResidual)}</TableCell><TableCell className="tabular-nums">{fmt(club.defenceForecast)} / {fmt(club.defenceActual, 0)} / {signed(club.defenceResidual)} <span className="text-xs text-muted-foreground">(positive worse)</span></TableCell><TableCell className="tabular-nums">{fmt(club.expectedCleanSheets)} / {club.actualCleanSheets}</TableCell></TableRow>)}</TableBody></Table></div></section>

      </details>

      <AccuracyObservationTable
        key={`${run.run_id}-${gwFilter}-${view}`}
        title="Exact team prediction observations"
        rows={observations}
        rowKey={r => `${r.fixture}-${r.team_id}`}
        searchText={r => `${r.team_name} ${r.team_short_name} ${r.opponent_team_name} GW${r.gw}`}
        context={`${run.season} · ${scopeLabel} · ${view} · forecast as of ${run.as_of}`}
        columns={[
          { key: "gw", label: "GW", value: r => r.gw },
          { key: "team", label: "Club", value: r => r.team_name },
          { key: "opponent", label: "Opponent", value: r => r.opponent_team_short_name },
          { key: "venue", label: "Venue", value: r => r.was_home ? "Home" : "Away" },
          { key: "forecast", label: view === "clean_sheet" ? "Forecast P(CS)" : "Forecast goals", value: r => view === "attack" ? r.lambda_for : view === "defence" ? r.lambda_against : r.probability_clean_sheet, render: r => <strong className="text-sky-700 dark:text-sky-300">{view === "clean_sheet" ? pct(r.probability_clean_sheet) : fmt(view === "attack" ? r.lambda_for : r.lambda_against, 2)}</strong> },
          { key: "actual", label: view === "clean_sheet" ? "Actual CS" : "Actual goals", value: r => view === "attack" ? r.actual_goals_for : view === "defence" ? r.actual_goals_against : Number(r.actual_clean_sheet), render: r => <strong>{view === "clean_sheet" ? r.actual_clean_sheet ? "Yes" : "No" : view === "attack" ? r.actual_goals_for : r.actual_goals_against}</strong> },
          { key: "delta", label: view === "clean_sheet" ? "Brier ↓" : "Δ Actual − forecast", value: r => view === "attack" ? r.attack_residual : view === "defence" ? r.defence_residual : r.clean_sheet_brier, render: r => view === "clean_sheet" ? fmt(r.clean_sheet_brier) : <AccuracyDelta value={view === "attack" ? r.attack_residual : r.defence_residual} /> },
          { key: "error", label: view === "clean_sheet" ? "CS error ↓" : "Abs error", value: r => view === "attack" ? Math.abs(r.attack_residual) : view === "defence" ? Math.abs(r.defence_residual) : r.clean_sheet_brier, render: r => fmt(view === "attack" ? Math.abs(r.attack_residual) : view === "defence" ? Math.abs(r.defence_residual) : r.clean_sheet_brier, 2) },
          { key: "crps", label: "CRPS ↓", value: r => view === "attack" ? r.attack_crps : view === "defence" ? r.defence_crps : null, render: r => fmt(view === "attack" ? r.attack_crps : view === "defence" ? r.defence_crps : null), advanced: true },
          { key: "fallback", label: "League-average prior", value: r => r.stage_a_league_average_team ? "Yes" : "No", advanced: true },
        ]}
      />

      <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">Calibration and breakdowns · full selected vintage</summary>
      <section className="space-y-2" aria-labelledby="team-calibration-heading"><h2 id="team-calibration-heading" className="text-sm font-semibold">Published reliability · full run</h2><p className="text-xs text-muted-foreground">Goal events come from exact stored team PMFs; clean-sheet values are published. The browser does not compute probabilities, CRPS, calibration, or buckets.</p><div className="overflow-x-auto rounded-md border"><Table aria-label="Team forecast calibration"><TableHeader><TableRow><TableHead>Event</TableHead><TableHead>Bucket</TableHead><TableHead>Rows</TableHead><TableHead>Predicted mean</TableHead><TableHead>Observed rate</TableHead></TableRow></TableHeader><TableBody>{run.calibration.map((row, index) => <TableRow key={`${row.event}-${row.threshold}-${row.bucket}-${index}`}><TableCell>{row.event === "clean_sheet" ? "P(clean sheet)" : `P(goals ≥ ${row.threshold})`}</TableCell><TableCell>{row.bucket}</TableCell><TableCell>{row.rows}</TableCell><TableCell>{pct(row.predicted_mean)}</TableCell><TableCell>{pct(row.observed_rate)}</TableCell></TableRow>)}</TableBody></Table></div></section>

      <div className="grid gap-4 xl:grid-cols-2"><SliceTable title="Scores by finalized gameweek" rows={sliceGw} view={view} /><SliceTable title="Scores by club" rows={sliceTeam} view={view} /><SliceTable title="Scores by venue" rows={sliceVenue} view={view} /><SliceTable title="Scores by Stage A fallback" rows={sliceFallback} view={view} /></div>

      </details>

      <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">Forecast record and methodology</summary><p className="mt-2 break-all">Run {run.run_id} · as of {run.as_of ?? "unknown"} · created {run.created_at ?? "unknown"}. Attack and defence CRPS were published from exact stored PMFs; defence uses the opponent’s recorded goals-for PMF, never a browser reconstruction from λ against.</p></details>
      <InsightSummaryPanel
        items={insightFacts}
        caveats={insightCaveats}
        remote={{
          page: "team_forecast_vs_actual",
          provenance: publishedInsightProvenance(state.data.manifest, run),
          scope: compactInsightScope({
            gw_from: gwFilter === "all" ? firstCompletedGw : Number(gwFilter),
            gw_to: gwFilter === "all" ? lastCompletedGw : Number(gwFilter),
            view,
          }),
          localScopeKey: JSON.stringify({ runId: run.run_id, gwFilter, view }),
        }}
      />
    </div>
  );
}
