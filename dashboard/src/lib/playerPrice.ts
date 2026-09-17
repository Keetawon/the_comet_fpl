import type { PlayerRecord } from "@/data/types";

export type PlayerPriceSource = "current" | "forecast";

export function currentPrice(player: PlayerRecord) {
  const current = player.current_price;
  return current != null && current.season === player.season && current.code === player.code &&
    current.source === "FPL" && current.semantics === "current_reported_not_forecast"
    ? current : null;
}

/** Display only. The original now_cost remains the planning/optimizer price. */
export function playerPrice(player: PlayerRecord, source: PlayerPriceSource): number | null {
  if (source === "forecast") return player.now_cost;
  return currentPrice(player)?.now_cost ?? null;
}

export function playerPriceTitle(player: PlayerRecord, source: PlayerPriceSource): string {
  if (source === "forecast") return `Forecast price · ${player.as_of}`;
  const current = currentPrice(player);
  return current
    ? `Current FPL price · captured ${current.captured_at}. Forecast price and published xP are unchanged.`
    : "Current FPL price unavailable; refresh the published data. Forecast price has not been substituted.";
}
