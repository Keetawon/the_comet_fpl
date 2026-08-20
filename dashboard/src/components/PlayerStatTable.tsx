// The shared player pivot table: identity (photo + badge), price/ownership/availability,
// the selected form window's stats as sortable columns, the range's summed xP, and one
// column per upcoming gameweek (the pivot the owner asked for). Rows are compact and
// paginated; expanding a row exposes the per-fixture primitives behind the chip colour,
// ordered by kickoff time -- the detail ignores the main table's sort on purpose.
//
// Used by the Players page (whole roster) and the Next GW page (squad rows beside plan
// EV columns via extraColumns).

import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { flexRender } from "@tanstack/react-table";
import {
  type LegacyColumnDef,
  getCoreRowModel,
  getExpandedRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useLegacyTable,
} from "@tanstack/react-table/legacy";
import type { ExpandedState, SortingState } from "@tanstack/table-core";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { FixtureChip } from "@/components/FixtureTicker";
import { PlayerPhoto, TeamBadge } from "@/components/Avatars";
import { DecisionTableFullscreen } from "@/components/DecisionTableFullscreen";
import { NULL_BUCKET_CLASS } from "@/lib/difficulty";
import type { ColorSource, ViewMode } from "@/lib/difficulty";
import { playerChipBucket, playerChipMetric } from "@/lib/playerChips";
import { availabilityLabel } from "@/lib/availability";
import type { PlayerFixture, PlayerFormWindow, PlayerRecord } from "@/data/types";

export interface PlayerStatRow {
  player: PlayerRecord;
  /** Venue/GW-filtered fixtures, sorted by (gw, kickoff). */
  filtered: PlayerFixture[];
  totalXp: number | null;
  form: PlayerFormWindow | null;
}

/** One plan-bound summary row rendered after the paginated player rows. */
export interface PlayerStatSummaryRow {
  id: string;
  label: ReactNode;
  /** Values are keyed by the table column id (for example `totalXp` or `gw-1`). */
  values: Readonly<Record<string, ReactNode>>;
  className?: string;
}

export interface PlayerStatTableProps {
  fullscreenLabel: string;
  rows: PlayerStatRow[];
  view: ViewMode;
  colorSource: ColorSource;
  gwFrom: number;
  gwTo: number;
  /** Opponent-strength index for a club code (display-time derivation, may be null). */
  opponentIndexOf: (teamCode: number) => number | null;
  /** e.g. "Last 5" -- names the window the App/G/... columns measure. */
  formHeading: string;
  /** Tooltip for the form columns: anchor season/gameweek of the window. */
  formTitle?: string;
  /** Players uses view-aware form columns; other consumers retain the compact legacy profile. */
  formColumnProfile?: "legacy" | "players";
  initialSorting?: SortingState;
  pageSize?: number;
  /** Columns inserted just BEFORE the per-gameweek fixture columns (fixtures stay last). */
  beforeFixtureColumns?: LegacyColumnDef<PlayerStatRow>[];
  extraColumns?: LegacyColumnDef<PlayerStatRow>[];
  /** Badges after the player name (C/V/bench/in-squad on the Next GW page). */
  nameSuffix?: (player: PlayerRecord) => ReactNode;
  /** Per-row conditional formatting (e.g. captain/vice/bench row colours). */
  rowClassName?: (row: PlayerStatRow) => string | undefined;
  /** Plan-bound totals. These do not derive from the visible/filterable table rows. */
  summaryRows?: PlayerStatSummaryRow[];
  summaryNote?: ReactNode;
  emptyMessage?: string;
}

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const price = (value: number | null) => (value == null ? "–" : `£${(value / 10).toFixed(1)}m`);

const HEAD_CLASS = "sticky top-0 z-10 h-8 bg-background px-2 text-xs whitespace-nowrap";
const CELL_CLASS = "px-2 py-1 text-xs whitespace-nowrap";
const DEFAULT_SORTING: SortingState = [{ id: "totalXp", desc: true }];

