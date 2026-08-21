// Browser-only squad sandbox. It binds to the one formal platform-default forecast
// vintage and the matching recorded rules snapshot, but never runs the optimizer or
// writes a decision artifact. Structural FPL squad rules are enforced while budget is
// deliberately advisory so managers can explore future value-growth scenarios.

import { useEffect, useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Check,
  CircleAlert,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";

import { PlayerPhoto, TeamBadge } from "@/components/Avatars";
import { DecisionTableFullscreen } from "@/components/DecisionTableFullscreen";
import {
  INITIAL_PLAYER_FILTERS,
  PlayerFiltersBar,
  matchesPlayerFilters,
  type PlayerFilters,
} from "@/components/PlayerFiltersBar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableFooter,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { loadNextGw, loadOptimizerAudit, loadPlayers } from "@/data/load";
import type {
  AuditPlan,
  NextGwPlan,
  OptimizerAuditData,
  PlayerRecord,
  RulesSnapshot,
} from "@/data/types";
import {
  buildUserDraftLoadedHorizonContext,
  deriveUserDraftRules,
  rawPlayerGameweekXp,
  screenUserDraftHorizon,
  userDraftSelectionGuard,
  userDraftStructure,
  userDraftTotals,
  type UserDraftRules,
} from "@/lib/userDraft";
import { cn } from "@/lib/utils";

const PLAYER_PAGE_SIZE = 40;
export const USER_DRAFT_STORAGE_KEY = "the-comet-user-draft-v1";

type SortKey = "player" | "price" | "total3" | "total5" | `gw:${number}`;
type SortDirection = "asc" | "desc";

interface ReadyState {
  status: "ready";
  plan: NextGwPlan;
  auditPlan: AuditPlan;
  players: PlayerRecord[];
  rules: UserDraftRules;
  loadedGws: number[];
}

type PageState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | ReadyState;

interface StoredDraft {
  version: 1;
  forecastRunId: string;
  season: string;
  playerCodes: number[];
}

function formatPrice(tenths: number | null): string {
  return tenths == null ? "–" : `£${(tenths / 10).toFixed(1)}m`;
}

function formatXp(value: number | null): string {
  return value == null ? "–" : value.toFixed(1);
}

function platformDefaultPlan(plans: readonly NextGwPlan[]): NextGwPlan {
  const defaults = plans.filter((plan) => plan.plan_kind === "platform_default");
  if (defaults.length !== 1) {
    throw new Error(
      `Squad Draft requires exactly one platform-default plan; found ${defaults.length}. ` +
        "Re-publish the dashboard read models.",
    );
  }
  return defaults[0];
}

function matchingAuditPlan(
  plan: NextGwPlan,
  audit: OptimizerAuditData,
): AuditPlan {
  const matches = audit.plans.filter(
    (candidate) =>
      candidate.optimizer_run_id === plan.optimizer_run_id &&
      candidate.decision_sha256 === plan.decision_sha256 &&
      candidate.forecast_run_id === plan.forecast_run_id &&
      candidate.plan_kind === "platform_default" &&
      candidate.season === plan.season &&
      candidate.gw_from === plan.gw_from &&
      candidate.gw_to === plan.gw_to &&
      candidate.as_of === plan.as_of,
  );
  if (matches.length !== 1) {
    throw new Error(
      "Squad Draft cannot find one exact rules snapshot for the platform-default plan. " +
        "Re-publish next_gw.json and optimizer_audit.json together.",
    );
  }
  return matches[0];
}

function resolveReadyState(
  allPlayers: readonly PlayerRecord[],
  plans: readonly NextGwPlan[],
  audit: OptimizerAuditData,
): ReadyState {
  const plan = platformDefaultPlan(plans);
  const auditPlan = matchingAuditPlan(plan, audit);
  const snapshot: RulesSnapshot = auditPlan.rules_snapshot;
  if (snapshot.season !== plan.season || auditPlan.season !== plan.season) {
    throw new Error(
      "Squad Draft rules and platform forecast belong to different seasons. " +
        "Re-publish the dashboard read models together.",
    );
  }
  const rules = deriveUserDraftRules(snapshot);
  const loadedGws = Array.from(
    { length: Math.min(5, plan.gw_to - plan.gw_from + 1) },
    (_, index) => plan.gw_from + index,
  );
  if (loadedGws.length === 0) {
    throw new Error("Squad Draft requires at least one loaded forecast gameweek.");
  }

  const runPlayers = allPlayers.filter(
    (player) =>
      player.run_id === plan.forecast_run_id &&
      player.season === plan.season &&
      player.now_cost != null &&
      Number.isFinite(player.now_cost) &&
      player.now_cost >= 0,
  );
  const codes = new Set(runPlayers.map((player) => player.code));
  if (codes.size !== runPlayers.length) {
    throw new Error(
      "Squad Draft found duplicate players in the platform-default forecast vintage.",
    );
  }
  if (runPlayers.length === 0) {
    throw new Error(
      "Squad Draft found no priced players for the platform-default forecast vintage.",
    );
  }
  return { status: "ready", plan, auditPlan, players: runPlayers, rules, loadedGws };
}

function restoreDraft(
  state: ReadyState,
): { players: PlayerRecord[]; warning: string | null } {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(USER_DRAFT_STORAGE_KEY);
  } catch {
    return {
      players: [],
      warning: "Browser storage is unavailable; this draft will last only for this tab.",
    };
  }
  if (!raw) return { players: [], warning: null };

  let candidate: unknown;
  try {
    candidate = JSON.parse(raw);
  } catch {
    return { players: [], warning: "The saved Squad Draft was invalid and was not restored." };
  }
  if (!candidate || typeof candidate !== "object") {
    return { players: [], warning: "The saved Squad Draft was invalid and was not restored." };
  }
  const stored = candidate as Partial<StoredDraft>;
  if (
    stored.version !== 1 ||
    stored.forecastRunId !== state.plan.forecast_run_id ||
    stored.season !== state.plan.season
  ) {
    return {
      players: [],
      warning: "A saved draft belongs to another forecast vintage, so a new draft was started.",
    };
  }
  if (!Array.isArray(stored.playerCodes)) {
    return { players: [], warning: "The saved Squad Draft was invalid and was not restored." };
  }

  const byCode = new Map(state.players.map((player) => [player.code, player]));
  const restored: PlayerRecord[] = [];
  let dropped = false;
  for (const code of stored.playerCodes) {
    if (!Number.isInteger(code)) {
      dropped = true;
      continue;
    }
    const player = byCode.get(code);
    if (!player || !userDraftSelectionGuard(restored, player, state.rules).allowed) {
      dropped = true;
      continue;
    }
    restored.push(player);
  }
  return {
    players: restored,
    warning: dropped
      ? "Some saved players were unavailable or broke the current structural rules and were omitted."
      : null,
  };
}

