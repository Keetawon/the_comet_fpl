// Fixture matrix (Team) page: the fixture pivot. One row per club of the SELECTED
// vintage, one COLUMN per upcoming gameweek (the pivot), default-sorted by the selected
// source average. Each source tab owns the horizon average, the per-GW headline, and its
// tier colour -- opponent strength by default, so the visible number and colour always
// describe the same metric. Expanding a row defaults to the latest five ended
// gameweeks across the forecast season boundary, with explicit single-season scopes available.

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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DifficultyLegend } from "@/components/DifficultyLegend";
import { DecisionTableFullscreen } from "@/components/DecisionTableFullscreen";
import { FilterBar, type FilterState } from "@/components/FilterBar";
import { FilterPanel } from "@/components/FilterPanel";
import { FixtureChip } from "@/components/FixtureTicker";
import { InsightSummaryPanel } from "@/components/InsightSummaryPanel";
import { MultiSelectFilter } from "@/components/MultiSelectFilter";
import { TeamBadge } from "@/components/Avatars";
import { VintageSelect } from "@/components/VintageSelect";
import {
  loadFixtureMatrix,
  loadNextGw,
  loadTeamActuals,
  loadTeamProvisionalActuals,
} from "@/data/load";
import type {
  DashboardManifest,
  FixtureScheduleOverlay,
  NextGwPlan,
  ScheduleFixture,
  TeamFixture,
  TeamFormWindow,
  TeamObservedActualsRecord,
  TeamRecord,
  WindowLabel,
} from "@/data/types";
import { WINDOW_LABELS } from "@/data/types";
import {
  BUCKET_CLASSES,
  NULL_BUCKET_CLASS,
  easeBucket,
  fdrBucket,
  type ColorSource,
  type ViewMode,
} from "@/lib/difficulty";
import {
  chipBucket,
  chipMetric,
  sourceMetricValue,
  viewMetric,
} from "@/lib/fixtureChips";
import {
  SCHEDULE_EASE_PROXY_FORMULA,
  buildOpponentStrength,
  opponentStrengthBucket,
  scheduleEaseProxy,
  type OpponentStrength,
} from "@/lib/opponentStrength";
import { defaultVintageRunId, vintageOptions } from "@/lib/vintage";
import {
  compactInsightScope,
  formWindowScope,
  insightFact,
  publishedInsightProvenance,
} from "@/lib/insights";
import {
  latestTeamActualGameweeks,
  mergeTeamActualRecords,
  teamActualGameweekLabel,
  teamActualDetailsForGameweeks,
  type TeamActualFixtureDetail,
} from "@/lib/teamActuals";

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "ready";
      teams: TeamRecord[];
      teamActuals: TeamObservedActualsRecord[];
      provisionalCapturedAt: string | null;
      schedule: FixtureScheduleOverlay;
      plans: NextGwPlan[];
      manifest: DashboardManifest | null;
      runs: { run_id: string; season: string; gw_from: number; gw_to: number }[];
      easeVersion: string;
      gwFrom: number;
      gwTo: number;
      defaultRunId: string;
    };

interface TeamRow {
  team: TeamRecord;
  filtered: TeamFixture[];
  scheduleOnly: ScheduleFixture[];
  form: TeamFormWindow | null;
  formLabel: string | null;
  horizonMetric: number | null;
  actualDetails: TeamActualFixtureDetail[];
}

type FixtureHorizon = 5 | 10 | 15;
const ROLLING_ACTUAL_SCOPE = "rolling-five";

function previousSeason(season: string): string | null {
  const match = /^(\d{4})-(\d{2})$/.exec(season);
  if (match == null) return null;
  const start = Number(match[1]);
  return `${start - 1}-${String(start).slice(-2)}`;
}

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

function horizonHeader(colorSource: ColorSource, gwFrom: number, gwTo: number): string {
  if (colorSource === "opponent") return `Avg Opp str (GW${gwFrom}-${gwTo})`;
  if (colorSource === "ease") return `Avg Club ease (GW${gwFrom}-${gwTo})`;
  return "Avg FDR";
}

