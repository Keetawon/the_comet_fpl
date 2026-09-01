import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadTeamForecastVsActual, loadTeamProvisionalActuals } from "@/data/load";
import sample from "@/data/sampleTeamForecastVsActual.json";
import type { TeamForecastVsActualData } from "@/data/types";
import { TeamForecastVsActualPage } from "./TeamForecastVsActualPage";

vi.mock("@/data/load", () => ({
  loadTeamForecastVsActual: vi.fn(),
  loadTeamProvisionalActuals: vi.fn(),
}));

const payload = sample as unknown as TeamForecastVsActualData;
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

beforeEach(() => {
  vi.mocked(loadTeamForecastVsActual).mockReset();
  vi.mocked(loadTeamProvisionalActuals).mockReset();
});

describe("TeamForecastVsActualPage", () => {
  it("renders reciprocal coverage, attack scores, identity scatter, cumulative clubs, and calibration", async () => {
    vi.mocked(loadTeamForecastVsActual).mockResolvedValue(payload);
    render(<TeamForecastVsActualPage />);

    expect(await screen.findByRole("heading", { name: "Team prediction vs actual" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    expect(screen.getByText(/4 of 6 forecast team-fixture sides scored/)).toBeInTheDocument();
    expect(screen.getByText(/two immutable reciprocal outcome sides agree/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Attack predicted vs actual/ })).toBeInTheDocument();
    expect(screen.getByTestId("identity-line")).toBeInTheDocument();
    expect(screen.getAllByTestId("accuracy-point")).toHaveLength(4);
    expect(screen.getByRole("table", { name: "Cumulative club prediction residuals" })).toBeInTheDocument();
    expect(screen.getByText(/expected count—not P\(at least one clean sheet\)/)).toBeInTheDocument();
    expect(screen.getByText(/browser does not compute probabilities, CRPS, calibration, or buckets/)).toBeInTheDocument();
    expect(loadTeamProvisionalActuals).not.toHaveBeenCalled();
  });

  it("labels defence residual direction in prose and exact values, not colour alone", async () => {
    vi.mocked(loadTeamForecastVsActual).mockResolvedValue(payload);
    render(<TeamForecastVsActualPage />);
    await screen.findByRole("heading", { name: "Team prediction vs actual" });

    fireEvent.click(screen.getByRole("button", { name: "Defence" }));
    expect(screen.getByText(/positive means more goals were conceded than forecast and is worse/i)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Defence predicted vs actual/ })).toBeInTheDocument();
    expect(screen.getAllByText(/positive worse/).length).toBeGreaterThan(0);
  });

  it("switches to published clean-sheet Brier/reliability without deriving probabilities", async () => {
    vi.mocked(loadTeamForecastVsActual).mockResolvedValue(payload);
    render(<TeamForecastVsActualPage />);
    await screen.findByRole("heading", { name: "Team prediction vs actual" });

    fireEvent.click(screen.getByRole("button", { name: "Clean sheet" }));
    expect(screen.getByText("Brier score")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Clean-sheet predicted vs actual/ })).toBeInTheDocument();
    expect(screen.getAllByText("P(clean sheet)").length).toBeGreaterThan(0);
  });

  it("filters geometry and KPIs to one published gameweek block", async () => {
    vi.mocked(loadTeamForecastVsActual).mockResolvedValue(payload);
    render(<TeamForecastVsActualPage />);
    await screen.findByRole("heading", { name: "Team prediction vs actual" });
    fireEvent.change(screen.getByLabelText("Completed team gameweek"), { target: { value: "2" } });

    await waitFor(() => expect(screen.getAllByTestId("accuracy-point")).toHaveLength(2));
    expect(screen.getByText("Attack predicted vs actual · GW2")).toBeInTheDocument();
    expect(screen.getAllByText("+0.700").length).toBeGreaterThan(0);
  });

  it("defaults to the scored prospective run and labels newer diagnostic and pending vintages", async () => {
    const mixed = clone(payload);
    const diagnostic = clone(mixed.runs[0]);
    diagnostic.run_id = "newer-scored-team-diagnostic";
    diagnostic.created_at = "2026-08-25T16:04:00Z";
    diagnostic.component_modes = {
      attacking_mode: "v1",
      assists_mode: "v1",
      appearance_mode: "seasonal",
    };
    const pending = clone(mixed.runs[0]);
    pending.run_id = "newer-pending-team-run";
    pending.created_at = "2026-08-25T16:05:00Z";
    pending.coverage.scored_rows = 0;
    mixed.runs.push(diagnostic, pending);
    vi.mocked(loadTeamForecastVsActual).mockResolvedValue(mixed);

    render(<TeamForecastVsActualPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Team forecast vintage")).toHaveValue("team-run-001"),
    );
    expect(
      screen.getAllByRole("option", {
        name: /Prospective default .* goals v3 .* assists coupled .* appearance seasonal/,
      }),
    ).toHaveLength(2);
    expect(
      screen.getByRole("option", {
        name: /Diagnostic comparator .* goals v1 .* assists v1 .* appearance seasonal/,
      }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Selected team forecast provenance")).toHaveTextContent(
      /Prospective default .* goals v3 .* assists coupled .* appearance seasonal/,
    );

    fireEvent.change(screen.getByLabelText("Completed team gameweek"), {
      target: { value: "2" },
    });
    fireEvent.change(screen.getByLabelText("Team forecast vintage"), {
      target: { value: diagnostic.run_id },
    });
    expect(screen.getByLabelText("Completed team gameweek")).toHaveValue("all");
    expect(screen.getByLabelText("Selected team forecast provenance")).toHaveTextContent(
      /Diagnostic comparator .* goals v1 .* assists v1 .* appearance seasonal/,
    );
  });

  it("shows pending empty state and loader errors explicitly", async () => {
    const empty = clone(payload);
    empty.has_outcomes = false;
    const run = empty.runs[0];
    run.coverage = {
      forecast_rows: 6,
      pending_rows: 6,
      missing_outcome_rows: 0,
      invalid_fixture_rows: 0,
      scored_rows: 0,
      attack_distribution_scored_rows: 0,
      defence_distribution_scored_rows: 0,
      clean_sheet_scored_rows: 0,
    };
    const emptyScore = { rows: 0, distribution_rows: 0, forecast_total: null, actual_total: null, forecast_mean: null, actual_mean: null, bias: null, mae: null, rmse: null, crps: null };
    run.attack = { ...emptyScore };
    run.defence = { ...emptyScore };
    run.clean_sheet = { rows: 0, predicted_mean: null, observed_rate: null, brier: null };
    run.by_gw = [];
    run.by_team = [];
    run.by_venue = [];
    run.by_fallback = [];
    run.calibration = [];
    run.observations = [];
    vi.mocked(loadTeamForecastVsActual).mockResolvedValue(empty);
    const { unmount } = render(<TeamForecastVsActualPage />);
    expect(await screen.findByText(/No finalized team outcomes/)).toBeInTheDocument();
    expect(screen.getByText(/Pending and missing fixtures are never read as zero/)).toBeInTheDocument();
    unmount();

    vi.mocked(loadTeamForecastVsActual).mockRejectedValue(new Error("team schema malformed"));
    render(<TeamForecastVsActualPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("team schema malformed");
  });
});
