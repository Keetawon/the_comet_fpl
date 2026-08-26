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
vi.mock("@/pages/ForecastVsActualPage", () => ({ ForecastVsActualPage: () => null }));
vi.mock("@/pages/OptimizerAuditPage", () => ({ OptimizerAuditPage: () => null }));
vi.mock("@/pages/PlayerAnalyticsPage", () => ({
  PlayerAnalyticsPage: () => <h1>Player analytics route</h1>,
}));
vi.mock("@/pages/TeamAnalyticsPage", () => ({
  TeamAnalyticsPage: () => <h1>Team analytics route</h1>,
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
});
