import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PublicationStatus } from "./PublicationStatus";

const receipt = {
  schema: "fpl.dashboard-publication-status/v1", data_manifest_sha256: "bound", exported_at: "2026-09-15",
  source_known_at: "2026-09-15", latest_finalized_gw: 3,
  awaiting_finality: [{gw: 4, fixtures_completed: 10, fixtures_total: 10}],
  latest_forecast: { as_of: "2026-09-14", gw_from: 5, gw_to: 9 }, current_platform_plan: true,
};
afterEach(() => vi.unstubAllGlobals());
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
  });
});
