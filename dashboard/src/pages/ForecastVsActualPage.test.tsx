// Page smoke: the populated state renders the score tables and calibration; the 2026-27
// no-outcomes state renders the explicit empty explanation, never zero-filled numbers.

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { loadForecastVsActual } from "@/data/load";
import sample from "@/data/sampleForecastVsActual.json";
import { ForecastVsActualPage } from "./ForecastVsActualPage";

vi.mock("@/data/load", () => ({ loadForecastVsActual: vi.fn() }));

describe("ForecastVsActualPage", () => {
  it("renders per-position and per-gameweek scores plus calibration when outcomes exist", async () => {
    vi.mocked(loadForecastVsActual).mockResolvedValue(sample);
    render(<ForecastVsActualPage />);
    await waitFor(() => expect(screen.getByText(/86a072ade6dd/)).toBeInTheDocument());
    expect(screen.getByText("Position")).toBeInTheDocument();
    expect(screen.getByText("Gameweek")).toBeInTheDocument();
    expect(screen.getAllByText(/Bias \(actual − EV\)/).length).toBe(2); // position + gw tables
    expect(screen.getByText(/P\(≥ 2 pts\) bucket/)).toBeInTheDocument();
    expect(screen.getAllByText("+1.00").length).toBeGreaterThan(0); // GK bias
  });

  it("shows the explicit empty state when no vintage has finalised outcomes", async () => {
    vi.mocked(loadForecastVsActual).mockResolvedValue({ has_outcomes: false, runs: [] });
    render(<ForecastVsActualPage />);
    await waitFor(() =>
      expect(
        screen.getByText(/No finalised outcomes inside any recorded vintage yet\./),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText(/never read as zero/)).toBeInTheDocument();
  });
});
