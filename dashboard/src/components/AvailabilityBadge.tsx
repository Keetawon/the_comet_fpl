import type { PlayerRecord } from "@/data/types";
import { availabilityLabel, currentAvailability, hasCurrentAvailabilityConcern } from "@/lib/availability";

function timestamp(value: string): string {
  return Number.isFinite(Date.parse(value))
    ? `${new Date(value).toISOString().slice(0, 16).replace("T", " ")} UTC`
    : "unknown date";
}

export function AvailabilityBadge({ player, details = false }: { player: PlayerRecord; details?: boolean }) {
  const current = currentAvailability(player);
  const legacy = player.current_availability === undefined;
  const status = current?.status ?? (legacy ? player.availability_status : null);
  const chance = current ? current.chance_of_playing_next_round : legacy ? player.chance_of_playing : null;
  const label = `${status == null ? "Unknown" : availabilityLabel(status)}${chance == null ? "" : ` · ${chance}%`}`;
  const source = current
    ? `FPL · ${current.next_gw == null ? "next GW unknown" : `${current.season} GW${current.next_gw}`} · captured ${timestamp(current.captured_at)}`
    : legacy
      ? `Forecast status · ${timestamp(player.as_of)}`
      : "Current FPL availability not published";
  const title = [source, current?.news, "Reported availability only; published xP is unchanged."].filter(Boolean).join("\n");
  const tone = status === "i" || status === "s" || chance === 0
    ? "rounded bg-red-900 px-1.5 py-0.5 text-white dark:bg-red-950 dark:text-red-50"
    : hasCurrentAvailabilityConcern(player)
      ? "text-amber-600 dark:text-amber-400"
      : "text-muted-foreground";
  return (
    <span className="inline-flex flex-col text-xs" title={title}>
      <span className={`self-start whitespace-nowrap font-medium tabular-nums ${tone}`}>
        {label}
      </span>
      {(legacy || details) && <span className="text-[10px] text-muted-foreground">{source}</span>}
      {details && current?.news && <span className="text-muted-foreground">{current.news}</span>}
    </span>
  );
}
