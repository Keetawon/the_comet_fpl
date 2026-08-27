import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  AnalyticsScatter,
  type AnalyticsScatterPoint,
} from "./AnalyticsScatter";

const points: AnalyticsScatterPoint[] = [
  {
    id: 101,
    label: "Alpha",
    groupLabel: "MID · AAA",
    x: 6.5,
    y: 28.25,
    xDisplay: "£6.5m",
    yDisplay: "28.25 xP",
    isFrontier: true,
    color: "#2563eb",
    radius: 7,
  },
  {
    id: 102,
    label: "Beta",
    x: 7.2,
    y: 22,
    isFrontier: false,
  },
];

const props = {
  title: "Player value frontier",
  description: "Published cumulative values only.",
  points,
  xAxis: {
    label: "Deadline price",
    direction: "minimize" as const,
    format: (value: number) => `£${value.toFixed(1)}m`,
  },
  yAxis: {
    label: "Cumulative xP",
    direction: "maximize" as const,
    format: (value: number) => value.toFixed(2),
  },
  vintageLabel: "run-abc123",
  horizonLabel: "GW2–GW6",
};

describe("AnalyticsScatter", () => {
  it("renders an accessible chart with exact axis labels and declared directions", () => {
    render(<AnalyticsScatter {...props} />);

    expect(screen.getByRole("group", { name: "Player value frontier" })).toBeInTheDocument();
    expect(screen.getByText("Deadline price (lower is better)")).toBeInTheDocument();
    expect(screen.getByText("Cumulative xP (higher is better)")).toBeInTheDocument();
    expect(screen.getByText("Forecast run-abc123 · GW2–GW6")).toBeInTheDocument();
  });

  it("labels explanatory axes as context without implying a better direction", () => {
    render(
      <AnalyticsScatter
        {...props}
        xAxis={{ ...props.xAxis, label: "Past xG per 90", direction: "explanatory" }}
      />,
    );

    expect(screen.getByText("Past xG per 90 (context only)")).toBeInTheDocument();
    expect(screen.queryByText(/Past xG per 90 \((higher|lower) is better\)/)).not.toBeInTheDocument();
    const [alpha] = screen.getAllByTestId("analytics-point");
    expect(alpha).toHaveAttribute("data-frontier", "not-applicable");
    expect(alpha.getAttribute("aria-label")).not.toContain("Pareto frontier");
  });

  it("makes every point focusable and exposes exact values, frontier, vintage, and horizon", () => {
    render(<AnalyticsScatter {...props} />);
    const [alpha, beta] = screen.getAllByTestId("analytics-point");

    expect(alpha).toHaveAttribute("tabindex", "0");
    expect(alpha).toHaveAttribute("data-frontier", "true");
    expect(alpha.getAttribute("aria-label")).toBe(
      "Alpha; MID · AAA; Deadline price: £6.5m; Cumulative xP: 28.25 xP; " +
        "Pareto frontier; vintage run-abc123; horizon GW2–GW6",
    );
    expect(beta).toHaveAttribute("data-frontier", "false");
    expect(beta.getAttribute("aria-label")).toContain("not on Pareto frontier");
  });

  it("shows a concise, edge-aware tooltip while preserving the full accessible name", () => {
    render(<AnalyticsScatter {...props} />);
    const alpha = screen.getAllByTestId("analytics-point")[0];

    fireEvent.focus(alpha);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip.parentElement).toHaveClass("overflow-visible");
    expect(tooltip).toHaveTextContent("Deadline price: £6.5m");
    expect(tooltip).toHaveTextContent("Efficient frontier");
    expect(tooltip).not.toHaveTextContent("run-abc123");
    expect(tooltip).not.toHaveTextContent("GW2–GW6");
    expect(tooltip).toHaveAttribute("data-horizontal-placement", "start");
    expect(tooltip).toHaveAttribute("data-vertical-placement", "below");
    expect(alpha).toHaveAccessibleName(/vintage run-abc123; horizon GW2–GW6/);
    expect(alpha).toHaveAttribute("aria-describedby", tooltip.id);

    fireEvent.blur(alpha);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.mouseEnter(alpha);
    expect(screen.getByRole("tooltip")).toHaveTextContent("Efficient frontier");
    fireEvent.mouseLeave(alpha);
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    const beta = screen.getAllByTestId("analytics-point")[1];
    fireEvent.focus(beta);
    expect(screen.getByRole("tooltip")).toHaveAttribute("data-horizontal-placement", "end");
    expect(screen.getByRole("tooltip")).toHaveAttribute("data-vertical-placement", "above");
    expect(beta).toHaveAccessibleName(/vintage run-abc123; horizon GW2–GW6/);
  });

  it("supports concise visible axis and provenance labels without weakening accessibility", () => {
    render(
      <AnalyticsScatter
        {...props}
        xAxis={{ ...props.xAxis, displayLabel: "Price" }}
        yAxis={{ ...props.yAxis, displayLabel: "xP" }}
        vintageDisplayLabel="2026-27 · run-abc…"
        horizonDisplayLabel="GW2-6"
      />,
    );

    expect(screen.getByText("Price (lower is better)")).toBeInTheDocument();
    expect(screen.getByText("xP (higher is better)")).toBeInTheDocument();
    expect(screen.getByText("Forecast 2026-27 · run-abc… · GW2-6")).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Player value frontier" });
    expect(group.querySelector("desc")).toHaveTextContent(
      /Deadline price \(lower is better\); Cumulative xP \(higher is better\).*run-abc123/,
    );
  });

  it("renders an optional concise chart-reading note", () => {
    render(
      <AnalyticsScatter
        {...props}
        readingNote="Move up and left; outlined points are Pareto-efficient."
      />,
    );

    expect(screen.getByRole("note")).toHaveTextContent(
      "How to read: Move up and left; outlined points are Pareto-efficient.",
    );
  });

  it("renders optional median quadrant guides without changing point values", () => {
    render(<AnalyticsScatter {...props} medianX={6.85} medianY={25} />);

    expect(screen.getByTestId("median-x")).toBeInTheDocument();
    expect(screen.getByTestId("median-y")).toBeInTheDocument();
    expect(screen.getAllByTestId("analytics-point")[0]).toHaveAttribute("cx");
  });

  it("clamps padded ticks to declared physical metric bounds", () => {
    render(
      <AnalyticsScatter
        {...props}
        points={[{ id: "certain", label: "Certain", x: 0, y: 1 }]}
        xAxis={{
          label: "P(blank)",
          direction: "minimize",
          bounds: { min: 0, max: 1 },
          format: (value) => `${Math.round(value * 100)}%`,
        }}
        yAxis={{
          label: "P(haul)",
          direction: "maximize",
          bounds: { min: 0, max: 1 },
          format: (value) => `${Math.round(value * 100)}%`,
        }}
      />,
    );

    expect(screen.getAllByText("0%").length).toBeGreaterThan(0);
    expect(screen.getAllByText("100%").length).toBeGreaterThan(0);
    expect(screen.queryByText("-100%")).not.toBeInTheDocument();
    expect(screen.queryByText("200%")).not.toBeInTheDocument();
  });

  it("renders an explicit empty state and ignores non-finite coordinates", () => {
    render(
      <AnalyticsScatter
        {...props}
        points={[{ id: "missing", label: "Missing", x: Number.NaN, y: 1 }]}
        emptyMessage="No players have both values."
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("No players have both values.");
    expect(screen.queryByRole("group", { name: "Player value frontier" })).not.toBeInTheDocument();
  });
});
