// Direction-labelled legend for the shared difficulty colour scale, with the
// colour-source toggle: opponent strength (default), the row club's model ease, or the
// official FDR. The three sources are never blended; the toggle switches the displayed
// average, chip headline, and matching colour tier together.

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  BUCKET_CLASSES,
  EASE_LEGEND,
  FDR_LEGEND,
  OPPONENT_LEGEND,
  type ColorSource,
} from "@/lib/difficulty";

interface DifficultyLegendProps {
  colorSource: ColorSource;
  onColorSourceChange: (source: ColorSource) => void;
  easeIndexFormulaVersion: string;
  /** What the defence view uses for club ease when a page needs a more specific note. */
  defenceScaleNote?: string;
}

const SOURCE_ORDER: readonly ColorSource[] = ["opponent", "ease", "fdr"];

const SOURCE_LABEL: Record<ColorSource, string> = {
  opponent: "Opponent strength",
  ease: "Club ease",
  fdr: "Official FDR",
};

export function DifficultyLegend({
  colorSource,
  onColorSourceChange,
  easeIndexFormulaVersion,
  defenceScaleNote,
}: DifficultyLegendProps) {
  const legend =
    colorSource === "ease" ? EASE_LEGEND : colorSource === "fdr" ? FDR_LEGEND : OPPONENT_LEGEND;
  const direction =
    colorSource === "opponent"
      ? "Green = weak opponent · Red = strong opponent"
      : "Green = easier · Red = harder";
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
      <ToggleGroup
        type="single"
        value={colorSource}
        onValueChange={(value) => {
          if (value) onColorSourceChange(value as ColorSource);
        }}
        variant="outline"
        size="sm"
        aria-label="Colour source"
      >
        {SOURCE_ORDER.map((source) => (
          <ToggleGroupItem key={source} value={source}>
            {SOURCE_LABEL[source]}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium">{direction}</span>
        {legend.map(({ bucket, label }) => (
          <span
            key={bucket}
            className={`rounded px-1.5 py-0.5 ${BUCKET_CLASSES[bucket]}`}
          >
            {label}
          </span>
        ))}
      </div>
      {colorSource === "opponent" ? (
        <span>
          Opponent strength from the vintage's model λ (100 = average club, higher =
          stronger opponent; display-time derivation, never blended into ease or FDR).
        </span>
      ) : colorSource === "ease" ? (
        <span>
          Ease index: 100 = league average, higher = easier (formula{" "}
          {easeIndexFormulaVersion}).{" "}
          {defenceScaleNote ??
            "Defence view uses the club defence ease index."}
        </span>
      ) : (
        <span>Official FDR, 1 = easiest … 5 = hardest; never blended into the model index.</span>
      )}
    </div>
  );
}
