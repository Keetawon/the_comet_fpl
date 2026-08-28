// Players page: the player-form pivot. One row per player of the SELECTED vintage (the
// export carries every recorded run -- the vintage selector picks one, so players never
// repeat), merging an exact cross-season range of finalized actuals with the vintage's
// per-fixture xP. Actual endpoints span the forecast season and its immediate predecessor and
// default to their latest five finalized gameweeks. Expanded history remains its own fixed rolling
// latest-five-GW view. Chips headline xP and are coloured by the active colour source (opponent
// strength by default).

import { useEffect, useMemo, useRef, useState } from "react";
import type { SortingState } from "@tanstack/table-core";
import { LoaderCircle, RotateCcw, UserRoundSearch } from "lucide-react";
import { DifficultyLegend } from "@/components/DifficultyLegend";
import { FilterBar, type FilterState } from "@/components/FilterBar";
import { FilterPanel } from "@/components/FilterPanel";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import {
  INITIAL_PLAYER_FILTERS,
  PlayerFiltersBar,
  matchesPlayerFilters,
  type PlayerFilters,
  type PlayerMultiFilters,
  type PlayerPosition,
} from "@/components/PlayerFiltersBar";
import { PlayerStatTable, type PlayerStatRow } from "@/components/PlayerStatTable";
import { VintageSelect } from "@/components/VintageSelect";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
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
import {
  actualGameweekLabel,
  actualGameweeksChronological,
  aggregatePlayerActuals,
  averageBpsPerAppearance,
  latestActualGameweeks,
  latestPlayerActualDetails,
} from "@/lib/playerActuals";
import { indexPlayerHorizons, playerHorizon } from "@/lib/playerHorizons";
import { fetchManagerTeamMembers, type ManagerTeamPreview } from "@/lib/planServer";
import { loadPlanServerToken } from "@/lib/planServerToken";
import { rawPlayerGameweekXp } from "@/lib/userDraft";
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
  fromIndex: number;
  toIndex: number;
}

interface ManagerSquadFilter {
  preview: ManagerTeamPreview;
  playerCodes: ReadonlySet<number>;
}

const PLAYERS_TABLE_INITIAL_SORTING: SortingState = [{ id: "gwFromXp", desc: true }];
const INITIAL_PLAYER_MULTI_FILTERS: PlayerMultiFilters = {
  playerCodes: [],
  positions: [],
  teamCodes: [],
};

function matchesPlayerMultiFilters(player: PlayerRecord, filters: PlayerMultiFilters): boolean {
  if (filters.playerCodes.length > 0 && !filters.playerCodes.includes(player.code)) return false;
  if (
    filters.positions.length > 0 &&
    !filters.positions.includes(player.position as PlayerPosition)
  )
    return false;
  if (filters.teamCodes.length > 0 && !filters.teamCodes.includes(player.team_code)) return false;
  return true;
}

function initialManagerId(): string {
  try {
    return window.localStorage.getItem("fpl-manager-id") ?? "";
  } catch {
    return "";
  }
}

function managerSquadForRun(
  preview: ManagerTeamPreview,
  runPlayers: readonly PlayerRecord[],
  runGwFrom: number,
): ManagerSquadFilter {
  if (preview.planning_gw !== runGwFrom) {
    throw new Error(
      `The fetched squad is for GW${preview.planning_gw}, but the selected forecast starts at GW${runGwFrom}. Select the current forecast vintage and fetch the squad again.`,
    );
  }
  const playersByCode = new Map(runPlayers.map((player) => [player.code, player]));
  const mismatched = preview.players.filter((managerPlayer) => {
    const forecastPlayer = playersByCode.get(managerPlayer.code);
    return (
      forecastPlayer == null ||
      forecastPlayer.position !== managerPlayer.position ||
      forecastPlayer.team_code !== managerPlayer.team_code ||
      forecastPlayer.now_cost !== managerPlayer.now_cost
    );
  });
  if (mismatched.length > 0) {
    throw new Error(
      "All 15 manager-squad players must match the selected forecast vintage. Select the current vintage and fetch the squad again.",
    );
  }
  return {
    preview,
    playerCodes: new Set(preview.players.map((player) => player.code)),
  };
}

function previousSeason(season: string): string | null {
  const matched = /^(\d{4})-(\d{2})$/.exec(season);
  if (matched == null) return null;
  const start = Number(matched[1]);
  return `${start - 1}-${String(start % 100).padStart(2, "0")}`;
}

