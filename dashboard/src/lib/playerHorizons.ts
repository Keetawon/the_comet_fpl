// Exact lookup over precomputed cumulative player outcomes. Probability arithmetic belongs
// to the Python emitter; this module only selects one published vintage/player/endpoint.

import type { PlayerHorizon, PlayerHorizonsRecord } from "@/data/types";

export type PlayerHorizonIndex = ReadonlyMap<string, PlayerHorizon>;

function horizonKey(runId: string, season: string, code: number, gwTo: number): string {
  return JSON.stringify([runId, season, code, gwTo]);
}

export function indexPlayerHorizons(
  records: readonly PlayerHorizonsRecord[],
): PlayerHorizonIndex {
  const index = new Map<string, PlayerHorizon>();
  for (const record of records) {
    for (const horizon of record.horizons) {
      const key = horizonKey(record.run_id, record.season, record.code, horizon.gw_to);
      if (index.has(key)) throw new Error(`duplicate player horizon ${key}`);
      index.set(key, horizon);
    }
  }
  return index;
}

export function playerHorizon(
  index: PlayerHorizonIndex,
  runId: string,
  season: string,
  code: number,
  gwTo: number,
): PlayerHorizon | null {
  return index.get(horizonKey(runId, season, code, gwTo)) ?? null;
}
