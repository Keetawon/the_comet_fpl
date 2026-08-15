// Fixture matrix (Team) page. One row per club: recent form (labelled with its anchor
// season -- at GW1 that is LAST season), the next-N fixture ticker coloured by the active
// view, and an expandable per-fixture table exposing every primitive beside the composite
// ease indices (raw lambdas, clean-sheet probability, official FDR).

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
import { DifficultyLegend } from "@/components/DifficultyLegend";
import { chipBucket, chipMetric, viewMetric } from "@/lib/fixtureChips";
import { FilterBar, type FilterState } from "@/components/FilterBar";
import { FixtureTicker } from "@/components/FixtureTicker";
import { loadFixtureMatrix } from "@/data/load";
import type { TeamFixture, TeamFormWindow, TeamRecord, WindowLabel } from "@/data/types";
import { WINDOW_LABELS } from "@/data/types";
import type { ColorSource, ViewMode } from "@/lib/difficulty";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; teams: TeamRecord[]; easeVersion: string; gwFrom: number; gwTo: number };

interface TeamRow {
  team: TeamRecord;
  filtered: TeamFixture[];
  form: TeamFormWindow | null;
  formLabel: string | null;
  avgMetric: number | null;
}

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const VIEW_LABEL: Record<ViewMode, string> = {
  overall: "overall ease",
  attack: "attack ease",
  defense: "clean-sheet probability",
};

function FormCell({ row }: { row: TeamRow }) {
  if (!row.form || !row.formLabel) return <span className="text-muted-foreground">No form data</span>;
  const f = row.form;
  return (
    <div className="text-xs leading-snug">
      <div className="text-[10px] text-muted-foreground">{row.formLabel}</div>
      <div className="tabular-nums">
        W{fmt(f.wins, 0)} D{fmt(f.draws, 0)} L{fmt(f.losses, 0)} · {fmt(f.goals_for, 0)}:
        {fmt(f.goals_against, 0)} · CS {fmt(f.clean_sheets, 0)}
      </div>
      <div className="tabular-nums text-muted-foreground">
        xG {fmt(f.team_xg_per_match, 2)}/m · xGC {fmt(f.team_xgc_per_match, 2)}/m
      </div>
    </div>
  );
}

