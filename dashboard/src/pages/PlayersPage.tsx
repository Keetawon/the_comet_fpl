// Players page (P1.7c): the player-form pivot. One row per (run, player) merging backward
// form (labelled with its anchor season -- LAST season at GW1) with the vintage's per-fixture
// xP. Chips headline the xP and are coloured by the active view's CLUB metric; the expanded
// row exposes every primitive behind the colour (club lambdas, ease, clean sheets) beside the
// player's own probabilities.

import { useEffect, useMemo, useState } from "react";
import { flexRender } from "@tanstack/react-table";
import {
  type LegacyColumnDef,
  getCoreRowModel,
  getExpandedRowModel,
  getSortedRowModel,
  useLegacyTable,
} from "@tanstack/react-table/legacy";
import type { ExpandedState, SortingState } from "@tanstack/table-core";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { DifficultyLegend } from "@/components/DifficultyLegend";
import { FilterBar, type FilterState } from "@/components/FilterBar";
import { FixtureTicker } from "@/components/FixtureTicker";
import { loadPlayers } from "@/data/load";
import type {
  PlayerFixture,
  PlayerFormWindow,
  PlayerRecord,
  WindowLabel,
} from "@/data/types";
import { WINDOW_LABELS } from "@/data/types";
import type { ColorSource } from "@/lib/difficulty";
import { playerChipBucket, playerChipMetric } from "@/lib/playerChips";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      players: PlayerRecord[];
      gwFrom: number;
      gwTo: number;
      easeVersion: string;
    };

/** Player-specific filters on top of the shared FilterBar (view/venue/gameweek range). */
interface PlayerFilters {
  position: string; // "all" | GK | DEF | MID | FWD
  teamCode: string; // "all" | String(team_code)
  minPrice: string; // £m, "" = unbounded
  maxPrice: string; // £m, "" = unbounded
  minMinutes: string; // avg minutes last 5, "" = unbounded
  availability: "all" | "available" | "flagged";
  formWindow: WindowLabel;
}

const INITIAL_PLAYER_FILTERS: PlayerFilters = {
  position: "all",
  teamCode: "all",
  minPrice: "",
  maxPrice: "",
  minMinutes: "",
  availability: "all",
  formWindow: "last_5",
};

const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const price = (value: number | null) => (value == null ? "–" : `£${(value / 10).toFixed(1)}m`);

const AVAILABILITY_LABEL: Record<string, string> = {
  a: "available",
  d: "doubtful",
  i: "injured",
  s: "suspended",
  u: "unavailable",
  n: "not available",
  x: "not announced",
};

function FormCell({ form, window }: { form: PlayerRecord["form"]; window: WindowLabel }) {
  if (!form) return <span className="text-muted-foreground">No form data</span>;
  const w: PlayerFormWindow | null = form.windows[window];
  if (!w) return <span className="text-muted-foreground">No form data</span>;
  return (
    <div className="text-xs leading-snug">
      <div className="text-[10px] text-muted-foreground">
        Form {form.season} · GW{form.as_at_gw}
      </div>
      <div className="tabular-nums">
        apps {fmt(w.appearances, 0)}/{fmt(w.rostered_fixtures, 0)} · min {fmt(w.minutes, 0)}
      </div>
      <div className="tabular-nums text-muted-foreground">
        xG {fmt(w.expected_goals, 2)} · xA {fmt(w.expected_assists, 2)} · pts{" "}
        {fmt(w.points_under_rules_2026_27, 0)}
      </div>
    </div>
  );
}

function AvailabilityCell({ player }: { player: PlayerRecord }) {
  const status = player.availability_status;
  if (status == null) return <span className="text-muted-foreground">–</span>;
  const label = AVAILABILITY_LABEL[status] ?? status;
  return (
    <div className="text-xs leading-snug">
      <div className={status === "a" ? "" : "text-amber-600 dark:text-amber-400"}>{label}</div>
      {player.chance_of_playing != null && (
        <div className="text-muted-foreground tabular-nums">
          {Math.round(player.chance_of_playing)}% next GW
        </div>
      )}
    </div>
  );
}

