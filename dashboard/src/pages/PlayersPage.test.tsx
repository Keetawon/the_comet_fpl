// Page smoke: the Players page renders from a read model without crashing -- player rows,
// the form anchor-season label, the availability overlay labelling, filter controls, xP
// chips, and the expandable per-fixture primitives.

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadPlayers } from "@/data/load";
import sample from "@/data/samplePlayers.json";
import { PlayersPage } from "./PlayersPage";

vi.mock("@/data/load", () => ({ loadPlayers: vi.fn() }));

beforeEach(() => {
  vi.mocked(loadPlayers).mockResolvedValue({ players: sample.players, manifest: null });
});

describe("PlayersPage", () => {
  it("renders players with form anchor labels, filters, availability overlay, and chips", async () => {
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    expect(screen.getByText("Beta")).toBeInTheDocument();
    // form is labelled with the season it was measured in, not the forecast season
    expect(screen.getByText(/Form 2025-26 · GW38/)).toBeInTheDocument();
    // availability is labelled as a reported overlay, never as "starts"
    expect(screen.getAllByText(/doubtful/).length).toBeGreaterThan(0);
    expect(
      screen.getByRole("spinbutton", { name: "Minimum price in millions" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Position")).toBeInTheDocument();
    // chips headline the xP
    expect(screen.getAllByTestId("chip").length).toBeGreaterThanOrEqual(3);
    expect(screen.getByText(/7\.4/)).toBeInTheDocument();
  });

  it("expands a row to the per-fixture primitives behind the colour", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    await user.click(screen.getAllByRole("button", { name: /expand fixtures/i })[0]);
    expect(await screen.findByText("Club λ for")).toBeInTheDocument();
    expect(screen.getByText("Club λ against")).toBeInTheDocument();
    expect(screen.getByText("Club CS")).toBeInTheDocument();
    expect(screen.getByText(/form anchored 2025-26 GW38/)).toBeInTheDocument();
  });

  it("marks unmeasured form as absent, never zero", async () => {
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Beta")).toBeInTheDocument());
    expect(screen.getByText("No form data")).toBeInTheDocument();
  });

  it("sorts through a keyboard-focusable button that carries aria-sort", async () => {
    const user = userEvent.setup();
    render(<PlayersPage />);
    await waitFor(() => expect(screen.getByText("Alpha")).toBeInTheDocument());
    const header = screen.getByRole("columnheader", { name: /^Price/ });
    expect(header).toHaveAttribute("aria-sort", "none");
    await user.click(within(header).getByRole("button"));
    // numeric columns sort descending first (tanstack auto sort direction)
    expect(header).toHaveAttribute("aria-sort", "descending");
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
