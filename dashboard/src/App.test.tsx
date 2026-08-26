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
vi.mock("@/pages/PlayersPage", () => ({ PlayersPage: () => null }));
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
vi.mock("@/pages/PlayerForecastVsActualPage", () => ({
  PlayerForecastVsActualPage: () => <h1>Player prediction accuracy route</h1>,
}));
vi.mock("@/pages/TeamForecastVsActualPage", () => ({
  TeamForecastVsActualPage: () => <h1>Team prediction accuracy route</h1>,
}));

import App from "./App";

describe("App deep-analytics routes", () => {
  afterEach(() => {
    window.location.hash = "";
  });

  it("renders both deep-analytics pages from their stable hash routes", () => {
    window.location.hash = "#player-analytics";
    render(<App />);

    expect(screen.getByRole("heading", { name: "Player analytics route" })).toBeInTheDocument();
    expect(screen.getByText("active:player-analytics")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#team-analytics";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });

    expect(screen.getByRole("heading", { name: "Team analytics route" })).toBeInTheDocument();
    expect(screen.getByText("active:team-analytics")).toBeInTheDocument();
  });

  it("renders separate prediction-accuracy routes and keeps the historical player alias", () => {
    window.location.hash = "#player-forecast-vs-actual";
    render(<App />);
    expect(screen.getByRole("heading", { name: "Player prediction accuracy route" })).toBeInTheDocument();
    expect(screen.getByText("active:player-forecast-vs-actual")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#team-forecast-vs-actual";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByRole("heading", { name: "Team prediction accuracy route" })).toBeInTheDocument();
    expect(screen.getByText("active:team-forecast-vs-actual")).toBeInTheDocument();

    act(() => {
      window.location.hash = "#forecast-vs-actual";
      window.dispatchEvent(new HashChangeEvent("hashchange"));
    });
    expect(screen.getByRole("heading", { name: "Player prediction accuracy route" })).toBeInTheDocument();
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
});
