// Shared player filters (position/team/price/minutes/availability/form window) plus the
// matching predicate. Used inside a FilterPanel by the Players page and the Next GW
// page's squad table. Unmeasured values never satisfy a bound: null is not 0.

import { useMemo } from "react";
import { Input } from "@/components/ui/input";
import { MultiSelectFilter } from "@/components/MultiSelectFilter";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { PlayerRecord, WindowLabel } from "@/data/types";
import { WINDOW_LABELS } from "@/data/types";

export interface PlayerFilters {
  position: string; // "all" | GK | DEF | MID | FWD
  teamCode: string; // "all" | String(team_code)
  minPrice: string; // £m, "" = unbounded
  maxPrice: string; // £m, "" = unbounded
  minMinutes: string; // L5 in shared routes; selected-Actual Min/g on Players; "" = unbounded
  availability: "all" | "available" | "flagged";
  formWindow: WindowLabel;
}

export const INITIAL_PLAYER_FILTERS: PlayerFilters = {
  position: "all",
  teamCode: "all",
  minPrice: "",
  maxPrice: "",
  minMinutes: "",
  availability: "all",
  formWindow: "last_5",
};

export const POSITIONS = ["GK", "DEF", "MID", "FWD"] as const;
export type PlayerPosition = (typeof POSITIONS)[number];

export interface PlayerMultiFilters {
  playerCodes: number[];
  positions: PlayerPosition[];
  teamCodes: number[];
}

export const FORM_WINDOW_LABEL: Record<WindowLabel, string> = {
  last_3: "Last 3",
  last_5: "Last 5",
  last_10: "Last 10",
  season_to_date: "Season",
};

export function matchesPlayerFilters(p: PlayerRecord, f: PlayerFilters): boolean {
  const minPrice = f.minPrice === "" ? null : Number(f.minPrice) * 10;
  const maxPrice = f.maxPrice === "" ? null : Number(f.maxPrice) * 10;
  const minMinutes = f.minMinutes === "" ? null : Number(f.minMinutes);
  if (f.position !== "all" && p.position !== f.position) return false;
  if (f.teamCode !== "all" && String(p.team_code) !== f.teamCode) return false;
  if (minPrice != null && !(p.now_cost != null && p.now_cost >= minPrice)) return false;
  if (maxPrice != null && !(p.now_cost != null && p.now_cost <= maxPrice)) return false;
  if (minMinutes != null && !(p.avg_minutes_last_5 != null && p.avg_minutes_last_5 >= minMinutes))
    return false;
  if (f.availability === "available" && p.availability_status !== "a") return false;
  if (
    f.availability === "flagged" &&
    !(p.availability_status != null && p.availability_status !== "a")
  )
    return false;
  return true;
}

interface PlayerFiltersBarProps {
  filters: PlayerFilters;
  onChange: (filters: PlayerFilters) => void;
  teams: [number, string][];
  /** The form-window select does not apply everywhere (e.g. the plan-builder picker); hide it there. */
  showFormWindow?: boolean;
  /** Players-table mode follows its explicit observed Actual range; all other routes keep L5. */
  minutesFilterKind?: "forecast_last_five" | "selected_actual_per_game";
  /** Players-table mode: searchable names plus multi-select position/team dimensions. */
  multiSelect?: {
    players: readonly PlayerRecord[];
    filters: PlayerMultiFilters;
    onChange: (filters: PlayerMultiFilters) => void;
  };
}

