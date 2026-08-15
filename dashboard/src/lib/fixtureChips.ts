// Chip metric + colour selection for fixture tickers: which number a chip shows and which
// bucket colours it, per (view, colour source). Pure functions so pages and tests share
// exactly one definition.

import type { TeamFixture } from "@/data/types";
import type { ChipMetric } from "@/components/FixtureTicker";
import {
  cleanSheetBucket,
  easeBucket,
  fdrBucket,
  type ColorSource,
  type DifficultyBucket,
  type ViewMode,
} from "@/lib/difficulty";

export function viewMetric(fixture: TeamFixture, view: ViewMode): number | null {
  if (view === "attack") return fixture.attack_ease_index;
  if (view === "defense") return fixture.probability_clean_sheet;
  return fixture.overall_ease_index;
}

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

export function chipMetric(
  fixture: TeamFixture,
  view: ViewMode,
  colorSource: ColorSource,
): ChipMetric {
  const primitives =
    `λfor ${fmt(fixture.lambda_for, 2)}, λagainst ${fmt(fixture.lambda_against, 2)}, ` +
    `CS ${fmt(fixture.probability_clean_sheet == null ? null : fixture.probability_clean_sheet * 100, 0)}%, ` +
    `ease a/d/o ${fmt(fixture.attack_ease_index, 0)}/${fmt(fixture.defence_ease_index, 0)}/` +
    `${fmt(fixture.overall_ease_index, 0)}, FDR ${fmt(fixture.official_fdr, 0)}`;
  if (colorSource === "fdr") {
    return {
      value: fixture.official_fdr,
      display: `FDR ${fixture.official_fdr ?? "–"}`,
      title: primitives,
    };
  }
  if (view === "defense") {
    const value = fixture.probability_clean_sheet;
    return {
      value,
      display: value == null ? "–" : `${Math.round(value * 100)}%`,
      title: primitives,
    };
  }
  const value = viewMetric(fixture, view);
  return { value, display: fmt(value, 0), title: primitives };
}

export function chipBucket(
  fixture: TeamFixture,
  view: ViewMode,
  colorSource: ColorSource,
  anchor: number | null,
): DifficultyBucket | null {
  if (colorSource === "fdr") return fdrBucket(fixture.official_fdr);
  if (view === "defense") {
    return cleanSheetBucket(fixture.probability_clean_sheet, anchor);
  }
  return easeBucket(viewMetric(fixture, view));
}
