// Official availability status codes -> labels. Reported overlay only: it never folds
// into xP and never means "starts".

import type { PlayerRecord } from "@/data/types";

export const AVAILABILITY_LABEL: Record<string, string> = {
  a: "available",
  d: "doubtful",
  i: "injured",
  s: "suspended",
  u: "unavailable",
  n: "not available",
  x: "not announced",
};

export function availabilityLabel(status: string | null): string {
  if (status == null) return "–";
  return AVAILABILITY_LABEL[status] ?? status;
}

/** Reporting only. Never substitute this value into forecast or optimizer records. */
export function currentAvailability(player: PlayerRecord) {
  const current = player.current_availability;
  return current != null && current.season === player.season && current.code === player.code &&
    current.source === "FPL" && current.semantics === "current_reported_not_forecast"
    ? current : null;
}

export function hasCurrentAvailabilityConcern(player: PlayerRecord): boolean {
  const current = currentAvailability(player);
  return current != null && (
    (current.status != null && current.status !== "a") ||
    (current.chance_of_playing_next_round != null && current.chance_of_playing_next_round < 100)
  );
}
