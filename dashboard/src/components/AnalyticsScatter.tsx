import { useId, useMemo, useState } from "react";
import type { CSSProperties } from "react";
import { cn } from "@/lib/utils";
import type { ParetoDirection } from "@/lib/pareto";

export type AnalyticsScatterDirection = ParetoDirection | "explanatory";

export interface AnalyticsScatterAxis {
  /** Exact metric name shown on the axis and repeated in point descriptions. */
  label: string;
  /** `explanatory` marks a context axis with no better/worse decision direction. */
  direction: AnalyticsScatterDirection;
  /** Display formatter only; it must not transform the plotted model value. */
  format?: (value: number) => string;
  /** Optional physical bounds used only to clamp padded chart ticks. */
  bounds?: {
    min?: number;
    max?: number;
  };
}

/**
 * Reusable point shape for both the SVG and the authoritative sibling data table.
 * `x` and `y` must already be finite; null omission belongs in the page/classifier.
 */
export interface AnalyticsScatterPoint {
  id: string | number;
  label: string;
  x: number;
  y: number;
  xDisplay?: string;
  yDisplay?: string;
  isFrontier?: boolean;
  /** CSS colour value. Position/team legends remain the page's responsibility. */
  color?: string;
  /** Radius in SVG view-box units; clamped to keep every point operable. */
  radius?: number;
  /** Optional category exposed in the tooltip and accessible point description. */
  groupLabel?: string;
}

export interface AnalyticsScatterProps {
  title: string;
  description?: string;
  points: readonly AnalyticsScatterPoint[];
  xAxis: AnalyticsScatterAxis;
  yAxis: AnalyticsScatterAxis;
  vintageLabel: string;
  horizonLabel: string;
  medianX?: number | null;
  medianY?: number | null;
  emptyMessage?: string;
  className?: string;
}

interface Domain {
  min: number;
  max: number;
}

const WIDTH = 720;
const HEIGHT = 420;
const MARGIN = { top: 24, right: 24, bottom: 72, left: 82 } as const;
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom;
const TICK_COUNT = 5;

function finite(value: number | null | undefined): value is number {
  return value != null && Number.isFinite(value);
}

function domain(
  values: readonly number[],
  bounds: AnalyticsScatterAxis["bounds"],
): Domain {
  const min = Math.min(...values);
  const max = Math.max(...values);
  let padded: Domain;
  if (min !== max) {
    const padding = (max - min) * 0.06;
    padded = { min: min - padding, max: max + padding };
  } else {
    const padding = Math.max(Math.abs(min) * 0.06, 1);
    padded = { min: min - padding, max: max + padding };
  }
  const clamped = {
    min: bounds?.min == null ? padded.min : Math.max(bounds.min, padded.min),
    max: bounds?.max == null ? padded.max : Math.min(bounds.max, padded.max),
  };
  if (clamped.min < clamped.max) return clamped;

  // A single point exactly on a physical bound still needs a non-zero plotting span.
  if (bounds?.min != null && min === bounds.min) {
    return { min: bounds.min, max: bounds.max ?? bounds.min + 1 };
  }
  if (bounds?.max != null && max === bounds.max) {
    return { min: bounds.min ?? bounds.max - 1, max: bounds.max };
  }
  return padded;
}

function ticks({ min, max }: Domain): number[] {
  return Array.from({ length: TICK_COUNT }, (_, index) => min + ((max - min) * index) / (TICK_COUNT - 1));
}

function scale(value: number, source: Domain, targetMin: number, targetMax: number): number {
  return targetMin + ((value - source.min) / (source.max - source.min)) * (targetMax - targetMin);
}

const defaultFormat = (value: number) =>
  new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 }).format(value);

const directionText = (direction: AnalyticsScatterDirection) => {
  if (direction === "explanatory") return "context only";
  return direction === "maximize" ? "higher is better" : "lower is better";
};

function boundedRadius(value: number | undefined): number {
  if (value == null || !Number.isFinite(value)) return 5;
  return Math.min(12, Math.max(4, value));
}