function latestFiveActualRange(gameweekCount: number): ActualRange | null {
  if (gameweekCount === 0) return null;
  return {
    fromIndex: Math.max(0, gameweekCount - 5),
    toIndex: gameweekCount - 1,
  };
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
  const hostedStatic = import.meta.env.VITE_HOSTED_STATIC === "true";
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [colorSource, setColorSource] = useState<ColorSource>("opponent");
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [playerFilters, setPlayerFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);
  const [playerMultiFilters, setPlayerMultiFilters] = useState<PlayerMultiFilters>(
    INITIAL_PLAYER_MULTI_FILTERS,
  );
  const [actualRange, setActualRange] = useState<ActualRange | null>(null);
  const [managerId, setManagerId] = useState(initialManagerId);
  const [managerSquad, setManagerSquad] = useState<ManagerSquadFilter | null>(null);
  const [managerLoading, setManagerLoading] = useState(false);
  const [managerError, setManagerError] = useState<string | null>(null);
  const managerRequestRef = useRef(0);

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

  useEffect(
    () => () => {
      managerRequestRef.current += 1;
    },
    [],
  );

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

  const rollingActualSeasons = useMemo(() => {
    if (selectedRun == null) return [];
    const previous = previousSeason(selectedRun.season);
    return [selectedRun.season, ...(previous == null ? [] : [previous])];
  }, [selectedRun]);

  const rollingActualRecords = useMemo(() => {
    if (state.status !== "ready") return [];
    const codes = new Set(runPlayers.map((player) => player.code));
    const seasons = new Set(rollingActualSeasons);
    return state.playerActuals.filter(
      (record) => codes.has(record.code) && seasons.has(record.season),
    );
  }, [rollingActualSeasons, runPlayers, state]);
  const rollingActualsByCode = useMemo(() => {
    const recordsByCode = new Map<number, PlayerActualsRecord[]>();
    for (const record of rollingActualRecords) {
      const existing = recordsByCode.get(record.code);
      if (existing == null) recordsByCode.set(record.code, [record]);
      else existing.push(record);
    }
    return recordsByCode;
  }, [rollingActualRecords]);
  const actualGameweeks = useMemo(
    () => actualGameweeksChronological(rollingActualRecords, rollingActualSeasons),
    [rollingActualRecords, rollingActualSeasons],
  );
  const selectedActualGameweeks = useMemo(
    () =>
      actualRange == null ||
      actualRange.fromIndex < 0 ||
      actualRange.toIndex >= actualGameweeks.length ||
      actualRange.fromIndex > actualRange.toIndex
        ? []
        : actualGameweeks.slice(actualRange.fromIndex, actualRange.toIndex + 1),
    [actualGameweeks, actualRange],
  );
  const actualFrom = selectedActualGameweeks[0] ?? null;
  const actualTo = selectedActualGameweeks.at(-1) ?? null;

  const cumulativeOutcomesAvailable =
    filters != null &&
    selectedRun != null &&
    filters.venue === "all" &&
    filters.gwFrom === selectedRun.gw_from;

  const expandedActualGameweeks = useMemo(
    () => latestActualGameweeks(rollingActualRecords, rollingActualSeasons),
    [rollingActualRecords, rollingActualSeasons],
  );

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
    setActualRange(latestFiveActualRange(actualGameweeks.length));
  }, [actualGameweeks, selectedRun?.run_id]);

  const rows: PlayerStatRow[] = useMemo(() => {
    if (!filters) return [];
    const wanted = runPlayers.filter(
      (player) =>
        (managerSquad == null || managerSquad.playerCodes.has(player.code)) &&
        matchesPlayerFilters(player, playerFilters) &&
        matchesPlayerMultiFilters(player, playerMultiFilters),
    );
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
      const gwFromHorizon = cumulativeOutcomesAvailable
        ? playerHorizon(
            horizonIndex,
            player.run_id,
            player.season,
            player.code,
            filters.gwFrom,
          )
        : null;
      const filteredGwFromXp =
        player.fixtures.length === 0
          ? null
          : rawPlayerGameweekXp({ ...player, fixtures: filtered }, filters.gwFrom);
      const selectedActuals = latestPlayerActualDetails(
        rollingActualsByCode.get(player.code) ?? [],
        selectedActualGameweeks,
      );
      return {
        // Suppress the shared detail row's retired prior-season form anchor on this page.
        player: { ...player, form: null },
        filtered,
        gwFromXp: gwFromHorizon?.xp ?? filteredGwFromXp,
        bpsPerAppearance:
          actualRange == null
            ? null
            : averageBpsPerAppearance(selectedActuals),
        actualDetails: latestPlayerActualDetails(
          rollingActualsByCode.get(player.code) ?? [],
          expandedActualGameweeks,
        ),
        totalXp: horizon?.xp ?? (xpValues.length ? xpValues.reduce((a, b) => a + b, 0) : null),
        horizon,
        form:
          actualRange == null
            ? null
            : aggregatePlayerActuals(selectedActuals),
      };
    });
  }, [
    runPlayers,
    filters,
    playerFilters,
    playerMultiFilters,
    cumulativeOutcomesAvailable,
    horizonIndex,
    actualRange,
    selectedActualGameweeks,
    expandedActualGameweeks,
    rollingActualsByCode,
    managerSquad,
  ]);

  const managerIdValid =
    /^\d{1,10}$/.test(managerId.trim()) && Number(managerId.trim()) > 0;

  const clearManagerSquad = () => {
    managerRequestRef.current += 1;
    setManagerSquad(null);
    setManagerLoading(false);
    setManagerError(null);
  };

  const importManagerSquad = async () => {
    if (hostedStatic) {
      setManagerError("Manager-squad filtering is available only with the trusted local Plan Server.");
      return;
    }
    if (!managerIdValid || state.status !== "ready" || selectedRun == null) {
      setManagerError("Enter a positive FPL manager ID.");
      return;
    }
    const requestId = ++managerRequestRef.current;
    setManagerLoading(true);
    setManagerError(null);
    try {
      const preview = await fetchManagerTeamMembers(
        managerId.trim(),
        loadPlanServerToken(),
      );
      const nextSquad = managerSquadForRun(
        preview,
        runPlayers,
        selectedRun.gw_from,
      );
      if (requestId !== managerRequestRef.current) return;
      setManagerSquad(nextSquad);
      try {
        window.localStorage.setItem("fpl-manager-id", String(preview.manager_id));
      } catch {
        // The verified squad remains active in component state when storage is unavailable.
      }
    } catch (error: unknown) {
      if (requestId !== managerRequestRef.current) return;
      const message = error instanceof Error ? error.message : String(error);
      setManagerError(
        managerSquad
          ? `${message} The verified My squad filter was kept unchanged.`
          : `${message} The current table scope was kept unchanged.`,
      );
    } finally {
      if (requestId === managerRequestRef.current) setManagerLoading(false);
    }
  };

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
  const changeVintage = (nextRunId: string) => {
    if (nextRunId === activeRunId) return;
    const nextPlayers = state.players.filter((player) => player.run_id === nextRunId);
    const nextPlayerCodes = new Set(nextPlayers.map((player) => player.code));
    const nextTeamCodes = new Set(nextPlayers.map((player) => player.team_code));
    setPlayerMultiFilters((current) => ({
      playerCodes: current.playerCodes.filter((code) => nextPlayerCodes.has(code)),
      positions: current.positions,
      teamCodes: current.teamCodes.filter((code) => nextTeamCodes.has(code)),
    }));
    const hadManagerScope = managerSquad != null;
    const cancelledManagerFetch = managerLoading;
    managerRequestRef.current += 1;
    setManagerLoading(false);
    setManagerSquad(null);
    setManagerError(
      hadManagerScope || cancelledManagerFetch
        ? "The My squad filter was cleared because the forecast vintage changed. Fetch the squad again to verify all 15 players."
        : null,
    );
    setRunId(nextRunId);
  };
  const clearFilters = () => {
    setFilters({
      view: "overall",
      venue: "all",
      gwFrom: selectedRun?.gw_from ?? state.gwFrom,
      gwTo: selectedRun?.gw_to ?? state.gwTo,
    });
    setPlayerFilters({ ...INITIAL_PLAYER_FILTERS });
    setPlayerMultiFilters({ ...INITIAL_PLAYER_MULTI_FILTERS });
    clearManagerSquad();
    setActualRange(latestFiveActualRange(actualGameweeks.length));
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
      actualFrom == null || actualTo == null
        ? "No finalized player actuals are published for the current/prior-season scope."
        : `${actualRows.length} visible players have finalized observations from ${actualGameweekLabel(actualFrom)} through ${actualGameweekLabel(actualTo)}.`,
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
    "Actual endpoints use exact finalized season/GW keys from the forecast season and its immediate predecessor.",
    ...(managerSquad
      ? [
          "My squad membership comes from a private local manager capture and only filters already-published player rows; it does not change any statistic.",
        ]
      : []),
  ];
  const multiSelectInsightUnavailableReason =
    playerMultiFilters.playerCodes.length > 0
      ? "AI explanation is unavailable while specific player names are selected because that scope is not part of the typed public insight contract. Deterministic facts remain available."
      : playerMultiFilters.positions.length > 1 || playerMultiFilters.teamCodes.length > 1
        ? "AI explanation is unavailable while multiple positions or teams are selected because the renderer accepts only one of each. Deterministic facts remain available."
        : undefined;

  return (
    <div className="flex flex-col gap-3 p-4 lg:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Players</h1>
        <div className="flex flex-wrap items-center gap-3">
          <VintageSelect
            options={vintageOptions(state.manifestRuns, state.plans)}
            value={activeRunId}
            onChange={changeVintage}
          />
          <p className="text-xs text-muted-foreground">
            {runPlayers.length} players · as of{" "}
            {activeRun?.as_of?.replace("T", " ").slice(0, 16)} UTC · forecast season{" "}
            {activeRun?.season}
          </p>
        </div>
      </div>

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
            actual_season_from: actualFrom?.season,
            actual_gw_from: actualFrom?.gw,
            actual_season_to: actualTo?.season,
            actual_gw_to: actualTo?.gw,
            position: playerPositionScope(playerMultiFilters.positions[0] ?? "all"),
            team_code: playerMultiFilters.teamCodes[0],
            view: filters?.view === "defense" ? "defence" : filters?.view,
            venue: filters?.venue,
            min_price_tenths: minPriceTenthsScope(playerFilters.minPrice),
            max_price_tenths: maxPriceTenthsScope(playerFilters.maxPrice),
            min_avg_minutes_l5: minAverageMinutesScope(playerFilters.minMinutes),
            availability: playerFilters.availability,
          }),
          unavailableReason: managerSquad
            ? "AI explanation is unavailable while the private My squad filter is active. Deterministic facts remain available."
            : multiSelectInsightUnavailableReason,
          localScopeKey: JSON.stringify({
            runId: activeRunId,
            filters,
            playerFilters,
            playerMultiFilters,
            actualRange,
            colorSource,
            managerScope: managerSquad ? "private_manager_squad" : "all_players",
          }),
        }}
      />

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
          <section
            className="rounded-lg border bg-background/50 p-3"
            aria-labelledby="players-squad-filter-heading"
            aria-busy={managerLoading}
          >
            <div className="flex flex-wrap items-end gap-2">
              <div className="mr-auto min-w-56 max-w-md">
                <h2 id="players-squad-filter-heading" className="text-sm font-medium">
                  My squad
                </h2>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Filter this table to a verified public FPL squad. Published forecasts and
                  actual stats are unchanged.
                </p>
              </div>
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  void importManagerSquad();
                }}
              >
                <div className="w-44">
                  <label htmlFor="players-manager-id" className="text-xs font-medium">
                    FPL manager ID
                  </label>
                  <Input
                    id="players-manager-id"
                    className="mt-1"
                    inputMode="numeric"
                    autoComplete="off"
                    value={managerId}
                    disabled={hostedStatic || managerLoading}
                    aria-invalid={managerId.length > 0 && !managerIdValid}
                    aria-describedby="players-manager-id-hint"
                    placeholder="e.g. 123456"
                    onChange={(event) => {
                      setManagerId(event.target.value);
                      setManagerError(null);
                    }}
                  />
                </div>
                <Button
                  type="submit"
                  size="sm"
                  disabled={hostedStatic || !managerIdValid || managerLoading}
                >
                  {managerLoading ? (
                    <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
                  ) : (
                    <UserRoundSearch className="size-3.5" aria-hidden />
                  )}
                  {managerLoading ? "Fetching squad…" : "Show my squad"}
                </Button>
                {managerSquad && (
                  <Button type="button" variant="outline" size="sm" onClick={clearManagerSquad}>
                    Show all players
                  </Button>
                )}
              </form>
            </div>
            <p id="players-manager-id-hint" className="mt-2 text-[11px] text-muted-foreground">
              {hostedStatic
                ? "Manager-squad filtering is local-only and requires the trusted Plan Server."
                : managerId.trim() && !managerIdValid
                  ? "Use 1–10 digits and a value greater than zero."
                  : "Use the number in fantasy.premierleague.com/entry/{id}."}
            </p>
            {managerSquad && (
              <p role="status" className="mt-2 text-xs text-emerald-700 dark:text-emerald-300">
                Verified 15/15 players for{" "}
                {managerSquad.preview.entry_name || `manager #${managerSquad.preview.manager_id}`}.
                {` ${rows.length} match the other visible filters.`}
              </p>
            )}
            {managerError && (
              <p role="alert" className="mt-2 text-xs text-destructive">
                {managerError}
              </p>
            )}
          </section>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <PlayerFiltersBar
              filters={playerFilters}
              onChange={setPlayerFilters}
              teams={teams}
              showFormWindow={false}
              multiSelect={{
                players: runPlayers,
                filters: playerMultiFilters,
                onChange: setPlayerMultiFilters,
              }}
            />
            {actualGameweeks.length > 0 && actualRange != null && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span>Actual from</span>
                <Select
                  value={String(actualRange.fromIndex)}
                  onValueChange={(value) =>
                    setActualRange((current) =>
                      current == null
                        ? current
                        : {
                            fromIndex: Number(value),
                            toIndex: Math.max(Number(value), current.toIndex),
                          },
                    )
                  }
                >
                  <SelectTrigger size="sm" className="w-36" aria-label="Actual from">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {actualGameweeks.map((gameweek, index) => (
                      <SelectItem
                        key={`${gameweek.season}-${gameweek.gw}`}
                        value={String(index)}
                      >
                        {actualGameweekLabel(gameweek)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span>Actual to</span>
                <Select
                  value={String(actualRange.toIndex)}
                  onValueChange={(value) =>
                    setActualRange((current) =>
                      current == null
                        ? current
                        : {
                            fromIndex: Math.min(current.fromIndex, Number(value)),
                            toIndex: Number(value),
                          },
                    )
                  }
                >
                  <SelectTrigger size="sm" className="w-36" aria-label="Actual to">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {actualGameweeks.map((gameweek, index) => (
                      <SelectItem
                        key={`${gameweek.season}-${gameweek.gw}`}
                        value={String(index)}
                      >
                        {actualGameweekLabel(gameweek)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Forecast GWs filter upcoming fixtures and xP only. Actual from/to independently
            aggregate every exact published season/GW key between the endpoints. Player, position,
            and team selections use OR within each box and AND across boxes; an empty box means all.
            Reset defaults to the latest five finalized keys across this season and its immediate predecessor. My
            squad intersects with every other player filter. Min avg min (L5) remains its separate
            published anchor. Expanded rows also remain an independent fixed rolling latest-five
            view and do not follow these Actual endpoints.
          </p>
          {actualGameweeks.length === 0 && (
            <p role="status" className="text-xs text-amber-700 dark:text-amber-300">
              No finalized player actuals are published for the forecast season or its immediate
              predecessor. Observed columns stay unavailable.
            </p>
          )}
        </div>
      </FilterPanel>

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
            actualFrom == null || actualTo == null
              ? "Actual unavailable"
              : `Actual ${actualGameweekLabel(actualFrom)}–${actualGameweekLabel(actualTo)}`
          }
          formTitle={
            actualFrom == null || actualTo == null
              ? "No finalized current/prior-season actuals published"
              : `Finalized actuals from ${actualGameweekLabel(actualFrom)} through ${actualGameweekLabel(actualTo)}`
          }
          formScopeLabel={
            actualFrom == null || actualTo == null
              ? "No finalized current/prior-season GWs"
              : actualFrom.season === actualTo.season && actualFrom.gw === actualTo.gw
                ? actualGameweekLabel(actualFrom)
                : `${actualGameweekLabel(actualFrom)} → ${actualGameweekLabel(actualTo)}`
          }
          formColumnProfile="players"
          showGwFromXp
          expandedRowMode="historical"
          initialSorting={PLAYERS_TABLE_INITIAL_SORTING}
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
