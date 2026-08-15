// Per-fixture chip strip: one chip per upcoming fixture, grouped by gameweek across the
// selected range. A gameweek with no fixture renders a blank dashed slot (never a 0); a
// double gameweek naturally renders two chips. NULL metric -> neutral chip with no number.

import { NULL_BUCKET_CLASS, BUCKET_CLASSES, type DifficultyBucket } from "@/lib/difficulty";
import type { TeamFixture } from "@/data/types";

export interface ChipMetric {
  /** Numeric headline; null = unmeasured -> blank chip, never 0. */
  value: number | null;
  /** Pre-formatted headline for the chip body. */
  display: string;
  /** Full primitives for the hover tooltip (expose the numbers behind the colour). */
  title: string;
}

export interface FixtureTickerProps {
  /** Venue/GW-filtered fixtures, sorted by (gw, kickoff). */
  fixtures: TeamFixture[];
  minGw: number;
  maxGw: number;
  metricOf: (fixture: TeamFixture) => ChipMetric;
  bucketOf: (fixture: TeamFixture) => DifficultyBucket | null;
}

export function FixtureTicker({
  fixtures,
  minGw,
  maxGw,
  metricOf,
  bucketOf,
}: FixtureTickerProps) {
  const byGw = new Map<number, TeamFixture[]>();
  for (const fixture of fixtures) {
    const group = byGw.get(fixture.gw);
    if (group) group.push(fixture);
    else byGw.set(fixture.gw, [fixture]);
  }
  const gameweeks = Array.from({ length: maxGw - minGw + 1 }, (_, i) => minGw + i);

  return (
    <div className="flex flex-wrap items-start gap-1.5">
      {gameweeks.map((gw) => {
        const group = byGw.get(gw);
        if (!group) {
          return (
            <span
              key={gw}
              data-testid="blank-slot"
              data-gw={gw}
              title={`GW${gw}: no fixture`}
              className={`inline-flex h-9 w-14 flex-col items-center justify-center rounded-md text-[10px] ${NULL_BUCKET_CLASS}`}
            >
              GW{gw}
            </span>
          );
        }
        return (
          <span key={gw} className="flex items-start gap-1">
            {group.map((fixture) => {
              const metric = metricOf(fixture);
              const bucket = bucketOf(fixture);
              const venue = fixture.was_home == null ? "" : fixture.was_home ? "(H)" : "(A)";
              const label =
                `GW${gw} vs ${fixture.opponent_short_name} ${venue}: ` +
                `${metric.value == null ? "unmeasured" : metric.title}`;
              return (
                <span
                  key={fixture.fixture}
                  data-testid="chip"
                  data-gw={gw}
                  data-bucket={bucket ?? "null"}
                  title={label}
                  aria-label={label}
                  className={`inline-flex h-9 min-w-14 flex-col justify-center rounded-md px-1.5 text-center ${
                    bucket ? BUCKET_CLASSES[bucket] : NULL_BUCKET_CLASS
                  }`}
                >
                  <span className="text-[11px] leading-tight font-semibold">
                    {fixture.opponent_short_name}
                    <span className="ml-0.5 font-normal">{venue}</span>
                  </span>
                  <span className="text-[10px] leading-tight tabular-nums">
                    GW{gw} · {metric.value == null ? "–" : metric.display}
                  </span>
                </span>
              );
            })}
          </span>
        );
      })}
    </div>
  );
}
