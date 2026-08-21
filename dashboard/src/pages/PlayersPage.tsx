// Players page: the player-form pivot. One row per player of the SELECTED vintage (the
// export carries every recorded run -- the vintage selector picks one, so players never
// repeat), merging backward form (labelled with its anchor season -- LAST season at
// GW1) with the vintage's per-fixture xP. Chips headline the xP and are coloured by the
// active colour source (opponent strength by default); the expanded row exposes every
// primitive behind the colour, ordered by kickoff time.

import { useEffect, useMemo, useState } from "react";
import { RotateCcw } from "lucide-react";
import { DifficultyLegend } from "@/components/DifficultyLegend";
import { FilterBar, type FilterState } from "@/components/FilterBar";
import { FilterPanel } from "@/components/FilterPanel";
import {
  FORM_WINDOW_LABEL,
  INITIAL_PLAYER_FILTERS,
  PlayerFiltersBar,
  matchesPlayerFilters,
  type PlayerFilters,
} from "@/components/PlayerFiltersBar";
import { PlayerStatTable, type PlayerStatRow } from "@/components/PlayerStatTable";
import { VintageSelect } from "@/components/VintageSelect";
import { Button } from "@/components/ui/button";
import { loadFixtureMatrix, loadNextGw, loadPlayers } from "@/data/load";
import type { NextGwPlan, PlayerRecord, TeamRecord } from "@/data/types";
import type { ColorSource } from "@/lib/difficulty";
import { buildOpponentStrength } from "@/lib/opponentStrength";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      players: PlayerRecord[];
      teams: TeamRecord[];
      plans: NextGwPlan[];
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

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadPlayers(), loadFixtureMatrix(), loadNextGw()])
      .then(([playersData, teamsData, nextGw]) => {
        if (cancelled) return;
        // Runs come from the manifest when present; the record grains repeat run_id
        // anyway, so deriving them from the players keeps tests (manifest: null) honest.
        const seen = new Map<
          string,
          { run_id: string; season: string; gw_from: number; gw_to: number }
        >();
        for (const p of playersData.players) {
          const gws = p.fixtures.map((f) => f.gw);
          const existing = seen.get(p.run_id);
          const from = gws.length ? Math.min(...gws) : 0;
          const to = gws.length ? Math.max(...gws) : 0;
          if (!existing) seen.set(p.run_id, { run_id: p.run_id, season: p.season, gw_from: from, gw_to: to });
          else
            seen.set(p.run_id, {
              ...existing,
              gw_from: Math.min(existing.gw_from, from),
              gw_to: Math.max(existing.gw_to, to),
            });
        }
        const runs =
          playersData.manifest?.runs ??
          [...seen.values()].sort((a, b) => a.run_id.localeCompare(b.run_id));
        const defaultRun = defaultVintageRunId(
          runs,
          nextGw.plans,
          playersData.manifest?.runs.at(-1)?.run_id ?? null,
        );
        const runRecords = playersData.players.filter((p) => p.run_id === defaultRun);
        const gws = runRecords.flatMap((p) => p.fixtures.map((f) => f.gw));
        const gwFrom = gws.length ? Math.min(...gws) : 1;
        const gwTo = gws.length ? Math.max(...gws) : 1;
        const first = runRecords[0] ?? playersData.players[0];
        setState({
          status: "ready",
          players: playersData.players,
          teams: teamsData.teams,
          plans: nextGw.plans,
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
    [state, state.status, runId],
  );

  const runTeams = useMemo(
    () =>
      state.status === "ready"
        ? state.teams.filter((t) => t.run_id === (runId ?? state.defaultRunId))
        : [],
    [state, state.status, runId],
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

  const rows: PlayerStatRow[] = useMemo(() => {
    if (state.status !== "ready" || !filters) return [];
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
      return {
        player,
        filtered,
        totalXp: xpValues.length ? xpValues.reduce((a, b) => a + b, 0) : null,
        form: player.form ? player.form.windows[playerFilters.formWindow] : null,
      };
    });
  }, [runPlayers, filters, playerFilters]);

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
  const formAnchor = activeRun?.form
    ? `${activeRun.form.season} GW${activeRun.form.as_at_gw}`
    : "anchor unknown";
  const clearFilters = () => {
    setFilters({ view: "overall", venue: "all", gwFrom: state.gwFrom, gwTo: state.gwTo });
    setPlayerFilters({ ...INITIAL_PLAYER_FILTERS });
  };

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
            {activeRun?.as_of?.replace("T", " ").slice(0, 16)} UTC · form anchored {formAnchor}
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
                minGw={state.gwFrom}
                maxGw={state.gwTo}
              />
              <Button type="button" variant="outline" size="sm" onClick={clearFilters}>
                <RotateCcw className="size-3.5" aria-hidden />
                Clear filters
              </Button>
            </div>
          )}
          <PlayerFiltersBar filters={playerFilters} onChange={setPlayerFilters} teams={teams} />
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
      </div>

      {filters && (
        <PlayerStatTable
          fullscreenLabel="Players table"
          rows={rows}
          view={filters.view}
          colorSource={colorSource}
          gwFrom={filters.gwFrom}
          gwTo={filters.gwTo}
          opponentIndexOf={opponentIndexOf}
          formHeading={FORM_WINDOW_LABEL[playerFilters.formWindow]}
          formTitle={`Form window ${FORM_WINDOW_LABEL[playerFilters.formWindow]}, anchored ${formAnchor} (last season at GW1)`}
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
