import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/Sidebar", () => ({
  Sidebar: ({ active }: { active: string }) => <aside>active:{active}</aside>,
}));
vi.mock("@/components/ThemeToggle", () => ({
  ThemeToggle: () => null,
  initTheme: vi.fn(),
}));
vi.mock("@/pages/SummaryPage", () => ({ SummaryPage: () => <h1>Summary route</h1> }));
vi.mock("@/pages/FixtureMatrixPage", () => ({ FixtureMatrixPage: () => null }));
vi.mock("@/pages/PlayersPage", () => ({ PlayersPage: () => <h1>Players route</h1> }));
vi.mock("@/pages/NextGwPage", () => ({ NextGwPage: () => null }));
vi.mock("@/pages/PlanBuilderPage", () => ({ PlanBuilderPage: () => null }));
vi.mock("@/pages/UserDraftPage", () => ({ UserDraftPage: () => null }));
vi.mock("@/pages/OptimizerAuditPage", () => ({ OptimizerAuditPage: () => null }));
vi.mock("@/pages/PlayerAnalyticsPage", () => ({
  PlayerAnalyticsPage: () => <h1>Player analytics route</h1>,
}));
vi.mock("@/pages/TeamAnalyticsPage", () => ({
  TeamAnalyticsPage: () => <h1>Team analytics route</h1>,
}));
vi.mock("@/pages/SdpStatsPage", () => ({
  TeamSdpStatsPage: () => <h1>Team stat from SDP</h1>,
}));
vi.mock("@/pages/PlayerForecastVsActualPage", () => ({
  PlayerForecastVsActualPage: () => <h1>Player prediction accuracy route</h1>,
}));
vi.mock("@/pages/TeamForecastVsActualPage", () => ({
  TeamForecastVsActualPage: () => <h1>Team prediction accuracy route</h1>,
}));

import App from "./App";

describe("App deep-analytics routes", () => {
  it("keeps the SDP team route and sends retired SDP player bookmarks to Players", async () => {
    window.location.hash = "#team-stat-sdp";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Team stat from SDP" })).toBeInTheDocument();
    act(() => { window.location.hash = "#players-stat-sdp"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByRole("heading", { name: "Players route" })).toBeInTheDocument();
    expect(screen.getByText("active:players")).toBeInTheDocument();
  });
  afterEach(() => {
    window.location.hash = "";
    vi.unstubAllEnvs();
  });

  it("keeps paused analytics bookmarks on the summary page", async () => {
    window.location.hash = "#player-analytics";
    render(<App />);
    expect(await screen.findByText("active:summary")).toBeInTheDocument();
    act(() => { window.location.hash = "#team-analytics"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(screen.getByText("active:summary")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /analytics route/ })).not.toBeInTheDocument();
  });

  it("renders separate prediction-accuracy routes and keeps the historical player alias", async () => {
    window.location.hash = "#player-forecast-vs-actual";
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Player prediction accuracy route" })).toBeInTheDocument();
    expect(screen.getByText("active:player-forecast-vs-actual")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#team-forecast-vs-actual";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: "Team prediction accuracy route" })).toBeInTheDocument();
    expect(screen.getByText("active:team-forecast-vs-actual")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#forecast-vs-actual";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(await screen.findByRole("heading", { name: "Player prediction accuracy route" })).toBeInTheDocument();
    expect(screen.getByText("active:forecast-vs-actual")).toBeInTheDocument();
  });

  it("keeps browser decision workspaces deterministic-only", () => {
    window.location.hash = "#plan-builder";
    render(<App />);

    expect(screen.getByRole("heading", { name: "Insight summary" })).toBeInTheDocument();
    expect(screen.getByText(/decision workspace remains deterministic and local/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain with AI" })).not.toBeInTheDocument();

    act(() => {
      window.location.hash = "#squad-draft";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByText(/draft workspace remains deterministic and local/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain with AI" })).not.toBeInTheDocument();
  });

  it.each(["next-gw", "plan-builder", "squad-draft", "optimizer"])(
    "rejects direct hosted navigation to %s", async route => {
      vi.stubEnv("VITE_HOSTED_STATIC", "true");
      window.location.hash = `#${route}`;
      render(<App />);
      expect(await screen.findByRole("heading", { name: "Summary route" })).toBeInTheDocument();
      expect(screen.getByText("active:summary")).toBeInTheDocument();
    },
  );

  it.each(["constructor", "__proto__", "toString", "unknown"])(
    "safely defaults an unknown/inherited route %s", async route => {
      window.location.hash = `#${route}`;
      render(<App />);
      expect(await screen.findByRole("heading", { name: "Summary route" })).toBeInTheDocument();
    },
  );
});
