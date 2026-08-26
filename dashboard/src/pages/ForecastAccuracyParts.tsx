import { useId, useMemo, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import type { ForecastAccuracyScoreBlock } from "@/data/types";

export interface AccuracyPlotPoint {
  id: string;
  label: string;
  predicted: number;
  actual: number;
  detail: string;
  color?: string;
}

interface AccuracyScatterProps {
  title: string;
  description: string;
  predictedLabel: string;
  actualLabel: string;
  points: readonly AccuracyPlotPoint[];
  emptyMessage: string;
}

const WIDTH = 680;
const HEIGHT = 390;
const MARGIN = { top: 24, right: 24, bottom: 68, left: 76 } as const;
const PLOT_WIDTH = WIDTH - MARGIN.left - MARGIN.right;
const PLOT_HEIGHT = HEIGHT - MARGIN.top - MARGIN.bottom;

function chartDomain(points: readonly AccuracyPlotPoint[]): { min: number; max: number } {
  const values = points.flatMap((point) => [point.predicted, point.actual]);
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  if (minimum === maximum) return { min: minimum - 1, max: maximum + 1 };
  const padding = (maximum - minimum) * 0.06;
  return { min: minimum - padding, max: maximum + padding };
}

function scale(value: number, minimum: number, maximum: number, start: number, end: number) {
  return start + ((value - minimum) / (maximum - minimum)) * (end - start);
}

const fmt = (value: number) =>
  new Intl.NumberFormat("en-GB", { maximumFractionDigits: 2 }).format(value);

export function AccuracyScatter({
  title,
  description,
  predictedLabel,
  actualLabel,
  points,
  emptyMessage,
}: AccuracyScatterProps) {
  const id = useId().replaceAll(":", "");
  const [activeId, setActiveId] = useState<string | null>(null);
  const eligible = useMemo(
    () => points.filter((point) => Number.isFinite(point.predicted) && Number.isFinite(point.actual)),
    [points],
  );
  const domain = useMemo(() => chartDomain(eligible), [eligible]);

  if (!eligible.length) {
    return (
      <section className="rounded-lg border bg-card p-4" aria-labelledby={`${id}-title`}>
        <h2 id={`${id}-title`} className="text-sm font-semibold">{title}</h2>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        <p role="status" className="mt-4 text-sm text-muted-foreground">{emptyMessage}</p>
      </section>
    );
  }

  const ticks = Array.from(
    { length: 5 },
    (_, index) => domain.min + ((domain.max - domain.min) * index) / 4,
  );
  const active = eligible.find((point) => point.id === activeId) ?? null;
  const activeX = active
    ? scale(active.predicted, domain.min, domain.max, MARGIN.left, MARGIN.left + PLOT_WIDTH)
    : 0;
  const activeY = active
    ? scale(active.actual, domain.min, domain.max, MARGIN.top + PLOT_HEIGHT, MARGIN.top)
    : 0;

  return (
    <section className="rounded-lg border bg-card p-3" aria-labelledby={`${id}-title`}>
      <h2 id={`${id}-title`} className="text-sm font-semibold">{title}</h2>
      <p id={`${id}-description`} className="mt-1 text-xs text-muted-foreground">{description}</p>
      <div className="relative mt-2 overflow-x-auto">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="block h-auto w-full min-w-[32rem]"
          role="img"
          aria-label={title}
          aria-describedby={`${id}-description`}
        >
          <g aria-hidden="true" className="text-muted-foreground">
            {ticks.map((tick) => {
              const x = scale(tick, domain.min, domain.max, MARGIN.left, MARGIN.left + PLOT_WIDTH);
              const y = scale(tick, domain.min, domain.max, MARGIN.top + PLOT_HEIGHT, MARGIN.top);
              return (
                <g key={tick}>
                  <line x1={x} x2={x} y1={MARGIN.top} y2={MARGIN.top + PLOT_HEIGHT} stroke="currentColor" opacity="0.1" />
                  <line x1={MARGIN.left} x2={MARGIN.left + PLOT_WIDTH} y1={y} y2={y} stroke="currentColor" opacity="0.1" />
                  <text x={x} y={MARGIN.top + PLOT_HEIGHT + 22} textAnchor="middle" fill="currentColor" fontSize="11">{fmt(tick)}</text>
                  <text x={MARGIN.left - 10} y={y + 4} textAnchor="end" fill="currentColor" fontSize="11">{fmt(tick)}</text>
                </g>
              );
            })}
            <line x1={MARGIN.left} x2={MARGIN.left + PLOT_WIDTH} y1={MARGIN.top + PLOT_HEIGHT} y2={MARGIN.top + PLOT_HEIGHT} stroke="currentColor" />
            <line x1={MARGIN.left} x2={MARGIN.left} y1={MARGIN.top} y2={MARGIN.top + PLOT_HEIGHT} stroke="currentColor" />
            <line
              data-testid="identity-line"
              x1={scale(domain.min, domain.min, domain.max, MARGIN.left, MARGIN.left + PLOT_WIDTH)}
              y1={scale(domain.min, domain.min, domain.max, MARGIN.top + PLOT_HEIGHT, MARGIN.top)}
              x2={scale(domain.max, domain.min, domain.max, MARGIN.left, MARGIN.left + PLOT_WIDTH)}
              y2={scale(domain.max, domain.min, domain.max, MARGIN.top + PLOT_HEIGHT, MARGIN.top)}
              stroke="currentColor"
              strokeDasharray="6 4"
              opacity="0.55"
            />
            <text x={MARGIN.left + PLOT_WIDTH / 2} y={HEIGHT - 17} textAnchor="middle" fill="currentColor" fontSize="12">{predictedLabel}</text>
            <text transform={`translate(18 ${MARGIN.top + PLOT_HEIGHT / 2}) rotate(-90)`} textAnchor="middle" fill="currentColor" fontSize="12">{actualLabel}</text>
          </g>
          <g>
            {eligible.map((point) => {
              const x = scale(point.predicted, domain.min, domain.max, MARGIN.left, MARGIN.left + PLOT_WIDTH);
              const y = scale(point.actual, domain.min, domain.max, MARGIN.top + PLOT_HEIGHT, MARGIN.top);
              const label = `${point.label}; ${predictedLabel}: ${fmt(point.predicted)}; ${actualLabel}: ${fmt(point.actual)}; ${point.detail}`;
              return (
                <circle
                  key={point.id}
                  data-testid="accuracy-point"
                  cx={x}
                  cy={y}
                  r={5}
                  fill={point.color ?? "var(--chart-2)"}
                  stroke="var(--background)"
                  strokeWidth={2}
                  tabIndex={0}
                  aria-label={label}
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
            role="tooltip"
            className="pointer-events-none absolute z-10 max-w-64 -translate-x-1/2 -translate-y-[calc(100%+0.5rem)] rounded-md bg-foreground px-3 py-2 text-xs text-background shadow-md"
            style={
              {
                left: `${(activeX / WIDTH) * 100}%`,
                top: `${(activeY / HEIGHT) * 100}%`,
              } as CSSProperties
            }
          >
            {active.label}; {predictedLabel}: {fmt(active.predicted)}; {actualLabel}: {fmt(active.actual)}; {active.detail}
          </div>
        )}
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">Dashed diagonal = prediction equals actual. Exact values are in the table below.</p>
    </section>
  );
}

export interface AccuracyKpi {
  label: string;
  value: ReactNode;
  note?: string;
}

export function AccuracyKpis({ items }: { items: readonly AccuracyKpi[] }) {
  return (
    <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="rounded-lg border bg-card p-3">
          <dt className="text-xs text-muted-foreground">{item.label}</dt>
          <dd className="mt-1 text-lg font-semibold tabular-nums">{item.value}</dd>
          {item.note && <p className="mt-1 text-[11px] text-muted-foreground">{item.note}</p>}
        </div>
      ))}
    </dl>
  );
}

