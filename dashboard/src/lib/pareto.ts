// Direction-aware Pareto classification for the analytics pages. This is display
// geometry over already-published values: it does not fit, smooth, or derive a model
// quantity. Null and non-finite coordinates are omitted rather than treated as zero.

export type ParetoDirection = "minimize" | "maximize";

export interface ParetoDirections {
  x: ParetoDirection;
  y: ParetoDirection;
}

/** Minimal, table-friendly shape accepted by the shared frontier classifier. */
export interface ParetoPoint {
  id: string | number;
  x: number | null;
  y: number | null;
}

export interface ParetoPlottedPoint<T extends ParetoPoint> {
  point: T;
  isFrontier: boolean;
}

export interface ParetoResult<T extends ParetoPoint> {
  /** Every point with two finite coordinates, in deterministic id order. */
  plotted: ParetoPlottedPoint<T>[];
  /** The nondominated subset. Duplicate coordinates remain separate members. */
  frontier: T[];
  /** Points missing either finite coordinate. Null is never coerced to zero. */
  omitted: T[];
}

function finiteCoordinates(point: ParetoPoint): point is ParetoPoint & { x: number; y: number } {
  return (
    point.x != null &&
    point.y != null &&
    Number.isFinite(point.x) &&
    Number.isFinite(point.y)
  );
}

function noWorse(candidate: number, subject: number, direction: ParetoDirection): boolean {
  return direction === "maximize" ? candidate >= subject : candidate <= subject;
}

function strictlyBetter(candidate: number, subject: number, direction: ParetoDirection): boolean {
  return direction === "maximize" ? candidate > subject : candidate < subject;
}

/**
 * True only when `candidate` is no worse on both axes and strictly better on at least one.
 * Coordinate ties therefore do not dominate one another.
 */
export function dominates(
  candidate: ParetoPoint,
  subject: ParetoPoint,
  directions: ParetoDirections,
): boolean {
  if (!finiteCoordinates(candidate) || !finiteCoordinates(subject)) return false;
  return (
    noWorse(candidate.x, subject.x, directions.x) &&
    noWorse(candidate.y, subject.y, directions.y) &&
    (strictlyBetter(candidate.x, subject.x, directions.x) ||
      strictlyBetter(candidate.y, subject.y, directions.y))
  );
}

function compareIds(left: string | number, right: string | number): number {
  if (typeof left === "number" && typeof right === "number") return left - right;
  if (typeof left === "string" && typeof right === "string") return left.localeCompare(right);
  return `${typeof left}:${String(left)}`.localeCompare(`${typeof right}:${String(right)}`);
}

/**
 * Classify a finite set with the exact pairwise definition from the dashboard contract.
 * The O(n^2) implementation is deliberate: page populations are small, and pairwise
 * comparison keeps all four direction combinations and duplicate coordinates auditable.
 */
export function classifyPareto<T extends ParetoPoint>(
  points: readonly T[],
  directions: ParetoDirections,
): ParetoResult<T> {
  const decorated = points.map((point, inputIndex) => ({ point, inputIndex }));
  const byStableId = (
    left: (typeof decorated)[number],
    right: (typeof decorated)[number],
  ) => compareIds(left.point.id, right.point.id) || left.inputIndex - right.inputIndex;

  const eligible = decorated.filter(({ point }) => finiteCoordinates(point)).sort(byStableId);
  const omitted = decorated
    .filter(({ point }) => !finiteCoordinates(point))
    .sort(byStableId)
    .map(({ point }) => point);

  const plotted = eligible.map(({ point }) => ({
    point,
    isFrontier: !eligible.some(
      ({ point: candidate }) => candidate !== point && dominates(candidate, point, directions),
    ),
  }));

  return {
    plotted,
    frontier: plotted.filter(({ isFrontier }) => isFrontier).map(({ point }) => point),
    omitted,
  };
}
