// Page smoke: the Fixture matrix page renders from a read model without crashing --
// team rows, the form anchor-season label (last season at GW1), ticker chips, and the
// colour-source toggle are all present.

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import sample from "@/data/sampleFixtureMatrix.json";
import { FixtureMatrixPage } from "./FixtureMatrixPage";

vi.mock("@/data/load", () => ({
  loadFixtureMatrix: vi.fn().mockResolvedValue({
    teams: sample.teams,
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  }),
}));

describe("FixtureMatrixPage", () => {
  it("renders team rows with anchor-labelled form and fixture chips", async () => {
    render(<FixtureMatrixPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();
    // the form block is labelled with the season it was measured in, not the forecast season
    expect(screen.getByText(/Form 2025-26 · GW38/)).toBeInTheDocument();
    expect(screen.getAllByTestId("chip").length).toBeGreaterThanOrEqual(4);
    // the two colour sources and the three views are reachable
    expect(screen.getByText("Official FDR")).toBeInTheDocument();
    expect(screen.getByText("Model ease")).toBeInTheDocument();
    expect(screen.getByText("Attack")).toBeInTheDocument();
  });
});
