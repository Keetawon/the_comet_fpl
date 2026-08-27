// Players page: the player-form pivot. One row per player of the SELECTED vintage (the
// export carries every recorded run -- the vintage selector picks one, so players never
// repeat), merging a separately selected season/range of finalized actuals with
// the vintage's per-fixture xP. A prior season is used only after explicit selection. Chips headline xP and are coloured by the
// active colour source (opponent strength by default); the expanded row exposes every
// primitive behind the colour, ordered by kickoff time.

import { useEffect, useMemo, useState } from "react";
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
import { loadFixtureMatrix, loadNextGw, loadPlayerActuals, loadPlayerHorizons, loadPlayers } from "@/data/load";
import type { DashboardManifest, NextGwPlan, PlayerActualsRecord, PlayerHorizonsRecord, PlayerRecord, TeamRecord } from "@/data/types";
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

function previousSeason(season: string): string | null {
  const matched = /^(\d{4})-(\d{2})$/.exec(season);
  if (matched == null) return null;
  const start = Number(matched[1]);
  return `${start - 1}-${String(start % 100).padStart(2, "0")}`;
}

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      players: PlayerRecord[];
      playerActuals: PlayerActualsRecord[];
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
  const [actualSeason, setActualSeason] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      loadPlayers(),
      loadPlayerActuals(),
      loadPlayerHorizons(),
      loadFixtureMatrix(),
      loadNextGw(),
    ])
      .then(([playersData, actualsData, horizonsData, teamsData, nextGw]) => {
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
          playerActuals: actualsData.players,
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
        setActualSeason(defaultRunRecord?.season ?? first?.season ?? null);
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

  const horizonIndex = useMemo(
    () => indexPlayerHorizons(state.status === "ready" ? state.playerHorizons : []),
    [state],
  );

  const selectedRun = useMemo(() => {
    if (state.status !== "ready") return null;
    const activeRunId = runId ?? state.defaultRunId;
    return state.manifestRuns.find((run) => run.run_id === activeRunId) ?? null;
  }, [state, runId]);

  const actualSeasons = useMemo(() => {
    if (state.status !== "ready" || selectedRun == null) return [];
    const codes = new Set(runPlayers.map((player) => player.code));
    const previous = previousSeason(selectedRun.season);
    const allowed = new Set([selectedRun.season, ...(previous == null ? [] : [previous])]);
    return [...new Set([
      selectedRun.season,
      ...state.playerActuals
        .filter((record) => codes.has(record.code) && allowed.has(record.season))
        .map((record) => record.season),
    ])].sort((left, right) => right.localeCompare(left));
  }, [runPlayers, selectedRun, state]);

  const selectedActualRecords = useMemo(() => {
    if (state.status !== "ready" || actualSeason == null) return [];
    const codes = new Set(runPlayers.map((player) => player.code));
    return state.playerActuals.filter(
      (record) => record.season === actualSeason && codes.has(record.code),
    );
  }, [actualSeason, runPlayers, state]);

  const actualsByCode = useMemo(
    () => new Map(selectedActualRecords.map((record) => [record.code, record.actuals])),
    [selectedActualRecords],
  );
  const actualBounds = useMemo(
    () => actualGameweekRange(selectedActualRecords),
    [selectedActualRecords],
  );

  const cumulativeOutcomesAvailable =
    filters != null &&
    selectedRun != null &&
    filters.venue === "all" &&
    filters.gwFrom === selectedRun.gw_from;

  useEffect(() => {
    if (selectedRun == null) return;
    setActualSeason(selectedRun.season);
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
  }, [actualBounds, actualSeason, selectedRun?.run_id]);

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
            : aggregatePlayerActuals(
                actualsByCode.get(player.code) ?? [],
                actualRange.gwFrom,
                actualRange.gwTo,
              ),
      };
    });
  }, [
    runPlayers,
    filters,
    playerFilters,
    cumulativeOutcomesAvailable,
    horizonIndex,
    actualRange,
    actualsByCode,
  ]);

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
    const resetSeason = selectedRun?.season ?? null;
    const resetCodes = new Set(runPlayers.map((player) => player.code));
    const resetBounds =
      state.status === "ready" && resetSeason != null
        ? actualGameweekRange(
            state.playerActuals.filter(
              (record) => record.season === resetSeason && resetCodes.has(record.code),
            ),
          )
        : null;
    setActualSeason(resetSeason);
    setActualRange(
      resetBounds == null
        ? null
        : { gwFrom: resetBounds.minGw, gwTo: resetBounds.maxGw },
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
      "coverage.selected_season_actuals",
      "coverage",
      actualRange == null
        ? `No visible player has finalized ${actualSeason ?? activeRun?.season} actuals; another season is not substituted.`
        : `${actualRows.length} visible players have finalized ${actualSeason} observations in the selected GW${actualRange.gwFrom}-GW${actualRange.gwTo} range.`,
      ["player_actuals.json"],
    ),
    ...(actualPointsLeader ? [
      insightFact(
        "rank.current_actual_points",
        "rank",
        `${actualPointsLeader.player.web_name} leads measured replayed points in the selected actual range with ${actualPointsLeader.form.points_under_rules_2026_27}.`,
        ["player_actuals.json"],
      ),
    ] : []),
  ];
  const insightCaveats = [
    "xP totals sum already-published player-fixture values or select an exact cumulative endpoint.",
    "Overlapping cumulative probability columns are intentionally kept out of this dense table; Player analytics exposes the exact published blank/haul endpoints.",
    "The availability status is a next-round overlay and is not applied to raw xP.",
    "Actual season and GW selectors use finalized observations only; a prior season appears only after explicit selection.",
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
            {activeRun?.as_of?.replace("T", " ").slice(0, 16)} UTC · forecast season{" "}
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
            {actualSeasons.length > 0 && actualSeason != null && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Actual season</span>
                <Select value={actualSeason} onValueChange={setActualSeason}>
                  <SelectTrigger size="sm" className="w-28" aria-label="Actual season">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {actualSeasons.map((season) => (
                      <SelectItem key={season} value={season}>{season}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
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
            finalized {actualSeason} observations. Changing Actual season is explicit and never
            mixes seasons in one aggregate.
            The Min avg min (L5) filter remains its separately published trailing-five anchor and
            does not follow Actual GWs.
          </p>
          {actualBounds == null && (
            <p role="status" className="text-xs text-amber-700 dark:text-amber-300">
              No finalized player actuals are published for {actualSeason}. Observed columns stay
              unavailable; another season is not substituted.
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
        <p className="mt-1 text-xs text-muted-foreground">
          The dense Players table omits the six overlapping P(≤/≥ threshold) columns. Use Player
          analytics for the exact backend-published blank and haul probabilities; this table keeps
          cumulative xP and observed stats readable.
        </p>
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
            actual_season: actualRange == null ? undefined : actualSeason ?? undefined,
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
            actualSeason,
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
            actualRange == null
              ? `Actual ${actualSeason ?? ""}`.trim()
              : `Actual ${actualSeason} GW${actualRange.gwFrom}-${actualRange.gwTo}`
          }
          formTitle={
            actualRange == null
              ? `No finalized ${actualSeason} actuals published`
              : `Finalized ${actualSeason} actuals, GW${actualRange.gwFrom}-GW${actualRange.gwTo}`
          }
          formColumnProfile="players"
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