function analyticsPointDescription(
  point: AnalyticsScatterPoint,
  xAxis: AnalyticsScatterAxis,
  yAxis: AnalyticsScatterAxis,
  vintageLabel: string,
  horizonLabel: string,
): string {
  const formatX = xAxis.format ?? defaultFormat;
  const formatY = yAxis.format ?? defaultFormat;
  const hasDecisionDirections =
    xAxis.direction !== "explanatory" && yAxis.direction !== "explanatory";
  const frontierDescription = hasDecisionDirections && point.isFrontier != null
    ? (point.isFrontier ? "Pareto frontier" : "not on Pareto frontier")
    : undefined;
  const fields = [
    point.label,
    point.groupLabel,
    `${xAxis.label}: ${point.xDisplay ?? formatX(point.x)}`,
    `${yAxis.label}: ${point.yDisplay ?? formatY(point.y)}`,
    frontierDescription,
    `vintage ${vintageLabel}`,
    `horizon ${horizonLabel}`,
  ];
  return fields.filter((value): value is string => Boolean(value)).join("; ");
}

export function AnalyticsScatter({
  title,
  description,
  points,
  xAxis,
  yAxis,
  vintageLabel,
  horizonLabel,
  medianX = null,
  medianY = null,
  emptyMessage = "No eligible values to plot.",
  className,
}: AnalyticsScatterProps) {
  const id = useId().replaceAll(":", "");
  const [activeId, setActiveId] = useState<string | number | null>(null);
  const eligible = useMemo(
    () => points.filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y)),
    [points],
  );

  const xDomain = useMemo(
    () => domain(
      [...eligible.map(({ x }) => x), ...(finite(medianX) ? [medianX] : [])],
      xAxis.bounds,
    ),
    [eligible, medianX, xAxis.bounds],
  );
  const yDomain = useMemo(
    () => domain(
      [...eligible.map(({ y }) => y), ...(finite(medianY) ? [medianY] : [])],
      yAxis.bounds,
    ),
    [eligible, medianY, yAxis.bounds],
  );

  if (!eligible.length) {
    return (
      <section className={cn("rounded-lg border bg-card p-4", className)} aria-labelledby={`${id}-title`}>
        <h2 id={`${id}-title`} className="text-sm font-semibold">{title}</h2>
        {description && <p className="mt-1 text-xs text-muted-foreground">{description}</p>}
        <p role="status" className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      </section>
    );
  }

  const formatX = xAxis.format ?? defaultFormat;
  const formatY = yAxis.format ?? defaultFormat;
  const axisX = `${xAxis.label} (${directionText(xAxis.direction)})`;
  const axisY = `${yAxis.label} (${directionText(yAxis.direction)})`;
  const hasDecisionDirections =
    xAxis.direction !== "explanatory" && yAxis.direction !== "explanatory";
  const active = eligible.find((point) => point.id === activeId) ?? null;
  const activeX = active ? scale(active.x, xDomain, MARGIN.left, MARGIN.left + PLOT_WIDTH) : 0;
  const activeY = active ? scale(active.y, yDomain, MARGIN.top + PLOT_HEIGHT, MARGIN.top) : 0;

  return (
    <section className={cn("rounded-lg border bg-card p-3", className)} aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="text-sm font-semibold">{title}</h2>
      {description && <p id={`${id}-description`} className="mt-1 text-xs text-muted-foreground">{description}</p>}
      <p className="mt-1 text-[11px] text-muted-foreground">
        Vintage {vintageLabel} · horizon {horizonLabel}
      </p>

      <div className="relative mt-2 w-full overflow-hidden">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="block h-auto w-full min-w-[32rem]"
          role="group"
          aria-labelledby={`${id}-chart-title`}
          aria-describedby={`${id}-chart-description`}
        >
          <title id={`${id}-chart-title`}>{title}</title>
          <desc id={`${id}-chart-description`}>
            {description ? `${description} ` : ""}{axisX}; {axisY}. Vintage {vintageLabel}; horizon {horizonLabel}.
          </desc>

          <g aria-hidden="true" className="text-muted-foreground">
            {ticks(xDomain).map((tick) => {
              const x = scale(tick, xDomain, MARGIN.left, MARGIN.left + PLOT_WIDTH);
              return (
                <g key={`x-${tick}`}>
                  <line x1={x} x2={x} y1={MARGIN.top} y2={MARGIN.top + PLOT_HEIGHT} stroke="currentColor" opacity="0.12" />
                  <text x={x} y={MARGIN.top + PLOT_HEIGHT + 22} textAnchor="middle" fill="currentColor" fontSize="11">
                    {formatX(tick)}
                  </text>
                </g>
              );
            })}
            {ticks(yDomain).map((tick) => {
              const y = scale(tick, yDomain, MARGIN.top + PLOT_HEIGHT, MARGIN.top);
              return (
                <g key={`y-${tick}`}>
                  <line x1={MARGIN.left} x2={MARGIN.left + PLOT_WIDTH} y1={y} y2={y} stroke="currentColor" opacity="0.12" />
                  <text x={MARGIN.left - 10} y={y + 4} textAnchor="end" fill="currentColor" fontSize="11">
                    {formatY(tick)}
                  </text>
                </g>
              );
            })}
            <line x1={MARGIN.left} x2={MARGIN.left + PLOT_WIDTH} y1={MARGIN.top + PLOT_HEIGHT} y2={MARGIN.top + PLOT_HEIGHT} stroke="currentColor" />
            <line x1={MARGIN.left} x2={MARGIN.left} y1={MARGIN.top} y2={MARGIN.top + PLOT_HEIGHT} stroke="currentColor" />
            <text x={MARGIN.left + PLOT_WIDTH / 2} y={HEIGHT - 18} textAnchor="middle" fill="currentColor" fontSize="12">
              {axisX}
            </text>
            <text transform={`translate(20 ${MARGIN.top + PLOT_HEIGHT / 2}) rotate(-90)`} textAnchor="middle" fill="currentColor" fontSize="12">
              {axisY}
            </text>
          </g>

          {finite(medianX) && (
            <line
              data-testid="median-x"
              aria-hidden="true"
              x1={scale(medianX, xDomain, MARGIN.left, MARGIN.left + PLOT_WIDTH)}
              x2={scale(medianX, xDomain, MARGIN.left, MARGIN.left + PLOT_WIDTH)}
              y1={MARGIN.top}
              y2={MARGIN.top + PLOT_HEIGHT}
              stroke="currentColor"
              strokeDasharray="5 4"
              opacity="0.45"
            />
          )}
          {finite(medianY) && (
            <line
              data-testid="median-y"
              aria-hidden="true"
              x1={MARGIN.left}
              x2={MARGIN.left + PLOT_WIDTH}
              y1={scale(medianY, yDomain, MARGIN.top + PLOT_HEIGHT, MARGIN.top)}
              y2={scale(medianY, yDomain, MARGIN.top + PLOT_HEIGHT, MARGIN.top)}
              stroke="currentColor"
              strokeDasharray="5 4"
              opacity="0.45"
            />
          )}

          <g>
            {eligible.map((point, index) => {
              const x = scale(point.x, xDomain, MARGIN.left, MARGIN.left + PLOT_WIDTH);
              const y = scale(point.y, yDomain, MARGIN.top + PLOT_HEIGHT, MARGIN.top);
              const label = analyticsPointDescription(
                point,
                xAxis,
                yAxis,
                vintageLabel,
                horizonLabel,
              );
              const tooltipId = `${id}-tooltip-${index}`;
              const activePoint = point.id === activeId;
              return (
                <circle
                  key={`${typeof point.id}-${String(point.id)}-${index}`}
                  data-testid="analytics-point"
                  data-frontier={hasDecisionDirections ? (point.isFrontier ? "true" : "false") : "not-applicable"}
                  cx={x}
                  cy={y}
                  r={boundedRadius(point.radius)}
                  fill={point.color ?? "var(--chart-2)"}
                  stroke={hasDecisionDirections && point.isFrontier ? "var(--foreground)" : "var(--background)"}
                  strokeWidth={hasDecisionDirections && point.isFrontier ? 3 : 1.5}
                  tabIndex={0}
                  aria-label={label}
                  aria-describedby={activePoint ? tooltipId : undefined}
                  onFocus={() => setActiveId(point.id)}
                  onBlur={() => setActiveId((current) => (current === point.id ? null : current))}
                  onMouseEnter={() => setActiveId(point.id)}
                  onMouseLeave={() => setActiveId((current) => (current === point.id ? null : current))}
                  className="cursor-pointer outline-none focus:stroke-[5px]"
                >
                  <title>{label}</title>
                </circle>
              );
            })}
          </g>
        </svg>

        {active && (
          <div
            id={`${id}-tooltip-${eligible.indexOf(active)}`}
            role="tooltip"
            className="pointer-events-none absolute z-10 max-w-64 -translate-x-1/2 -translate-y-[calc(100%+0.5rem)] rounded-md bg-foreground px-3 py-2 text-xs text-background shadow-md"
            style={
              {
                left: `${(activeX / WIDTH) * 100}%`,
                top: `${(activeY / HEIGHT) * 100}%`,
              } as CSSProperties
            }
          >
            {analyticsPointDescription(active, xAxis, yAxis, vintageLabel, horizonLabel)}
          </div>
        )}
      </div>
    </section>
  );
}