function scoreKpis(block: ForecastAccuracyScoreBlock): AccuracyKpi[] {
  const value = (metric: number | null, digits = 3) =>
    metric == null ? "—" : metric.toFixed(digits);
  const signed = (metric: number | null) =>
    metric == null ? "—" : `${metric >= 0 ? "+" : ""}${metric.toFixed(3)}`;
  return [
    { label: "Scored rows", value: block.rows, note: `${block.distribution_rows} with a scored PMF` },
    { label: "Forecast / actual total", value: `${value(block.forecast_total, 2)} / ${value(block.actual_total, 2)}` },
    { label: "Bias (actual − forecast)", value: signed(block.bias), note: "Positive = model under-predicted" },
    { label: "MAE", value: value(block.mae) },
    { label: "RMSE", value: value(block.rmse) },
    { label: "CRPS", value: value(block.crps), note: "Published from the stored distribution" },
  ];
}

export function AccuracyScoreKpis({
  block,
  biasNote,
}: {
  block: ForecastAccuracyScoreBlock;
  biasNote?: string;
}) {
  const items = scoreKpis(block).map((item) =>
    biasNote && item.label === "Bias (actual − forecast)"
      ? { ...item, note: biasNote }
      : item,
  );
  return <AccuracyKpis items={items} />;
}
