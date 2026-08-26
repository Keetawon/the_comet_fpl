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
    expect(screen.getByRole("combobox", { name: "Chart extent" })).toHaveTextContent(
      "All plotted clubs",
    );
    expect(
      screen.getByText(/efficient frontier \(Pareto-nondominated direct values\)/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Exact team analytics values" })).toBeInTheDocument();
    expect(screen.getByText("Expected CS count / fixture")).toBeInTheDocument();
    expect(screen.getByText(/expected count, not P\(at least one clean sheet\)/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Insight summary" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    expect(screen.getByText(/selected-scope modelled rows use the published Stage A/i)).toBeInTheDocument();
    expect(screen.getByText(/Both DGW legs count separately/)).toBeInTheDocument();
  });

  it("lets the user fit the axes to the sanctioned direct-value efficient frontier", async () => {
    const user = userEvent.setup();
    render(<TeamAnalyticsPage />);
    await screen.findByRole("table", { name: "Exact team analytics values" });

    const allPoints = screen.getAllByTestId("analytics-point");
    const frontierCount = allPoints.filter(
      (point) => point.getAttribute("data-frontier") === "true",
    ).length;
    expect(frontierCount).toBeGreaterThan(0);
    expect(
      screen.getByRole("group", { name: /Two-sided club environment/ }).querySelector("desc"),
    ).toHaveTextContent(/published λ against/i);
    const insightBeforeFocus = screen.getByTestId("insight-summary-panel").textContent;

    await user.click(screen.getByRole("combobox", { name: "Chart extent" }));
    await user.click(screen.getByRole("option", { name: "Efficient frontier only" }));

    const focusedPoints = screen.getAllByTestId("analytics-point");
    expect(focusedPoints).toHaveLength(frontierCount);
    expect(focusedPoints.every((point) => point.getAttribute("data-frontier") === "true")).toBe(
      true,
    );
    expect(screen.queryByTestId("median-x")).not.toBeInTheDocument();
    expect(screen.queryByTestId("median-y")).not.toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(`Chart shows ${frontierCount} of ${allPoints.length}`)),
    ).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Exact team analytics values" })).toBeInTheDocument();
    expect(screen.getByTestId("insight-summary-panel").textContent).toBe(insightBeforeFocus);
  });

  it("offers chart-only horizontal bounds without changing the frontier or exact table", async () => {
    const user = userEvent.setup();
    render(<TeamAnalyticsPage />);
    const table = await screen.findByRole("table", { name: "Exact team analytics values" });
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(2);

    await user.type(
      screen.getByRole("spinbutton", { name: /X minimum · Summed expected goals against/ }),
      "4",
    );

    const focusedPoints = screen.getAllByTestId("analytics-point");
    expect(focusedPoints).toHaveLength(1);
    expect(focusedPoints[0]).toHaveAccessibleName(/^Alpha;/);
    expect(focusedPoints[0]).toHaveAttribute("data-frontier", "true");
    expect(screen.getByText(/Horizontal focus hides 1 eligible club/)).toBeInTheDocument();
    expect(screen.getByText(/frontier membership and the exact table stay based on the full/i)).toBeInTheDocument();
    expect(within(table).getByText("Alpha")).toBeInTheDocument();
    expect(within(table).getByText("Beta")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset X" }));
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(2);

    const minimum = screen.getByRole("spinbutton", {
      name: /X minimum · Summed expected goals against/,
    });
    const maximum = screen.getByRole("spinbutton", {
      name: /X maximum · Summed expected goals against/,
    });
    await user.type(minimum, "5");
    await user.type(maximum, "4");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "X minimum must not exceed X maximum. The chart remains unfiltered.",
    );
    expect(minimum).toHaveAttribute("aria-invalid", "true");
    expect(maximum).toHaveAttribute("aria-invalid", "true");
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(2);
  });

  it("explains an empty intersection between horizontal focus and frontier focus", async () => {
    const user = userEvent.setup();
    const gamma: TeamRecord = {
      ...teams[1],
      team_code: 103,
      team_name: "Gamma",
      short_name: "GAM",
      fixtures: teams[1].fixtures.map((fixture, index) => ({
        ...fixture,
        fixture: 200 + index,
        lambda_for: 1,
        lambda_against: 2,
      })),
    };
    vi.mocked(loadFixtureMatrix).mockResolvedValueOnce({
      teams: [...teams, gamma],
      schedule,
      manifest: null,
      easeIndexFormulaVersion: "fixture-ease-v1",
    });

    render(<TeamAnalyticsPage />);
    const table = await screen.findByRole("table", { name: "Exact team analytics values" });
    await user.type(
      screen.getByRole("spinbutton", { name: /X minimum · Summed expected goals against/ }),
      "3.5",
    );
    await user.type(
      screen.getByRole("spinbutton", { name: /X maximum · Summed expected goals against/ }),
      "4.1",
    );
    await user.click(screen.getByRole("combobox", { name: "Chart extent" }));
    await user.click(screen.getByRole("option", { name: "Efficient frontier only" }));

    expect(screen.queryAllByTestId("analytics-point")).toHaveLength(0);
    expect(
      screen.getByText(/No efficient-frontier club falls inside the selected horizontal focus/),
    ).toBeInTheDocument();
    expect(within(table).getByText("Gamma")).toBeInTheDocument();
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
    expect(screen.queryByRole("combobox", { name: "Chart extent" })).not.toBeInTheDocument();
    expect(screen.getAllByText(/latest at static export/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/may post-date an older run/i)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Exact team analytics values" });
    expect(within(table).getByText("Observed form anchor")).toBeInTheDocument();
    expect(within(table).getAllByText("2025-26 GW38").length).toBeGreaterThan(0);
  });

  it("clears stale horizontal bounds when the analytical scope changes", async () => {
    const user = userEvent.setup();
    render(<TeamAnalyticsPage />);
    await screen.findByRole("table", { name: "Exact team analytics values" });

    const minimum = screen.getByRole("spinbutton", {
      name: /X minimum · Summed expected goals against/,
    });
    await user.type(minimum, "4");
    expect(minimum).toHaveValue(4);

    await user.click(screen.getByRole("radio", { name: "Home" }));
    expect(minimum).toHaveValue(null);
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
