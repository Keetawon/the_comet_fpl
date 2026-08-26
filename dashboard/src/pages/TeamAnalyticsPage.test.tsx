import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { loadFixtureMatrix, loadNextGw } from "@/data/load";
import sample from "@/data/sampleFixtureMatrix.json";
import type { FixtureScheduleOverlay, TeamRecord } from "@/data/types";
import { TeamAnalyticsPage } from "./TeamAnalyticsPage";

vi.mock("@/data/load", () => ({
  loadFixtureMatrix: vi.fn(),
  loadNextGw: vi.fn(),
}));

const teams = sample.teams as unknown as TeamRecord[];
const schedule: FixtureScheduleOverlay = {
  schema_version: 2,
  semantics: "current_at_export_not_forecast_vintage",
  export_created_at: "2026-08-21T12:00:00+00:00",
  database_sha256: "d".repeat(64),
  teams: [],
};

beforeAll(() => {
  HTMLElement.prototype.hasPointerCapture = () => false;
  HTMLElement.prototype.setPointerCapture = () => undefined;
  HTMLElement.prototype.releasePointerCapture = () => undefined;
  HTMLElement.prototype.scrollIntoView = () => undefined;
});

beforeEach(() => {
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams,
    schedule,
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
  vi.mocked(loadNextGw).mockResolvedValue({ plans: [] });
});

