import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/Sidebar", () => ({
  CometMark: () => <svg aria-hidden="true" />,
  PageBreadcrumb: () => null,
  Sidebar: ({ active, onNavigate, collapsed, onToggleCollapse, variant }: {
    active: string; onNavigate: (id: string) => void; collapsed?: boolean;
    onToggleCollapse?: () => void; variant?: string;
  }) => <aside data-variant={variant}>active:{active}
    <button onClick={() => onNavigate("players")}>Open Players</button>
    {onToggleCollapse && <button onClick={onToggleCollapse} aria-expanded={!collapsed}>
      {collapsed ? "Expand sidebar" : "Collapse sidebar"}</button>}
  </aside>,
}));
vi.mock("@/components/ThemeToggle", () => ({
  ThemeToggle: () => null,
  initTheme: vi.fn(),
}));
vi.mock("@/pages/SummaryPage", () => ({ SummaryPage: () => <h1>Summary route</h1> }));
vi.mock("@/pages/FixtureMatrixPage", () => ({ FixtureMatrixPage: () => null }));
vi.mock("@/pages/GwAnalysisPage", () => ({ GwAnalysisPage: () => <h1>GW Analysis route</h1> }));
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
  it.each(["#score-prediction", "#gw-analysis", "#gw-analysis?gw=5"])("opens Score Prediction from %s in hosted mode", async hash => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    window.location.hash = hash;
    const historyLength = window.history.length;
    render(<App />);
    expect(await screen.findByRole("heading", { name: "GW Analysis route" })).toBeInTheDocument();
    expect(screen.getByText("active:score-prediction")).toBeInTheDocument();
    expect(window.location.hash).toBe(hash.replace("#gw-analysis", "#score-prediction"));
    expect(window.history.length).toBe(historyLength);
    act(() => { window.location.hash = "#players"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByRole("heading", { name: "Players route" })).toBeInTheDocument();
    act(() => { window.location.hash = "#gw-analysis"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(await screen.findByRole("heading", { name: "GW Analysis route" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#score-prediction");
  });
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

  it("allows the hosted browser draft without exposing the optimizer", async () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    window.location.hash = "#squad-draft";
    render(<App />);
    expect(await screen.findByText("active:squad-draft")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Explain with AI" })).not.toBeInTheDocument();
  });

  it.each(["next-gw", "plan-builder", "optimizer"])(
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

describe("responsive navigation", () => {
  afterEach(() => {
    window.location.hash = "";
    window.localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("opens a dismissible menu, closes after navigation, and keeps quick links available", async () => {
    const user = userEvent.setup();
    render(<App />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    const dialog = screen.getByRole("dialog", { name: "Explore The Comet" });
    expect(screen.getByRole("button", { name: "Open navigation", hidden: true })).toHaveAttribute("aria-expanded", "true");
    await user.click(within(dialog).getByRole("button", { name: "Open Players" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Players route" })).toBeInTheDocument();
    const quick = within(screen.getByRole("navigation", { name: "Quick navigation" }));
    expect(quick.getByRole("button", { name: "Players" })).toHaveAttribute("aria-current", "page");
    await user.click(quick.getByRole("button", { name: "Summary" }));
    expect(await screen.findByRole("heading", { name: "Summary route" })).toBeInTheDocument();
  });

  it("closes with Escape or the close control and returns focus to the invoking button", async () => {
    const user = userEvent.setup();
    render(<App />);
    const more = screen.getByRole("button", { name: "More" });
    await user.click(more);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(more).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    await user.click(screen.getByRole("button", { name: "Close navigation" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveFocus();
  });

  it("dismisses the drawer by tapping its backdrop", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "More" }));
    const overlay = document.querySelector<HTMLElement>(".comet-menu-overlay");
    expect(overlay).not.toBeNull();
    await user.click(overlay!);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("still toggles navigation when preference storage is blocked", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked"); });
    try {
      render(<App />);
      fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
      expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    } finally { get.mockRestore(); set.mockRestore(); }
  });

  it("releases the drawer on desktop resize and cleans up its media listener", async () => {
    const change = new EventTarget();
    const media = { matches: false, addEventListener: vi.fn(change.addEventListener.bind(change)), removeEventListener: vi.fn(change.removeEventListener.bind(change)) };
    vi.stubGlobal("matchMedia", vi.fn(() => media));
    const { unmount } = render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    act(() => { media.matches = true; change.dispatchEvent(new Event("change")); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    unmount();
    expect(media.removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  });

  it("closes the drawer on browser history navigation", async () => {
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    act(() => { window.location.hash = "#players"; window.dispatchEvent(new HashChangeEvent("hashchange")); });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Players route" })).toBeInTheDocument();
  });

  it("persists desktop collapse without changing the route", () => {
    window.localStorage.setItem("comet:sidebar-collapsed", "true");
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(screen.getByRole("button", { name: "Collapse sidebar" })).toHaveAttribute("aria-expanded", "true");
    expect(window.localStorage.getItem("comet:sidebar-collapsed")).toBe("false");
    fireEvent.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute("aria-expanded", "false");
    expect(window.localStorage.getItem("comet:sidebar-collapsed")).toBe("true");
    expect(screen.getByText("active:summary")).toBeInTheDocument();
  });
});
