import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";

describe("Sidebar", () => {
  it("keeps collapsed icons accessible and supports the desktop toggle", () => {
    const toggle = vi.fn();
    render(<Sidebar active="players" onNavigate={vi.fn()} collapsed onToggleCollapse={toggle} />);
    expect(screen.getByRole("navigation", { name: "Pages" })).toHaveAttribute("data-collapsed", "true");
    const players = screen.getByRole("button", { name: "Players" });
    expect(players).toHaveAttribute("title", "Players");
    expect(players).toHaveAttribute("aria-current", "page");
    expect(players).not.toHaveTextContent("Players");
    fireEvent.click(screen.getByRole("button", { name: "Expand sidebar" }));
    expect(toggle).toHaveBeenCalledOnce();
  });

  it("shows full labels in the mobile drawer without exposing hosted-only routes", () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    render(<Sidebar active="summary" onNavigate={vi.fn()} variant="drawer" />);
    expect(screen.getByRole("navigation", { name: "All pages" })).toHaveAttribute("data-variant", "drawer");
    expect(screen.getByRole("button", { name: "Score Prediction" })).toHaveTextContent("Score Prediction");
    expect(screen.queryByRole("button", { name: "Plan builder" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Collapse sidebar" })).not.toBeInTheDocument();
  });

  it("keeps GW Analysis separate from Fixture matrix", () => {
    const onNavigate = vi.fn();
    render(<Sidebar active="gw-analysis" onNavigate={onNavigate} />);
    expect(screen.getByRole("button", { name: "Score Prediction" })).toHaveAttribute("aria-current", "page");
    fireEvent.click(screen.getByRole("button", { name: "Fixture matrix" }));
    expect(onNavigate).toHaveBeenCalledWith("fixtures");
  });
  afterEach(() => vi.unstubAllEnvs());
  it("hides local decision pages only in the public build", () => {
    vi.stubEnv("VITE_HOSTED_STATIC", "true");
    const { rerender } = render(<Sidebar active="summary" onNavigate={vi.fn()} />);
    for (const name of ["Next GW suggestion", "Plan builder", "Optimizer audit"]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Team stat from SDP" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Squad draft" })).toBeInTheDocument();
    vi.stubEnv("VITE_HOSTED_STATIC", "false");
    rerender(<Sidebar active="summary" onNavigate={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Optimizer audit" })).toBeInTheDocument();
  });

  it.each(["false", "true"])("links to the owner's support page safely when hosted=%s", hosted => {
    vi.stubEnv("VITE_HOSTED_STATIC", hosted);
    render(<Sidebar active="summary" onNavigate={vi.fn()} />);
    const link = screen.getByRole("link", { name: "Buy Me a Coffee (opens in a new tab)" });
    expect(link).toHaveAttribute("href", "https://buymeacoffee.com/thecomet");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByText(/coming soon|Payments are not available yet/i)).not.toBeInTheDocument();
  });
  it("keeps the SDP team tab and consolidates duplicate player statistics into Players", () => {
    const onNavigate = vi.fn();
    render(<Sidebar active="team-stat-sdp" onNavigate={onNavigate} />);
    expect(screen.getByRole("button", { name: "Team stat from SDP" })).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("button", { name: "Players stat from SDP" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Players" }));
    expect(onNavigate).toHaveBeenCalledWith("players");
  });
  it("hides both paused analytics pages in local and hosted navigation", () => {
    render(<Sidebar active="summary" onNavigate={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Team analytics" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Player analytics" })).not.toBeInTheDocument();
  });

  it("exposes separate player and team prediction-accuracy routes", () => {
    const onNavigate = vi.fn();
    render(<Sidebar active="player-forecast-vs-actual" onNavigate={onNavigate} />);

    expect(screen.getByRole("button", { name: "Player prediction vs actual" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(screen.getByRole("button", { name: "Team prediction vs actual" }));
    expect(onNavigate).toHaveBeenCalledWith("team-forecast-vs-actual");
    expect(screen.queryByRole("button", { name: "Forecast vs actual" })).not.toBeInTheDocument();
  });
});