function horizonTitle(
  colorSource: ColorSource,
  view: ViewMode,
  gwFrom: number,
  gwTo: number,
): string {
  const scope = `GW${gwFrom}-${gwTo}`;
  if (colorSource === "opponent") {
    return `Average opponent-strength index across measured ${scope} fixture cards; every DGW leg counts.`;
  }
  if (colorSource === "fdr") {
    return `Average official FDR across measured ${scope} fixture cards; every DGW leg counts.`;
  }
  return `Average ${view} club-ease index across measured ${scope} fixture cards; every DGW leg counts.`;
}

function averageMeasured(values: (number | null)[]): number | null {
  const measured = values.filter(
    (value): value is number => value != null && Number.isFinite(value),
  );
  return measured.length
    ? measured.reduce((total, value) => total + value, 0) / measured.length
    : null;
}

function scheduleEaseValue(
  easeProxy: ReturnType<typeof scheduleEaseProxy>,
  view: ViewMode,
): number | null {
  if (view === "attack") return easeProxy.attackEase;
  if (view === "defense") return easeProxy.defenceEase;
  return easeProxy.overallEase;
}

function scheduleSourceMetric(
  fixture: ScheduleFixture,
  teamCode: number,
  view: ViewMode,
  colorSource: ColorSource,
  strengthOf: (teamCode: number) => OpponentStrength | null,
) {
  const opponentStrength = strengthOf(fixture.opponent_team_code);
  const opponentIndex = opponentStrength?.index ?? null;
  const easeProxy = scheduleEaseProxy(strengthOf(teamCode), opponentStrength);
  const value =
    colorSource === "opponent"
      ? opponentIndex
      : colorSource === "fdr"
        ? fixture.official_fdr ?? null
        : scheduleEaseValue(easeProxy, view);
  const bucket =
    colorSource === "opponent"
      ? opponentStrengthBucket(value)
      : colorSource === "fdr"
        ? fdrBucket(value)
        : easeBucket(value);
  const display =
    value == null ? "—" : colorSource === "fdr" ? `FDR ${value.toFixed(0)}` : value.toFixed(0);
  const description =
    colorSource === "opponent"
      ? value == null
        ? "selected-vintage opponent strength proxy unavailable"
        : `selected-vintage opponent strength proxy ${value.toFixed(0)}`
      : colorSource === "fdr"
        ? value == null
          ? "current official FDR unavailable"
          : `current official FDR ${value.toFixed(0)}`
        : value == null
          ? `selected-vintage ${view} club-ease proxy unavailable`
          : `selected-vintage ${view} club-ease proxy ${value.toFixed(0)} (${SCHEDULE_EASE_PROXY_FORMULA})`;
  return { value, bucket, display, description };
}

const HEAD_CLASS = "sticky top-0 z-10 h-8 bg-background px-2 text-xs whitespace-nowrap";
const CELL_CLASS = "px-2 py-1 text-xs whitespace-nowrap";
const GW_COLUMN_WIDTH_CLASS = "box-border w-20 min-w-20 max-w-20";
const FIXTURE_CARD_WIDTH_CLASS = "w-16 min-w-16 max-w-16";

const FORM_WINDOW_LABEL: Record<WindowLabel, string> = {
  last_3: "Last 3",
  last_5: "Last 5",
  last_10: "Last 10",
  season_to_date: "Season",
};

