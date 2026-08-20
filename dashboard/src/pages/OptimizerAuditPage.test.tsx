// Page smoke: the audit page renders provenance, solver identity, the bounded-search policy,
// the constraints snapshot, assumptions, and the transfer path pulled from next_gw.json.

import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import auditSample from "@/data/sampleOptimizerAudit.json";
import nextGwSample from "@/data/sampleNextGw.json";
import { OptimizerAuditPage } from "./OptimizerAuditPage";

vi.mock("@/data/load", () => ({
  loadOptimizerAudit: vi.fn().mockResolvedValue(auditSample),
  loadNextGw: vi.fn().mockResolvedValue({ plans: nextGwSample.plans }),
}));

describe("OptimizerAuditPage", () => {
  it("renders the provenance, solver, policy, constraints, assumptions, and hits", async () => {
    render(<OptimizerAuditPage />);
    await waitFor(() =>
      expect(screen.getByText(/Optimizer audit/)).toBeInTheDocument(),
    );
    // development-only banner is always visible
    expect(screen.getByText(/development-only/)).toBeInTheDocument();
    // solver identity and status
    expect(screen.getByText(/CBC \(pulp 3\.0\.0/)).toBeInTheDocument();
    expect(screen.getByText("Optimal")).toBeInTheDocument();
    // search policy bounds and the no-global-optimality scope
    expect(screen.getByText(/not globally exact/)).toBeInTheDocument();
    expect(screen.getByText("bounded deterministic dynamic programme with beam pruning")).toBeInTheDocument();
    // constraints snapshot
    expect(screen.getByText("Constraints (verified squad-rule snapshot)")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Enter Optimizer position constraints table fullscreen",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("£100.0m")).toBeInTheDocument(); // budget_tenths 1000
    // assumptions list
    expect(screen.getByText(/bench points and autosub probabilities/)).toBeInTheDocument();
    // transfer path from next_gw.json (sample has no transfers in week 1)
    expect(screen.getByText(/no transfers/)).toBeInTheDocument();
  });
});
