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
    expect(screen.getByRole("heading", { name: "Deterministic insight" })).toBeInTheDocument();
    expect(screen.getByText(/exact fixed-start GW1-5 endpoint/)).toBeInTheDocument();

    const table = screen.getByRole("table", { name: /Player analytics exact values · Value frontier/ });
    const alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("£12.8m")).toBeInTheDocument();
    expect(within(alpha).getByText("27.000000")).toBeInTheDocument();
    expect(within(alpha).getByText("Yes")).toBeInTheDocument();

    const alphaPoint = screen.getByLabelText(
      /Alpha; MID · ALP; Deadline price \(£m\): £12\.8m; Cumulative xP · GW1-5: 27\.000000; Pareto frontier; vintage run-a · 2026-27; horizon GW1-5 \(fixed start\)/,
    );
    expect(alphaPoint).toHaveAttribute("tabindex", "0");
    expect(screen.getByLabelText("Player position colour legend")).toHaveTextContent(
      "outlined = Pareto frontier",
    );
  });

  it("selects published downside/upside endpoints and changes threshold without arithmetic", async () => {
    const user = userEvent.setup();
    render(<PlayerAnalyticsPage />);
    await screen.findByRole("heading", { name: "Player analytics" });

    await user.click(screen.getByRole("radio", { name: "Upside / downside" }));
    let table = screen.getByRole("table", {
      name: /Player analytics exact values · Upside \/ downside/,
    });
    let alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("0.50% (0.005000)")).toBeInTheDocument();
    expect(within(alpha).getByText("96.00% (0.960000)")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Haul threshold" }));
    await user.click(screen.getByRole("option", { name: "≥ 15" }));
    table = screen.getByRole("table", {
      name: /Player analytics exact values · Upside \/ downside/,
    });
    alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("86.00% (0.860000)")).toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Cumulative horizon endpoint" }));
    await user.click(screen.getByRole("option", { name: "GW1-1" }));
    alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("25.00% (0.250000)")).toBeInTheDocument();
    expect(within(alpha).getByText("10.00% (0.100000)")).toBeInTheDocument();
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
    expect(screen.getAllByText(/context only/).length).toBeGreaterThan(0);
    expect(screen.queryByText("outlined = Pareto frontier")).not.toBeInTheDocument();
    const table = screen.getByRole("table", { name: /Past vs future/ });
    const alpha = within(table).getByText("Alpha").closest("tr")!;
    expect(within(alpha).getByText("31")).toBeInTheDocument();
    expect(within(alpha).getByText("Context only")).toBeInTheDocument();
    expect(screen.getByText(/comparison is explanatory, not causal/)).toBeInTheDocument();
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
