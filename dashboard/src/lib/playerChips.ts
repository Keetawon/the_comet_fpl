// Player chip metric + colour selection: the headline is the player's xP for that fixture;
// the COLOUR comes from the player's club fixture fields for the same fixture, per
// (view, colour source). Pure functions so the page and tests share one definition.

import type { PlayerFixture } from "@/data/types";
import type { ChipMetric } from "@/components/FixtureTicker";
import {
  easeBucket,
  fdrBucket,
  type ColorSource,
  type DifficultyBucket,
  type ViewMode,
} from "@/lib/difficulty";

/**
 * The club metric that colours a player chip. Defence colours on the club's defence ease
 * (the player's own clean-sheet probability is a different, separately shown measure, and
 * is null until the ledger persists it).
 */
export function playerViewMetric(fixture: PlayerFixture, view: ViewMode): number | null {
  if (view === "attack") return fixture.team_attack_ease_index;
  if (view === "defense") return fixture.team_defence_ease_index;
  return fixture.team_overall_ease_index;
}

const fmt = (value: number | null | undefined, digits = 1) =>
  value == null ? "–" : value.toFixed(digits);

export function playerChipMetric(
  fixture: PlayerFixture,
  _view: ViewMode, // kept for call-site symmetry with the team chipMetric; the headline never depends on the view
  colorSource: ColorSource,
): ChipMetric {
  const primitives =
    `xP ${fmt(fixture.expected_points, 2)}, club λfor ${fmt(fixture.team_lambda_for, 2)}, ` +
    `λagainst ${fmt(fixture.team_lambda_against, 2)}, club CS ` +
    `${fmt(fixture.team_probability_clean_sheet == null ? null : fixture.team_probability_clean_sheet * 100, 0)}%, ` +
    `ease a/d/o ${fmt(fixture.team_attack_ease_index, 0)}/${fmt(fixture.team_defence_ease_index, 0)}/` +
    `${fmt(fixture.team_overall_ease_index, 0)}, FDR ${fmt(fixture.team_official_fdr, 0)}`;
  if (colorSource === "fdr") {
    return {
      value: fixture.team_official_fdr,
      display: `FDR ${fixture.team_official_fdr ?? "–"}`,
      title: primitives,
    };
  }
  // Headline is the xP; the colour (bucketOf) tracks the view metric, not the headline.
  return {
    value: fixture.expected_points,
    display: fmt(fixture.expected_points, 1),
    title: primitives,
  };
}

export function playerChipBucket(
  fixture: PlayerFixture,
  view: ViewMode,
  colorSource: ColorSource,
): DifficultyBucket | null {
  if (colorSource === "fdr") return fdrBucket(fixture.team_official_fdr);
  return easeBucket(playerViewMetric(fixture, view));
}
