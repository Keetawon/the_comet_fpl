// Page smoke: the Players pivot renders from a read model without crashing -- one row
// per player of the SELECTED vintage (never one per recorded run), player filters, the
// availability overlay label, per-GW chip columns with blank slots, and the expandable
// per-fixture primitives ordered by kickoff.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadFixtureMatrix, loadNextGw, loadPlayers } from "@/data/load";
import playersSample from "@/data/samplePlayers.json";
import teamsSample from "@/data/sampleFixtureMatrix.json";
import nextGwSample from "@/data/sampleNextGw.json";
import type { NextGwPlan, PlayerFormWindow, PlayerRecord, TeamRecord } from "@/data/types";
import { PlayersPage } from "./PlayersPage";

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];

vi.mock("@/data/load", () => ({
  loadPlayers: vi.fn(),
  loadFixtureMatrix: vi.fn(),
  loadNextGw: vi.fn(),
}));

const teamsForRunA: TeamRecord[] = teamsSample.teams.map((t) => ({ ...t, run_id: "run-a" }));

function playerWithLastFive(
  code: number,
  webName: string,
  position: string,
  form: Partial<PlayerFormWindow>,
): PlayerRecord {
  const source = playersSample.players[0] as unknown as PlayerRecord;
  if (source.form == null) throw new Error("sample player must carry observed form");
  return {
    ...source,
    code,
    web_name: webName,
    position,
    form: {
      ...source.form,
      windows: {
        ...source.form.windows,
        last_5: { ...source.form.windows.last_5, ...form },
      },
    },
  };
}

beforeEach(() => {
  vi.mocked(loadPlayers).mockResolvedValue({ players: playersSample.players, manifest: null });
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams: teamsForRunA,
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
});