const ATTACK_FORM_COLUMN_IDS = new Set([
  "form-goals_scored",
  "form-assists",
  "form-expected_goals",
  "form-expected_assists",
  "form-expected_goals_per_90",
  "form-expected_assists_per_90",
]);
const DEFENSE_FORM_COLUMN_IDS = new Set([
  "form-clean_sheets",
  "form-goals_conceded",
  "form-saves",
  "form-defensive_contribution",
  "form-expected_goals_conceded",
]);
const VIEW_SPECIFIC_FORM_COLUMN_IDS = new Set([
  ...ATTACK_FORM_COLUMN_IDS,
  ...DEFENSE_FORM_COLUMN_IDS,
]);

/** One per-fixture detail cell: value text plus whether the active view emphasises it. */
interface DetailColumn {
  key: string;
  label: string;
  value: (fixture: PlayerFixture) => string;
  muted: boolean;
}

/** The expanded per-fixture table: selected-view primitives lead; Overall treats both honestly. */
function detailColumns(view: ViewMode): DetailColumn[] {
  const pct = (v: number | null) => (v == null ? "–" : `${Math.round(v * 100)}%`);
  const clubCs = (f: PlayerFixture) => pct(f.team_probability_clean_sheet);
  const base: DetailColumn[] = [
    { key: "kickoff", label: "Kickoff (UTC)", value: (f) => (f.kickoff_time ? f.kickoff_time.replace("T", " ").slice(0, 16) : "–"), muted: false },
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
  ];
  const defense: DetailColumn[] = [
    { key: "probability_appears", label: "P(plays)", value: (f) => pct(f.probability_appears), muted: false },
    { key: "probability_sixty_minutes", label: "P(60+)", value: (f) => pct(f.probability_sixty_minutes), muted: false },
    { key: "probability_clean_sheet", label: "CS (own)", value: (f) => pct(f.probability_clean_sheet), muted: false },
    { key: "team_lambda_against", label: "Club λ against", value: (f) => fmt(f.team_lambda_against, 2), muted: false },
    { key: "team_probability_clean_sheet", label: "Club CS", value: clubCs, muted: false },
    { key: "team_defence_ease_index", label: "Def ease", value: (f) => fmt(f.team_defence_ease_index, 0), muted: false },
  ];
  const tail: DetailColumn[] = [
    { key: "team_overall_ease_index", label: "Ovr ease", value: (f) => fmt(f.team_overall_ease_index, 0), muted: false },
    { key: "team_official_fdr", label: "FDR", value: (f) => fmt(f.team_official_fdr, 0), muted: false },
  ];
  const muted = (columns: DetailColumn[]) => columns.map((column) => ({ ...column, muted: true }));
  const viewed =
    view === "attack"
      ? [...attack, ...muted(defense)]
      : view === "defense"
        ? [...defense, ...muted(attack)]
        : [...attack, ...defense];
  return [...base, ...viewed, ...tail];
}

function GwCell({
  fixtures,
  gw,
  view,
  colorSource,
  opponentIndexOf,
}: {
  fixtures: PlayerFixture[];
  gw: number;
  view: ViewMode;
  colorSource: ColorSource;
  opponentIndexOf: (teamCode: number) => number | null;
}) {
  const inGw = fixtures.filter((f) => f.gw === gw);
  if (!inGw.length) {
    return (
      <span
        data-testid="blank-slot"
        data-gw={gw}
        title={`GW${gw}: no fixture`}
        className={`inline-flex h-8 w-12 items-center justify-center rounded-md text-[10px] ${NULL_BUCKET_CLASS}`}
      >
        GW{gw}
      </span>
    );
  }
  return (
    <span className="inline-flex flex-col items-stretch gap-0.5">
      {inGw.map((f) => (
        <FixtureChip
          key={f.fixture}
          fixture={f}
          metric={playerChipMetric(f, view, colorSource, opponentIndexOf(f.opponent_team_code))}
          bucket={playerChipBucket(f, view, colorSource, opponentIndexOf(f.opponent_team_code))}
        />
      ))}
    </span>
  );
}

