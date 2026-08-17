// Plan builder (wizard v1): a screen-per-step wizard -- Start, manager import (clickable,
// collects the id with honest post-deadline labelling), Set your rules (picker + shared filters
// + threshold + budget meter), Review & run (lock chips, exact command bridge). Flow invariant:
// every screen has a forward and a backward edge, navigation never clears state (only the
// labelled Reset rules does, in place), and the review screen ends forward with a Done link to
// the Next GW page -- no destructive or dead-end exit anywhere.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadNextGw, loadOptimizerAudit, loadPlayers } from "@/data/load";
import playersSample from "@/data/samplePlayers.json";
import nextGwSample from "@/data/sampleNextGw.json";
import auditSample from "@/data/sampleOptimizerAudit.json";
import type { NextGwPlan, OptimizerAuditData } from "@/data/types";
import { PlanBuilderPage } from "./PlanBuilderPage";

vi.mock("@/data/load", () => ({
  loadPlayers: vi.fn(),
  loadNextGw: vi.fn(),
  loadOptimizerAudit: vi.fn(),
}));

const plans: NextGwPlan[] = nextGwSample.plans as unknown as NextGwPlan[];
const audit: OptimizerAuditData = auditSample as unknown as OptimizerAuditData;

beforeEach(() => {
  vi.mocked(loadPlayers).mockResolvedValue({ players: playersSample.players, manifest: null });
  vi.mocked(loadNextGw).mockResolvedValue({ plans });
  vi.mocked(loadOptimizerAudit).mockResolvedValue(audit);
  window.localStorage.clear();
});

describe("PlanBuilderPage", () => {
  it("starts with the two entry cards; import is clickable and labelled post-deadline", async () => {
    render(<PlanBuilderPage />);
    expect(await screen.findByText("Import my team")).toBeInTheDocument();
    expect(screen.getByText(/Lands after the GW1 deadline/)).toBeInTheDocument();
    expect(screen.getByText("Build from scratch →")).toBeInTheDocument();
  });

  it("opens the import screen, validates the manager id, and offers the scratch fallback", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Import my team"));
    const input = await screen.findByLabelText("FPL manager id");
    await user.type(input, "12a4");
    expect(screen.getByText(/Digits only/)).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "1234567");
    expect(screen.getByText(/Manager #1234567 saved/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Continue without import/ }));
    expect(screen.getByLabelText("Search player")).toBeInTheDocument();
  });

  it("locks a searched player, advances to review, and emits the exact command", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    const search = screen.getByRole("textbox", { name: "Search player" });
    await user.type(search, "Alpha");
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    expect(screen.getByText("locked")).toBeInTheDocument();
    // the shared filter bar is present (team/price/minutes/availability, no form window)
    expect(screen.getByRole("combobox", { name: "Team filter" })).toBeInTheDocument();
    expect(screen.getByRole("spinbutton", { name: "Minimum price in millions" })).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "Form window" })).not.toBeInTheDocument();
    // threshold + budget meter live on the rules screen
    await user.click(screen.getByText("25%"));
    expect(screen.getByRole("img", { name: /^Budget meter/ })).toBeInTheDocument();
    expect(screen.getByText(/headroom £/)).toBeInTheDocument();
    // advancing to review keeps the lock and shows the command with both flags
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    expect(screen.getByRole("button", { name: "Remove Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy command" })).toBeInTheDocument();
    const pre = document.querySelector("pre")!; // the command block is the page's only <pre>
    expect(pre.textContent).toContain("--lock 1");
    expect(pre.textContent).toContain("--min-bench-appearance 0.25");
    // removing the lock through the chip drops it from the command
    await user.click(screen.getByRole("button", { name: "Remove Alpha" }));
    expect(pre.textContent).not.toContain("--lock 1");
  });

  it("never strands the user: exits are movement-only and the review ends forward", async () => {
    const user = userEvent.setup();
    render(<PlanBuilderPage />);
    await user.click(await screen.findByText("Build from scratch →"));
    await user.type(screen.getByRole("textbox", { name: "Search player" }), "Alpha");
    await user.click(screen.getByRole("button", { name: /Alpha/ }));
    await user.click(screen.getByText("25%"));
    // Back to start is navigation only: re-entering resumes with the lock intact
    await user.click(screen.getByRole("button", { name: /Back to start/ }));
    expect(screen.getByText("Build from scratch →")).toBeInTheDocument();
    await user.click(screen.getByText("Build from scratch →"));
    expect(screen.getByRole("button", { name: /Alpha/ })).toHaveAttribute("aria-pressed", "true");
    // Reset rules is the only clearing action, and it clears in place
    await user.click(screen.getByRole("button", { name: /Reset rules/ }));
    expect(screen.queryByText("locked")).not.toBeInTheDocument();
    // the review screen ends forward: a Done link to the Next GW page, plus back -- never a
    // destructive reset (the reported last-page-to-first-page jump)
    await user.click(screen.getByRole("button", { name: /Next: Review & run/ }));
    const done = screen.getByRole("link", { name: /view Next GW/ });
    expect(done).toHaveAttribute("href", "#next-gw");
    await user.click(screen.getByRole("button", { name: /Back to rules/ }));
    expect(screen.getByRole("textbox", { name: "Search player" })).toBeInTheDocument();
  });
});
