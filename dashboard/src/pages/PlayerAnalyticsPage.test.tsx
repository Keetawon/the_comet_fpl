import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { loadNextGw, loadPlayerHorizons, loadPlayers } from "@/data/load";
import nextGwSample from "@/data/sampleNextGw.json";
import horizonsSample from "@/data/samplePlayerHorizons.json";
import playersSample from "@/data/samplePlayers.json";
import type { NextGwPlan, PlayerHorizonsData, PlayerRecord } from "@/data/types";
import { PLAYER_HORIZON_FIELDS } from "@/data/types";
import { PlayerAnalyticsPage } from "./PlayerAnalyticsPage";

vi.mock("@/data/load", () => ({
  loadPlayers: vi.fn(),
  loadPlayerHorizons: vi.fn(),
  loadNextGw: vi.fn(),
}));

const plans = nextGwSample.plans as unknown as NextGwPlan[];
const horizons: PlayerHorizonsData = {
  ...(horizonsSample as unknown as Omit<
    PlayerHorizonsData,
    "horizon_fields" | "players"
  >),
  horizon_fields: PLAYER_HORIZON_FIELDS,
  players: horizonsSample.players.map((player) => ({
    ...player,
    horizons: player.horizons.map(
      ([gw_to, xp, p_le_2, p_ge_2, p_ge_4, p_ge_6, p_ge_10, p_ge_15]) => ({
        gw_to,
        xp,
        p_le_2,
        p_ge_2,
        p_ge_4,
        p_ge_6,
        p_ge_10,
        p_ge_15,
      }),
    ),
  })),
};

beforeAll(() => {
  HTMLElement.prototype.hasPointerCapture = () => false;
  HTMLElement.prototype.setPointerCapture = () => undefined;
  HTMLElement.prototype.releasePointerCapture = () => undefined;
  HTMLElement.prototype.scrollIntoView = () => undefined;
});

beforeEach(() => {
  vi.mocked(loadPlayers).mockResolvedValue({
    players: playersSample.players as unknown as PlayerRecord[],
    manifest: null,
  });
  vi.mocked(loadPlayerHorizons).mockResolvedValue(horizons);
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
});

