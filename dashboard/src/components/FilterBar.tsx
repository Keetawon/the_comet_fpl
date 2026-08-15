// Fixture-matrix controls: Overall/Attack/Defense view, venue filter, and a gameweek-range
// control bounded by the vintage horizon. The colour-source toggle lives in the legend
// (DifficultyLegend) so it always sits beside the scale it switches.

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { ViewMode } from "@/lib/difficulty";

export interface FilterState {
  view: ViewMode;
  venue: "all" | "home" | "away";
  gwFrom: number;
  gwTo: number;
}

interface FilterBarProps {
  filters: FilterState;
  onChange: (filters: FilterState) => void;
  minGw: number;
  maxGw: number;
}

const gwOptions = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => from + i);

export function FilterBar({ filters, onChange, minGw, maxGw }: FilterBarProps) {
  const gwFromOptions = gwOptions(minGw, filters.gwTo);
  const gwToOptions = gwOptions(filters.gwFrom, maxGw);
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <ToggleGroup
        type="single"
        value={filters.view}
        onValueChange={(value) => {
          if (value) onChange({ ...filters, view: value as ViewMode });
        }}
        variant="outline"
        aria-label="View"
      >
        <ToggleGroupItem value="overall">Overall</ToggleGroupItem>
        <ToggleGroupItem value="attack">Attack</ToggleGroupItem>
        <ToggleGroupItem value="defense">Defense</ToggleGroupItem>
      </ToggleGroup>
      <ToggleGroup
        type="single"
        value={filters.venue}
        onValueChange={(value) => {
          if (value) onChange({ ...filters, venue: value as FilterState["venue"] });
        }}
        variant="outline"
        aria-label="Venue filter"
      >
        <ToggleGroupItem value="all">All</ToggleGroupItem>
        <ToggleGroupItem value="home">Home</ToggleGroupItem>
        <ToggleGroupItem value="away">Away</ToggleGroupItem>
      </ToggleGroup>
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <span>Gameweeks</span>
        <Select
          value={String(filters.gwFrom)}
          onValueChange={(value) =>
            onChange({ ...filters, gwFrom: Math.min(Number(value), filters.gwTo) })
          }
        >
          <SelectTrigger size="sm" className="w-16" aria-label="From gameweek">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {gwFromOptions.map((gw) => (
              <SelectItem key={gw} value={String(gw)}>
                GW{gw}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span>to</span>
        <Select
          value={String(filters.gwTo)}
          onValueChange={(value) =>
            onChange({ ...filters, gwTo: Math.max(Number(value), filters.gwFrom) })
          }
        >
          <SelectTrigger size="sm" className="w-16" aria-label="To gameweek">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {gwToOptions.map((gw) => (
              <SelectItem key={gw} value={String(gw)}>
                GW{gw}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
