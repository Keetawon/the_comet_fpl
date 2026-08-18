import { useState } from "react";
import { ArrowDownUp, ChevronDown, ChevronRight } from "lucide-react";
import { PlayerPhoto, TeamBadge } from "@/components/Avatars";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { NextGwPlan, PlanPlayer, PlanWeek } from "@/data/types";
import { horizonXp } from "@/lib/nextGw";
import { cn } from "@/lib/utils";

const POSITION_ORDER = ["GK", "DEF", "MID", "FWD"] as const;

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

const price = (value: number | null) =>
  value == null ? "–" : `£${(value / 10).toFixed(1)}m`;

function planPlayerOrder(left: PlanPlayer, right: PlanPlayer): number {
  const leftRole = left.role === "starting_xi" ? 0 : 1;
  const rightRole = right.role === "starting_xi" ? 0 : 1;
  return (
    leftRole - rightRole ||
    (leftRole === 0
      ? POSITION_ORDER.indexOf(left.position as (typeof POSITION_ORDER)[number]) -
        POSITION_ORDER.indexOf(right.position as (typeof POSITION_ORDER)[number])
      : left.role === "bench_goalkeeper"
        ? -1
        : right.role === "bench_goalkeeper"
          ? 1
          : (left.bench_order_index ?? 99) - (right.bench_order_index ?? 99)) ||
    left.web_name.localeCompare(right.web_name) ||
    left.code - right.code
  );
}

function roleLabel(player: PlanPlayer): string {
  if (player.role === "starting_xi") return "Starting XI";
  if (player.role === "bench_goalkeeper") return "Bench GK";
  return `Bench ${player.bench_order_index ?? ""}`.trim();
}

function membershipLabel(player: PlanPlayer | undefined): string {
  if (!player) return "Not in post-transfer squad";
  const labels = [roleLabel(player)];
  if (player.is_captain) labels.push("captain");
  if (player.is_vice_captain) labels.push("vice-captain");
  if (player.transferred_in) labels.push("transferred in");
  return labels.join(" · ");
}

type SortDirection = "asc" | "desc";
interface PlanSort {
  weeks: number;
  direction: SortDirection;
}

/** A compact, plan-bound analysis table. The fifteen rows and all role styling are fixed to
 * GW1; sorting changes display order only. Cumulative values come strictly from the artifact's
 * player_xp map, so no other forecast vintage can be substituted. */