describe("PlayerAnalyticsPage", () => {
  it("renders one exact fixed-start value frontier with a focusable chart and exact table", async () => {
    render(<PlayerAnalyticsPage />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Player analytics" })).toBeInTheDocument());
    expect(screen.getByText(/fixed start GW1/)).toBeInTheDocument();
    expect(screen.getByText(/2 plotted · 0 not plotted of 2 filtered players/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Insight summary" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeInTheDocument();
    expect(screen.getByText(/exact fixed-start GW1-5 endpoint/)).toBeInTheDocument();

    const table = screen.getByRole("table", { name: /Player analytics exact eligible values · Value frontier/ });
    const alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("£12.8m")).toBeInTheDocument();
    expect(within(alpha).getByText("27.000000")).toBeInTheDocument();
    expect(within(alpha).getByText("Yes")).toBeInTheDocument();

    const alphaPoint = screen.getByLabelText(
      /Alpha; MID · ALP; Deadline price \(£m\): £12\.8m; Cumulative xP · GW1-5: 27\.000000; Pareto frontier; vintage run-a · 2026-27; horizon GW1-5 \(fixed start\)/,
    );
    expect(alphaPoint).toHaveAttribute("tabindex", "0");
    expect(screen.getByLabelText("Player position colour legend")).toHaveTextContent(
      "outlined = efficient frontier (Pareto)",
    );
  });

  it("selects published downside/upside endpoints and changes threshold without arithmetic", async () => {
    const user = userEvent.setup();
    render(<PlayerAnalyticsPage />);
    await screen.findByRole("heading", { name: "Player analytics" });

    await user.click(screen.getByRole("radio", { name: "Upside / downside" }));
    const horizontalMin = screen.getByRole("spinbutton", {
      name: /Minimum horizontal chart value · P\(total/,
    });
    expect(horizontalMin.parentElement).toHaveTextContent(
      "Horizontal range (P(total ≤ 2), %)",
    );
    expect(horizontalMin).toHaveAttribute("max", "100");
    await user.type(horizontalMin, "5");
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(1);
    expect(screen.getByLabelText(/Beta; GK · BET/)).toBeInTheDocument();
    await user.clear(horizontalMin);

    let table = screen.getByRole("table", {
      name: /Player analytics exact eligible values · Upside \/ downside/,
    });
    let alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("0.50% (0.005000)")).toBeInTheDocument();
    expect(within(alpha).getByText("96.00% (0.960000)")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Haul threshold" }));
    await user.click(screen.getByRole("option", { name: "≥ 15" }));
    table = screen.getByRole("table", {
      name: /Player analytics exact eligible values · Upside \/ downside/,
    });
    alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("86.00% (0.860000)")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Cumulative horizon endpoint" }));
    await user.click(screen.getByRole("option", { name: "GW1-1" }));
    alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("25.00% (0.250000)")).toBeInTheDocument();
    expect(within(alpha).getByText("10.00% (0.100000)")).toBeInTheDocument();
  });

  it("focuses the horizontal chart domain without changing exact rows or frontier geometry", async () => {
    const user = userEvent.setup();
    render(<PlayerAnalyticsPage />);
    await screen.findByRole("heading", { name: "Player analytics" });

    const minimum = screen.getByRole("spinbutton", {
      name: /Minimum horizontal chart value · Deadline price/,
    });
    const maximum = screen.getByRole("spinbutton", {
      name: /Maximum horizontal chart value · Deadline price/,
    });
    expect(screen.getByText(/Horizontal range \(Deadline price/)).toBeInTheDocument();
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(2);
    const insightBeforeFocus = screen.getByTestId("insight-summary-panel").textContent;

    await user.type(minimum, "10");
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(1);
    expect(screen.getByText(/1 currently shown in the chart/)).toBeInTheDocument();
    const exactTable = screen.getByRole("table", { name: /exact eligible values · Value frontier/ });
    expect(within(exactTable).getByText("Alpha")).toBeInTheDocument();
    expect(within(exactTable).getByText("Beta")).toBeInTheDocument();

    await user.type(maximum, "5");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Min must not exceed max. Horizontal bounds are ignored.",
    );
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "Clear player analytics filters" }));
    expect(minimum).toHaveValue(null);
    expect(maximum).toHaveValue(null);
    expect(screen.getAllByTestId("analytics-point")).toHaveLength(2);

    await user.click(within(screen.getByRole("radiogroup", { name: "Chart point scope" })).getByRole("radio", { name: "Efficient frontier only" }));
    expect(screen.getAllByTestId("analytics-point").every((point) => point.dataset.frontier === "true"))
      .toBe(true);
    expect(within(exactTable).getByText("Beta")).toBeInTheDocument();
    expect(screen.getByTestId("insight-summary-panel").textContent).toBe(insightBeforeFocus);
  });

  it("counts unmeasured ownership as omitted in differential mode instead of zero", async () => {
    const user = userEvent.setup();
    render(<PlayerAnalyticsPage />);
    await screen.findByRole("heading", { name: "Player analytics" });

    await user.click(screen.getByRole("radio", { name: "Differential" }));
    expect(screen.getByText(/1 plotted · 1 not plotted of 2 filtered players/)).toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Differential/ });
    expect(within(table).getByText("Alpha")).toBeInTheDocument();
    expect(within(table).queryByText("Beta")).not.toBeInTheDocument();
    expect(screen.getByText(/1 are omitted because at least one selected axis value is unmeasured/)).toBeInTheDocument();
  });

  it("marks past-vs-future as explanatory context and never creates a frontier", async () => {
    const user = userEvent.setup();
    render(<PlayerAnalyticsPage />);
    await screen.findByRole("heading", { name: "Player analytics" });

    await user.click(screen.getByRole("radio", { name: "Past vs future" }));
    const horizontalMin = screen.getByRole("spinbutton", {
      name: /Minimum horizontal chart value · Observed points/,
    });
    await user.type(horizontalMin, "10");
    await user.click(screen.getByRole("combobox", { name: "Past form window" }));
    await user.click(screen.getByRole("option", { name: "Last 3" }));
    await waitFor(() => expect(horizontalMin).toHaveValue(null));
    expect(screen.getAllByText(/context only/).length).toBeGreaterThan(0);
    expect(screen.queryByText("outlined = efficient frontier (Pareto)")).not.toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Past vs future/ });
    const alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("16")).toBeInTheDocument();
    expect(within(alpha).getByText("2025-26 GW38")).toBeInTheDocument();
    expect(within(alpha).getByText("Context only")).toBeInTheDocument();
    expect(screen.getAllByText(/latest static-export anchor/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/may post-date the selected forecast vintage/i).length).toBeGreaterThan(0);
  });

  it("reuses player filters and explains a fully empty filtered scope", async () => {
    const user = userEvent.setup();
    render(<PlayerAnalyticsPage />);
    await screen.findByRole("heading", { name: "Player analytics" });

    await user.type(screen.getByRole("spinbutton", { name: "Minimum price in millions" }), "99");
    expect(screen.getAllByText("No players match the current filters.").length).toBeGreaterThan(0);
    expect(screen.getByText(/0 plotted · 0 not plotted of 0 filtered players/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear player analytics filters" }));
    expect(screen.getByText(/2 plotted · 0 not plotted of 2 filtered players/)).toBeInTheDocument();
  });

  it("shows honest error and no-vintage states", async () => {
    vi.mocked(loadPlayers).mockRejectedValueOnce(new Error("read model unavailable"));
    const { unmount } = render(<PlayerAnalyticsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("read model unavailable");
    unmount();

    vi.mocked(loadPlayers).mockResolvedValueOnce({ players: [], manifest: null });
    vi.mocked(loadPlayerHorizons).mockResolvedValueOnce({ ...horizons, players: [] });
    render(<PlayerAnalyticsPage />);
    expect(
      await screen.findByText(/No recorded forecast vintages with cumulative player endpoints/),
    ).toBeInTheDocument();
  });
});