describe("TeamAnalyticsPage", () => {
  it("renders the accessible scatter, deterministic facts, and authoritative exact table", async () => {
    render(<TeamAnalyticsPage />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Team analytics" })).toBeInTheDocument());

    expect(screen.getByRole("group", { name: /Two-sided club environment/ })).toBeInTheDocument();
    const points = screen.getAllByTestId("analytics-point");
    expect(points.length).toBeGreaterThan(0);
    expect(points[0]).toHaveAttribute("tabindex", "0");
    expect(points[0]).toHaveAccessibleName(/Summed expected goals against/);
    expect(screen.getByRole("table", { name: "Exact team analytics values" })).toBeInTheDocument();
    expect(screen.getByText("Expected CS count / fixture")).toBeInTheDocument();
    expect(screen.getByText(/expected count, not P\(at least one clean sheet\)/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Deterministic insight facts" })).toBeInTheDocument();
    expect(screen.getByText(/Stage A fallback row\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/Both DGW legs count separately/)).toBeInTheDocument();
  });

  it("filters to home modelled rows and never includes schedule-only rows", async () => {
    const user = userEvent.setup();
    render(<TeamAnalyticsPage />);
    await screen.findByRole("table", { name: "Exact team analytics values" });

    await user.click(screen.getByRole("radio", { name: "Home" }));
    const table = screen.getByRole("table", { name: "Exact team analytics values" });
    const alphaRow = within(table).getByText("Alpha").closest("tr");
    expect(alphaRow).not.toBeNull();
    // Alpha has exactly two home legs in the selected vintage: GW1 and one GW2 DGW leg.
    expect(within(alphaRow!).getByText("2")).toBeInTheDocument();
    expect(within(alphaRow!).getByText("3.700000 / 1.850000")).toBeInTheDocument();
    expect(screen.getByText(/3 modelled fixture rows/)).toBeInTheDocument();
  });

  it("changes the exact modelled end GW and retains both DGW legs", async () => {
    const user = userEvent.setup();
    render(<TeamAnalyticsPage />);
    await screen.findByRole("table", { name: "Exact team analytics values" });

    await user.click(screen.getByRole("combobox", { name: "To modelled gameweek" }));
    await user.click(screen.getByRole("option", { name: "GW2" }));

    const table = screen.getByRole("table", { name: "Exact team analytics values" });
    const alphaRow = within(table).getByText("Alpha").closest("tr");
    expect(alphaRow).not.toBeNull();
    expect(within(alphaRow!).getByText("3")).toBeInTheDocument();
    expect(within(alphaRow!).getByText("4.700000 / 1.566667")).toBeInTheDocument();
    expect(screen.getByText(/GW1-2, all venue, 4 modelled fixture rows/)).toBeInTheDocument();
  });

  it("labels expected clean sheets as a summed count and omits incomplete axes", async () => {
    const user = userEvent.setup();
    render(<TeamAnalyticsPage />);
    await screen.findByRole("table", { name: "Exact team analytics values" });

    await user.click(screen.getByRole("radio", { name: "Attack + defensive floor" }));
    expect(
      screen.getAllByText(/Expected clean sheets \(summed expected count\) \(higher is better\)/)
        .length,
    ).toBeGreaterThan(0);
    // Alpha's GW4 CS probability is null, so its full-horizon expected count is null, not a
    // partial 0.80. Beta's two measured values sum to 0.44.
    const table = screen.getByRole("table", { name: "Exact team analytics values" });
    const alphaRow = within(table).getByText("Alpha").closest("tr");
    const betaRow = within(table).getByText("Beta").closest("tr");
    expect(alphaRow).not.toBeNull();
    expect(betaRow).not.toBeNull();
    expect(within(alphaRow!).getByText("Not plotted — missing axis")).toBeInTheDocument();
    expect(within(betaRow!).getByText("0.440000 / 0.220000")).toBeInTheDocument();
    expect(screen.getByText(/Highest expected CS count: Beta \(0.440000\)/)).toBeInTheDocument();
  });

  it("makes past-vs-future explicitly explanatory with no frontier claim", async () => {
    const user = userEvent.setup();
    render(<TeamAnalyticsPage />);
    await screen.findByRole("table", { name: "Exact team analytics values" });

    await user.click(screen.getByRole("radio", { name: "Past vs future" }));
    expect(screen.getByRole("combobox", { name: "Past form window" })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Past metric" })).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: /Past xG for/ }).querySelector("desc"),
    ).toHaveTextContent("context only");
    expect(screen.getAllByText(/no frontier or buy\/avoid claim/i).length).toBeGreaterThan(0);
    expect(screen.queryByText("Heavy outline = Pareto-nondominated environment")).not.toBeInTheDocument();
  });

  it("switches vintages without mixing their team rows", async () => {
    const user = userEvent.setup();
    const runA = "aaaaaaaa00000000";
    const runB = "bbbbbbbb00000000";
    const multiVintage = teams.flatMap((team) => [
      { ...team, run_id: runA },
      {
        ...team,
        run_id: runB,
        fixtures: team.fixtures.map((fixture) => ({ ...fixture, lambda_for: 9 })),
      },
    ]);
    vi.mocked(loadFixtureMatrix).mockResolvedValueOnce({
      teams: multiVintage,
      schedule,
      manifest: null,
      easeIndexFormulaVersion: "fixture-ease-v1",
    });

    render(<TeamAnalyticsPage />);
    await screen.findByRole("combobox", { name: "Forecast vintage" });
    await user.click(screen.getByRole("combobox", { name: "Forecast vintage" }));
    await user.click(screen.getByRole("option", { name: /bbbbbbbb/ }));

    const table = screen.getByRole("table", { name: "Exact team analytics values" });
    const betaRow = within(table).getByText("Beta").closest("tr");
    expect(betaRow).not.toBeNull();
    expect(within(betaRow!).getByText("18.000000 / 9.000000")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Forecast vintage" })).toHaveTextContent(
      "Vintage · bbbbbbbb",
    );
  });

  it("renders explicit empty and error states", async () => {
    vi.mocked(loadFixtureMatrix).mockResolvedValueOnce({
      teams: [],
      schedule,
      manifest: null,
      easeIndexFormulaVersion: "fixture-ease-v1",
    });
    const first = render(<TeamAnalyticsPage />);
    expect(await screen.findByText(/No recorded forecast vintage/)).toBeInTheDocument();
    first.unmount();

    vi.mocked(loadFixtureMatrix).mockRejectedValueOnce(new Error("read model unavailable"));
    render(<TeamAnalyticsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("read model unavailable");
  });
});