export function FixtureMatrixPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [colorSource, setColorSource] = useState<ColorSource>("ease");
  const [formWindow, setFormWindow] = useState<WindowLabel>("last_5");
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  useEffect(() => {
    let cancelled = false;
    loadFixtureMatrix()
      .then((data) => {
        if (cancelled) return;
        const gws = data.teams.flatMap((t) => t.fixtures.map((f) => f.gw));
        const run = data.manifest?.runs.find(
          (r) => r.run_id === data.teams[0]?.run_id && r.season === data.teams[0]?.season,
        );
        const gwFrom = run?.gw_from ?? Math.min(...gws);
        const gwTo = run?.gw_to ?? Math.max(...gws);
        setState({
          status: "ready",
          teams: data.teams,
          easeVersion: data.easeIndexFormulaVersion,
          gwFrom,
          gwTo,
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

  const cleanSheetAnchor = useMemo(() => {
    if (state.status !== "ready") return null;
    const values = state.teams
      .flatMap((t) => t.fixtures.map((f) => f.probability_clean_sheet))
      .filter((v): v is number => v != null);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  }, [state]);

  const rows: TeamRow[] = useMemo(() => {
    if (state.status !== "ready" || !filters) return [];
    return state.teams.map((team) => {
      const filtered = team.fixtures
        .filter(
          (f) =>
            f.gw >= filters.gwFrom &&
            f.gw <= filters.gwTo &&
            (filters.venue === "all" ||
              (filters.venue === "home" ? f.was_home === true : f.was_home === false)),
        )
        .sort((a, b) => a.gw - b.gw || (a.kickoff_time ?? "").localeCompare(b.kickoff_time ?? ""));
      const values = filtered
        .map((f) => viewMetric(f, filters.view))
        .filter((v): v is number => v != null);
      const form = team.form;
      return {
        team,
        filtered,
        form: form ? form.windows[formWindow] : null,
        formLabel: form ? `Form ${form.season} · GW${form.as_at_gw}` : null,
        avgMetric: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null,
      };
    });
  }, [state, filters, formWindow]);

  const columns = useMemo<LegacyColumnDef<TeamRow>[]>(
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
        accessorKey: "team.short_name",
        header: "Team",
        cell: ({ row }) => (
          <div>
            <div className="font-medium">{row.original.team.team_name}</div>
            <div className="text-xs text-muted-foreground">{row.original.team.season}</div>
          </div>
        ),
      },
      {
        id: "form",
        header: "Recent form",
        cell: ({ row }) => <FormCell row={row.original} />,
      },
      {
        id: "avgMetric",
        header: `Avg ${filters ? VIEW_LABEL[filters.view] : ""}`,
        cell: ({ row }) => {
          const value = row.original.avgMetric;
          if (value == null) return <span className="text-muted-foreground">–</span>;
          const text =
            filters?.view === "defense" ? `${Math.round(value * 100)}%` : value.toFixed(1);
          return <span className="tabular-nums">{text}</span>;
        },
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
              metricOf={(f) => chipMetric(f, filters?.view ?? "overall", colorSource)}
              bucketOf={(f) =>
                chipBucket(f, filters?.view ?? "overall", colorSource, cleanSheetAnchor)
              }
            />
          ) : (
            <span className="text-xs text-muted-foreground">No fixtures in range</span>
          ),
      },
    ],
    [filters, colorSource, cleanSheetAnchor],
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
        <h1 className="mb-2 text-lg font-semibold">Fixture matrix</h1>
        <p className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }

  const runId = state.teams[0]?.run_id;
  const asOf = state.teams[0]?.as_of;

  return (
    <div className="flex flex-col gap-3 p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Fixture matrix</h1>
        <p className="text-xs text-muted-foreground">
          run {runId?.slice(0, 12)}… · as of {asOf?.replace("T", " ").slice(0, 16)} UTC ·
          horizon GW{filters?.gwFrom ?? state.gwFrom}-GW{filters?.gwTo ?? state.gwTo}
        </p>
      </div>
      <FilterBar filters={filters!} onChange={setFilters} minGw={state.gwFrom} maxGw={state.gwTo} />
      <div className="flex flex-wrap items-center gap-3">
        <DifficultyLegend
          colorSource={colorSource}
          onColorSourceChange={setColorSource}
          easeIndexFormulaVersion={state.easeVersion}
          cleanSheetAnchor={cleanSheetAnchor}
        />
        <Separator orientation="vertical" className="h-6" />
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          Form window
          <Select
            value={formWindow}
            onValueChange={(value) => setFormWindow(value as WindowLabel)}
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
              const fixtures = row.original.team.fixtures;
              return [
                cells,
                <TableRow key={`${row.id}-detail`}>
                  <TableCell colSpan={row.getVisibleCells().length} className="bg-muted/40 p-3">
                    <div className="max-w-3xl space-y-1">
                      <p className="text-xs font-medium">
                        {row.original.team.team_name} — all primitives (ease formula{" "}
                        {state.easeVersion})
                      </p>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>GW</TableHead>
                            <TableHead>Opponent</TableHead>
                            <TableHead>Venue</TableHead>
                            <TableHead>Kickoff (UTC)</TableHead>
                            <TableHead>λ for</TableHead>
                            <TableHead>λ against</TableHead>
                            <TableHead>CS %</TableHead>
                            <TableHead>Atk ease</TableHead>
                            <TableHead>Def ease</TableHead>
                            <TableHead>Ovr ease</TableHead>
                            <TableHead>FDR</TableHead>
                            <TableHead>Stage A league avg</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {fixtures.map((f) => (
                            <TableRow key={f.fixture}>
                              <TableCell className="tabular-nums">{f.gw}</TableCell>
                              <TableCell>{f.opponent_short_name}</TableCell>
                              <TableCell>{f.was_home == null ? "–" : f.was_home ? "H" : "A"}</TableCell>
                              <TableCell className="tabular-nums">
                                {f.kickoff_time ? f.kickoff_time.replace("T", " ").slice(0, 16) : "–"}
                              </TableCell>
                              <TableCell className="tabular-nums">{fmt(f.lambda_for, 2)}</TableCell>
                              <TableCell className="tabular-nums">{fmt(f.lambda_against, 2)}</TableCell>
                              <TableCell className="tabular-nums">
                                {fmt(f.probability_clean_sheet == null ? null : f.probability_clean_sheet * 100, 1)}
                              </TableCell>
                              <TableCell className="tabular-nums">{fmt(f.attack_ease_index)}</TableCell>
                              <TableCell className="tabular-nums">{fmt(f.defence_ease_index)}</TableCell>
                              <TableCell className="tabular-nums">{fmt(f.overall_ease_index)}</TableCell>
                              <TableCell className="tabular-nums">{fmt(f.official_fdr, 0)}</TableCell>
                              <TableCell>{f.stage_a_league_average_team ? "yes" : "no"}</TableCell>
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
        Availability and chance-of-playing are reported overlays valid for the next gameweek;
        they are not shown here and never fold into these distributions. Later-gameweek
        schedule context beyond this vintage horizon is unknown.
      </p>
    </div>
  );
}
