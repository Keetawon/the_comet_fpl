import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Sidebar } from "./Sidebar";

describe("Sidebar", () => {
  it("exposes both deep-analytics routes and navigates by stable route id", () => {
    const onNavigate = vi.fn();
    render(<Sidebar active="team-analytics" onNavigate={onNavigate} />);

    expect(screen.getByRole("button", { name: "Team analytics" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    fireEvent.click(screen.getByRole("button", { name: "Player analytics" }));
    expect(onNavigate).toHaveBeenCalledWith("player-analytics");
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
