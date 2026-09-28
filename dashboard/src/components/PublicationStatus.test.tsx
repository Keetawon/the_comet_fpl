import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PublicationStatus } from "./PublicationStatus";

const receipt = {
  schema: "fpl.dashboard-publication-status/v1", data_manifest_sha256: "bound", exported_at: "2026-09-15",
  source_known_at: "2026-09-15", latest_finalized_gw: 3,
  awaiting_finality: [{gw: 4, fixtures_completed: 10, fixtures_total: 10}],
  latest_forecast: { as_of: "2026-09-14", gw_from: 5, gw_to: 9 }, current_platform_plan: true,
};
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });
describe("publication freshness", () => {
  it("separates latest forecast from ended but unfinalized GW4", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: true, json: async () => receipt}));
    render(<PublicationStatus manifestHash="bound" />);
    expect(await screen.findByLabelText("Dashboard publication status")).toHaveTextContent("through GW3");
    expect(screen.getByText("GW4: 10/10 matches ended.")).toBeInTheDocument();
    expect(screen.getByLabelText("Dashboard publication status")).toHaveTextContent("GW5–9");
    expect(screen.getByText(/prediction scores remain pending/)).toBeInTheDocument();
  });
  it("does not mix a receipt with a different data generation", async () => {
    const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => receipt});
    vi.stubGlobal("fetch", fetcher);
    render(<PublicationStatus manifestHash="other" />);
    await waitFor(() => expect(fetcher).toHaveBeenCalledOnce());
    expect(screen.queryByLabelText("Dashboard publication status")).not.toBeInTheDocument();
    expect(screen.queryByText("Data update overdue")).not.toBeInTheDocument();
  });
  it("warns as an open page ages beyond the operational limit without changing data", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-15T07:59:00Z"));
    const fetcher = vi.fn().mockResolvedValue({ok: true, json: async () => receipt});
    vi.stubGlobal("fetch", fetcher);
    await act(async () => { render(<PublicationStatus manifestHash="bound" freshnessOnly />); });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    await act(async () => { await vi.advanceTimersByTimeAsync(120_000); });
    expect(screen.getByRole("status")).toHaveTextContent("Data update overdue");
    expect(screen.getByRole("status")).toHaveTextContent("FPL source: 2026-09-15");
    expect(screen.queryByText(/Officially finalized/)).not.toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledOnce();
  });
  it("does not treat a fresh export as proof of a fresh source", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-28T03:00:00Z"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: true, json: async () => ({
      ...receipt, exported_at: "2026-09-28T02:59:00Z",
    })}));
    await act(async () => { render(<PublicationStatus manifestHash="bound" freshnessOnly />); });
    expect(screen.getByRole("status")).toHaveTextContent("Data update overdue");
  });
  it("reports missing source freshness", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-15T01:00:00Z"));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ok: true, json: async () => ({
      ...receipt, source_known_at: null,
    })}));
    await act(async () => { render(<PublicationStatus manifestHash="bound" freshnessOnly />); });
    expect(screen.getByRole("status")).toHaveTextContent("Data freshness unavailable");
  });
});
