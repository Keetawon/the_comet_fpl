// Direction-labelled legend for the shared difficulty colour scale, with the
// colour-source toggle: model ease (default) vs official FDR. The two sources are never
// blended; the toggle switches which one colours chips and cells.

import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  BUCKET_CLASSES,
  EASE_LEGEND,
  FDR_LEGEND,
  type ColorSource,
} from "@/lib/difficulty";

interface DifficultyLegendProps {
  colorSource: ColorSource;
  onColorSourceChange: (source: ColorSource) => void;
  easeIndexFormulaVersion: string;
  /** League-mean clean-sheet probability the defence scale is anchored on (0-1). */
  cleanSheetAnchor: number | null;
  /** What the defence view colours on, when a page differs from the team CS default. */
  defenceScaleNote?: string;
}

export function DifficultyLegend({
  colorSource,
  onColorSourceChange,
  easeIndexFormulaVersion,
  cleanSheetAnchor,
  defenceScaleNote,
}: DifficultyLegendProps) {
  const legend = colorSource === "ease" ? EASE_LEGEND : FDR_LEGEND;
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
        <ToggleGroupItem value="ease">Model ease</ToggleGroupItem>
        <ToggleGroupItem value="fdr">Official FDR</ToggleGroupItem>
      </ToggleGroup>
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium">Green = easier · Red = harder</span>
        {legend.map(({ bucket, label }) => (
          <span
            key={bucket}
            className={`rounded px-1.5 py-0.5 ${BUCKET_CLASSES[bucket]}`}
          >
            {label}
          </span>
        ))}
      </div>
      {colorSource === "ease" ? (
        <span>
          Ease index: 100 = league average, higher = easier (formula{" "}
          {easeIndexFormulaVersion}).{" "}
          {defenceScaleNote ??
            `Defence view colours on clean-sheet probability anchored at the league mean (${
              cleanSheetAnchor == null ? "unavailable" : `${Math.round(cleanSheetAnchor * 100)}%`
            }).`}
        </span>
      ) : (
        <span>Official FDR, 1 = easiest … 5 = hardest; never blended into the model index.</span>
      )}
    </div>
  );
}