function guardReasonLabel(reason: ReturnType<typeof userDraftSelectionGuard>["reason"]): string {
  switch (reason) {
    case "duplicate_player":
      return "Already selected";
    case "squad_full":
      return "Draft is full";
    case "unknown_position":
      return "Position is not in the recorded rules";
    case "position_full":
      return "Position quota is full";
    case "club_full":
      return "Three-player club limit reached";
    default:
      return "Add player";
  }
}

function DraftPager({
  page,
  pageCount,
  total,
  placement,
  onChange,
}: {
  page: number;
  pageCount: number;
  total: number;
  placement: "top" | "bottom";
  onChange: (page: number) => void;
}) {
  const first = total === 0 ? 0 : page * PLAYER_PAGE_SIZE + 1;
  const last = Math.min((page + 1) * PLAYER_PAGE_SIZE, total);
  return (
    <nav
      aria-label={`Squad Draft player pages (${placement})`}
      className={cn(
        "flex items-center justify-between gap-2 rounded-md border bg-background/95 px-2 py-1.5 shadow-sm backdrop-blur",
        placement === "top" ? "sticky top-2 z-20 mb-2" : "mt-3",
      )}
    >
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={page === 0}
        onClick={() => onChange(Math.max(0, page - 1))}
      >
        Previous players
      </Button>
      <span className="text-center text-xs tabular-nums text-muted-foreground">
        Page {page + 1} of {pageCount}
        {total > 0 && (
          <span className="hidden sm:inline"> · showing {first}–{last} of {total}</span>
        )}
      </span>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={page >= pageCount - 1}
        onClick={() => onChange(Math.min(pageCount - 1, page + 1))}
      >
        Next players
      </Button>
    </nav>
  );
}

