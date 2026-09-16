import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { AccuracyObservationTable } from "./AccuracyObservationTable";
import { isPageAvailable } from "@/lib/pageAccess";

const rows = [{ name: "First", actual: -2, error: 3 }, { name: "Second", actual: 0, error: 1 }];
const columns = [
  { key: "name", label: "Player", value: (r: typeof rows[number]) => r.name },
  { key: "actual", label: "Actual", value: (r: typeof rows[number]) => r.actual },
  { key: "error", label: "Error", value: (r: typeof rows[number]) => r.error },
];

describe("published comparison table", () => {
  it("preserves signed/zero values, sorts and searches without changing the observations", () => {
    const before = JSON.stringify(rows);
    render(<AccuracyObservationTable title="Comparison" rows={rows} columns={columns} rowKey={r => r.name} searchText={r => r.name} context="GW3 frozen" />);
    const table = screen.getByRole("table", { name: "Comparison" });
    expect(within(table).getByText("-2")).toBeInTheDocument();
    expect(within(table).getByText("0")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Error ↓" }));
    expect(within(table).getAllByRole("row")[1]).toHaveTextContent("Second");
    fireEvent.change(screen.getByLabelText("Search Comparison"), { target: { value: "first" } });
    expect(within(table).queryByText("Second")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset table" }));
    expect(within(table).getByText("Second")).toBeInTheDocument();
    expect(screen.getByLabelText("Capture Comparison")).toBeInTheDocument();
    expect(JSON.stringify(rows)).toBe(before);
  });
  it("keeps pending observations empty rather than constructing outcomes", () => {
    render(<AccuracyObservationTable title="Pending" rows={[]} columns={columns} rowKey={r => r.name} searchText={r => r.name} context="GW4 pending" />);
    expect(screen.getByText(/Pending or missing results are not zero/)).toBeInTheDocument();
  });
  it("hides the two analytics routes without hiding actuals or observed SDP", () => {
    expect(isPageAvailable("team-analytics")).toBe(false);
    expect(isPageAvailable("player-analytics")).toBe(false);
    expect(isPageAvailable("team-stat-sdp")).toBe(true);
    expect(isPageAvailable("player-forecast-vs-actual")).toBe(true);
  });
});
