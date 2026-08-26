// Players page: the player-form pivot. One row per player of the SELECTED vintage (the
// export carries every recorded run -- the vintage selector picks one, so players never
// repeat), merging a separately selected range of finalized current-season actuals with
// the vintage's per-fixture xP. Prior-season form is never substituted. Chips headline xP and are coloured by the
// active colour source (opponent strength by default); the expanded row exposes every
// primitive behind the colour, ordered by kickoff time.

import { useEffect, useMemo, useState } from "react";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";
import { RotateCcw } from "lucide-react";
import { DifficultyLegend } from "@/components/DifficultyLegend";
import { FilterBar, type FilterState } from "@/components/FilterBar";
import { FilterPanel } from "@/components/FilterPanel";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import {
  INITIAL_PLAYER_FILTERS,
  PlayerFiltersBar,
  matchesPlayerFilters,
  type PlayerFilters,
} from "@/components/PlayerFiltersBar";
import { PlayerStatTable, type PlayerStatRow } from "@/components/PlayerStatTable";
import { VintageSelect } from "@/components/VintageSelect";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { loadFixtureMatrix, loadNextGw, loadPlayerHorizons, loadPlayers } from "@/data/load";
import type { DashboardManifest, NextGwPlan, PlayerHorizonsRecord, PlayerRecord, TeamRecord } from "@/data/types";
import type { ColorSource } from "@/lib/difficulty";
import { buildOpponentStrength } from "@/lib/opponentStrength";
import { actualGameweekRange, aggregatePlayerActuals } from "@/lib/playerActuals";
import { indexPlayerHorizons, playerHorizon } from "@/lib/playerHorizons";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";
import {
  compactInsightScope,
  insightFact,
  maxPriceTenthsScope,
  minAverageMinutesScope,
  minPriceTenthsScope,
  playerPositionScope,
  publishedInsightProvenance,
} from "@/lib/insights";

interface ActualRange {
  gwFrom: number;
  gwTo: number;
}

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      players: PlayerRecord[];
      playerHorizons: PlayerHorizonsRecord[];
      teams: TeamRecord[];
      plans: NextGwPlan[];
      manifest: DashboardManifest | null;
      manifestRuns: { run_id: string; season: string; gw_from: number; gw_to: number }[];
      easeVersion: string;
      gwFrom: number;
      gwTo: number;
      defaultRunId: string;
    };

