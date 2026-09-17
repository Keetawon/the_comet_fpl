import type { PlayerRecord } from "@/data/types";
import { userDraftSelectionGuard, userDraftStructure, type UserDraftRules } from "./userDraft";

/** Latest publicly revealed picks, explicitly not authenticated current ownership. */
export interface PublicManagerSquad {
  schema: "fpl.public-manager-squad";
  schema_version: 1;
  source: "official_fpl_public_picks";
  manager_id: number;
  season: string;
  picks_event: number;
  picks_deadline: string;
  planning_gw: number | null;
  active_chip: string | null;
  captured_at: string;
  snapshot_id: string;
  players: { element_id: number; code: number; position: string; team_code: number }[];
}

export function publicManagerImportUrl(): string | null {
  const configured = import.meta.env.VITE_PUBLIC_MANAGER_IMPORT_URL?.trim();
  if (!configured) return null;
  try {
    const url = new URL(configured);
    if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash ||
        url.pathname !== "/manager-team") return null;
    return url.href;
  } catch { return null; }
}

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid public squad response.");
  return value as Record<string, unknown>;
}

function positive(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

function date(value: unknown): value is string {
  return typeof value === "string" && /(Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
}

export function parsePublicManagerSquad(payload: unknown, managerId: number): PublicManagerSquad {
  const value = object(payload);
  if (value.schema !== "fpl.public-manager-squad" || value.schema_version !== 1 ||
      value.source !== "official_fpl_public_picks" || value.manager_id !== managerId ||
      typeof value.season !== "string" || !/^\d{4}-\d{2}$/.test(value.season) ||
      !positive(value.picks_event) || value.picks_event > 38 ||
      !(value.planning_gw === null || positive(value.planning_gw) && value.planning_gw > value.picks_event && value.planning_gw <= 38) ||
      !(value.active_chip === null || typeof value.active_chip === "string") ||
      !date(value.picks_deadline) || !date(value.captured_at) ||
      Date.parse(value.picks_deadline) > Date.parse(value.captured_at) ||
      typeof value.snapshot_id !== "string" || !/^[a-f0-9]{64}$/.test(value.snapshot_id) ||
      !Array.isArray(value.players) || value.players.length !== 15) {
    throw new Error("Public squad identity or gameweek evidence is incomplete.");
  }
  const players = value.players.map(raw => {
    const player = object(raw);
    if (!positive(player.element_id) || !positive(player.code) || !positive(player.team_code) ||
        typeof player.position !== "string" || !["GK", "DEF", "MID", "FWD"].includes(player.position)) {
      throw new Error("Public squad contains an invalid player identity.");
    }
    return { element_id: player.element_id, code: player.code, team_code: player.team_code, position: player.position };
  });
  if (new Set(players.map(player => player.code)).size !== 15 || new Set(players.map(player => player.element_id)).size !== 15) {
    throw new Error("Public squad contains duplicate players.");
  }
  // Explicit projection: never propagate additional upstream manager fields into page state.
  return {
    schema: "fpl.public-manager-squad", schema_version: 1, source: "official_fpl_public_picks",
    manager_id: managerId, season: value.season, picks_event: value.picks_event,
    planning_gw: value.planning_gw as number | null, picks_deadline: value.picks_deadline,
    captured_at: value.captured_at, snapshot_id: value.snapshot_id,
    active_chip: value.active_chip as string | null, players,
  };
}

export async function fetchPublicManagerTeam(managerId: string, signal?: AbortSignal): Promise<PublicManagerSquad> {
  const clean = managerId.trim();
  if (!/^\d{1,10}$/.test(clean) || Number(clean) <= 0) throw new Error("Enter a positive FPL manager ID.");
  const url = publicManagerImportUrl();
  if (!url) throw new Error("Online Manager ID import has not been enabled yet. You can still build your draft manually.");
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ manager_id: Number(clean) }), credentials: "omit", cache: "no-store",
      referrerPolicy: "no-referrer", redirect: "error",
      signal: signal ?? AbortSignal.timeout(30_000),
    });
  } catch {
    throw new Error("Could not reach FPL team import. Please try again shortly.");
  }
  let payload: unknown;
  try { payload = await response.json(); }
  catch { throw new Error("FPL team import returned an unreadable response."); }
  if (!response.ok) {
    const error = object(payload).error;
    throw new Error(typeof error === "string" && error.length <= 300 ? error : `Team import failed (${response.status}).`);
  }
  return parsePublicManagerSquad(payload, Number(clean));
}

/** Atomic membership import; prices and every xP remain the selected published values. */
export function publicSquadDraft(
  squad: PublicManagerSquad,
  forecast: { season: string; gw_from: number },
  players: readonly PlayerRecord[],
  rules: UserDraftRules,
): PlayerRecord[] {
  if (squad.season !== forecast.season || squad.planning_gw !== forecast.gw_from) {
    throw new Error(`The public team is from ${squad.season} GW${squad.picks_event}, but this forecast is not for its next planning GW. Refresh the published forecast before importing.`);
  }
  const selected: PlayerRecord[] = [];
  for (const member of squad.players) {
    const matches = players.filter(player => player.code === member.code && player.season === squad.season);
    const player = matches[0];
    if (matches.length !== 1 || player.position !== member.position || player.team_code !== member.team_code) {
      throw new Error(`Player ${member.code} does not match this forecast's position and club. The dashboard needs a matching roster refresh.`);
    }
    const guard = userDraftSelectionGuard(selected, player, rules);
    if (!guard.allowed) throw new Error(`The imported squad does not meet the draft's squad rules (${guard.reason}).`);
    selected.push(player);
  }
  if (!userDraftStructure(selected, rules).isComplete) throw new Error("A complete 15-player squad is required.");
  return selected;
}