interface PlayerRow {
  player: PlayerRecord;
  filtered: PlayerFixture[];
  totalXp: number | null;
}

/** One per-fixture detail cell: value text plus whether the active view emphasises it. */
interface DetailColumn {
  key: keyof PlayerFixture | "venue";
  label: string;
  value: (fixture: PlayerFixture) => string;
  muted: boolean;
}

/** The expanded per-fixture table: the view's own stats lead, the others stay visible but muted. */
function detailColumns(view: FilterState["view"]): DetailColumn[] {
  const pct = (v: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const clubCs = (f: PlayerFixture) => pct(f.team_probability_clean_sheet);
  const base: DetailColumn[] = [
    { key: "gw", label: "GW", value: (f) => String(f.gw), muted: false },
    { key: "opponent_short_name", label: "Opponent", value: (f) => f.opponent_short_name, muted: false },
    {
      key: "venue",
      label: "Venue",
      value: (f) => (f.was_home == null ? "–" : f.was_home ? "H" : "A"),
      muted: false,
    },
    {
      key: "expected_points",
      label: "xP",
      value: (f) => fmt(f.expected_points, 2),
      muted: false,
    },
  ];
  const attack: DetailColumn[] = [
    { key: "expected_goals", label: "xG", value: (f) => fmt(f.expected_goals, 2), muted: false },
    { key: "expected_assists", label: "xA", value: (f) => fmt(f.expected_assists, 2), muted: false },
    { key: "team_lambda_for", label: "Club λ for", value: (f) => fmt(f.team_lambda_for, 2), muted: false },
    { key: "team_attack_ease_index", label: "Atk ease", value: (f) => fmt(f.team_attack_ease_index, 0), muted: false },
    { key: "probability_appears", label: "P(plays)", value: (f) => pct(f.probability_appears), muted: true },
    { key: "probability_sixty_minutes", label: "P(60+)", value: (f) => pct(f.probability_sixty_minutes), muted: true },
    { key: "probability_clean_sheet", label: "CS (own)", value: (f) => pct(f.probability_clean_sheet), muted: true },
    { key: "team_probability_clean_sheet", label: "Club CS", value: clubCs, muted: true },
    { key: "team_lambda_against", label: "Club λ against", value: (f) => fmt(f.team_lambda_against, 2), muted: true },
    { key: "team_defence_ease_index", label: "Def ease", value: (f) => fmt(f.team_defence_ease_index, 0), muted: true },
  ];
  const defense: DetailColumn[] = [
    { key: "probability_appears", label: "P(plays)", value: (f) => pct(f.probability_appears), muted: false },
    { key: "probability_sixty_minutes", label: "P(60+)", value: (f) => pct(f.probability_sixty_minutes), muted: false },
    { key: "probability_clean_sheet", label: "CS (own)", value: (f) => pct(f.probability_clean_sheet), muted: false },
    { key: "team_lambda_against", label: "Club λ against", value: (f) => fmt(f.team_lambda_against, 2), muted: false },
    { key: "team_probability_clean_sheet", label: "Club CS", value: clubCs, muted: false },
    { key: "team_defence_ease_index", label: "Def ease", value: (f) => fmt(f.team_defence_ease_index, 0), muted: false },
    { key: "expected_goals", label: "xG", value: (f) => fmt(f.expected_goals, 2), muted: true },
    { key: "expected_assists", label: "xA", value: (f) => fmt(f.expected_assists, 2), muted: true },
    { key: "team_lambda_for", label: "Club λ for", value: (f) => fmt(f.team_lambda_for, 2), muted: true },
    { key: "team_attack_ease_index", label: "Atk ease", value: (f) => fmt(f.team_attack_ease_index, 0), muted: true },
  ];
  const tail: DetailColumn[] = [
    { key: "team_overall_ease_index", label: "Ovr ease", value: (f) => fmt(f.team_overall_ease_index, 0), muted: false },
    { key: "team_official_fdr", label: "FDR", value: (f) => fmt(f.team_official_fdr, 0), muted: false },
  ];
  return [...base, ...(view === "attack" ? attack : defense), ...tail];
}

export function PlayersPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [colorSource, setColorSource] = useState<ColorSource>("ease");
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [playerFilters, setPlayerFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);
  const [sorting, setSorting] = useState<SortingState>([{ id: "totalXp", desc: true }]);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  useEffect(() => {
    let cancelled = false;
    loadPlayers()
      .then((data) => {
        if (cancelled) return;
        const gws = data.players.flatMap((p) => p.fixtures.map((f) => f.gw));
        const first = data.players[0];
        const run = data.manifest?.runs.find(
          (r) => r.run_id === first?.run_id && r.season === first?.season,
        );
        const gwFrom = run?.gw_from ?? Math.min(...gws);
        const gwTo = run?.gw_to ?? Math.max(...gws);
        setState({
          status: "ready",
          players: data.players,
          gwFrom,
          gwTo,
          easeVersion: data.manifest?.ease_index_formula_version ?? "unknown",
        });
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

  const teams = useMemo(() => {
    if (state.status !== "ready") return [];
    const seen = new Map<number, string>();
    for (const p of state.players) if (!seen.has(p.team_code)) seen.set(p.team_code, p.team_short_name);
    return [...seen.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [state]);

  const rows: PlayerRow[] = useMemo(() => {
    if (state.status !== "ready" || !filters) return [];
    const minPrice = playerFilters.minPrice === "" ? null : Number(playerFilters.minPrice) * 10;
    const maxPrice = playerFilters.maxPrice === "" ? null : Number(playerFilters.maxPrice) * 10;
    const minMinutes = playerFilters.minMinutes === "" ? null : Number(playerFilters.minMinutes);
    const wanted = state.players.filter((p) => {
      if (playerFilters.position !== "all" && p.position !== playerFilters.position) return false;
      if (playerFilters.teamCode !== "all" && String(p.team_code) !== playerFilters.teamCode)
        return false;
      // Unmeasured price/minutes never satisfy a bound: null is not 0.
      if (minPrice != null && !(p.now_cost != null && p.now_cost >= minPrice)) return false;
      if (maxPrice != null && !(p.now_cost != null && p.now_cost <= maxPrice)) return false;
      if (minMinutes != null && !(p.avg_minutes_last_5 != null && p.avg_minutes_last_5 >= minMinutes))
        return false;
      if (playerFilters.availability === "available" && p.availability_status !== "a") return false;
      if (
        playerFilters.availability === "flagged" &&
        !(p.availability_status != null && p.availability_status !== "a")
      )
        return false;
      return true;
    });
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
      };
    });
  }, [state, filters, playerFilters]);

  const columns = useMemo<LegacyColumnDef<PlayerRow>[]>(
    () => [
      {
        id: "expander",
        header: "",
        cell: ({ row }) => (
          <Button
            variant="ghost"
            size="icon"
            className="size-6"
            aria-label={row.getIsExpanded() ? "Collapse fixtures" : "Expand fixtures"}
            onClick={row.getToggleExpandedHandler()}
          >
            {row.getIsExpanded() ? (
              <ChevronDown className="size-4" />
            ) : (
              <ChevronRight className="size-4" />
            )}
          </Button>
        ),
      },
      {
        accessorKey: "player.web_name",
        header: "Player",
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.player.web_name}</div>
            <div className="text-xs text-muted-foreground">{row.original.player.team_short_name}</div>
          </div>
        ),
      },
      {
        accessorKey: "player.position",
        header: "Pos",
      },
      {
        accessorKey: "player.now_cost",
        header: "Price",
        cell: ({ row }) => (
          <span className="tabular-nums">{price(row.original.player.now_cost)}</span>
        ),
      },
      {
        accessorKey: "player.selected_by_percent",
        header: "TS%",
        cell: ({ row }) => {
          const value = row.original.player.selected_by_percent;
          return <span className="tabular-nums">{value == null ? "–" : value.toFixed(1)}</span>;
        },
      },
      {
        id: "availability",
        header: "Availability",
        enableSorting: false,
        cell: ({ row }) => <AvailabilityCell player={row.original.player} />,
      },
      {
        id: "form",
        header: `Form (${playerFilters.formWindow.replace("last_", "last ").replace("_", " ")})`,
        enableSorting: false,
        cell: ({ row }) => (
          <FormCell form={row.original.player.form} window={playerFilters.formWindow} />
        ),
      },
      {
        accessorKey: "player.avg_minutes_last_5",
        header: "Avg min L5",
        cell: ({ row }) => (
          <span className="tabular-nums">{fmt(row.original.player.avg_minutes_last_5, 0)}</span>
        ),
      },
      {
        id: "totalXp",
        header: "xP",
        cell: ({ row }) => (
          <span className="tabular-nums font-medium">
            {row.original.totalXp == null ? "–" : row.original.totalXp.toFixed(1)}
          </span>
        ),
      },
      {
        id: "fixtures",
        header: "Fixtures",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.filtered.length ? (
            <FixtureTicker
              fixtures={row.original.filtered}
              minGw={filters?.gwFrom ?? 1}
              maxGw={filters?.gwTo ?? 1}
              metricOf={(f) => playerChipMetric(f, filters?.view ?? "overall", colorSource)}
              bucketOf={(f) => playerChipBucket(f, filters?.view ?? "overall", colorSource)}
            />
          ) : (
            <span className="text-xs text-muted-foreground">No fixtures in range</span>
          ),
      },
    ],
    [filters, colorSource, playerFilters.formWindow],
  );

  const table = useLegacyTable({
    data: rows,
    columns,
    state: { sorting, expanded },
    onSortingChange: setSorting,
    onExpandedChange: setExpanded,
    getRowCanExpand: () => true,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getExpandedRowModel: getExpandedRowModel(),
  });

  if (state.status === "loading") return <p className="p-6 text-muted-foreground">Loading read models…</p>;
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Players</h1>
        <p className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }

  const runId = state.players[0]?.run_id;
  const asOf = state.players[0]?.as_of;
  const setPf = (patch: Partial<PlayerFilters>) => setPlayerFilters((pf) => ({ ...pf, ...patch }));

  return (
    <div className="flex flex-col gap-3 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Players</h1>
        <p className="text-xs text-muted-foreground">
          run {runId?.slice(0, 12)}… · as of {asOf?.replace("T", " ").slice(0, 16)} UTC ·
          horizon GW{filters?.gwFrom ?? state.gwFrom}-GW{filters?.gwTo ?? state.gwTo} ·{" "}
          {rows.length} of {state.players.length} players
        </p>
      </div>
      {filters && <FilterBar filters={filters} onChange={setFilters} minGw={state.gwFrom} maxGw={state.gwTo} />}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>Position</span>
          <Select
            value={playerFilters.position}
            onValueChange={(value) => setPf({ position: value })}
          >
            <SelectTrigger size="sm" className="w-24" aria-label="Position filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {POSITIONS.map((p) => (
                <SelectItem key={p} value={p}>
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-2">
          <span>Team</span>
          <Select value={playerFilters.teamCode} onValueChange={(value) => setPf({ teamCode: value })}>
            <SelectTrigger size="sm" className="w-28" aria-label="Team filter">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All</SelectItem>
              {teams.map(([code, short]) => (
                <SelectItem key={code} value={String(code)}>
                  {short}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="flex items-center gap-1">
          <span>Price £m</span>
          <Input
            type="number"
            inputMode="decimal"
            min={0}
            step={0.5}
            placeholder="min"
            aria-label="Minimum price in millions"
            className="h-8 w-20"
            value={playerFilters.minPrice}
            onChange={(e) => setPf({ minPrice: e.target.value })}
          />
          <span>–</span>
          <Input
            type="number"
            inputMode="decimal"
            min={0}
            step={0.5}
            placeholder="max"
            aria-label="Maximum price in millions"
            className="h-8 w-20"
            value={playerFilters.maxPrice}
            onChange={(e) => setPf({ maxPrice: e.target.value })}
          />
        </div>
        <div className="flex items-center gap-2">
          <span>Min avg min (L5)</span>
          <Input
            type="number"
            inputMode="numeric"
            min={0}
            step={10}
            placeholder="any"
            aria-label="Minimum average minutes over the last 5"
            className="h-8 w-20"
            value={playerFilters.minMinutes}
            onChange={(e) => setPf({ minMinutes: e.target.value })}
          />
        </div>
        <ToggleGroup
          type="single"
          value={playerFilters.availability}
          onValueChange={(value) => {
            if (value) setPf({ availability: value as PlayerFilters["availability"] });
          }}
          variant="outline"
          aria-label="Availability filter"
        >
          <ToggleGroupItem value="all">All</ToggleGroupItem>
          <ToggleGroupItem value="available">Available</ToggleGroupItem>
          <ToggleGroupItem value="flagged">Flagged</ToggleGroupItem>
        </ToggleGroup>
        <div className="flex items-center gap-2">
          <span>Form window</span>
          <Select
            value={playerFilters.formWindow}
            onValueChange={(value) => setPf({ formWindow: value as WindowLabel })}
          >
            <SelectTrigger size="sm" className="w-36" aria-label="Form window">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WINDOW_LABELS.map((label) => (
                <SelectItem key={label} value={label}>
                  {label === "season_to_date" ? "Season to date" : label.replace("last_", "Last ")}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <DifficultyLegend
          colorSource={colorSource}
          onColorSourceChange={setColorSource}
          easeIndexFormulaVersion={state.easeVersion}
          cleanSheetAnchor={null}
          defenceScaleNote="Defence view colours on the club's defence ease index (higher = the club concedes less)."
        />
        <Separator orientation="vertical" className="h-6" />
        <span className="text-xs text-muted-foreground">
          Chip headline is the fixture xP; the colour follows the view's club metric.
        </span>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <TableHead
                    key={header.id}
                    className={header.column.getCanSort() ? "cursor-pointer select-none" : ""}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {{ asc: " ↑", desc: " ↓" }[header.column.getIsSorted() as string] ?? ""}
                  </TableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.flatMap((row) => {
              const cells = (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              );
              if (!row.getIsExpanded()) return [cells];
              const player = row.original.player;
              const view = filters?.view ?? "overall";
              const columns2 = detailColumns(view);
              return [
                cells,
                <TableRow key={`${row.id}-detail`}>
                  <TableCell colSpan={row.getVisibleCells().length} className="bg-muted/40 p-3">
                    <div className="max-w-4xl space-y-1">
                      <p className="text-xs font-medium">
                        {player.web_name} ({player.position}, {player.team_short_name}) —
                        per-fixture detail
                        {player.form
                          ? ` · form anchored ${player.form.season} GW${player.form.as_at_gw}`
                          : " · no observed form"}
                      </p>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            {columns2.map((c) => (
                              <TableHead key={c.key} className={c.muted ? "opacity-50" : ""}>
                                {c.label}
                              </TableHead>
                            ))}
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {row.original.filtered.map((f) => (
                            <TableRow key={f.fixture}>
                              {columns2.map((c) => (
                                <TableCell
                                  key={c.key}
                                  className={`tabular-nums ${c.muted ? "opacity-50" : ""}`}
                                >
                                  {c.value(f)}
                                </TableCell>
                              ))}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </div>
                  </TableCell>
                </TableRow>,
              ];
            })}
          </TableBody>
        </Table>
      </div>
      <p className="text-xs text-muted-foreground">
        Availability and chance-of-playing are reported overlays valid for the next gameweek
        only; they label rows here and never fold into xP. Player-fixture probabilities are
        null until the ledger persists them — never 0. Club λ/ease/CS are the primitives behind
        the chip colour.
      </p>
    </div>
  );
}
