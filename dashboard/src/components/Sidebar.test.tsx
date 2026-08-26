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
});
