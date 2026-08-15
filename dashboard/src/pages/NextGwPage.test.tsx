// Page smoke: Summary and Next GW render from read models -- run header, overlay labelling,
// the XI with captain/vice, the horizon selector, the diff card, and no-EV-across-plans rule.

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import summarySample from "@/data/sampleSummary.json";
import nextGwSample from "@/data/sampleNextGw.json";
import { NextGwPage } from "./NextGwPage";
import { SummaryPage } from "./SummaryPage";

vi.mock("@/data/load", () => ({
  loadSummary: vi.fn().mockResolvedValue(summarySample),
  loadNextGw: vi.fn().mockResolvedValue({ plans: nextGwSample.plans }),
}));

describe("SummaryPage", () => {
  it("renders the latest run, next-gameweek kickoff, headline lists, and plan labels", async () => {
    render(<SummaryPage />);
    await waitFor(() => expect(screen.getByText("Summary")).toBeInTheDocument());
    expect(screen.getByText(/2026-27 · GW1-5/)).toBeInTheDocument();
    expect(screen.getByText(/first kickoff 2026-08-22 11:30 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/deadlines are not sourced/)).toBeInTheDocument();
    expect(screen.getByText("Top GW1 xP")).toBeInTheDocument();
    expect(screen.getByText(/Availability flags \(reported overlay\)/)).toBeInTheDocument();
    expect(screen.getByText(/\(default\)/)).toBeInTheDocument();
    expect(screen.getByText(/\(diagnostic\)/)).toBeInTheDocument();
  });
});

describe("NextGwPage", () => {
  it("renders the default plan's XI, captain, bench, and the diff card", async () => {
    render(<NextGwPage />);
    await waitFor(() => expect(screen.getByText(/Next GW suggestion — GW1/)).toBeInTheDocument());
    // the XI line names the captain and vice inside nested spans, so match the paragraph
    expect(screen.getByText(/Formation/).textContent).toContain("captain Alpha");
    expect(screen.getByText(/Formation/).textContent).toContain("vice Beta");
    // bench carries the autosub order
    expect(screen.getByText(/Bench \(autosub order/)).toBeInTheDocument();
    // the diff card reports overlap and never compares EV across architectures
    expect(screen.getByText(/Default vs diagnostic \(GW1\)/)).toBeInTheDocument();
    expect(screen.getByText(/squad overlap 2\/3/)).toBeInTheDocument();
    expect(screen.getByText(/captain differs/)).toBeInTheDocument();
    expect(screen.getAllByText(/Gamma/).length).toBeGreaterThan(0); // unique-to-default list
    expect(screen.getByText(/Delta/)).toBeInTheDocument();
  });

  it("widens the EV horizon via the bounded selector", async () => {
    const user = userEvent.setup();
    render(<NextGwPage />);
    await waitFor(() => expect(screen.getByText(/Next GW suggestion — GW1/)).toBeInTheDocument());
    await user.click(screen.getByText("3 GWs"));
    expect(await screen.findByText("19.0")).toBeInTheDocument(); // 7.4 + 6.1 + 5.5
  });

  it("labels availability as a reported overlay with the chance percentage", async () => {
    render(<NextGwPage />);
    await waitFor(() => expect(screen.getByText(/doubtful 75%/)).toBeInTheDocument());
    expect(screen.getByText(/Availability \(overlay\)/)).toBeInTheDocument();
  });
});