export function PlayerFiltersBar({
  filters,
  onChange,
  teams,
  showFormWindow = true,
  minutesFilterKind = "forecast_last_five",
  multiSelect,
}: PlayerFiltersBarProps) {
  const set = (patch: Partial<PlayerFilters>) => onChange({ ...filters, ...patch });
  const setMulti = (patch: Partial<PlayerMultiFilters>) => {
    if (multiSelect) multiSelect.onChange({ ...multiSelect.filters, ...patch });
  };
  const playerOptions = useMemo(
    () =>
      multiSelect == null
        ? []
        : [...multiSelect.players]
            .sort(
              (left, right) =>
                left.web_name.localeCompare(right.web_name) || left.code - right.code,
            )
            .map((player) => ({
              value: player.code,
              label: `${player.web_name} · ${player.team_short_name} · ${player.position}`,
              searchText: `${player.team_short_name} ${player.position}`,
            })),
    [multiSelect],
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm text-muted-foreground">
      {multiSelect ? (
        <>
          <MultiSelectFilter
            label="Player"
            ariaLabel="Player name filter"
            allLabel="All players"
            options={playerOptions}
            selected={multiSelect.filters.playerCodes}
            onChange={(playerCodes) => setMulti({ playerCodes })}
            searchable
            searchLabel="Search player names"
            emptyLabel="No players match that search"
          />
          <MultiSelectFilter
            label="Position"
            ariaLabel="Position filter"
            allLabel="All positions"
            options={POSITIONS.map((position) => ({ value: position, label: position }))}
            selected={multiSelect.filters.positions}
            onChange={(positions) => setMulti({ positions })}
          />
          <MultiSelectFilter
            label="Team"
            ariaLabel="Team filter"
            allLabel="All teams"
            options={teams.map(([code, short]) => ({ value: code, label: short }))}
            selected={multiSelect.filters.teamCodes}
            onChange={(teamCodes) => setMulti({ teamCodes })}
            searchable
            searchLabel="Search teams"
            emptyLabel="No teams match that search"
          />
        </>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <span>Position</span>
            <Select value={filters.position} onValueChange={(value) => set({ position: value })}>
              <SelectTrigger size="sm" className="w-24" aria-label="Position filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                {POSITIONS.map((p) => (
                  <SelectItem key={p} value={p}>
                    {p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-2">
            <span>Team</span>
            <Select value={filters.teamCode} onValueChange={(value) => set({ teamCode: value })}>
              <SelectTrigger size="sm" className="w-28" aria-label="Team filter">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                {teams.map(([code, short]) => (
                  <SelectItem key={code} value={String(code)}>
                    {short}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </>
      )}
      <div className="flex items-center gap-1">
        <span>Price £m</span>
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          step={0.5}
          placeholder="min"
          aria-label="Minimum price in millions"
          className="h-8 w-20"
          value={filters.minPrice}
          onChange={(e) => set({ minPrice: e.target.value })}
        />
        <span>–</span>
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          step={0.5}
          placeholder="max"
          aria-label="Maximum price in millions"
          className="h-8 w-20"
          value={filters.maxPrice}
          onChange={(e) => set({ maxPrice: e.target.value })}
        />
      </div>
      <div className="flex items-center gap-2">
        <span
          title={
            minutesFilterKind === "selected_actual_per_game"
              ? "Observed minutes divided by games played in the selected Actual range; zero-minute DNPs are excluded"
              : undefined
          }
        >
          {minutesFilterKind === "selected_actual_per_game" ? "Min min/g" : "Min avg min (L5)"}
        </span>
        <Input
          type="number"
          inputMode="numeric"
          min={0}
          step={10}
          placeholder="any"
          aria-label={
            minutesFilterKind === "selected_actual_per_game"
              ? "Minimum observed minutes per game played in selected Actual range"
              : "Minimum average minutes over the last 5"
          }
          className="h-8 w-20"
          value={filters.minMinutes}
          onChange={(e) => set({ minMinutes: e.target.value })}
        />
      </div>
      <ToggleGroup
        type="single"
        value={filters.availability}
        onValueChange={(value) => {
          if (value) set({ availability: value as PlayerFilters["availability"] });
        }}
        variant="outline"
        aria-label="Availability filter"
      >
        <ToggleGroupItem value="all">All</ToggleGroupItem>
        <ToggleGroupItem value="available">Available</ToggleGroupItem>
        <ToggleGroupItem value="flagged">Flagged</ToggleGroupItem>
      </ToggleGroup>
      {showFormWindow && (
        <div className="flex items-center gap-2">
          <span>Past form window</span>
          <Select
            value={filters.formWindow}
            onValueChange={(value) => set({ formWindow: value as WindowLabel })}
          >
            <SelectTrigger size="sm" className="w-28" aria-label="Past form window">
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
      )}
    </div>
  );
}
