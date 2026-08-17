// Fixture matrix (Team) page: the fixture pivot. One row per club of the SELECTED
// vintage, one COLUMN per upcoming gameweek (the pivot), default-sorted by average ease
// (easiest schedule first). Cells colour on the selected source -- opponent strength by
// default, so a strong club's row is no longer uniformly green: the colour follows the
// OPPONENT, not the row club. Expanding a row exposes every primitive (raw lambdas,
// clean-sheet probability, all ease indices, official FDR) ordered by kickoff time.

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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DifficultyLegend } from "@/components/DifficultyLegend";
import { FilterBar, type FilterState } from "@/components/FilterBar";
import { FilterPanel } from "@/components/FilterPanel";
import { FixtureChip } from "@/components/FixtureTicker";
import { TeamBadge } from "@/components/Avatars";
import { VintageSelect } from "@/components/VintageSelect";
import { loadFixtureMatrix, loadNextGw } from "@/data/load";
import type { NextGwPlan, TeamFixture, TeamFormWindow, TeamRecord, WindowLabel } from "@/data/types";
import { WINDOW_LABELS } from "@/data/types";
import { NULL_BUCKET_CLASS, type ColorSource, type ViewMode } from "@/lib/difficulty";
import { chipBucket, chipMetric, viewMetric } from "@/lib/fixtureChips";
import { buildOpponentStrength } from "@/lib/opponentStrength";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      teams: TeamRecord[];
      plans: NextGwPlan[];
      runs: { run_id: string; season: string; gw_from: number; gw_to: number }[];
      easeVersion: string;
      gwFrom: number;
      gwTo: number;
      defaultRunId: string;
    };

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

const HEAD_CLASS = "sticky top-0 z-10 h-8 bg-background px-2 text-xs whitespace-nowrap";
const CELL_CLASS = "px-2 py-1 text-xs whitespace-nowrap";

const FORM_WINDOW_LABEL: Record<WindowLabel, string> = {
  last_3: "Last 3",
  last_5: "Last 5",
  last_10: "Last 10",
  season_to_date: "Season",
};

function TeamGwCell({
  fixtures,
  gw,
  view,
  colorSource,
  opponentIndexOf,
  cleanSheetAnchor,
}: {
  fixtures: TeamFixture[];
  gw: number;
  view: ViewMode;
  colorSource: ColorSource;
  opponentIndexOf: (teamCode: number) => number | null;
  cleanSheetAnchor: number | null;
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
      {inGw.map((f) => {
        const opponentIndex = opponentIndexOf(f.opponent_team_code);
        return (
          <FixtureChip
            key={f.fixture}
            fixture={f}
            metric={chipMetric(f, view, colorSource, opponentIndex)}
            bucket={chipBucket(f, view, colorSource, cleanSheetAnchor, opponentIndex)}
          />
        );
      })}
    </span>
  );
}