function SortHeader({
  label,
  sortKey,
  activeKey,
  direction,
  onSort,
  className,
}: {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  direction: SortDirection;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = activeKey === sortKey;
  const Icon = !active ? ArrowUpDown : direction === "asc" ? ArrowUp : ArrowDown;
  return (
    <TableHead
      className={className}
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        className="inline-flex items-center gap-1 hover:text-primary"
        onClick={() => onSort(sortKey)}
        aria-label={`Sort by ${label}`}
      >
        {label} <Icon className="size-3" aria-hidden />
      </button>
    </TableHead>
  );
}

function DraftSquadTable({
  selected,
  rules,
  loadedGws,
  onRemove,
}: {
  selected: readonly PlayerRecord[];
  rules: UserDraftRules;
  loadedGws: readonly number[];
  onRemove: (code: number) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("total5");
  const [direction, setDirection] = useState<SortDirection>("desc");
  const totals = useMemo(() => userDraftTotals(selected, loadedGws), [selected, loadedGws]);
  const projections = useMemo(
    () =>
      new Map(
        selected.map((player) => [player.code, userDraftTotals([player], loadedGws)]),
      ),
    [selected, loadedGws],
  );

  const sorted = useMemo(() => {
    const valueOf = (player: PlayerRecord): string | number | null => {
      const projection = projections.get(player.code);
      if (sortKey === "player") return player.web_name.toLocaleLowerCase();
      if (sortKey === "price") return player.now_cost;
      if (sortKey === "total3") return projection?.totalThreeGameweeksXp ?? null;
      if (sortKey === "total5") return projection?.totalFiveGameweeksXp ?? null;
      return rawPlayerGameweekXp(player, Number(sortKey.slice(3)));
    };
    return [...selected].sort((left, right) => {
      const leftValue = valueOf(left);
      const rightValue = valueOf(right);
      if (leftValue == null && rightValue == null) return left.code - right.code;
      if (leftValue == null) return 1;
      if (rightValue == null) return -1;
      const comparison =
        typeof leftValue === "string" && typeof rightValue === "string"
          ? leftValue.localeCompare(rightValue)
          : Number(leftValue) - Number(rightValue);
      return (direction === "asc" ? comparison : -comparison) || left.code - right.code;
    });
  }, [selected, projections, sortKey, direction]);

  const chooseSort = (next: SortKey) => {
    if (next === sortKey) setDirection((current) => (current === "asc" ? "desc" : "asc"));
    else {
      setSortKey(next);
      setDirection(next === "player" ? "asc" : "desc");
    }
  };

  return (
    <DecisionTableFullscreen label="Squad Draft players table">
      {({ isFullscreen }) => (
        <Table
          containerClassName={cn(isFullscreen && "min-h-0 flex-1 overflow-auto")}
          className="min-w-[980px]"
        >
          <TableCaption className="sr-only">
            Selected Squad Draft players with raw expected points by gameweek.
          </TableCaption>
          <TableHeader className="sticky top-0 z-10 bg-background">
            <TableRow>
              <SortHeader
                label="Player"
                sortKey="player"
                activeKey={sortKey}
                direction={direction}
                onSort={chooseSort}
                className="sticky left-0 z-20 min-w-52 bg-background"
              />
              <TableHead>Team</TableHead>
              <TableHead>Pos</TableHead>
              <SortHeader
                label="Price"
                sortKey="price"
                activeKey={sortKey}
                direction={direction}
                onSort={chooseSort}
                className="text-right"
              />
              <SortHeader
                label="Total 3 GWs xP"
                sortKey="total3"
                activeKey={sortKey}
                direction={direction}
                onSort={chooseSort}
                className="text-right"
              />
              <SortHeader
                label="Total 5 GWs xP"
                sortKey="total5"
                activeKey={sortKey}
                direction={direction}
                onSort={chooseSort}
                className="text-right"
              />
              {loadedGws.map((gw) => (
                <SortHeader
                  key={gw}
                  label={`GW${gw} xP`}
                  sortKey={`gw:${gw}`}
                  activeKey={sortKey}
                  direction={direction}
                  onSort={chooseSort}
                  className="text-right"
                />
              ))}
              <TableHead className="text-right">Remove</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sorted.length === 0 ? (
              <TableRow>
                <TableCell
                  colSpan={7 + loadedGws.length}
                  className="h-24 text-center text-muted-foreground"
                >
                  No players selected. Add anyone from the full player list below.
                </TableCell>
              </TableRow>
            ) : (
              sorted.map((player) => {
                const projection = projections.get(player.code);
                return (
                  <TableRow key={player.code}>
                    <TableCell className="sticky left-0 z-[1] bg-background">
                      <div className="flex items-center gap-2">
                        <PlayerPhoto code={player.code} name={player.web_name} />
                        <span className="font-medium">{player.web_name}</span>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="inline-flex items-center gap-1.5">
                        <TeamBadge
                          teamCode={player.team_code}
                          shortName={player.team_short_name}
                        />
                        {player.team_short_name}
                      </span>
                    </TableCell>
                    <TableCell>{player.position}</TableCell>
                    <TableCell className="text-right tabular-nums">
                      {formatPrice(player.now_cost)}
                    </TableCell>
                    <TableCell className="text-right font-medium tabular-nums">
                      {formatXp(projection?.totalThreeGameweeksXp ?? null)}
                    </TableCell>
                    <TableCell className="text-right font-semibold tabular-nums">
                      {formatXp(projection?.totalFiveGameweeksXp ?? null)}
                    </TableCell>
                    {loadedGws.map((gw) => (
                      <TableCell key={gw} className="text-right tabular-nums">
                        {formatXp(projection?.xpByGw[gw] ?? null)}
                      </TableCell>
                    ))}
                    <TableCell className="text-right">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={`Remove ${player.web_name}`}
                        title={`Remove ${player.web_name}`}
                        onClick={() => onRemove(player.code)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })
            )}
          </TableBody>
          <TableFooter aria-label="Draft squad totals">
            <TableRow>
              <TableCell colSpan={3} role="rowheader" className="font-semibold">
                Draft squad total ({totals.selectedCount}/{rules.squadSize})
              </TableCell>
              <TableCell className="text-right font-semibold tabular-nums">
                {formatPrice(totals.totalCostTenths)}
              </TableCell>
              <TableCell className="text-right font-semibold tabular-nums">
                {formatXp(totals.totalThreeGameweeksXp)}
              </TableCell>
              <TableCell className="text-right font-semibold tabular-nums">
                {formatXp(totals.totalFiveGameweeksXp)}
              </TableCell>
              {loadedGws.map((gw) => (
                <TableCell key={gw} className="text-right font-semibold tabular-nums">
                  {formatXp(totals.xpByGw[gw] ?? null)}
                </TableCell>
              ))}
              <TableCell />
            </TableRow>
          </TableFooter>
        </Table>
      )}
    </DecisionTableFullscreen>
  );
}

export function UserDraftPage() {
  const [state, setState] = useState<PageState>({ status: "loading" });
  const [selected, setSelected] = useState<PlayerRecord[]>([]);
  const [storageWarning, setStorageWarning] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<PlayerFilters>(INITIAL_PLAYER_FILTERS);
  const [page, setPage] = useState(0);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadPlayers(), loadNextGw(), loadOptimizerAudit()])
      .then(([playersData, nextGw, audit]) => {
        if (cancelled) return;
        const ready = resolveReadyState(playersData.players, nextGw.plans, audit);
        const restored = restoreDraft(ready);
        setState(ready);
        setSelected(restored.players);
        setStorageWarning(restored.warning);
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : String(error),
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const persistSelection = (ready: ReadyState, next: PlayerRecord[]) => {
    setSelected(next);
    const payload: StoredDraft = {
      version: 1,
      forecastRunId: ready.plan.forecast_run_id,
      season: ready.plan.season,
      playerCodes: next.map((player) => player.code),
    };
    try {
      window.localStorage.setItem(USER_DRAFT_STORAGE_KEY, JSON.stringify(payload));
      setStorageWarning(null);
    } catch {
      setStorageWarning("Browser storage is unavailable; this draft will last only for this tab.");
    }
  };

  const teams = useMemo(() => {
    if (state.status !== "ready") return [];
    const unique = new Map<number, string>();
    for (const player of state.players) {
      if (!unique.has(player.team_code)) unique.set(player.team_code, player.team_short_name);
    }
    return [...unique.entries()].sort((left, right) => left[1].localeCompare(right[1]));
  }, [state]);

  const candidates = useMemo(() => {
    if (state.status !== "ready") return [];
    const needle = search.trim().toLocaleLowerCase();
    return state.players
      .filter(
        (player) =>
          matchesPlayerFilters(player, filters) &&
          (!needle ||
            player.web_name.toLocaleLowerCase().includes(needle) ||
            player.team_short_name.toLocaleLowerCase().includes(needle) ||
            player.position.toLocaleLowerCase().includes(needle)),
      )
      .map((player) => ({
        player,
        projection: userDraftTotals([player], state.loadedGws),
      }))
      .sort((left, right) => {
        const leftXp = left.projection.totalFiveGameweeksXp;
        const rightXp = right.projection.totalFiveGameweeksXp;
        if (leftXp == null && rightXp == null) {
          return left.player.web_name.localeCompare(right.player.web_name);
        }
        if (leftXp == null) return 1;
        if (rightXp == null) return -1;
        return rightXp - leftXp || left.player.web_name.localeCompare(right.player.web_name);
      });
  }, [state, search, filters]);

  if (state.status === "loading") {
    return <p role="status" className="p-6 text-muted-foreground">Loading Squad Draft…</p>;
  }
  if (state.status === "error") {
    return (
      <div className="p-6">
        <h1 className="mb-2 text-lg font-semibold">Squad Draft</h1>
        <p role="alert" className="max-w-2xl text-sm text-destructive">{state.message}</p>
      </div>
    );
  }

  const structure = userDraftStructure(selected, state.rules);
  const totals = userDraftTotals(selected, state.loadedGws);
  const screen = screenUserDraftHorizon(selected, state.rules, state.loadedGws);
  const lineupContext = buildUserDraftLoadedHorizonContext(
    selected,
    state.rules,
    state.loadedGws,
  );
  const overBudget =
    totals.totalCostTenths != null && totals.totalCostTenths > state.rules.budgetTenths;
  const pageCount = Math.max(1, Math.ceil(candidates.length / PLAYER_PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visibleCandidates = candidates.slice(
    safePage * PLAYER_PAGE_SIZE,
    (safePage + 1) * PLAYER_PAGE_SIZE,
  );

  return (
    <div className="flex flex-col gap-4 p-4 lg:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h1 className="text-lg font-semibold">Squad Draft</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Build a manual what-if squad from the platform forecast. Position quotas and the
            maximum-per-club rule are enforced; cost is shown but never blocks an experimental
            draft. Nothing here runs or replaces the optimizer.
          </p>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <p>{state.plan.season} · GW{state.loadedGws[0]}–GW{state.loadedGws.at(-1)}</p>
          <p title={state.plan.forecast_run_id}>
            platform forecast {state.plan.forecast_run_id.slice(0, 12)}…
          </p>
        </div>
      </div>

      {storageWarning && (
        <p
          role="status"
          className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200"
        >
          {storageWarning}
        </p>
      )}

      <section className="rounded-xl border bg-card p-4 shadow-sm" aria-label="Draft status">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={structure.isComplete ? "default" : "outline"}>
              {structure.isComplete ? <Check className="size-3" /> : null}
              {structure.selectedCount}/{state.rules.squadSize} players
            </Badge>
            {state.rules.positions.map(({ position, squad }) => (
              <Badge key={position} variant="outline">
                {position} {structure.positionCounts[position] ?? 0}/{squad}
              </Badge>
            ))}
            <Badge variant="outline">max {state.rules.maximumPerClub} per club</Badge>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={selected.length === 0}
            onClick={() => persistSelection(state, [])}
          >
            <RotateCcw className="size-3.5" /> Clear draft
          </Button>
        </div>
        <div
          className={cn(
            "mt-3 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm",
            overBudget
              ? "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100"
              : "border-border bg-muted/30 text-muted-foreground",
          )}
        >
          {overBudget && <CircleAlert className="mt-0.5 size-4 shrink-0" />}
          <p>
            Current draft cost <span className="font-semibold text-foreground">{formatPrice(totals.totalCostTenths)}</span>
            {overBudget
              ? ` — ${formatPrice((totals.totalCostTenths ?? 0) - state.rules.budgetTenths)} above the recorded ${formatPrice(state.rules.budgetTenths)} budget. This is allowed here for planning.`
              : ` · recorded budget ${formatPrice(state.rules.budgetTenths)}. Affordability is advisory on this page.`}
          </p>
        </div>
      </section>

      <section aria-labelledby="draft-table-heading" className="space-y-2">
        <div>
          <h2 id="draft-table-heading" className="font-semibold">Your selected players</h2>
          <p className="text-xs text-muted-foreground">
            Raw player xP only. Sort order never changes the totals in the final row.
          </p>
        </div>
        <DraftSquadTable
          selected={selected}
          rules={state.rules}
          loadedGws={state.loadedGws}
          onRemove={(code) =>
            persistSelection(state, selected.filter((player) => player.code !== code))
          }
        />
      </section>

      <section
        className="rounded-xl border bg-card p-4 shadow-sm"
        aria-labelledby="chip-screen-heading"
      >
        <h2 id="chip-screen-heading" className="font-semibold">Loaded-horizon chip screen</h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Descriptive xP context for GW{state.loadedGws[0]}–GW{state.loadedGws.at(-1)} only — not a
          chip recommendation. It does not know chip inventory, later fixtures, future
          availability, autosubs, selling values, or your live team.
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border bg-muted/20 p-3">
            <p className="text-xs font-medium text-muted-foreground">Bench Boost screen</p>
            {lineupContext.highestBenchXpGameweek ? (
              <p className="mt-1 text-sm">
                Highest measured bench after choosing the best legal XI: <strong>GW{lineupContext.highestBenchXpGameweek.gw}</strong>{" "}
                at <strong>{formatXp(lineupContext.highestBenchXpGameweek.benchXp)} xP</strong>.
                This ignores autosubs and every gameweek beyond the loaded horizon.
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">
                Complete a structurally legal {state.rules.squadSize}-player squad to screen the
                projected bench gameweeks. Unknown xP makes that gameweek unavailable.
              </p>
            )}
          </div>
          <div className="rounded-lg border bg-muted/20 p-3">
            <p className="text-xs font-medium text-muted-foreground">Single-player xP screen</p>
            {screen.highestIndividualPlayerGameweek ? (
              <p className="mt-1 text-sm">
                Highest selected-player fixture-week: <strong>{screen.highestIndividualPlayerGameweek.playerName}</strong>{" "}
                in <strong>GW{screen.highestIndividualPlayerGameweek.gw}</strong> at{" "}
                <strong>{formatXp(screen.highestIndividualPlayerGameweek.expectedPoints)} xP</strong>.
                This is only a Triple Captain shortlist signal.
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">
                Add a player to begin the single-player screen.
              </p>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-xl border bg-card p-4 shadow-sm" aria-labelledby="add-player-heading">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="add-player-heading" className="font-semibold">Add players</h2>
            <p className="text-xs text-muted-foreground">
              Full priced roster for the exact platform-default forecast vintage.
            </p>
          </div>
          <Input
            aria-label="Search Squad Draft players"
            className="w-full sm:w-72"
            placeholder="Search player, club, or position"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
          />
        </div>
        <div className="mt-3 rounded-lg border bg-muted/20 p-3">
          <PlayerFiltersBar
            filters={filters}
            teams={teams}
            showFormWindow={false}
            onChange={(next) => {
              setFilters(next);
              setPage(0);
            }}
          />
        </div>

        <div className="mt-3">
          <DraftPager
            page={safePage}
            pageCount={pageCount}
            total={candidates.length}
            placement="top"
            onChange={setPage}
          />
          <ul aria-label="Squad Draft player list" className="grid gap-2 lg:grid-cols-2">
            {visibleCandidates.map(({ player, projection }) => {
              const guard = userDraftSelectionGuard(selected, player, state.rules);
              const isSelected = guard.reason === "duplicate_player";
              const reason = guardReasonLabel(guard.reason);
              return (
                <li
                  key={player.code}
                  className={cn(
                    "flex min-w-0 items-center gap-2 rounded-lg border p-2",
                    guard.reason === "duplicate_player" &&
                      "border-emerald-300 bg-emerald-50/70 dark:border-emerald-800 dark:bg-emerald-950/20",
                  )}
                >
                  <PlayerPhoto code={player.code} name={player.web_name} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{player.web_name}</p>
                    <p className="truncate text-[11px] text-muted-foreground">
                      {player.team_short_name} · {player.position} · {formatPrice(player.now_cost)}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-sm font-semibold tabular-nums">
                      {formatXp(projection.totalFiveGameweeksXp)}
                    </p>
                    <p className="text-[9px] text-muted-foreground">5-GW xP</p>
                  </div>
                  <Button
                    type="button"
                    size="sm"
                    variant={isSelected ? "outline" : "default"}
                    disabled={!isSelected && !guard.allowed}
                    title={isSelected ? `Remove ${player.web_name} from draft` : reason}
                    aria-label={
                      isSelected
                        ? `Remove ${player.web_name} from draft`
                        : guard.allowed
                          ? `Add ${player.web_name}`
                          : `${player.web_name}: ${reason}`
                    }
                    aria-pressed={isSelected}
                    onClick={() =>
                      persistSelection(
                        state,
                        isSelected
                          ? selected.filter((selectedPlayer) => selectedPlayer.code !== player.code)
                          : [...selected, player],
                      )
                    }
                  >
                    {isSelected ? (
                      <Check className="size-3.5" />
                    ) : (
                      <Plus className="size-3.5" />
                    )}
                    {isSelected ? "Selected" : "Add"}
                  </Button>
                </li>
              );
            })}
          </ul>
          {visibleCandidates.length === 0 && (
            <p className="py-8 text-center text-sm text-muted-foreground">
              No priced players match these filters.
            </p>
          )}
          <DraftPager
            page={safePage}
            pageCount={pageCount}
            total={candidates.length}
            placement="bottom"
            onChange={setPage}
          />
        </div>
      </section>

      <p className="text-xs leading-relaxed text-muted-foreground">
        Expected points and prices come from the recorded platform forecast vintage. A blank
        gameweek is zero only when that gameweek is inside the loaded horizon; any unknown fixture
        xP propagates as “–”. Availability is a next-gameweek overlay and is never projected across
        this five-gameweek draft.
      </p>
    </div>
  );
}