export function PlayersPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [colorSource, setColorSource] = useState<ColorSource>("opponent");
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [playerFilters, setPlayerFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);
  const [actualRange, setActualRange] = useState<ActualRange | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadPlayers(), loadPlayerHorizons(), loadFixtureMatrix(), loadNextGw()])
      .then(([playersData, horizonsData, teamsData, nextGw]) => {
        if (cancelled) return;
        // The manifest owns run bounds when present. Without it, the validated horizon
        // vectors are authoritative: fixture arrays omit blank weeks and may be empty.
        const horizonRuns = new Map<
          string,
          { run_id: string; season: string; gw_from: number; gw_to: number }
        >();
        for (const player of horizonsData.players) {
          const first = player.horizons[0];
          const last = player.horizons.at(-1);
          if (!first || !last || horizonRuns.has(player.run_id)) continue;
          horizonRuns.set(player.run_id, {
            run_id: player.run_id,
            season: player.season,
            gw_from: first.gw_to,
            gw_to: last.gw_to,
          });
        }
        const runs =
          playersData.manifest?.runs ??
          [...horizonRuns.values()].sort((a, b) => a.run_id.localeCompare(b.run_id));
        const defaultRun = defaultVintageRunId(
          runs,
          nextGw.plans,
          playersData.manifest?.runs.at(-1)?.run_id ?? null,
        );
        const runRecords = playersData.players.filter((p) => p.run_id === defaultRun);
        const defaultRunRecord = runs.find((run) => run.run_id === defaultRun);
        const gwFrom = defaultRunRecord?.gw_from ?? 1;
        const gwTo = defaultRunRecord?.gw_to ?? 1;
        const first = runRecords[0] ?? playersData.players[0];
        setState({
          status: "ready",
          players: playersData.players,
          playerHorizons: horizonsData.players,
          teams: teamsData.teams,
          plans: nextGw.plans,
          manifest: playersData.manifest,
          manifestRuns: runs,
          easeVersion:
            playersData.manifest?.ease_index_formula_version ?? teamsData.easeIndexFormulaVersion,
          gwFrom,
          gwTo,
          defaultRunId: defaultRun ?? first?.run_id ?? "",
        });
        setRunId(defaultRun ?? first?.run_id ?? null);
        setFilters({ view: "overall", venue: "all", gwFrom, gwTo });
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const runPlayers = useMemo(
    () =>
      state.status === "ready"
        ? state.players.filter((p) => p.run_id === (runId ?? state.defaultRunId))
        : [],
    [state, runId],
  );

  const runTeams = useMemo(
    () =>
      state.status === "ready"
        ? state.teams.filter((t) => t.run_id === (runId ?? state.defaultRunId))
        : [],
    [state, runId],
  );

  const opponentStrength = useMemo(() => buildOpponentStrength(runTeams), [runTeams]);
  const opponentIndexOf = useMemo(
    () => (teamCode: number) => opponentStrength.get(teamCode)?.index ?? null,
    [opponentStrength],
  );

  const teams = useMemo(() => {
    const seen = new Map<number, string>();
    for (const p of runPlayers) if (!seen.has(p.team_code)) seen.set(p.team_code, p.team_short_name);
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [runPlayers]);

  const actualBounds = useMemo(() => actualGameweekRange(runPlayers), [runPlayers]);

  const horizonIndex = useMemo(
    () => indexPlayerHorizons(state.status === "ready" ? state.playerHorizons : []),
    [state],
  );

  const selectedRun = useMemo(() => {
    if (state.status !== "ready") return null;
    const activeRunId = runId ?? state.defaultRunId;
    return state.manifestRuns.find((run) => run.run_id === activeRunId) ?? null;
  }, [state, runId]);

  const cumulativeOutcomesAvailable =
    filters != null &&
    selectedRun != null &&
    filters.venue === "all" &&
    filters.gwFrom === selectedRun.gw_from;

  useEffect(() => {
    if (selectedRun == null) return;
    setFilters((current) =>
      current == null
        ? current
        : {
            ...current,
            gwFrom: selectedRun.gw_from,
            gwTo: selectedRun.gw_to,
          },
    );
  }, [selectedRun]);

  useEffect(() => {
    setActualRange(
      actualBounds == null
        ? null
        : { gwFrom: actualBounds.minGw, gwTo: actualBounds.maxGw },
    );
  }, [actualBounds, selectedRun?.run_id]);

  const rows: PlayerStatRow[] = useMemo(() => {
    if (!filters) return [];
    const wanted = runPlayers.filter((p) => matchesPlayerFilters(p, playerFilters));
    return wanted.map((player) => {
      const filtered = player.fixtures
        .filter(
          (f) =>
            f.gw >= filters.gwFrom &&
            f.gw <= filters.gwTo &&
            (filters.venue === "all" ||
              (filters.venue === "home" ? f.was_home === true : f.was_home === false)),
        )
        .sort((a, b) => a.gw - b.gw || (a.kickoff_time ?? "").localeCompare(b.kickoff_time ?? ""));
      const xpValues = filtered
        .map((f) => f.expected_points)
        .filter((v): v is number => v != null);
      const horizon = cumulativeOutcomesAvailable
        ? playerHorizon(
            horizonIndex,
            player.run_id,
            player.season,
            player.code,
            filters.gwTo,
          )
        : null;
      return {
        // Suppress the shared detail row's retired prior-season form anchor on this page.
        player: { ...player, form: null },
        filtered,
        totalXp: horizon?.xp ?? (xpValues.length ? xpValues.reduce((a, b) => a + b, 0) : null),
        horizon,
        form:
          actualRange == null
            ? null
            : aggregatePlayerActuals(player.actuals, actualRange.gwFrom, actualRange.gwTo),
      };
    });
  }, [runPlayers, filters, playerFilters, cumulativeOutcomesAvailable, horizonIndex, actualRange]);

  const cumulativeColumns = useMemo<LegacyColumnDef<PlayerStatRow>[]>(() => {
    if (!cumulativeOutcomesAvailable) return [];
    const probability = (
      key: "p_le_2" | "p_ge_2" | "p_ge_4" | "p_ge_6" | "p_ge_10" | "p_ge_15",
      label: string,
    ): LegacyColumnDef<PlayerStatRow> => ({
      id: key,
      header: label,
      accessorFn: (row) => row.horizon?.[key],
      sortUndefined: "last",
      cell: ({ row }) => {
        const value = row.original.horizon?.[key];
        return (
          <span className="tabular-nums" title={`${label}, raw model probability`}>
            {value == null ? "–" : `${Math.round(value * 100)}%`}
          </span>
        );
      },
    });
    return [
      probability("p_le_2", "P(≤2)"),
      probability("p_ge_2", "P(≥2)"),
      probability("p_ge_4", "P(≥4)"),
      probability("p_ge_6", "P(≥6)"),
      probability("p_ge_10", "P(≥10)"),
      probability("p_ge_15", "P(≥15)"),
    ];
  }, [cumulativeOutcomesAvailable]);

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Players</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!state.players.length) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Players</h1>
        <p className="max-w-xl text-sm text-muted-foreground">
          No recorded forecast vintages in this export. Generate one first (see
          dashboard/README.md).
        </p>
      </div>
    );
  }

  const activeRunId = runId ?? state.defaultRunId;
  const activeRun = runPlayers[0];
  const clearFilters = () => {
    setFilters({
      view: "overall",
      venue: "all",
      gwFrom: selectedRun?.gw_from ?? state.gwFrom,
      gwTo: selectedRun?.gw_to ?? state.gwTo,
    });
    setPlayerFilters({ ...INITIAL_PLAYER_FILTERS });
    setActualRange(
      actualBounds == null
        ? null
        : { gwFrom: actualBounds.minGw, gwTo: actualBounds.maxGw },
    );
  };
  const rankedRows = [...rows]
    .filter((row): row is PlayerStatRow & { totalXp: number } => row.totalXp != null)
    .sort((left, right) => right.totalXp - left.totalXp || left.player.code - right.player.code);
  const topXp = rankedRows[0];
  const actualRows = rows.filter((row) => row.form != null);
  const measuredActualPoints = actualRows
    .filter(
      (row): row is PlayerStatRow & { form: NonNullable<PlayerStatRow["form"]> } =>
        row.form?.points_under_rules_2026_27 != null,
    )
    .sort(
      (left, right) =>
        (right.form.points_under_rules_2026_27 ?? 0) -
          (left.form.points_under_rules_2026_27 ?? 0) ||
        left.player.code - right.player.code,
    );
  const actualPointsLeader = measuredActualPoints[0];
  const flaggedCount = rows.filter(
    (row) => row.player.availability_status != null && row.player.availability_status !== "a",
  ).length;
  const insightFacts = [
    insightFact(
      "coverage.filtered_players",
      "coverage",
      `${rows.length} players match the visible filters; ${rows.length - rankedRows.length} have no xP value in this scope.`,
      ["players.json", "player_horizons.json"],
    ),
    ...(topXp ? [
      insightFact(
        "rank.highest_xp",
        "rank",
        `${topXp.player.web_name} has the highest visible xP total at ${topXp.totalXp.toFixed(3)} from GW${filters?.gwFrom ?? selectedRun?.gw_from} through GW${filters?.gwTo ?? selectedRun?.gw_to}.`,
        ["players.json", "player_horizons.json"],
      ),
    ] : []),
    insightFact(
      "coverage.flagged_overlay",
      "coverage",
      `${flaggedCount} visible players carry a non-available next-round status overlay.`,
      ["players.json"],
    ),
    insightFact(
      "coverage.current_season_actuals",
      "coverage",
      actualRange == null
        ? `No visible player has finalized ${activeRun?.season} actuals; prior-season form is not substituted.`
        : `${actualRows.length} visible players have finalized ${activeRun?.season} observations in the selected GW${actualRange.gwFrom}-GW${actualRange.gwTo} range.`,
      ["players.json"],
    ),
    ...(actualPointsLeader ? [
      insightFact(
        "rank.current_actual_points",
        "rank",
        `${actualPointsLeader.player.web_name} leads measured replayed points in the selected actual range with ${actualPointsLeader.form.points_under_rules_2026_27}.`,
        ["players.json"],
      ),
    ] : []),
  ];
  const insightCaveats = [
    "xP totals sum already-published player-fixture values or select an exact cumulative endpoint.",
    "Outcome probabilities are shown only for the run's fixed start and all venues.",
    "The availability status is a next-round overlay and is not applied to raw xP.",
    "Actual GWs contain finalized observations from the selected vintage's current season only.",
  ];

  return (
    <div className="flex flex-col gap-3 p-4 lg:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Players</h1>
        <div className="flex flex-wrap items-center gap-3">
          <VintageSelect
            options={vintageOptions(state.manifestRuns, state.plans)}
            value={activeRunId}
            onChange={setRunId}
          />
          <p className="text-xs text-muted-foreground">
            {runPlayers.length} players · as of{" "}
            {activeRun?.as_of?.replace("T", " ").slice(0, 16)} UTC · actuals restricted to{" "}
            {activeRun?.season}
          </p>
        </div>
      </div>

      <FilterPanel>
        <div className="flex flex-col gap-2">
          {filters && (
            <div className="flex flex-wrap items-start justify-between gap-2">
              <FilterBar
                filters={filters}
                onChange={setFilters}
                minGw={selectedRun?.gw_from ?? state.gwFrom}
                maxGw={selectedRun?.gw_to ?? state.gwTo}
                gameweekLabel="Forecast GWs"
              />
              <Button type="button" variant="outline" size="sm" onClick={clearFilters}>
                <RotateCcw className="size-3.5" aria-hidden />
                Clear filters
              </Button>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <PlayerFiltersBar
              filters={playerFilters}
              onChange={setPlayerFilters}
              teams={teams}
              showFormWindow={false}
            />
            {actualBounds != null && actualRange != null && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Actual GWs</span>
                <Select
                  value={String(actualRange.gwFrom)}
                  onValueChange={(value) =>
                    setActualRange((current) =>
                      current == null
                        ? current
                        : { ...current, gwFrom: Math.min(Number(value), current.gwTo) },
                    )
                  }
                >
                  <SelectTrigger size="sm" className="w-16" aria-label="Actual from gameweek">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from(
                      { length: actualRange.gwTo - actualBounds.minGw + 1 },
                      (_, index) => actualBounds.minGw + index,
                    ).map((gw) => (
                      <SelectItem key={gw} value={String(gw)}>GW{gw}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span>to</span>
                <Select
                  value={String(actualRange.gwTo)}
                  onValueChange={(value) =>
                    setActualRange((current) =>
                      current == null
                        ? current
                        : { ...current, gwTo: Math.max(Number(value), current.gwFrom) },
                    )
                  }
                >
                  <SelectTrigger size="sm" className="w-16" aria-label="Actual to gameweek">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from(
                      { length: actualBounds.maxGw - actualRange.gwFrom + 1 },
                      (_, index) => actualRange.gwFrom + index,
                    ).map((gw) => (
                      <SelectItem key={gw} value={String(gw)}>GW{gw}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Forecast GWs filter upcoming fixtures and xP only. Actual GWs independently aggregate
            finalized {activeRun?.season} observations; they never include a previous season.
            The Min avg min (L5) filter remains its separately published trailing-five anchor and
            does not follow Actual GWs.
          </p>
          {actualBounds == null && (
            <p role="status" className="text-xs text-amber-700 dark:text-amber-300">
              No finalized player actuals are published for {activeRun?.season}. Observed columns
              stay unavailable; prior-season form is not substituted.
            </p>
          )}
        </div>
      </FilterPanel>

      <div className="rounded-lg border bg-card p-2">
        <DifficultyLegend
          colorSource={colorSource}
          onColorSourceChange={setColorSource}
          easeIndexFormulaVersion={state.easeVersion}
          cleanSheetAnchor={null}
          defenceScaleNote="Defence view colours on the club's defence ease index (higher = the club concedes less)."
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Observed form columns follow Overall, Attack, or Defense. Chip headline is fixture xP;
          its colour follows the selected source. GW columns are the pivot -- one per gameweek,
          two chips in a double gameweek.
        </p>
        {cumulativeOutcomesAvailable && filters && selectedRun ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Outcome probabilities cover every fixture from GW{selectedRun.gw_from} through GW
            {filters.gwTo}. They are backend-convolved independent-gameweek model values, raw and
            unadjusted for the next-round availability overlay. Both ≤2 and ≥2 include score 2.
          </p>
        ) : selectedRun ? (
          <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
            Cumulative probabilities are hidden for a shifted start or Home/Away filter. Select
            All venues and start at GW{selectedRun.gw_from}; marginal probabilities cannot be
            subtracted or conditioned in the browser.
          </p>
        ) : null}
      </div>

      <InsightSummaryPanel
        items={insightFacts}
        caveats={insightCaveats}
        remote={{
          page: "players",
          provenance: publishedInsightProvenance(state.manifest, {
            ...selectedRun!,
            as_of: activeRun?.as_of,
          }),
          scope: compactInsightScope({
            gw_from: filters?.gwFrom,
            gw_to: filters?.gwTo,
            actual_gw_from: actualRange?.gwFrom,
            actual_gw_to: actualRange?.gwTo,
            position: playerPositionScope(playerFilters.position),
            team_code: playerFilters.teamCode === "all" ? undefined : Number(playerFilters.teamCode),
            view: filters?.view === "defense" ? "defence" : filters?.view,
            venue: filters?.venue,
            min_price_tenths: minPriceTenthsScope(playerFilters.minPrice),
            max_price_tenths: maxPriceTenthsScope(playerFilters.maxPrice),
            min_avg_minutes_l5: minAverageMinutesScope(playerFilters.minMinutes),
            availability: playerFilters.availability,
          }),
          localScopeKey: JSON.stringify({
            runId: activeRunId,
            filters,
            playerFilters,
            actualRange,
            colorSource,
          }),
        }}
      />

      {filters && (
        <PlayerStatTable
          fullscreenLabel="Players table"
          rows={rows}
          view={filters.view}
          colorSource={colorSource}
          gwFrom={filters.gwFrom}
          gwTo={filters.gwTo}
          opponentIndexOf={opponentIndexOf}
          formHeading={
            actualRange == null ? "Actual" : `Actual GW${actualRange.gwFrom}-${actualRange.gwTo}`
          }
          formTitle={
            actualRange == null
              ? `No finalized ${activeRun?.season} actuals published`
              : `Finalized ${activeRun?.season} actuals, GW${actualRange.gwFrom}-GW${actualRange.gwTo}`
          }
          formColumnProfile="players"
          beforeFixtureColumns={cumulativeColumns}
        />
      )}

      <p className="text-xs text-muted-foreground">
        Availability and chance-of-playing are reported overlays valid for the next gameweek
        only; they label rows here and never fold into xP. Player-fixture probabilities are
        null until the ledger persists them — never 0. Club λ/ease/CS are the primitives behind
        the chip colour.
      </p>
    </div>
  );
}
