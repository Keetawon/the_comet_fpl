// Page smoke: Summary and Next GW render from read models -- the landing sections (next
// GW, optimizer squad summaries, availability watch, players/teams to watch) and the
// squad pivot (plan EV columns beside the fixture chips, filters, the diff card, and the
// no-EV-across-plans rule).

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadFixtureMatrix,
  loadNextGw,
  loadPlayers,
  loadSummary,
} from "@/data/load";
import summarySample from "@/data/sampleSummary.json";
import nextGwSample from "@/data/sampleNextGw.json";
import playersSample from "@/data/samplePlayers.json";
import teamsSample from "@/data/sampleFixtureMatrix.json";
import type { NextGwPlan, TeamRecord } from "@/data/types";
import { NextGwPage } from "./NextGwPage";
import { SummaryPage } from "./SummaryPage";

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];

vi.mock("@/data/load", () => ({
  loadSummary: vi.fn(),
  loadNextGw: vi.fn(),
  loadPlayers: vi.fn(),
  loadFixtureMatrix: vi.fn(),
}));

const teamsForRunA: TeamRecord[] = teamsSample.teams.map((t) => ({ ...t, run_id: "run-a" }));

beforeEach(() => {
  vi.mocked(loadSummary).mockResolvedValue(summarySample);
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadPlayers).mockResolvedValue({ players: playersSample.players, manifest: null });
  vi.mocked(loadFixtureMatrix).mockResolvedValue({
    teams: teamsForRunA,
    manifest: null,
    easeIndexFormulaVersion: "fixture-ease-v1",
  });
});

describe("SummaryPage", () => {
  it("shows next GW, optimizer squad summaries, availability watch, and watchlists", async () => {
    render(<SummaryPage />);
    await waitFor(() => expect(screen.getByText(/2026-27 · GW1-3/)).toBeInTheDocument());
    expect(screen.getByText(/first kickoff 2026-08-22 11:30 UTC/)).toBeInTheDocument();
    expect(screen.getByText(/Deadlines are not sourced/)).toBeInTheDocument();
    // one summary card per plan, labelled by architecture, never comparing EV
    expect(screen.getByText(/Optimizer squad — default/)).toBeInTheDocument();
    expect(screen.getByText(/Optimizer squad — diagnostic/)).toBeInTheDocument();
    expect(screen.getAllByText(/GW1 squad xP/).length).toBe(2); // one card per plan
    // availability watch labels the official overlay status and chance
    expect(screen.getByText(/Availability watch/)).toBeInTheDocument();
    expect(screen.getByText(/doubtful 75%/)).toBeInTheDocument();
    // player and team watchlists derive from the selected vintage
    expect(screen.getAllByText(/Players to watch/).length).toBe(2);
    expect(screen.getByText(/easiest schedules/)).toBeInTheDocument();
    expect(screen.getByText(/hardest schedules/)).toBeInTheDocument();
  });
});

describe("NextGwPage", () => {
  it("renders the default plan's XI, captain, bench, the squad pivot, and the diff card", async () => {
    render(<NextGwPage />);
    await waitFor(() => expect(screen.getByText(/Next GW suggestion — GW1/)).toBeInTheDocument());
    expect(screen.getByText(/Formation/).textContent).toContain("captain Alpha");
    expect(screen.getByText(/Formation/).textContent).toContain("vice Beta");
    expect(screen.getByText(/Bench \(autosub order/)).toBeInTheDocument();
    // the squad table is the shared pivot: plan EV columns beside the GW fixture chips
    expect(screen.getByRole("columnheader", { name: /Plan xP GW1/ })).toBeInTheDocument();
    expect(screen.getAllByTestId("chip").length).toBeGreaterThan(0);
    // captain badge marks Alpha in the table
    expect(screen.getAllByText("C").length).toBeGreaterThan(0);
    // the diff card reports overlap and never compares EV across architectures
    expect(screen.getByText(/Default vs diagnostic \(GW1\)/)).toBeInTheDocument();
    expect(screen.getByText(/squad overlap 2\/3/)).toBeInTheDocument();
    expect(screen.getByText(/captain differs/)).toBeInTheDocument();
  });

  it("widens the EV horizon via the bounded selector", async () => {
    const user = userEvent.setup();
    render(<NextGwPage />);
    await waitFor(() => expect(screen.getByText(/Next GW suggestion — GW1/)).toBeInTheDocument());
    await user.click(screen.getByText("3 GWs"));
    expect(await screen.findByText("19.0")).toBeInTheDocument(); // 7.4 + 6.1 + 5.5
  });

  it("switches the pivot to compare the whole roster", async () => {
    const user = userEvent.setup();
    render(<NextGwPage />);
    await waitFor(() => expect(screen.getByText(/Next GW suggestion — GW1/)).toBeInTheDocument());
    await user.click(screen.getByText("Compare all players"));
    // the whole run-a roster (Alpha, Beta) renders -- Gamma has no read-model row
    expect(await screen.findByText("Squad only")).toBeInTheDocument();
    expect(screen.getAllByText("Alpha").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Beta").length).toBeGreaterThan(0);
  });

  it("colour-codes suggestion rows by role: captain gold, vice pale gold, bench grey", async () => {
    render(<NextGwPage />);
    await waitFor(() => expect(screen.getByText(/Next GW suggestion — GW1/)).toBeInTheDocument());
    const rowsOf = (name: string) =>
      screen.getAllByText(name).flatMap((element) => {
        const row = element.closest("tr");
        return row ? [row] : [];
      });
    // Alpha captains the default plan: a gold-highlighted row with an amber accent.
    expect(rowsOf("Alpha").some((row) => row.className.includes("bg-amber-100"))).toBe(true);
    // Beta is the vice-captain starter: the paler amber variant.
    expect(rowsOf("Beta").some((row) => row.className.includes("bg-amber-50"))).toBe(true);
    expect(screen.getByText(/row colours: gold = captain/)).toBeInTheDocument();
  });
});
