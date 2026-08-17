// Directed difficulty colour scale, shared by every page.
//
// Direction: GREEN = easier/better for the named team, RED = harder. Ease indices are
// directed (100 = league average, higher = easier); official FDR is the opposite direction
// (1 = easiest ... 5 = hardest) and is never blended into an ease value. NULL is unmeasured
// and gets no colour at all -- it is distinct from "league average".

export type ViewMode = "overall" | "attack" | "defense";

/**
 * What colours a fixture cell: "opponent" = the opponent club's model strength
 * (higher = stronger opponent = harder, reverse of ease; derived at display time from
 * the published lambdas), "ease" = the row club's own ease index, "fdr" = the official
 * FDR. Never blended with one another.
 */
export type ColorSource = "opponent" | "ease" | "fdr";

export type DifficultyBucket =
  | "much-easier"
  | "easier"
  | "average"
  | "harder"
  | "much-harder";

export const NULL_BUCKET_CLASS =
  "border border-dashed border-zinc-400 text-zinc-400 dark:border-zinc-600 dark:text-zinc-500";

export const BUCKET_CLASSES: Record<DifficultyBucket, string> = {
  "much-easier": "bg-green-600 text-white dark:bg-green-600 dark:text-white",
  easier: "bg-green-200 text-green-950 dark:bg-green-950 dark:text-green-200",
  average: "bg-zinc-200 text-zinc-900 dark:bg-zinc-700 dark:text-zinc-100",
  harder: "bg-red-200 text-red-950 dark:bg-red-950 dark:text-red-200",
  "much-harder": "bg-red-600 text-white dark:bg-red-600 dark:text-white",
};

/** Ease index: 100 = league average, higher = easier. */
export function easeBucket(value: number | null | undefined): DifficultyBucket | null {
  if (value == null) return null;
  if (value <= 85) return "much-harder";
  if (value <= 95) return "harder";
  if (value <= 105) return "average";
  if (value <= 120) return "easier";
  return "much-easier";
}

/** Official FDR: 1 = easiest ... 5 = hardest (opposite direction to an ease index). */
export function fdrBucket(value: number | null | undefined): DifficultyBucket | null {
  if (value == null) return null;
  if (value <= 1) return "much-easier";
  if (value === 2) return "easier";
  if (value === 3) return "average";
  if (value === 4) return "harder";
  return "much-harder";
}

/**
 * Clean-sheet probability (defence view), anchored on the league mean across the loaded
 * gameweek so "average" means what it says. The anchor is measured from the data, never
 * hard-coded.
 */
export function cleanSheetBucket(
  value: number | null | undefined,
  anchor: number | null,
): DifficultyBucket | null {
  if (value == null || anchor == null || !(anchor > 0)) return null;
  const ratio = value / anchor;
  if (ratio <= 0.7) return "much-harder";
  if (ratio <= 0.9) return "harder";
  if (ratio <= 1.1) return "average";
  if (ratio <= 1.35) return "easier";
  return "much-easier";
}

export const EASE_LEGEND: readonly { bucket: DifficultyBucket; label: string }[] = [
  { bucket: "much-easier", label: "> 120 much easier" },
  { bucket: "easier", label: "105-120 easier" },
  { bucket: "average", label: "95-105 league average" },
  { bucket: "harder", label: "85-95 harder" },
  { bucket: "much-harder", label: "<= 85 much harder" },
];

export const FDR_LEGEND: readonly { bucket: DifficultyBucket; label: string }[] = [
  { bucket: "much-easier", label: "FDR 1 easiest" },
  { bucket: "easier", label: "FDR 2" },
  { bucket: "average", label: "FDR 3 average" },
  { bucket: "harder", label: "FDR 4" },
  { bucket: "much-harder", label: "FDR 5 hardest" },
];

/** Opponent strength: 100 = average club, HIGHER = stronger opponent = harder (red). */
export const OPPONENT_LEGEND: readonly { bucket: DifficultyBucket; label: string }[] = [
  { bucket: "much-easier", label: "<= 85 weak opponent" },
  { bucket: "easier", label: "85-95 below average" },
  { bucket: "average", label: "95-105 average club" },
  { bucket: "harder", label: "105-120 strong opponent" },
  { bucket: "much-harder", label: "> 120 strongest" },
];
