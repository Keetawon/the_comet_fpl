import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadPlayerForecastVsActual } from "@/data/load";
import sample from "@/data/samplePlayerForecastVsActual.json";
import type { PlayerForecastVsActualData } from "@/data/types";
import { PlayerForecastVsActualPage } from "./PlayerForecastVsActualPage";

vi.mock("@/data/load", () => ({ loadPlayerForecastVsActual: vi.fn() }));

const payload = sample as unknown as PlayerForecastVsActualData;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

beforeEach(() => {
  vi.mocked(loadPlayerForecastVsActual).mockReset();
});

describe("PlayerForecastVsActualPage", () => {
  it("renders coverage, published KPIs, identity scatter, exact observations, and reliability", async () => {
    vi.mocked(loadPlayerForecastVsActual).mockResolvedValue(payload);
    render(<PlayerForecastVsActualPage />);

    expect(await screen.findByRole("heading", { name: "Player prediction vs actual" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    expect(screen.getByText(/4 of 6 forecast player-gameweeks scored/)).toBeInTheDocument();
    expect(screen.getByText(/partial double gameweek scores nothing/i)).toBeInTheDocument();
    expect(screen.getByText("Bias (actual − forecast)")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Player expected vs actual/ })).toBeInTheDocument();
    expect(screen.getByTestId("identity-line")).toBeInTheDocument();
    expect(screen.getAllByTestId("accuracy-point")).toHaveLength(4);
    expect(screen.getByRole("table", { name: "Exact player prediction observations" })).toBeInTheDocument();
    expect(screen.getAllByText("P(total ≤ 2)")).not.toHaveLength(0);
    expect(screen.getByText(/computed by the static Python emitter/)).toBeInTheDocument();
    expect(screen.getByText(/Largest under-prediction: Alpha GW1 \(\+2\.000\)/)).toBeInTheDocument();
  });

  it("uses a published single-gameweek score block instead of recomputing metrics", async () => {
    vi.mocked(loadPlayerForecastVsActual).mockResolvedValue(payload);
    render(<PlayerForecastVsActualPage />);
    await screen.findByRole("heading", { name: "Player prediction vs actual" });

    fireEvent.change(screen.getByLabelText("Completed player gameweek"), { target: { value: "2" } });
    await waitFor(() => expect(screen.getAllByTestId("accuracy-point")).toHaveLength(2));
    expect(screen.getByText("Player expected vs actual · GW2")).toBeInTheDocument();
    // Exact published by_gw bias is -0.5; observation aggregation is deliberately not used for KPI scoring.
    expect(screen.getAllByText("-0.500").length).toBeGreaterThan(0);
    expect(screen.getByText(/full run/)).toBeInTheDocument();
  });

  it("defaults to the newest scored vintage when a newer run has no actuals", async () => {
    const mixed = clone(payload);
    const pending = clone(mixed.runs[0]);
    pending.run_id = "newer-pending-player-run";
    pending.created_at = "2026-08-25T16:05:00Z";
    pending.coverage.scored_rows = 0;
    mixed.runs.push(pending);
    vi.mocked(loadPlayerForecastVsActual).mockResolvedValue(mixed);

    render(<PlayerForecastVsActualPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Player forecast vintage")).toHaveValue("player-run-001"),
    );
  });

  it("shows explicit no-outcome coverage without zero-filling", async () => {
    const empty = clone(payload);
    empty.has_outcomes = false;
    const run = empty.runs[0];
    run.coverage = {
      forecast_rows: 6,
      pending_rows: 6,
      final_eligible_rows: 0,
      missing_outcome_rows: 0,
      legacy_unavailable_rows: 0,
      scored_rows: 0,
      distribution_scored_rows: 0,
    };
    run.overall = {
      rows: 0,
      distribution_rows: 0,
      forecast_total: null,
      actual_total: null,
      forecast_mean: null,
      actual_mean: null,
      bias: null,
      mae: null,
      rmse: null,
      crps: null,
    };
    run.by_position = [];
    run.by_gw = [];
    run.by_team = [];
    run.calibration = [];
    run.observations = [];
    vi.mocked(loadPlayerForecastVsActual).mockResolvedValue(empty);

    render(<PlayerForecastVsActualPage />);
    expect(await screen.findByText(/No finalized player outcomes/)).toBeInTheDocument();
    expect(screen.getByText(/Pending and missing rows are never read as zero/)).toBeInTheDocument();
    expect(screen.getByText(/No fully finalized player-gameweek observations exist/)).toBeInTheDocument();
  });

  it("renders loader errors without stale values", async () => {
    vi.mocked(loadPlayerForecastVsActual).mockRejectedValue(new Error("schema v5 malformed"));
    render(<PlayerForecastVsActualPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("schema v5 malformed");
    expect(screen.queryByTestId("accuracy-point")).not.toBeInTheDocument();
  });
});
