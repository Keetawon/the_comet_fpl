// FixtureTicker behaviour: chip colour direction, NULL -> neutral chip, double gameweek
// -> two chips, blank gameweek -> empty slot. Uses the committed sample read-model data
// with source-led headlines whose displayed number always matches the colour bucket.

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { TeamFixture } from "@/data/types";
import sample from "@/data/sampleFixtureMatrix.json";
import { chipBucket, chipMetric } from "@/lib/fixtureChips";
import { FixtureTicker } from "./FixtureTicker";

const alpha = sample.teams[0];
const beta = sample.teams[1];
const fixtures = alpha.fixtures as TeamFixture[];

function tickerProps(view: "overall" | "attack" | "defense", colorSource: "ease" | "fdr") {
  return {
    fixtures,
    minGw: 1,
    maxGw: 5,
    metricOf: (f: TeamFixture) => chipMetric(f, view, colorSource),
    bucketOf: (f: TeamFixture) => chipBucket(f, view, colorSource),
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

  it("switches the headline and colour to official FDR together", () => {
    render(<FixtureTicker {...tickerProps("overall", "fdr")} />);
    const fdr2 = chips().find((c) => c.dataset.gw === "1")!;
    const fdr4 = chips().find((c) => c.dataset.gw === "2" && c.textContent?.includes("GAM"))!;
    expect(fdr2.dataset.bucket).toBe("easier");
    expect(fdr2.textContent).toContain("FDR 2");
    expect(fdr2).not.toHaveTextContent("130");
    expect(fdr2).toHaveAccessibleName(/selected official FDR 2/i);
    expect(fdr4.dataset.bucket).toBe("harder");
  });

  it("keeps opponent-strength headlines and buckets aligned across analytical views", () => {
    const { rerender } = render(
      <FixtureTicker
        {...tickerProps("attack", "ease")}
        metricOf={(fixture) => chipMetric(fixture, "attack", "opponent", 91)}
        bucketOf={(fixture) => chipBucket(fixture, "attack", "opponent", 91)}
      />,
    );
    const attack = chips().find((chip) => chip.dataset.gw === "1")!;
    expect(attack).toHaveTextContent(/GW1 · 91/);
    expect(attack).toHaveAccessibleName(/selected opponent strength 91/i);

    rerender(
      <FixtureTicker
        {...tickerProps("defense", "ease")}
        metricOf={(fixture) => chipMetric(fixture, "defense", "opponent", 91)}
        bucketOf={(fixture) => chipBucket(fixture, "defense", "opponent", 91)}
      />,
    );
    const defense = chips().find((chip) => chip.dataset.gw === "1")!;
    expect(defense).toHaveTextContent(/GW1 · 91/);
    expect(defense.dataset.bucket).toBe("easier");
  });

  it("uses the defence ease index for the Club ease headline and tier", () => {
    render(
      <FixtureTicker
        fixtures={fixtures}
        minGw={1}
        maxGw={5}
        metricOf={(fixture) => chipMetric(fixture, "defense", "ease")}
        bucketOf={(fixture) => chipBucket(fixture, "defense", "ease")}
      />,
    );
    const defenseEase = chips().find((chip) => chip.dataset.gw === "1")!;
    expect(defenseEase).toHaveTextContent(/GW1 · 131/);
    expect(defenseEase).toHaveAttribute("data-bucket", "much-easier");
    expect(defenseEase).toHaveAccessibleName(/selected club defense ease index 131/i);
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