function SortableHead({
  sorted,
  canSort,
  onToggle,
  children,
  title,
}: {
  sorted: false | "asc" | "desc";
  canSort: boolean;
  onToggle: ((event: unknown) => void) | undefined;
  children: ReactNode;
  title?: string;
}) {
  return (
    <TableHead className={HEAD_CLASS} title={title} aria-sort={
      sorted === "asc" ? "ascending" : sorted === "desc" ? "descending" : canSort ? "none" : undefined
    }>
      {canSort ? (
        <button
          type="button"
          onClick={onToggle}
          className="inline-flex cursor-pointer select-none items-center gap-0.5 text-left"
        >
          {children}
          <span aria-hidden>
            {sorted === "asc" ? (
              <ChevronUp className="size-3" />
            ) : sorted === "desc" ? (
              <ChevronDown className="size-3" />
            ) : (
              ""
            )}
          </span>
        </button>
      ) : (
        children
      )}
    </TableHead>
  );
}

export function PlayerStatTable({
  fullscreenLabel,
  rows,
  view,
  colorSource,
  gwFrom,
  gwTo,
  opponentIndexOf,
  formHeading,
  formTitle,
  formColumnProfile = "legacy",
  initialSorting = DEFAULT_SORTING,
  pageSize = 50,
  beforeFixtureColumns = [],
  extraColumns = [],
  nameSuffix,
  rowClassName,
  summaryRows = [],
  summaryNote,
  emptyMessage = "No players match the current filters.",
}: PlayerStatTableProps) {
  const [sorting, setSorting] = useState<SortingState>(initialSorting);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  useEffect(() => {
    if (formColumnProfile !== "players") return;
    const visibleViewColumns =
      view === "attack"
        ? ATTACK_FORM_COLUMN_IDS
        : view === "defense"
          ? DEFENSE_FORM_COLUMN_IDS
          : VIEW_SPECIFIC_FORM_COLUMN_IDS;
    setSorting((current) =>
      current.some(
        ({ id }) => VIEW_SPECIFIC_FORM_COLUMN_IDS.has(id) && !visibleViewColumns.has(id),
      )
        ? [...initialSorting]
        : current,
    );
  }, [formColumnProfile, initialSorting, view]);

  const columns = useMemo<LegacyColumnDef<PlayerStatRow>[]>(() => {
    const formStat = (
      key: keyof PlayerFormWindow,
      label: string,
      options: {
        digits?: number;
        positions?: readonly string[];
        headerTitle?: string;
      } = {},
    ): LegacyColumnDef<PlayerStatRow> => ({
      id: `form-${key}`,
      header: options.headerTitle
        ? () => <span title={options.headerTitle}>{label}</span>
        : label,
      accessorFn: (row) => {
        if (options.positions && !options.positions.includes(row.player.position)) return undefined;
        const value = row.form?.[key];
        return value == null ? undefined : value;
      },
      sortUndefined: "last",
      cell: ({ row }) => {
        const { player, form } = row.original;
        const applicable = !options.positions || options.positions.includes(player.position);
        const value = applicable ? form?.[key] : null;
        const title = !applicable
          ? `${label} is not applicable to ${player.position}`
          : value == null
            ? form == null
              ? `No observed form is available for ${label}`
              : `${label} is unmeasured in this form window`
            : `Observed ${label}: ${fmt(value, options.digits ?? 0)}`;
        return (
          <span className="tabular-nums" title={title}>
            {fmt(value, options.digits ?? 0)}
          </span>
        );
      },
    });
    const minutesPerGame: LegacyColumnDef<PlayerStatRow> = {
      id: "form-minutes-per-game",
      header: "Min/g",
      accessorFn: (row) =>
        row.form?.appearances != null && row.form.appearances > 0 && row.form.minutes != null
          ? row.form.minutes / row.form.appearances
          : undefined,
      sortUndefined: "last",
      cell: ({ row }) => {
        const f = row.original.form;
        const value =
          f?.appearances != null && f.appearances > 0 && f.minutes != null
            ? f.minutes / f.appearances
            : null;
        return (
          <span
            className="tabular-nums"
            title={value == null ? "Minutes per appearance is unmeasured" : `Observed Min/g: ${fmt(value, 0)}`}
          >
            {fmt(value, 0)}
          </span>
        );
      },
    };
    const gwColumns: LegacyColumnDef<PlayerStatRow>[] = Array.from(
      { length: gwTo - gwFrom + 1 },
      (_, i) => gwFrom + i,
    ).map((gw) => ({
      id: `gw-${gw}`,
      header: `GW${gw}`,
      enableSorting: false,
      cell: ({ row }) => (
        <GwCell
          fixtures={row.original.filtered}
          gw={gw}
          view={view}
          colorSource={colorSource}
          opponentIndexOf={opponentIndexOf}
        />
      ),
    }));
    const commonFormColumns = [
      formStat("appearances", `${formHeading} App`),
      formStat("starts", "Starts"),
      minutesPerGame,
    ];
    const attackFormColumns = [
      formStat("goals_scored", "G"),
      formStat("assists", "A"),
      formStat("expected_goals", "xG", { digits: 1 }),
      formStat("expected_assists", "xA", { digits: 1 }),
      formStat("expected_goals_per_90", "xG/90", { digits: 2 }),
      formStat("expected_assists_per_90", "xA/90", { digits: 2 }),
    ];
    const defenseFormColumns = [
      formStat("clean_sheets", "CS", {
        positions: ["GK", "DEF", "MID"],
        headerTitle: "Observed clean sheets credited to the player",
      }),
      formStat("goals_conceded", "GC", {
        positions: ["GK", "DEF"],
        headerTitle: "Observed goals conceded while the player was on the pitch",
      }),
      formStat("saves", "Saves", {
        positions: ["GK"],
        headerTitle: "Observed goalkeeper saves",
      }),
      formStat("defensive_contribution", "DC", {
        positions: ["DEF", "MID", "FWD"],
        headerTitle: "Observed defensive-contribution count; raw actions, not fantasy points",
      }),
      formStat("expected_goals_conceded", "xGC", {
        digits: 1,
        positions: ["GK", "DEF"],
        headerTitle: "Observed expected goals conceded while the player was on the pitch",
      }),
    ];
    const outcomeFormColumns = [
      formStat("bonus", "Bonus"),
      formStat("bps", "BPS"),
      formStat("points_under_rules_2026_27", "Pts"),
    ];
    const playerFormColumns =
      view === "attack"
        ? [...commonFormColumns, ...attackFormColumns, ...outcomeFormColumns]
        : view === "defense"
          ? [...commonFormColumns, ...defenseFormColumns, ...outcomeFormColumns]
          : [
              ...commonFormColumns,
              ...attackFormColumns,
              ...defenseFormColumns,
              ...outcomeFormColumns,
            ];
    const legacyFormColumns = [
      formStat("appearances", `${formHeading} App`),
      minutesPerGame,
      formStat("goals_scored", "G"),
      formStat("assists", "A"),
      formStat("expected_goals", "xG", { digits: 1 }),
      formStat("expected_assists", "xA", { digits: 1 }),
      formStat("points_under_rules_2026_27", "Pts"),
    ];
    const visibleFormColumns =
      formColumnProfile === "players" ? playerFormColumns : legacyFormColumns;
    return [
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
        cell: ({ row }) => {
          const p = row.original.player;
          return (
            <div className="flex items-center gap-1.5">
              <PlayerPhoto code={p.code} name={p.web_name} />
              <div className="min-w-0">
                <div className="flex items-center gap-1 font-medium">
                  <span className="truncate">{p.web_name}</span>
                  {nameSuffix ? nameSuffix(p) : null}
                </div>
                <div className="flex items-center gap-1 text-muted-foreground">
                  <TeamBadge teamCode={p.team_code} shortName={p.team_short_name} />
                  <span>{p.team_short_name}</span>
                  <span aria-hidden>·</span>
                  <span>{p.position}</span>
                </div>
              </div>
            </div>
          );
        },
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
        accessorKey: "player.availability_status",
        header: "Avail",
        cell: ({ row }) => {
          const p = row.original.player;
          const flagged = p.availability_status != null && p.availability_status !== "a";
          return (
            <span
              className={flagged ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}
              title={
                flagged && p.chance_of_playing != null
                  ? `${Math.round(p.chance_of_playing)}% chance of playing next round`
                  : undefined
              }
            >
              {availabilityLabel(p.availability_status)}
            </span>
          );
        },
      },
      ...visibleFormColumns,
      {
        id: "totalXp",
        header: `xP GW${gwFrom}-${gwTo}`,
        accessorFn: (row) => row.totalXp,
        cell: ({ row }) => (
          <span className="tabular-nums font-semibold">
            {row.original.totalXp == null ? "–" : row.original.totalXp.toFixed(1)}
          </span>
        ),
      },
      ...beforeFixtureColumns,
      ...gwColumns,
      ...extraColumns,
    ];
  }, [
    view,
    colorSource,
    gwFrom,
    gwTo,
    formHeading,
    formColumnProfile,
    nameSuffix,
    beforeFixtureColumns,
    extraColumns,
    opponentIndexOf,
  ]);

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
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageIndex: 0, pageSize } },
  });

  const pageCount = table.getPageCount();
  const pageIndex = table.getState().pagination.pageIndex;

  return (
    <DecisionTableFullscreen label={fullscreenLabel}>
      {({ isFullscreen }) => (
        <div className={`flex flex-col gap-2 ${isFullscreen ? "min-h-0 flex-1" : ""}`}>
          <div
            className={`${
              isFullscreen ? "min-h-0 max-h-none flex-1" : "max-h-[calc(100vh-12rem)]"
            } overflow-auto overscroll-contain`}
          >
        <Table containerClassName="overflow-visible">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <SortableHead
                    key={header.id}
                    sorted={header.column.getIsSorted()}
                    canSort={header.column.getCanSort()}
                    onToggle={header.column.getToggleSortingHandler()}
                    title={
                      header.column.id.startsWith("form-") ? formTitle : undefined
                    }
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                  </SortableHead>
                ))}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={table.getVisibleLeafColumns().length} className="text-muted-foreground">
                  {emptyMessage}
                </TableCell>
              </TableRow>
            ) : (
              table.getRowModel().rows.flatMap((row) => {
                const cells = (
                  <TableRow key={row.id} className={rowClassName?.(row.original)}>
                    {row.getVisibleCells().map((cell) => (
                      <TableCell key={cell.id} className={CELL_CLASS}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </TableCell>
                    ))}
                  </TableRow>
                );
                if (!row.getIsExpanded()) return [cells];
                const player = row.original.player;
                const detail = detailColumns(view);
                // The detail table follows MATCH TIME, not the main table's sort.
                const byKickoff = [...player.fixtures].sort(
                  (a, b) =>
                    (a.kickoff_time ?? "9999").localeCompare(b.kickoff_time ?? "9999") ||
                    a.gw - b.gw,
                );
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
                              {detail.map((c) => (
                                <TableHead key={c.key} className={`h-7 px-2 text-[11px] ${c.muted ? "opacity-50" : ""}`}>
                                  {c.label}
                                </TableHead>
                              ))}
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {byKickoff.map((f) => (
                              <TableRow key={f.fixture}>
                                {detail.map((c) => (
                                  <TableCell
                                    key={c.key}
                                    className={`px-2 py-1 text-[11px] tabular-nums ${c.muted ? "opacity-50" : ""}`}
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
              })
            )}
          </TableBody>
          {summaryRows.length > 0 && (
            <TableFooter aria-label="Planned squad xP totals">
              {summaryRows.map((summary) => (
                <TableRow key={summary.id} className={summary.className}>
                  {table.getVisibleLeafColumns().map((column, columnIndex) =>
                    columnIndex === 1 ? (
                      <TableHead
                        key={column.id}
                        scope="row"
                        className={`${CELL_CLASS} h-auto text-left font-semibold`}
                      >
                        {summary.label}
                      </TableHead>
                    ) : (
                      <TableCell key={column.id} className={`${CELL_CLASS} tabular-nums`}>
                        {columnIndex === 0 ? null : summary.values[column.id] ?? null}
                      </TableCell>
                    ),
                  )}
                </TableRow>
              ))}
            </TableFooter>
          )}
        </Table>
          </div>
      {summaryRows.length > 0 && summaryNote != null && (
        <p className="px-2 text-[10px] text-muted-foreground">{summaryNote}</p>
      )}
      {rows.length > pageSize && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>
            {pageIndex * pageSize + 1}–{Math.min((pageIndex + 1) * pageSize, rows.length)} of{" "}
            {rows.length}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
              aria-label="Previous page"
            >
              <ChevronLeft className="size-4" />
            </Button>
            <span>
              page {pageIndex + 1} / {pageCount}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
              aria-label="Next page"
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
        </div>
      )}
    </DecisionTableFullscreen>
  );
}
