// Chip metric + colour selection for fixture cells: which number a chip shows and which
// bucket colours it, per (view, colour source). Pure functions so pages and tests share
// exactly one definition. The opponent-strength value is resolved by the caller (from
// the run's team lambdas) and passed in -- it is a display-time derivation, never part
// of the published record.

import type { TeamFixture } from "@/data/types";
import {
  cleanSheetBucket,
  easeBucket,
  fdrBucket,
  type ColorSource,
  type DifficultyBucket,
  type ViewMode,
} from "@/lib/difficulty";
import { opponentStrengthBucket } from "@/lib/opponentStrength";

export interface ChipMetric {
  /** Numeric headline; null = unmeasured -> blank chip, never 0. */
  value: number | null;
  /** Pre-formatted headline for the chip body. */
  display: string;
  /** Full primitives for the hover tooltip (expose the numbers behind the colour). */
  title: string;
}

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
  opponentIndex?: number | null,
): ChipMetric {
  const primitives =
    `λfor ${fmt(fixture.lambda_for, 2)}, λagainst ${fmt(fixture.lambda_against, 2)}, ` +
    `CS ${fmt(fixture.probability_clean_sheet == null ? null : fixture.probability_clean_sheet * 100, 0)}%, ` +
    `ease a/d/o ${fmt(fixture.attack_ease_index, 0)}/${fmt(fixture.defence_ease_index, 0)}/` +
    `${fmt(fixture.overall_ease_index, 0)}, FDR ${fmt(fixture.official_fdr, 0)}`;
  const withOpponent =
    opponentIndex == null
      ? primitives
      : `${primitives}, opp strength ${fmt(opponentIndex, 0)}`;
  if (colorSource === "fdr") {
    return {
      value: fixture.official_fdr,
      display: `FDR ${fixture.official_fdr ?? "–"}`,
      title: primitives,
    };
  }
  if (colorSource === "opponent") {
    return {
      value: opponentIndex ?? null,
      display: fmt(opponentIndex, 0),
      title: withOpponent,
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
  opponentIndex?: number | null,
): DifficultyBucket | null {
  if (colorSource === "fdr") return fdrBucket(fixture.official_fdr);
  if (colorSource === "opponent") return opponentStrengthBucket(opponentIndex ?? null);
  if (view === "defense") {
    return cleanSheetBucket(fixture.probability_clean_sheet, anchor);
  }
  return easeBucket(viewMetric(fixture, view));
}
