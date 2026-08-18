import { Badge } from "@/components/ui/badge";
import type { PlanWeek } from "@/data/types";

const POSITION_ORDER = ["GK", "DEF", "MID", "FWD"] as const;

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

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
