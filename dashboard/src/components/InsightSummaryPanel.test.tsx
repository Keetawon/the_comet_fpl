import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InsightSummaryPanel, type RemoteInsightConfig } from "./InsightSummaryPanel";
import { fetchInsightStatus, fetchInsightSummary } from "@/lib/planServer";

vi.mock("@/lib/planServer", async () => {
  const actual = await vi.importActual<typeof import("@/lib/planServer")>("@/lib/planServer");
  return {
    ...actual,
    fetchInsightStatus: vi.fn(),
    fetchInsightSummary: vi.fn(),
  };
});

vi.mock("@/lib/planServerToken", () => ({ loadPlanServerToken: () => "test-token" }));

const provenance = {
  manifestSha256: "a".repeat(64),
  runId: "run-1",
  season: "2026-27",
  asOf: "2026-08-21T16:00:00Z",
};

function remote(gwTo = 5): RemoteInsightConfig {
  return {
    page: "players",
    provenance,
    scope: {
      gw_from: 1,
      gw_to: gwTo,
      position: "all",
      form_window: "season_to_date",
      min_price_tenths: 45,
      max_price_tenths: 150,
      min_avg_minutes_l5: 30,
      availability: "available",
      past_metric: "xg_per_90",
    },
  };
}

function panel(gwTo = 5, config = remote(gwTo)) {
  return (
    <InsightSummaryPanel
      items={[{ id: "coverage.players", statement: `${gwTo} players are visible.` }]}
      caveats={["Missing values are not zero."]}
      remote={config}
    />
  );
}

const response = {
  schema: "fpl.insight-summary-response" as const,
  schema_version: 1 as const,
  source: "provider" as const,
  provider: "zai_glm",
  model: "glm-test",
  prompt_version: "evidence-renderer-v1" as const,
  cache_key: "b".repeat(64),
  generated_at: "2026-08-26T08:00:00Z",
  headline: "Published coverage",
  items: [{ text: "Five rows are visible.", citations: ["coverage.players"] }],
};

beforeEach(() => {
  vi.mocked(fetchInsightStatus).mockResolvedValue({
    enabled: true,
    provider: "zai_glm",
    model: "glm-test",
    prompt_version: "evidence-renderer-v1",
  });
  vi.mocked(fetchInsightSummary).mockResolvedValue(response);
});

afterEach(() => {
  vi.clearAllMocks();
  vi.unstubAllEnvs();
});

describe("InsightSummaryPanel", () => {
  it("keeps deterministic-only panels network-free", () => {
    render(
      <InsightSummaryPanel
        items={[{ id: "local.scope", statement: "Two published plans are visible." }]}
        localOnlyReason="AI explanation is disabled on this decision route."
      />,
    );

    expect(screen.getByText("Two published plans are visible.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain with AI" })).not.toBeInTheDocument();
    expect(screen.getByText(/disabled on this decision route/i)).toBeInTheDocument();
    expect(fetchInsightStatus).not.toHaveBeenCalled();
    expect(fetchInsightSummary).not.toHaveBeenCalled();
  });

  it("renders deterministic facts immediately and makes no automatic request", () => {
    render(panel());

    expect(screen.getByRole("heading", { name: "Insight summary" })).toBeInTheDocument();
    expect(screen.getByText("5 players are visible.")).toBeInTheDocument();
    expect(fetchInsightStatus).not.toHaveBeenCalled();
    expect(fetchInsightSummary).not.toHaveBeenCalled();
  });

  it("disables opt-in without exact published provenance", () => {
    render(panel(5, { ...remote(), provenance: null }));

    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeDisabled();
    expect(screen.getByText(/requires a published manifest hash/i)).toBeInTheDocument();
    expect(fetchInsightStatus).not.toHaveBeenCalled();
    expect(fetchInsightSummary).not.toHaveBeenCalled();
  });

  it("requests the exact evidence packet only after explicit opt-in and renders prose inertly", async () => {
    vi.mocked(fetchInsightSummary).mockResolvedValue({
      ...response,
      headline: "<strong>Injected</strong>",
      items: [{
        text: "[Click](javascript:alert(1))",
        citations: ["coverage.players"],
      }],
    });
    const { container } = render(panel());

    await userEvent.click(screen.getByRole("button", { name: "Explain with AI" }));

    await waitFor(() => expect(fetchInsightSummary).toHaveBeenCalledOnce());
    expect(fetchInsightSummary).toHaveBeenCalledWith(
      {
        schema: "fpl.insight-summary-request",
        schema_version: 1,
        page: "players",
        manifest_sha256: "a".repeat(64),
        run_id: "run-1",
        season: "2026-27",
        as_of: "2026-08-21T16:00:00Z",
        scope: {
          gw_from: 1,
          gw_to: 5,
          position: "all",
          form_window: "season_to_date",
          min_price_tenths: 45,
          max_price_tenths: 150,
          min_avg_minutes_l5: 30,
          availability: "available",
          past_metric: "xg_per_90",
        },
      },
      "test-token",
    );
    const submitted = vi.mocked(fetchInsightSummary).mock.calls[0][0] as unknown as Record<string, unknown>;
    expect(submitted).not.toHaveProperty("facts");
    expect(submitted).not.toHaveProperty("caveats");
    expect(screen.getByText("<strong>Injected</strong>")).toBeInTheDocument();
    expect(screen.getByText("[Click](javascript:alert(1))")).toBeInTheDocument();
    expect(screen.getByText("[coverage.players]")).toBeInTheDocument();
    expect(container.querySelector("strong")).toBeNull();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("makes no insight status or summary call in hosted-static mode", async () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    render(panel());

    expect(screen.getByRole("button", { name: "Explain with AI" })).toBeDisabled();
    expect(screen.getByText(/disabled in the hosted static dashboard/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Explain with AI" }));
    expect(fetchInsightStatus).not.toHaveBeenCalled();
    expect(fetchInsightSummary).not.toHaveBeenCalled();
  });

  it("invalidates old prose and ignores a response that resolves after the scope changes", async () => {
    let resolveSummary: (value: typeof response) => void = () => undefined;
    vi.mocked(fetchInsightSummary).mockReturnValue(
      new Promise((resolve) => {
        resolveSummary = resolve;
      }),
    );
    const { rerender } = render(panel(5));
    await userEvent.click(screen.getByRole("button", { name: "Explain with AI" }));
    await waitFor(() => expect(fetchInsightSummary).toHaveBeenCalledOnce());

    rerender(panel(3));
    expect(screen.getByText("3 players are visible.")).toBeInTheDocument();
    await act(async () => resolveSummary(response));

    expect(screen.queryByLabelText("AI-selected explanation")).not.toBeInTheDocument();
  });

  it("preserves deterministic facts when the optional renderer fails", async () => {
    vi.mocked(fetchInsightStatus).mockRejectedValue(new Error("local renderer unavailable"));
    render(panel());

    await userEvent.click(screen.getByRole("button", { name: "Explain with AI" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("local renderer unavailable");
    expect(screen.getByText("5 players are visible.")).toBeInTheDocument();
  });
});