describe("PlayersPage", () => {
  it("renders the pivot: players, form columns, availability overlay, GW chips", async () => {
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();
    // the form window is a named column set anchored to the season it measured
    expect(screen.getByText("Last 5 App")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /xP GW1-3/ })).toBeInTheDocument();
    // availability is labelled as the official overlay, never as "starts"
    expect(screen.getAllByText(/doubtful/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("spinbutton", { name: "Minimum price in millions" }),
    ).toBeInTheDocument();
    // one chip per fixture, blank slot for a gameweek with none (GW2 for Beta)
    expect(screen.getAllByTestId("chip").length).toBeGreaterThanOrEqual(4);
    expect(screen.getAllByTestId("blank-slot").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/7\.4/)).toBeInTheDocument();
  });

  it("switches the Players-only observed columns between Overall, Attack, and Defense", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());

    // Overall is genuinely balanced: common, attack, and defense form are all present.
    for (const name of ["Starts", "G", "xG/90", "CS", "GC", "Saves", "DC", "xGC", "BPS"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("radio", { name: "Defense" }));
    expect(screen.queryByRole("columnheader", { name: "G" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "xG/90" })).not.toBeInTheDocument();
    for (const name of ["CS", "GC", "Saves", "DC", "xGC", "Bonus", "BPS", "Pts"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }

    await user.click(screen.getByRole("radio", { name: "Attack" }));
    expect(screen.queryByRole("columnheader", { name: "CS" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "xGC" })).not.toBeInTheDocument();
    for (const name of ["G", "A", "xG", "xA", "xG/90", "xA/90", "Bonus", "BPS", "Pts"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument();
    }
  });

  it("distinguishes measured zero, unmeasured, and position-inapplicable defense form", async () => {
    const user = userEvent.setup();
    const players = [
      playerWithLastFive(11, "Null Defender", "DEF", {
        clean_sheets: 0,
        goals_conceded: 4,
        saves: 0,
        defensive_contribution: 0,
        expected_goals_conceded: null,
      }),
      playerWithLastFive(12, "Keeper", "GK", {
        clean_sheets: 2,
        goals_conceded: 3,
        saves: 12,
        defensive_contribution: 0,
        expected_goals_conceded: 1.2,
      }),
      playerWithLastFive(13, "Measured Defender", "DEF", {
        clean_sheets: 1,
        goals_conceded: 2,
        saves: 0,
        defensive_contribution: 17,
        expected_goals_conceded: 2.4,
      }),
      playerWithLastFive(14, "Midfielder", "MID", {
        clean_sheets: 1,
        goals_conceded: 7,
        saves: 0,
        defensive_contribution: 9,
        expected_goals_conceded: 3.1,
      }),
    ];
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players, manifest: null });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Null Defender")).toBeInTheDocument());
    await user.click(screen.getByRole("radio", { name: "Defense" }));

    const nullDefenderRow = screen.getByText("Null Defender").closest("tr")!;
    expect(within(nullDefenderRow).getByTitle("Observed CS: 0")).toHaveTextContent("0");
    expect(within(nullDefenderRow).getByTitle("Saves is not applicable to DEF")).toHaveTextContent(
      "–",
    );
    expect(
      within(nullDefenderRow).getByTitle("xGC is unmeasured in this form window"),
    ).toHaveTextContent("–");
    const keeperRow = screen.getByText("Keeper").closest("tr")!;
    expect(within(keeperRow).getByTitle("Observed GC: 3")).toHaveTextContent("3");
    expect(within(keeperRow).getByTitle("Observed Saves: 12")).toHaveTextContent("12");
    expect(within(keeperRow).getByTitle("Observed xGC: 1.2")).toHaveTextContent("1.2");
    expect(within(keeperRow).getByTitle("DC is not applicable to GK")).toHaveTextContent("–");
    const midfielderRow = screen.getByText("Midfielder").closest("tr")!;
    expect(within(midfielderRow).getByTitle("Observed DC: 9")).toHaveTextContent("9");
    for (const metric of ["GC", "Saves", "xGC"]) {
      expect(
        within(midfielderRow).getByTitle(`${metric} is not applicable to MID`),
      ).toHaveTextContent("–");
    }

    // Undefined/inapplicable values stay last in either sort direction.
    const xgc = screen.getByRole("columnheader", { name: "xGC" });
    const table = xgc.closest("table")!;
    const order = () =>
      [...table.querySelectorAll("tbody > tr")]
        .map((row) =>
          ["Null Defender", "Keeper", "Measured Defender", "Midfielder"].find((name) =>
            row.textContent?.includes(name),
          ),
        )
        .filter((name): name is string => name != null);
    await user.click(within(xgc).getByRole("button"));
    const firstDirection = order();
    expect(new Set(firstDirection.slice(-2))).toEqual(new Set(["Null Defender", "Midfielder"]));
    await user.click(within(xgc).getByRole("button"));
    const secondDirection = order();
    expect(new Set(secondDirection.slice(-2))).toEqual(new Set(["Null Defender", "Midfielder"]));
    expect(secondDirection.slice(0, 2)).toEqual(firstDirection.slice(0, 2).reverse());
  });

  it("shows each player once even when the export carries several vintages", async () => {
    const duplicated = [
      ...playersSample.players,
      ...playersSample.players.map((p) => ({ ...p, run_id: "run-b" })),
    ];
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players: duplicated, manifest: null });
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getAllByText("Alpha").length).toBe(1);
    expect(screen.getAllByText("Beta").length).toBe(1);
    // the vintage selector appears and names the default architecture
    expect(screen.getByRole("combobox", { name: "Forecast vintage" })).toBeInTheDocument();
  });

  it("expands a row to the per-fixture primitives behind the colour", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: /expand fixtures/i })[0]);
    expect(await screen.findByText("Club λ for")).toBeInTheDocument();
    expect(screen.getByText("Club λ against")).toBeInTheDocument();
    const clubCs = screen.getByText("Club CS");
    const detailTable = clubCs.closest("table")!;
    expect(within(detailTable).getByRole("columnheader", { name: "xG" })).not.toHaveClass(
      "opacity-50",
    );
    expect(within(detailTable).getByRole("columnheader", { name: "Club CS" })).not.toHaveClass(
      "opacity-50",
    );
    expect(screen.getAllByText(/form anchored 2025-26 GW38/).length).toBeGreaterThan(0);
    // the detail table leads with match time, not the main table's sort
    expect(screen.getByText("Kickoff (UTC)")).toBeInTheDocument();
  });

  it("sorts through a keyboard-focusable button that carries aria-sort", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const header = screen.getByRole("columnheader", { name: /^Price/ });
    expect(header).toHaveAttribute("aria-sort", "none");
    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "descending");
  });

  it("sorts by the range xP column (the default sort)", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const header = screen.getByRole("columnheader", { name: /xP GW1-3/ });
    // the page opens sorted by xP descending; clicking flips it to ascending
    expect(header).toHaveAttribute("aria-sort", "descending");
    await user.click(within(header).getByRole("button"));
    expect(header).toHaveAttribute("aria-sort", "ascending");
  });

  it("resets a sort whose form column disappears when the view changes", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const goals = screen.getByRole("columnheader", { name: "G" });
    const rangeXp = screen.getByRole("columnheader", { name: /xP GW1-3/ });
    await user.click(within(goals).getByRole("button"));
    expect(goals).not.toHaveAttribute("aria-sort", "none");
    expect(rangeXp).toHaveAttribute("aria-sort", "none");

    await user.click(screen.getByRole("radio", { name: "Defense" }));
    await waitFor(() => expect(rangeXp).toHaveAttribute("aria-sort", "descending"));
    expect(screen.queryByRole("columnheader", { name: "G" })).not.toBeInTheDocument();
  });

  it("says so when no players match the current filters", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    await user.type(screen.getByRole("spinbutton", { name: "Minimum price in millions" }), "99");
    expect(await screen.findByText("No players match the current filters.")).toBeInTheDocument();
  });

  it("explains when the export carries no players at all", async () => {
    vi.mocked(loadPlayers).mockResolvedValueOnce({ players: [], manifest: null });
    render(<PlayersPage />);
    expect(await screen.findByText(/No recorded forecast vintages/)).toBeInTheDocument();
  });
});