export function PlanSquadTable({ plan }: { plan: NextGwPlan }) {
  const [sort, setSort] = useState<PlanSort | null>(null);
  const [expandedCodes, setExpandedCodes] = useState<Set<number>>(() => new Set());
  const firstWeek = plan.weeks[0];
  if (!firstWeek) {
    return (
      <p role="alert" className="text-sm text-destructive">
        The exact custom plan has no gameweek rows.
      </p>
    );
  }
  const uniqueCodes = new Set(firstWeek.players.map((player) => player.code));
  const starters = firstWeek.players.filter((player) => player.role === "starting_xi");
  const benchGoalkeepers = firstWeek.players.filter(
    (player) => player.role === "bench_goalkeeper",
  );
  const benchOutfield = firstWeek.players.filter((player) => player.role === "bench_outfield");
  const captains = firstWeek.players.filter((player) => player.is_captain);
  const viceCaptains = firstWeek.players.filter((player) => player.is_vice_captain);
  const validSquadShape =
    firstWeek.players.length === 15 &&
    uniqueCodes.size === 15 &&
    starters.length === 11 &&
    benchGoalkeepers.length === 1 &&
    benchOutfield.length === 3 &&
    captains.length === 1 &&
    viceCaptains.length === 1 &&
    captains[0]?.role === "starting_xi" &&
    viceCaptains[0]?.role === "starting_xi" &&
    captains[0]?.code !== viceCaptains[0]?.code &&
    captains[0]?.code === firstWeek.captain_code &&
    viceCaptains[0]?.code === firstWeek.vice_captain_code;
  if (!validSquadShape) {
    return (
      <p role="alert" className="text-sm text-destructive">
        The exact custom plan failed the GW{firstWeek.gw} squad contract. Expected 15 unique
        players: 11 starters, one bench goalkeeper, three bench outfield players, and distinct
        starting captain and vice-captain.
      </p>
    );
  }
  const horizon = Math.min(5, Math.max(0, plan.gw_to - plan.gw_from + 1));
  const horizons = Array.from({ length: horizon }, (_, index) => index + 1);
  const horizonGws = horizons.map((weeks) => plan.gw_from + weeks - 1);
  const baseline = [...firstWeek.players].sort(planPlayerOrder);
  const rows = sort
    ? [...baseline].sort((left, right) => {
        const leftXp = horizonXp(plan, left.code, sort.weeks);
        const rightXp = horizonXp(plan, right.code, sort.weeks);
        if (leftXp == null && rightXp == null) return left.code - right.code;
        if (leftXp == null) return 1;
        if (rightXp == null) return -1;
        const difference = sort.direction === "desc" ? rightXp - leftXp : leftXp - rightXp;
        return difference || left.code - right.code;
      })
    : baseline;

  const toggleSort = (weeks: number) => {
    setSort((current) => {
      if (!current || current.weeks !== weeks) return { weeks, direction: "desc" };
      if (current.direction === "desc") return { weeks, direction: "asc" };
      return null;
    });
  };
  const toggleExpanded = (code: number) => {
    setExpandedCodes((current) => {
      const next = new Set(current);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <div className="space-y-2">
      <p className="text-xs leading-relaxed text-muted-foreground">
        Row colours and role labels show the fixed GW{firstWeek.gw} decision; sorting changes
        display order only. Select a cumulative xP heading to rank the squad, or expand a player
        for gameweek detail.
      </p>
      <div className="overflow-hidden rounded-lg border bg-card shadow-sm">
        <Table aria-label={`GW${firstWeek.gw} custom squad analysis`}>
          <TableHeader>
            <TableRow className="bg-muted/40 hover:bg-muted/40">
              <TableHead className="h-8 w-8 px-1">
                <span className="sr-only">Gameweek details</span>
              </TableHead>
              <TableHead className="h-8 text-xs">Player</TableHead>
              <TableHead className="h-8 text-xs">GW{firstWeek.gw} role</TableHead>
              <TableHead className="h-8 text-xs">Position</TableHead>
              <TableHead className="h-8 text-xs">Price</TableHead>
              {horizons.map((weeks) => {
                const direction = sort?.weeks === weeks ? sort.direction : null;
                const throughGw = plan.gw_from + weeks - 1;
                return (
                  <TableHead
                    key={weeks}
                    className="h-8 text-right text-xs"
                    aria-sort={
                      direction === "asc"
                        ? "ascending"
                        : direction === "desc"
                          ? "descending"
                          : undefined
                    }
                  >
                    <button
                      type="button"
                      onClick={() => toggleSort(weeks)}
                      className="ml-auto inline-flex items-center gap-1 whitespace-nowrap font-medium"
                      aria-label={`Sort by cumulative player xP from GW${plan.gw_from} through GW${throughGw}`}
                    >
                      {weeks} GW{weeks === 1 ? "" : "s"} xP
                      <ArrowDownUp className="size-3" aria-hidden />
                    </button>
                  </TableHead>
                );
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.flatMap((player) => {
              const expanded = expandedCodes.has(player.code);
              const detailId = `plan-player-details-${player.code}`;
              const bench = player.role !== "starting_xi";
              const rowClass = player.is_captain
                ? "border-l-4 border-l-amber-500 bg-amber-100/70 dark:bg-amber-950/40"
                : player.is_vice_captain
                  ? "border-l-4 border-l-amber-300 bg-amber-50 dark:border-l-amber-700 dark:bg-amber-950/20"
                  : bench
                    ? "border-l-4 border-l-transparent bg-zinc-200 dark:bg-zinc-800/80"
                    : undefined;
              const mainRow = (
                <TableRow key={`player-${player.code}`} data-player-code={player.code} className={rowClass}>
                  <TableCell className="px-1 py-1.5">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="size-7"
                      aria-label={`${expanded ? "Hide" : "Show"} gameweek details for ${player.web_name}`}
                      aria-expanded={expanded}
                      aria-controls={detailId}
                      onClick={() => toggleExpanded(player.code)}
                    >
                      {expanded ? (
                        <ChevronDown className="size-4" aria-hidden />
                      ) : (
                        <ChevronRight className="size-4" aria-hidden />
                      )}
                    </Button>
                  </TableCell>
                  <TableCell className="py-1.5">
                    <div className="flex min-w-44 items-center gap-1.5">
                      <PlayerPhoto code={player.code} name={player.web_name} />
                      <div className="min-w-0">
                        <div className="flex items-center gap-1 font-medium">
                          <span className="truncate">{player.web_name}</span>
                          {player.is_captain && (
                            <Badge
                              className="px-1 text-[9px]"
                              aria-label={`Captain: ${player.web_name}`}
                              title="Captain"
                            >
                              C
                            </Badge>
                          )}
                          {player.is_vice_captain && (
                            <Badge
                              variant="outline"
                              className="px-1 text-[9px]"
                              aria-label={`Vice-captain: ${player.web_name}`}
                              title="Vice-captain"
                            >
                              V
                            </Badge>
                          )}
                        </div>
                        <div className="flex items-center gap-1 text-xs text-muted-foreground">
                          <TeamBadge
                            teamCode={player.team_code}
                            shortName={player.team_short_name}
                          />
                          <span>{player.team_short_name}</span>
                        </div>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className={cn("py-1.5 text-xs", bench && "font-medium")}>
                    {roleLabel(player)}
                  </TableCell>
                  <TableCell className="py-1.5 text-xs">{player.position}</TableCell>
                  <TableCell className="py-1.5 text-xs tabular-nums">
                    {price(player.now_cost)}
                  </TableCell>
                  {horizons.map((weeks) => (
                    <TableCell key={weeks} className="py-1.5 text-right text-xs font-medium tabular-nums">
                      {fmt(horizonXp(plan, player.code, weeks))}
                    </TableCell>
                  ))}
                </TableRow>
              );
              if (!expanded) return [mainRow];
              return [
                mainRow,
                <TableRow key={`details-${player.code}`} className="bg-muted/20 hover:bg-muted/20">
                  <TableCell colSpan={5 + horizons.length} className="p-0 whitespace-normal">
                    <div id={detailId} className="grid gap-2 p-3 sm:grid-cols-2 lg:grid-cols-5">
                      {horizonGws.map((gw) => {
                        const planWeek = plan.weeks.find((candidate) => candidate.gw === gw);
                        const membership = planWeek?.players.find(
                          (candidate) => candidate.code === player.code,
                        );
                        const rawXp = plan.player_xp[String(player.code)]?.[String(gw)];
                        return (
                          <div key={gw} className="rounded-md border bg-background/80 p-2">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-xs font-medium">GW{gw}</span>
                              <span className="text-xs font-semibold tabular-nums">
                                {fmt(rawXp)} xP
                              </span>
                            </div>
                            <p className="mt-1 text-[10px] leading-relaxed text-muted-foreground">
                              {planWeek ? membershipLabel(membership) : "Plan role unavailable"}
                            </p>
                          </div>
                        );
                      })}
                    </div>
                  </TableCell>
                </TableRow>,
              ];
            })}
          </TableBody>
        </Table>
      </div>
      <p className="text-[10px] leading-relaxed text-muted-foreground">
        Cumulative columns are the player's unconditional forecast from GW{plan.gw_from} onward.
        They continue after a later planned transfer-out and are not plan contribution, captain
        weighting, or bench weighting. Null stays unmeasured and sorts last. Gold = captain · pale
        gold = vice-captain · grey = bench.
      </p>
    </div>
  );
}

export function XiBlock({ week }: { week: PlanWeek }) {
  const xi = week.players.filter((player) => player.role === "starting_xi");
  const formation = POSITION_ORDER.map(
    (position) => xi.filter((player) => player.position === position).length,
  );
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Formation {formation.slice(1).join("-")} · captain{" "}
        <span className="font-medium text-foreground">
          {xi.find((player) => player.code === week.captain_code)?.web_name ??
            week.captain_code}
        </span>{" "}
        · vice{" "}
        <span className="font-medium text-foreground">
          {xi.find((player) => player.code === week.vice_captain_code)?.web_name ??
            week.vice_captain_code}
        </span>
      </p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {POSITION_ORDER.map((position) => (
          <div key={position} className="rounded-md border p-2">
            <p className="mb-1 text-[10px] font-medium text-muted-foreground">{position}</p>
            <ul className="space-y-1 text-sm">
              {xi
                .filter((player) => player.position === position)
                .map((player) => (
                  <li key={player.code} className="flex items-baseline justify-between gap-1">
                    <span className="truncate">
                      {player.web_name}
                      {player.is_captain && (
                        <Badge className="ml-1 size-fit px-1 text-[9px]">C</Badge>
                      )}
                      {player.is_vice_captain && (
                        <Badge variant="outline" className="ml-1 size-fit px-1 text-[9px]">
                          V
                        </Badge>
                      )}
                    </span>
                    <span className="tabular-nums text-xs text-muted-foreground">
                      {fmt(player.expected_points)}
                    </span>
                  </li>
                ))}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BenchBlock({ week }: { week: PlanWeek }) {
  const bench = week.players
    .filter((player) => player.role !== "starting_xi")
    .sort((left, right) => {
      if (left.role === "bench_goalkeeper") return -1;
      if (right.role === "bench_goalkeeper") return 1;
      return (left.bench_order_index ?? 99) - (right.bench_order_index ?? 99);
    });
  return (
    <div className="rounded-md border p-2">
      <p className="mb-1 text-[10px] font-medium text-muted-foreground">
        Bench (autosub order; the goalkeeper covers first)
      </p>
      <ol className="space-y-1 text-sm">
        {bench.map((player) => (
          <li key={player.code} className="flex items-baseline justify-between gap-1">
            <span className="truncate">
              {player.web_name}
              <span className="ml-1 text-xs text-muted-foreground">{player.position}</span>
            </span>
            <span className="tabular-nums text-xs text-muted-foreground">
              {fmt(player.expected_points)}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function TransferPath({ weeks }: { weeks: PlanWeek[] }) {
  return (
    <div className="rounded-md border p-2">
      <p className="mb-1 text-[10px] font-medium text-muted-foreground">
        Transfer path over the horizon (frozen prices; no price-change model)
      </p>
      <ul className="space-y-1 text-sm">
        {weeks.map((week) => {
          const incoming = week.players.filter((player) => player.transferred_in);
          const outgoing = week.players.filter((player) => player.transferred_out);
          return (
            <li key={week.gw} className="tabular-nums">
              <span className="font-medium">GW{week.gw}</span> · hit -{week.hit_points}
              {incoming.length || outgoing.length ? (
                <span className="text-muted-foreground">
                  {" "}
                  in: {incoming.map((player) => player.web_name).join(", ") || "–"} · out:{" "}
                  {outgoing.map((player) => player.web_name).join(", ") || "–"}
                </span>
              ) : (
                <span className="text-muted-foreground"> no transfers</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
