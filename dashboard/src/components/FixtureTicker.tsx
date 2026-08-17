// Per-fixture chips: one chip per fixture, grouped by gameweek. FixtureChip is the
// single-cell building block the pivot tables put in one column per gameweek;
// FixtureTicker lays the same chips out as a strip (used on the Summary page). A
// gameweek with no fixture renders a blank dashed slot (never a 0); a double gameweek
// naturally renders two chips. NULL metric -> neutral chip with no number.

import {
  NULL_BUCKET_CLASS,
  BUCKET_CLASSES,
  type DifficultyBucket,
} from "@/lib/difficulty";
import type { ChipMetric } from "@/lib/fixtureChips";

/** Any fixture shape the chip can render: team rows and player rows both satisfy it. */
export interface TickerFixture {
  gw: number;
  fixture: number;
  opponent_short_name: string;
  was_home: boolean | null;
}

export interface FixtureChipProps<T extends TickerFixture> {
  fixture: T;
  /** Chip headline + primitives resolved by the caller (metric + colour source). */
  metric: ChipMetric;
  bucket: DifficultyBucket | null;
}

export function FixtureChip<T extends TickerFixture>({ fixture, metric, bucket }: FixtureChipProps<T>) {
  const venue = fixture.was_home == null ? "" : fixture.was_home ? "(H)" : "(A)";
  const label =
    `GW${fixture.gw} vs ${fixture.opponent_short_name} ${venue}: ` +
    `${metric.value == null ? "unmeasured" : metric.title}`;
  return (
    <span
      data-testid="chip"
      data-gw={fixture.gw}
      data-bucket={bucket ?? "null"}
      title={label}
      aria-label={label}
      className={`inline-flex h-8 min-w-12 flex-col justify-center rounded-md px-1 text-center ${
        bucket ? BUCKET_CLASSES[bucket] : NULL_BUCKET_CLASS
      }`}
    >
      <span className="text-[10px] leading-tight font-semibold">
        {fixture.opponent_short_name}
        <span className="ml-0.5 font-normal">{venue}</span>
      </span>
      <span className="text-[9px] leading-tight tabular-nums">
        GW{fixture.gw} · {metric.value == null ? "–" : metric.display}
      </span>
    </span>
  );
}

function BlankSlot({ gw }: { gw: number }) {
  return (
    <span
      data-testid="blank-slot"
      data-gw={gw}
      title={`GW${gw}: no fixture`}
      className={`inline-flex h-8 w-12 flex-col items-center justify-center rounded-md text-[10px] ${NULL_BUCKET_CLASS}`}
    >
      GW{gw}
    </span>
  );
}

export interface FixtureTickerProps<T extends TickerFixture> {
  /** Venue/GW-filtered fixtures, sorted by (gw, kickoff). */
  fixtures: T[];
  minGw: number;
  maxGw: number;
  metricOf: (fixture: T) => ChipMetric;
  bucketOf: (fixture: T) => DifficultyBucket | null;
}

export function FixtureTicker<T extends TickerFixture>({
  fixtures,
  minGw,
  maxGw,
  metricOf,
  bucketOf,
}: FixtureTickerProps<T>) {
  const byGw = new Map<number, T[]>();
  for (const fixture of fixtures) {
    const group = byGw.get(fixture.gw);
    if (group) group.push(fixture);
    else byGw.set(fixture.gw, [fixture]);
  }
  const gameweeks = Array.from({ length: maxGw - minGw + 1 }, (_, i) => minGw + i);

  return (
    <div className="flex flex-wrap items-start gap-1">
      {gameweeks.map((gw) => {
        const group = byGw.get(gw);
        if (!group) return <BlankSlot key={gw} gw={gw} />;
        return (
          <span key={gw} className="flex items-start gap-1">
            {group.map((fixture) => (
              <FixtureChip
                key={fixture.fixture}
                fixture={fixture}
                metric={metricOf(fixture)}
                bucket={bucketOf(fixture)}
              />
            ))}
          </span>
        );
      })}
    </div>
  );
}
