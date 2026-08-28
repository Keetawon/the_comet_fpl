// FixtureTicker behaviour: chip colour direction, NULL -> neutral chip, double gameweek
// -> two chips, blank gameweek -> empty slot. Uses the committed sample read-model data
// and both Fixture Matrix's view-owned and Summary's source-led headline helpers.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TeamFixture } from "@/data/types";
import sample from "@/data/sampleFixtureMatrix.json";
import { chipBucket, chipMetric, fixtureViewChipMetric } from "@/lib/fixtureChips";
import { FixtureTicker } from "./FixtureTicker";

const alpha = sample.teams[0];
const beta = sample.teams[1];
const fixtures = alpha.fixtures as TeamFixture[];

function tickerProps(view: "overall" | "attack" | "defense", colorSource: "ease" | "fdr") {
  return {
    fixtures,
    minGw: 1,
    maxGw: 5,
    metricOf: (f: TeamFixture) => fixtureViewChipMetric(f, view, colorSource),
    bucketOf: (f: TeamFixture) => chipBucket(f, view, colorSource, 0.25),
  };
}

const chips = () => screen.getAllByTestId("chip");

describe("FixtureTicker", () => {
  it("colours an easy fixture green and a hard one red under the model ease source", () => {
    render(<FixtureTicker {...tickerProps("overall", "ease")} />);
    const easy = chips().find((c) => c.dataset.gw === "1")!;
    const hard = chips().find((c) => c.dataset.gw === "2" && c.textContent?.includes("GAM"))!;
    expect(easy.dataset.bucket).toBe("much-easier");
    expect(easy.className).toContain("bg-green-600");
    expect(easy.textContent).toContain("130");
    expect(hard.dataset.bucket).toBe("harder");
    expect(hard.className).toContain("bg-red-200");
    expect(hard.className).not.toContain("bg-green");
  });

  it("switches the colour to official FDR without replacing the overall headline", () => {
    render(<FixtureTicker {...tickerProps("overall", "fdr")} />);
    const fdr2 = chips().find((c) => c.dataset.gw === "1")!;
    const fdr4 = chips().find((c) => c.dataset.gw === "2" && c.textContent?.includes("GAM"))!;
    expect(fdr2.dataset.bucket).toBe("easier");
    expect(fdr2.textContent).toContain("130");
    expect(fdr2).toHaveAccessibleName(/colour uses official FDR 2/i);
    expect(fdr4.dataset.bucket).toBe("harder");
  });

  it("keeps Attack and Defense headlines independent from opponent colour", () => {
    const { rerender } = render(
      <FixtureTicker
        {...tickerProps("attack", "ease")}
        metricOf={(fixture) => fixtureViewChipMetric(fixture, "attack", "opponent", 91)}
        bucketOf={(fixture) => chipBucket(fixture, "attack", "opponent", null, 91)}
      />,
    );
    const attack = chips().find((chip) => chip.dataset.gw === "1")!;
    expect(attack).toHaveTextContent("xGF 2.10");
    expect(attack).toHaveAccessibleName(/published expected goals for.*colour uses opponent strength 91/i);

    rerender(
      <FixtureTicker
        {...tickerProps("defense", "ease")}
        metricOf={(fixture) => fixtureViewChipMetric(fixture, "defense", "opponent", 91)}
        bucketOf={(fixture) => chipBucket(fixture, "defense", "opponent", null, 91)}
      />,
    );
    const defense = chips().find((chip) => chip.dataset.gw === "1")!;
    expect(defense).toHaveTextContent("CS 41%");
    expect(defense.dataset.bucket).toBe("easier");
  });

  it("keeps the Summary ticker's source-led opponent-strength headline", () => {
    render(
      <FixtureTicker
        fixtures={fixtures}
        minGw={1}
        maxGw={5}
        metricOf={(fixture) => chipMetric(fixture, "overall", "opponent", 91)}
        bucketOf={(fixture) => chipBucket(fixture, "overall", "opponent", null, 91)}
      />,
    );
    const summaryChip = chips().find((chip) => chip.dataset.gw === "1")!;
    expect(summaryChip).toHaveTextContent(/GW1 · 91/);
    expect(summaryChip).not.toHaveTextContent("130");
  });

  it("renders an unmeasured metric as a neutral chip with no number, never 0", () => {
    render(<FixtureTicker {...tickerProps("overall", "ease")} />);
    const unmeasured = chips().find((c) => c.dataset.gw === "4")!;
    expect(unmeasured.dataset.bucket).toBe("null");
    expect(unmeasured.className).not.toMatch(/bg-(green|red)/);
    expect(unmeasured.textContent).toContain("–");
    expect(unmeasured.textContent).not.toMatch(/GW4 · 0/);
  });

  it("stays neutral when the colour source itself is unmeasured (FDR null)", () => {
    render(
      <FixtureTicker
        {...tickerProps("overall", "fdr")}
        fixtures={beta.fixtures as TeamFixture[]}
      />,
    );
    const gw1 = chips().find((c) => c.dataset.gw === "1")!;
    expect(gw1.dataset.bucket).toBe("null");
    expect(gw1.textContent).toContain("GW1 · –");
    expect(gw1.textContent).not.toContain("FDR 0");
  });

  it("shows two chips for a double gameweek and an empty slot for a blank gameweek", () => {
    render(<FixtureTicker {...tickerProps("overall", "ease")} />);
    const gw2 = chips().filter((c) => c.dataset.gw === "2");
    expect(gw2).toHaveLength(2);
    expect(screen.getAllByTestId("blank-slot").map((c) => c.dataset.gw)).toEqual(["3", "5"]);
  });

  it("carries the raw primitives in the accessible label", () => {
    render(<FixtureTicker {...tickerProps("overall", "ease")} />);
    const easy = chips().find((c) => c.dataset.gw === "1")!;
    expect(easy.getAttribute("aria-label")).toContain("lambda for 2.10");
    expect(easy.getAttribute("aria-label")).toContain("FDR 2");
  });
});
