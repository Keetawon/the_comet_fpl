// Page smoke: the Fixture matrix pivot renders from a read model -- one row per club of
// the selected vintage, per-GW chip columns with blank slots, the three colour sources,
// default sort by average ease (easiest first), and opponent-strength colouring direction
// (a weak opponent colours green, a strong opponent red, regardless of the row club).

import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadFixtureMatrix, loadNextGw } from "@/data/load";
import sample from "@/data/sampleFixtureMatrix.json";
import nextGwSample from "@/data/sampleNextGw.json";
import type { NextGwPlan } from "@/data/types";
import { FixtureMatrixPage } from "./FixtureMatrixPage";

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];

vi.mock("@/data/load", () => ({
  loadFixtureMatrix: vi.fn(),
  loadNextGw: vi.fn(),
}));

beforeEach(() => {
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams: sample.teams,
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
});

describe("FixtureMatrixPage", () => {
  it("renders one row per club with per-GW chips, blank slots, and all colour sources", async () => {
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getAllByText("Beta").length).toBeGreaterThan(0);
    // recent form from the anchor season, one compact line
    expect(screen.getByText(/W3 D1 L1/)).toBeInTheDocument();
    // the three colour sources and the three views are reachable
    expect(screen.getByText("Opponent strength")).toBeInTheDocument();
    expect(screen.getByText("Club ease")).toBeInTheDocument();
    expect(screen.getByText("Official FDR")).toBeInTheDocument();
    expect(screen.getByText("Attack")).toBeInTheDocument();
    // per-GW pivot cells: chips for played gameweeks, blank slots for missing ones
    expect(screen.getAllByTestId("chip").length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByTestId("blank-slot").length).toBeGreaterThanOrEqual(1);
  });

  it("defaults to opponent-strength colouring: weak opponent green, strong opponent red", async () => {
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    // Beta (model λ: scores little, concedes lots) reads ~90 -> green end
    const alphaGw1 = screen.getAllByTestId("chip").find(
      (c) => c.dataset.gw === "1" && c.closest("tr")!.textContent!.includes("Alpha"),
    )!;
    expect(alphaGw1.dataset.bucket).toBe("easier");
    expect(alphaGw1.className).toContain("bg-green");
    // Alpha (model λ: strong both ways) reads ~120 -> red end
    const betaGw1 = screen.getAllByTestId("chip").find(
      (c) => c.dataset.gw === "1" && c.closest("tr")!.textContent!.includes("Beta"),
    )!;
    expect(betaGw1.dataset.bucket).toBe("harder");
    expect(betaGw1.className).toContain("bg-red");
  });

  it("sorts by average ease by default, easiest schedule first", async () => {
    const { container } = render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const rows = container.querySelectorAll("tbody > tr");
    const firstTeamRow = [...rows].find(
      (r) => r.textContent?.includes("Beta") || r.textContent?.includes("Alpha"),
    );
    // Beta's only measured fixture averages 118.6 vs Alpha's 106.5, so Beta leads.
    expect(firstTeamRow!.textContent).toContain("Beta");
  });

  it("explains when the export carries no recorded vintage", async () => {
    vi.mocked(loadFixtureMatrix).mockResolvedValueOnce({
      teams: [],
      manifest: null,
      easeIndexFormulaVersion: "fixture-ease-v1",
    });
    render(<FixtureMatrixPage />);
    expect(await screen.findByText(/No recorded forecast vintages/)).toBeInTheDocument();
  });
});