export function FixtureMatrixPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [runId, setRunId] = useState<string | null>(null);
  const [colorSource, setColorSource] = useState<ColorSource>("opponent");
  const [formWindow, setFormWindow] = useState<WindowLabel>("last_5");
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [sorting, setSorting] = useState<SortingState>([{ id: "avgMetric", desc: true }]);
  const [expanded, setExpanded] = useState<ExpandedState>({});

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadFixtureMatrix(), loadNextGw()])
      .then(([fixtureData, nextGw]) => {
        if (cancelled) return;
        const seen = new Map<string, { run_id: string; season: string; gw_from: number; gw_to: number }>();
        for (const t of fixtureData.teams) {
          const gws = t.fixtures.map((f) => f.gw);
          const from = gws.length ? Math.min(...gws) : 0;
          const to = gws.length ? Math.max(...gws) : 0;
          const existing = seen.get(t.run_id);
          if (!existing) seen.set(t.run_id, { run_id: t.run_id, season: t.season, gw_from: from, gw_to: to });
          else
            seen.set(t.run_id, {
              ...existing,
              gw_from: Math.min(existing.gw_from, from),
              gw_to: Math.max(existing.gw_to, to),
            });
        }
        const runs =
          fixtureData.manifest?.runs ??
          [...seen.values()].sort((a, b) => a.run_id.localeCompare(b.run_id));
        const defaultRun = defaultVintageRunId(
          runs,
          nextGw.plans,
          fixtureData.manifest?.runs.at(-1)?.run_id ?? null,
        );
        const first =
          fixtureData.teams.find((t) => t.run_id === defaultRun) ?? fixtureData.teams[0];
        const gws = first ? first.fixtures.map((f) => f.gw) : [];
        const gwFrom = gws.length ? Math.min(...gws) : 1;
        const gwTo = gws.length ? Math.max(...gws) : 1;
        setState({
          status: "ready",
          teams: fixtureData.teams,
          plans: nextGw.plans,
          runs,
          easeVersion: fixtureData.easeIndexFormulaVersion,
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

  const runTeams = useMemo(
    () =>
      state.status === "ready"
        ? state.teams.filter((t) => t.run_id === (runId ?? state.defaultRunId))
        : [],
    [state, runId],
  );

  const cleanSheetAnchor = useMemo(() => {
    const values = runTeams
      .flatMap((t) => t.fixtures.map((f) => f.probability_clean_sheet))
      .filter((v): v is number => v != null);
    return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  }, [runTeams]);

  const opponentStrength = useMemo(() => buildOpponentStrength(runTeams), [runTeams]);
  const opponentIndexOf = useMemo(
    () => (teamCode: number) => opponentStrength.get(teamCode)?.index ?? null,
    [opponentStrength],
  );

  const rows: TeamRow[] = useMemo(() => {
    if (!filters) return [];
    return runTeams.map((team) => {
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
        formLabel: form ? `${form.season} · GW${form.as_at_gw}` : null,
        avgMetric: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null,
      };
    });
  }, [runTeams, filters, formWindow]);

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
          <div className="flex items-center gap-1.5">
            <TeamBadge teamCode={row.original.team.team_code} shortName={row.original.team.short_name} />
            <span className="font-medium">{row.original.team.team_name}</span>
          </div>
        ),
      },
      {
        id: "form",
        header: `Form ${FORM_WINDOW_LABEL[formWindow]}`,
        enableSorting: false,
        cell: ({ row }) => {
          const f = row.original.form;
          if (!f || !row.original.formLabel) return <span className="text-muted-foreground">–</span>;
          return (
            <span
              className="text-xs tabular-nums"
              title={`Form anchored ${row.original.formLabel} (last season at GW1)`}
            >
              W{fmt(f.wins, 0)} D{fmt(f.draws, 0)} L{fmt(f.losses, 0)} · {fmt(f.goals_for, 0)}:
              {fmt(f.goals_against, 0)} · xG {fmt(f.team_xg_per_match, 2)}/m · xGC{" "}
              {fmt(f.team_xgc_per_match, 2)}/m
            </span>
          );
        },
      },
      {
        id: "avgMetric",
        header: `Avg ${filters ? VIEW_LABEL[filters.view] : ""}`,
        accessorFn: (row) => row.avgMetric,
        cell: ({ row }) => {
          const value = row.original.avgMetric;
          if (value == null) return <span className="text-muted-foreground">–</span>;
          const text =
            filters?.view === "defense" ? `${Math.round(value * 100)}%` : value.toFixed(1);
          return <span className="tabular-nums font-medium">{text}</span>;
        },
      },
      ...Array.from(
        { length: (filters?.gwTo ?? 1) - (filters?.gwFrom ?? 1) + 1 },
        (_, i) => (filters?.gwFrom ?? 1) + i,
      ).map((gw) => ({
        id: `gw-${gw}`,
        header: `GW${gw}`,
        enableSorting: false,
        cell: ({ row }: { row: { original: TeamRow } }) => (
          <TeamGwCell
            fixtures={row.original.filtered}
            gw={gw}
            view={filters?.view ?? "overall"}
            colorSource={colorSource}
            opponentIndexOf={opponentIndexOf}
            cleanSheetAnchor={cleanSheetAnchor}
          />
        ),
      })),
    ],
    [filters, colorSource, cleanSheetAnchor, opponentIndexOf, formWindow],
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

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading read models…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Fixture matrix</h1>
        <p role="alert" className="max-w-xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }
  if (!state.teams.length) {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Fixture matrix</h1>
        <p className="max-w-xl text-sm text-muted-foreground">
          No recorded forecast vintages in this export. Generate one first (see
          dashboard/README.md).
        </p>
      </div>
    );
  }

  const activeRunId = runId ?? state.defaultRunId;
  const activeRun = runTeams[0];

  return (
    <div className="flex flex-col gap-3 p-4 lg:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Fixture matrix</h1>
        <div className="flex flex-wrap items-center gap-3">
          <VintageSelect options={vintageOptions(state.runs, state.plans)} value={activeRunId} onChange={setRunId} />
          <p className="text-xs text-muted-foreground">
            {runTeams.length} clubs · as of {activeRun?.as_of?.replace("T", " ").slice(0, 16)} UTC
            {activeRun?.form ? ` · form anchored ${activeRun.form.season} GW${activeRun.form.as_at_gw}` : ""}
          </p>
        </div>
      </div>

      <FilterPanel>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {filters && (
            <FilterBar filters={filters} onChange={setFilters} minGw={state.gwFrom} maxGw={state.gwTo} />
          )}
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            Form window
            <Select
              value={formWindow}
              onValueChange={(value) => setFormWindow(value as WindowLabel)}
            >
              <SelectTrigger size="sm" className="w-28" aria-label="Form window">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {WINDOW_LABELS.map((label) => (
                  <SelectItem key={label} value={label}>
                    {FORM_WINDOW_LABEL[label]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      </FilterPanel>

      <div className="rounded-lg border bg-card p-2">
        <DifficultyLegend
          colorSource={colorSource}
          onColorSourceChange={setColorSource}
          easeIndexFormulaVersion={state.easeVersion}
          cleanSheetAnchor={cleanSheetAnchor}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Sorted by average ease, easiest schedule first (click any column to re-sort). One
          column per gameweek; two chips in a double gameweek.
        </p>
      </div>

      <div className="max-h-[calc(100vh-14rem)] overflow-auto rounded-md border">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead
                      key={header.id}
                      className={HEAD_CLASS}
                      aria-sort={
                        sorted === "asc"
                          ? "ascending"
                          : sorted === "desc"
                            ? "descending"
                            : header.column.getCanSort()
                              ? "none"
                              : undefined
                      }
                    >
                      {header.column.getCanSort() ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex cursor-pointer select-none items-center gap-0.5 text-left"
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          <span aria-hidden>
                            {sorted === "asc" ? "↑" : sorted === "desc" ? "↓" : ""}
                          </span>
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.flatMap((row) => {
              const cells = (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} className={CELL_CLASS}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              );
              if (!row.getIsExpanded()) return [cells];
              const byKickoff = [...row.original.team.fixtures].sort(
                (a, b) =>
                  (a.kickoff_time ?? "9999").localeCompare(b.kickoff_time ?? "9999") || a.gw - b.gw,
              );
              return [
                cells,
                <TableRow key={`${row.id}-detail`}>
                  <TableCell colSpan={row.getVisibleCells().length} className="bg-muted/40 p-3">
                    <div className="max-w-3xl space-y-1">
                      <p className="text-xs font-medium">
                        {row.original.team.team_name} — all primitives, by kickoff (ease formula{" "}
                        {state.easeVersion})
                      </p>
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead className="h-7 px-2 text-[11px]">Kickoff (UTC)</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">GW</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">Opponent</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">Venue</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">λ for</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">λ against</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">CS %</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">Atk ease</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">Def ease</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">Ovr ease</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">Opp strength</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">FDR</TableHead>
                            <TableHead className="h-7 px-2 text-[11px]">Stage A league avg</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {byKickoff.map((f) => (
                            <TableRow key={f.fixture}>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                {f.kickoff_time ? f.kickoff_time.replace("T", " ").slice(0, 16) : "–"}
                              </TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">{f.gw}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px]">{f.opponent_short_name}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px]">{f.was_home == null ? "–" : f.was_home ? "H" : "A"}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">{fmt(f.lambda_for, 2)}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">{fmt(f.lambda_against, 2)}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                {fmt(f.probability_clean_sheet == null ? null : f.probability_clean_sheet * 100, 1)}
                              </TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">{fmt(f.attack_ease_index)}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">{fmt(f.defence_ease_index)}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">{fmt(f.overall_ease_index)}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                {fmt(opponentIndexOf(f.opponent_team_code), 0)}
                              </TableCell>
                              <TableCell className="px-2 py-1 text-[11px] tabular-nums">{fmt(f.official_fdr, 0)}</TableCell>
                              <TableCell className="px-2 py-1 text-[11px]">{f.stage_a_league_average_team ? "yes" : "no"}</TableCell>
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