function TeamGwCell({
  fixtures,
  scheduleOnly,
  teamCode,
  gw,
  view,
  colorSource,
  opponentIndexOf,
  strengthOf,
  modelGwFrom,
  modelGwTo,
}: {
  fixtures: TeamFixture[];
  scheduleOnly: ScheduleFixture[];
  teamCode: number;
  gw: number;
  view: ViewMode;
  colorSource: ColorSource;
  opponentIndexOf: (teamCode: number) => number | null;
  strengthOf: (teamCode: number) => OpponentStrength | null;
  modelGwFrom: number;
  modelGwTo: number;
}) {
  const inGw = fixtures.filter((f) => f.gw === gw);
  const scheduleInGw = scheduleOnly.filter((f) => f.gw === gw);
  if (!inGw.length && !scheduleInGw.length) {
    return (
      <span
        data-testid="blank-slot"
        data-gw={gw}
        title={`GW${gw}: no fixture`}
        className={`inline-flex h-8 ${FIXTURE_CARD_WIDTH_CLASS} items-center justify-center rounded-md text-[10px] ${NULL_BUCKET_CLASS}`}
      >
        GW{gw}
      </span>
    );
  }
  return (
    <span
      data-testid="fixture-card-stack"
      data-gw={gw}
      className={`inline-flex ${FIXTURE_CARD_WIDTH_CLASS} flex-col items-stretch gap-0.5`}
    >
      {inGw.map((f) => {
        const opponentIndex = opponentIndexOf(f.opponent_team_code);
        return (
          <FixtureChip
            key={f.fixture}
            fixture={f}
            metric={chipMetric(f, view, colorSource, opponentIndex)}
            bucket={chipBucket(f, view, colorSource, opponentIndex)}
            className={FIXTURE_CARD_WIDTH_CLASS}
          />
        );
      })}
      {scheduleInGw.map((fixture) => {
        const metric = scheduleSourceMetric(
          fixture,
          teamCode,
          view,
          colorSource,
          strengthOf,
        );
        const venue =
          fixture.was_home == null ? "" : fixture.was_home ? "(H)" : "(A)";
        const kickoff = fixture.kickoff_time
          ? fixture.kickoff_time.replace("T", " ").slice(0, 16)
          : "kickoff TBC";
        const label =
          `GW${fixture.gw} vs ${fixture.opponent_short_name} ${venue}: current official ` +
          `schedule only; selected metric is ${metric.description}, derived from ` +
          `GW${modelGwFrom}-GW${modelGwTo} team lambdas when proxy-based; ` +
          `no later fixture-specific model or venue adjustment; ${kickoff} UTC`;
        return (
          <span
            key={fixture.fixture}
            data-testid="schedule-chip"
            data-gw={fixture.gw}
            data-bucket={metric.bucket ?? "null"}
            title={label}
            aria-label={label}
            className={`inline-flex h-8 ${FIXTURE_CARD_WIDTH_CLASS} flex-col justify-center rounded-md px-1 text-center ${
              metric.bucket
                ? BUCKET_CLASSES[metric.bucket]
                : "border border-border bg-muted text-muted-foreground"
            }`}
          >
            <span className="text-[10px] leading-tight font-semibold">
              {fixture.opponent_short_name}
              <span className="ml-0.5 font-normal">{venue}</span>
            </span>
            <span className="text-[9px] leading-tight tabular-nums">
              GW{fixture.gw} · {metric.display}
            </span>
          </span>
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
  const [horizon, setHorizon] = useState<FixtureHorizon>(5);
  const [filters, setFilters] = useState<FilterState | null>(null);
  const [sorting, setSorting] = useState<SortingState>([{ id: "horizonMetric", desc: true }]);
  const [expanded, setExpanded] = useState<ExpandedState>({});
  const [actualScope, setActualScope] = useState(ROLLING_ACTUAL_SCOPE);
  const [selectedTeamCodes, setSelectedTeamCodes] = useState<number[]>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      loadFixtureMatrix(),
      loadNextGw(),
      loadTeamActuals(),
      loadTeamProvisionalActuals(),
    ])
      .then(([fixtureData, nextGw, teamActuals, provisionalActuals]) => {
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
          teamActuals: mergeTeamActualRecords(
            teamActuals.teams,
            provisionalActuals.teams,
          ),
          provisionalCapturedAt: provisionalActuals.captured_at,
          schedule: fixtureData.schedule,
          plans: nextGw.plans,
          manifest: fixtureData.manifest,
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

  const teamOptions = useMemo(
    () =>
      [...runTeams]
        .sort(
          (left, right) =>
            left.team_name.localeCompare(right.team_name) || left.team_code - right.team_code,
        )
        .map((team) => ({
          value: team.team_code,
          label: team.short_name,
          searchText: team.team_name,
        })),
    [runTeams],
  );

  const runBounds = useMemo(() => {
    const gws = runTeams.flatMap((team) => team.fixtures.map((fixture) => fixture.gw));
    return {
      from: gws.length ? Math.min(...gws) : 1,
      to: gws.length ? Math.max(...gws) : 1,
      season: runTeams[0]?.season ?? null,
    };
  }, [runTeams]);

  const actualSeasonOptions = useMemo(() => {
    if (state.status !== "ready" || runBounds.season == null) return [];
    const previous = previousSeason(runBounds.season);
    const allowed = new Set([
      runBounds.season,
      ...(previous == null ? [] : [previous]),
    ]);
    return [
      ...new Set([
        runBounds.season,
        ...state.teamActuals
          .filter((team) => allowed.has(team.season))
          .map((team) => team.season),
      ]),
    ].sort((left, right) => right.localeCompare(left));
  }, [state, runBounds.season]);

  const actualScopeTeams = useMemo(() => {
    if (state.status !== "ready" || runBounds.season == null) return [];
    if (actualScope !== ROLLING_ACTUAL_SCOPE) {
      return state.teamActuals.filter((team) => team.season === actualScope);
    }
    const previous = previousSeason(runBounds.season);
    const rollingSeasons = new Set([
      runBounds.season,
      ...(previous == null ? [] : [previous]),
    ]);
    return state.teamActuals.filter((team) => rollingSeasons.has(team.season));
  }, [state, runBounds.season, actualScope]);

  const actualGameweeks = useMemo(
    () => latestTeamActualGameweeks(actualScopeTeams),
    [actualScopeTeams],
  );
  const actualScopeIncludesProvisional = actualGameweeks.some(
    (gameweek) => gameweek.outcome_status === "provisional",
  );

  const actualByTeamCode = useMemo(() => {
    const byTeamCode = new Map<number, TeamObservedActualsRecord[]>();
    for (const team of actualScopeTeams) {
      const records = byTeamCode.get(team.team_code) ?? [];
      records.push(team);
      byTeamCode.set(team.team_code, records);
    }
    return byTeamCode;
  }, [actualScopeTeams]);

  useEffect(() => {
    setActualScope(ROLLING_ACTUAL_SCOPE);
    setExpanded({});
  }, [runBounds.season]);

  const scheduleTeams = useMemo(() => {
    if (state.status !== "ready" || runBounds.season == null) return [];
    return state.schedule.teams.filter((team) => team.season === runBounds.season);
  }, [state, runBounds.season]);

  const scheduleByTeam = useMemo(
    () => new Map(scheduleTeams.map((team) => [team.team_code, team])),
    [scheduleTeams],
  );

  const scheduleMaxGw = useMemo(() => {
    const gws = scheduleTeams.flatMap((team) => team.fixtures.map((fixture) => fixture.gw));
    return gws.length ? Math.max(...gws) : runBounds.to;
  }, [scheduleTeams, runBounds.to]);

  useEffect(() => {
    setFilters((current) => {
      if (!current || !runTeams.length) return current;
      const nextTo = Math.min(runBounds.from + horizon - 1, scheduleMaxGw);
      if (current.gwFrom === runBounds.from && current.gwTo === nextTo) return current;
      return { ...current, gwFrom: runBounds.from, gwTo: nextTo };
    });
    setExpanded({});
  }, [horizon, runBounds.from, runTeams.length, scheduleMaxGw]);

  const opponentStrength = useMemo(() => buildOpponentStrength(runTeams), [runTeams]);
  const strengthOf = useMemo(
    () => (teamCode: number) => opponentStrength.get(teamCode) ?? null,
    [opponentStrength],
  );
  const opponentIndexOf = useMemo(
    () => (teamCode: number) => strengthOf(teamCode)?.index ?? null,
    [strengthOf],
  );

  const rows: TeamRow[] = useMemo(() => {
    if (!filters) return [];
    return runTeams
      .filter(
        (team) =>
          selectedTeamCodes.length === 0 || selectedTeamCodes.includes(team.team_code),
      )
      .map((team) => {
        const filtered = team.fixtures
          .filter(
            (f) =>
              f.gw >= filters.gwFrom &&
              f.gw <= filters.gwTo &&
              (filters.venue === "all" ||
                (filters.venue === "home" ? f.was_home === true : f.was_home === false)),
          )
          .sort(
            (a, b) =>
              a.gw - b.gw || (a.kickoff_time ?? "").localeCompare(b.kickoff_time ?? ""),
          );
        const scheduleOnly = (scheduleByTeam.get(team.team_code)?.fixtures ?? [])
          .filter(
            (fixture) =>
              fixture.gw > runBounds.to &&
              fixture.gw >= filters.gwFrom &&
              fixture.gw <= filters.gwTo &&
              (filters.venue === "all" ||
                (filters.venue === "home"
                  ? fixture.was_home === true
                  : fixture.was_home === false)),
          )
          .sort(
            (a, b) =>
              a.gw - b.gw ||
              (a.kickoff_time ?? "").localeCompare(b.kickoff_time ?? "") ||
              a.fixture - b.fixture,
          );
        const form = team.form;
        const sourceValues = [
          ...filtered.map((fixture) =>
            sourceMetricValue(
              fixture,
              filters.view,
              colorSource,
              opponentIndexOf(fixture.opponent_team_code),
            ),
          ),
          ...scheduleOnly.map(
            (fixture) =>
              scheduleSourceMetric(
                fixture,
                team.team_code,
                filters.view,
                colorSource,
                strengthOf,
              ).value,
          ),
        ];
        return {
          team,
          filtered,
          scheduleOnly,
          form: form ? form.windows[formWindow] : null,
          formLabel: form ? `${form.season} · GW${form.as_at_gw}` : null,
          horizonMetric: averageMeasured(sourceValues),
          actualDetails: teamActualDetailsForGameweeks(
            actualByTeamCode.get(team.team_code) ?? [],
            actualGameweeks,
          ),
        };
      });
  }, [
    runTeams,
    selectedTeamCodes,
    filters,
    formWindow,
    colorSource,
    opponentIndexOf,
    strengthOf,
    scheduleByTeam,
    runBounds.to,
    actualByTeamCode,
    actualGameweeks,
  ]);

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
            aria-label={row.getIsExpanded() ? "Collapse recent results" : "Expand recent results"}
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
        id: "horizonMetric",
        header: () => (
          <span
            title={
              filters
                ? horizonTitle(colorSource, filters.view, filters.gwFrom, filters.gwTo)
                : undefined
            }
          >
            {filters
              ? horizonHeader(colorSource, filters.gwFrom, filters.gwTo)
              : "Fixture average"}
          </span>
        ),
        accessorFn: (row) => row.horizonMetric,
        cell: ({ row }) => {
          const value = row.original.horizonMetric;
          if (value == null) return <span className="text-muted-foreground">—</span>;
          const text = colorSource === "fdr" ? value.toFixed(2) : value.toFixed(1);
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
            scheduleOnly={row.original.scheduleOnly}
            teamCode={row.original.team.team_code}
            gw={gw}
            view={filters?.view ?? "overall"}
            colorSource={colorSource}
            opponentIndexOf={opponentIndexOf}
            strengthOf={strengthOf}
            modelGwFrom={runBounds.from}
            modelGwTo={runBounds.to}
          />
        ),
      })),
    ],
    [
      filters,
      colorSource,
      opponentIndexOf,
      strengthOf,
      formWindow,
      runBounds.from,
      runBounds.to,
    ],
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
  const changeVintage = (nextRunId: string) => {
    if (nextRunId === activeRunId) return;
    const nextTeamCodes = new Set(
      state.teams
        .filter((team) => team.run_id === nextRunId)
        .map((team) => team.team_code),
    );
    setSelectedTeamCodes((current) => current.filter((code) => nextTeamCodes.has(code)));
    setExpanded({});
    setRunId(nextRunId);
  };
  const modelledFacts = rows.flatMap((row) =>
    row.filtered.map((fixture) => ({
      team: row.team,
      fixture,
      value: filters ? viewMetric(fixture, filters.view) : null,
    })),
  );
  const rankedFixtures = modelledFacts
    .filter((row): row is typeof row & { value: number } => row.value != null)
    .sort(
      (left, right) =>
        right.value - left.value ||
        left.team.team_code - right.team.team_code ||
        left.fixture.fixture - right.fixture.fixture,
    );
  const bestFixture = rankedFixtures[0];
  const selectedFixtureMetricLabel =
    filters?.view === "attack"
      ? "published expected goals for"
      : filters?.view === "defense"
        ? "published clean-sheet probability"
        : "published overall ease index";
  const formatSelectedFixtureMetric = (value: number) =>
    filters?.view === "defense"
      ? `${Math.round(value * 100)}%`
      : filters?.view === "attack"
        ? value.toFixed(2)
        : value.toFixed(1);
  const scheduleOnlyRows = rows.reduce((total, row) => total + row.scheduleOnly.length, 0);
  const fallbackRows = modelledFacts.filter((row) => row.fixture.stage_a_league_average_team).length;
  const insightFacts = [
    insightFact(
      "coverage.fixture_rows",
      "coverage",
      `${modelledFacts.length} modelled team-fixture rows and ${scheduleOnlyRows} schedule-only rows are visible in this scope.`,
      ["fixture_matrix.json"],
    ),
    insightFact(
      "coverage.fallback_rows",
      "coverage",
      `${fallbackRows} visible modelled rows use the published Stage A league-average fallback.`,
      ["fixture_matrix.json"],
    ),
    ...(bestFixture ? [
      insightFact(
        "rank.highest_fixture_metric",
        "rank",
        `${bestFixture.team.team_name} against ${bestFixture.fixture.opponent_short_name} in GW${bestFixture.fixture.gw} has the highest selected-view modelled ${selectedFixtureMetricLabel} at ${formatSelectedFixtureMetric(bestFixture.value)}.`,
        ["fixture_matrix.json"],
      ),
    ] : []),
  ];
  const insightCaveats = [
    "Insight ranks use the selected analytical view's directly published modelled values; the source tabs separately own the table average, card headline, and colour tier.",
    "Source averages include every measured visible fixture leg, including schedule-only display proxies; unavailable values are omitted rather than zero-filled.",
    "The current schedule overlay may be newer than the selected forecast vintage.",
    "Null fixture values are omitted from ranks and averages; no missing value is treated as zero.",
  ];
  const multiTeamInsightUnavailableReason =
    selectedTeamCodes.length > 1
      ? "AI explanation is unavailable while multiple teams are selected because the renderer accepts only one club. Deterministic facts remain available."
      : undefined;

  return (
    <div className="flex flex-col gap-3 p-4 lg:p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-lg font-semibold">Fixture matrix</h1>
        <div className="flex flex-wrap items-center gap-3">
          <VintageSelect
            options={vintageOptions(state.runs, state.plans)}
            value={activeRunId}
            onChange={changeVintage}
          />
          <p className="text-xs text-muted-foreground">
            {rows.length === runTeams.length
              ? `${runTeams.length} clubs`
              : `${rows.length} of ${runTeams.length} clubs`} · as of{" "}
            {activeRun?.as_of?.replace("T", " ").slice(0, 16)} UTC
            {activeRun?.form ? ` · form anchored ${activeRun.form.season} GW${activeRun.form.as_at_gw}` : ""}
          </p>
        </div>
      </div>

      <div className="rounded-lg border bg-card p-2">
        <DifficultyLegend
          colorSource={colorSource}
          onColorSourceChange={setColorSource}
          easeIndexFormulaVersion={state.easeVersion}
        />
        <p className="mt-1 text-xs text-muted-foreground">
          Sorted by the selected source average, highest first (click any column to re-sort).
          Opponent strength, club ease, and official FDR each own the table average, every card
          headline, and the card's colour tier. Every measured double-gameweek leg counts.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Beyond GW{runBounds.to}, current official fixtures use current schedule FDR or a fixed
          selected-vintage display proxy for opponent strength or club ease. Those measured cards
          enter the displayed GW-range average but remain display context, not later fixture forecasts.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Current schedule overlay exported{" "}
          {state.schedule.export_created_at.replace("T", " ").slice(0, 16)} UTC; it is separate
          from the selected forecast vintage and may include later schedule amendments.
        </p>
      </div>

      <InsightSummaryPanel
        items={insightFacts}
        caveats={insightCaveats}
        remote={{
          page: "fixture_matrix",
          provenance: publishedInsightProvenance(state.manifest, {
            ...(state.runs.find((run) => run.run_id === activeRunId) ?? {
              run_id: activeRunId,
              season: activeRun?.season ?? "",
            }),
            as_of: activeRun?.as_of,
          }),
          scope: compactInsightScope({
            gw_from: filters?.gwFrom,
            gw_to: filters?.gwTo,
            team_code: selectedTeamCodes.length === 1 ? selectedTeamCodes[0] : undefined,
            view: filters?.view === "defense" ? "defence" : filters?.view,
            venue: filters?.venue,
            form_window: formWindowScope(formWindow),
          }),
          localScopeKey: JSON.stringify({
            runId: activeRunId,
            filters,
            horizon,
            formWindow,
            colorSource,
            sorting,
            selectedTeamCodes,
          }),
          unavailableReason: multiTeamInsightUnavailableReason,
        }}
      />

      <FilterPanel>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <MultiSelectFilter
            label="Team"
            ariaLabel="Team filter"
            allLabel="All teams"
            options={teamOptions}
            selected={selectedTeamCodes}
            onChange={(teamCodes) => {
              setSelectedTeamCodes(teamCodes);
              setExpanded({});
            }}
            searchable
            searchLabel="Search teams"
            emptyLabel="No teams match that search"
            className="text-sm text-muted-foreground"
          />
          {filters && (
            <FilterBar
              filters={filters}
              onChange={setFilters}
              minGw={state.gwFrom}
              maxGw={state.gwTo}
              showGameweekRange={false}
            />
          )}
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            Fixture horizon
            <ToggleGroup
              type="single"
              value={String(horizon)}
              onValueChange={(value) => {
                if (value) setHorizon(Number(value) as FixtureHorizon);
              }}
              variant="outline"
              aria-label="Fixture horizon"
            >
              {([5, 10, 15] as const).map((weeks) => (
                <ToggleGroupItem key={weeks} value={String(weeks)}>
                  {weeks} GWs
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </div>
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
          {actualSeasonOptions.length > 0 && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              Actual scope
              <Select
                value={actualScope}
                onValueChange={(value) => {
                  setActualScope(value);
                  setExpanded({});
                }}
              >
                <SelectTrigger size="sm" className="w-36" aria-label="Actual scope">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ROLLING_ACTUAL_SCOPE}>Rolling 5</SelectItem>
                  {actualSeasonOptions.map((season) => (
                    <SelectItem key={season} value={season}>
                      {season}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">
          Expanded rows default to a shared rolling window of the latest five ended gameweeks.
          At a season boundary it continues into the immediately preceding season; the season
          options isolate either season. Double-gameweek legs stay separate, and clubs are never
          individually backfilled outside the shared window. xG, xGC, BPS, and DC are source-row
          aggregates; unavailable evidence is shown as –. Possession and shots are unavailable in
          the approved published sources, so no proxy is shown.
        </p>
        {actualScopeIncludesProvisional && (
          <p
            role="status"
            className="mt-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-950 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100"
          >
            Provisional team results are included from the live capture at{" "}
            {state.provisionalCapturedAt
              ? new Date(state.provisionalCapturedAt).toISOString().replace("T", " ").slice(0, 16)
              : "unknown time"} UTC.
            These display-only rows are not yet attached to the immutable outcome ledger. Scores
            and source-row stats may still change and are never used on prediction-vs-actual pages.
          </p>
        )}
      </FilterPanel>

      <DecisionTableFullscreen label="Fixture matrix table">
        {({ isFullscreen }) => (
      <div
        className={`${
          isFullscreen ? "min-h-0 max-h-none flex-1" : "max-h-[calc(100vh-14rem)]"
        } overflow-auto overscroll-contain`}
      >
        <Table aria-label="Fixture matrix" containerClassName="overflow-visible">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const sorted = header.column.getIsSorted();
                  return (
                    <TableHead
                      key={header.id}
                      data-column-kind={header.column.id.startsWith("gw-") ? "gameweek" : undefined}
                      className={`${HEAD_CLASS} ${
                        header.column.id.startsWith("gw-") ? GW_COLUMN_WIDTH_CLASS : ""
                      }`}
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
                    <TableCell
                      key={cell.id}
                      data-column-kind={cell.column.id.startsWith("gw-") ? "gameweek" : undefined}
                      className={`${CELL_CLASS} ${
                        cell.column.id.startsWith("gw-") ? GW_COLUMN_WIDTH_CLASS : ""
                      }`}
                    >
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              );
              if (!row.getIsExpanded()) return [cells];
              return [
                cells,
                <TableRow key={`${row.id}-detail`}>
                  <TableCell colSpan={row.getVisibleCells().length} className="bg-muted/40 p-3">
                    <div
                      className="max-w-3xl space-y-1"
                      data-testid={`team-actual-details-${row.original.team.team_code}`}
                    >
                      <p className="text-xs font-medium">
                        {row.original.team.team_name} — recent results ·{" "}
                        {actualScope === ROLLING_ACTUAL_SCOPE ? "Rolling 5" : actualScope}
                        {actualGameweeks.length > 0
                          ? ` · shared window ${actualGameweeks
                              .map(teamActualGameweekLabel)
                              .join(", ")}`
                          : ""}
                      </p>
                      {row.original.actualDetails.length === 0 ? (
                        <p className="py-2 text-xs text-muted-foreground">
                          No ended results are available for this club in the selected Actual scope
                          and shared five-gameweek window.
                        </p>
                      ) : (
                        <Table aria-label={`${row.original.team.team_name} recent results`}>
                          <TableHeader>
                            <TableRow>
                              <TableHead className="h-7 px-2 text-[11px]">
                                Season / GW / date
                              </TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">Opponent</TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">Status</TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">GF</TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">GA</TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">xG</TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">xGC</TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">BPS sum</TableHead>
                              <TableHead className="h-7 px-2 text-[11px]">DC sum</TableHead>
                            </TableRow>
                          </TableHeader>
                          <TableBody>
                            {row.original.actualDetails.map((actual) => (
                              <TableRow
                                key={`${actual.season}-${actual.fixture}`}
                                data-actual-fixture={actual.fixture}
                              >
                                <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                  {actual.season} GW{actual.gw} · {actual.kickoff_time.slice(0, 10)}
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px]">
                                  {actual.opponent_short_name} ({actual.was_home ? "H" : "A"})
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px]">
                                  {actual.outcome_status === "provisional" ? (
                                    <span className="rounded border border-amber-400 bg-amber-50 px-1 text-[9px] font-medium text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
                                      Provisional
                                    </span>
                                  ) : (
                                    <span className="text-muted-foreground">Final</span>
                                  )}
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                  {actual.goals_for}
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                  {actual.goals_against}
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                  {fmt(actual.team_xg, 2)}
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                  {fmt(actual.team_xgc, 2)}
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                  {fmt(actual.team_bps, 0)}
                                </TableCell>
                                <TableCell className="px-2 py-1 text-[11px] tabular-nums">
                                  {fmt(actual.defensive_contribution, 0)}
                                </TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      )}
                    </div>
                  </TableCell>
                </TableRow>,
              ];
            })}
          </TableBody>
        </Table>
      </div>
        )}
      </DecisionTableFullscreen>
      <p className="text-xs text-muted-foreground">
        Availability and chance-of-playing are reported overlays valid for the next gameweek;
        they are not shown here and never fold into these distributions. The 10- and 15-GW
        extensions add current official fixtures. Their current FDR and fixed selected-vintage
        opponent-strength or club-ease proxies drive the matching tab's card headline, average,
        and colour tier, but remain display context rather than later fixture-specific forecasts;
        hover a card for its exact source.
      </p>
    </div>
  );
}
