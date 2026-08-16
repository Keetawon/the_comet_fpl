// Theme toggle: flipping it must move the `dark` class on the document root (what every
// token and dark: variant keys off) and persist the choice.

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ThemeToggle } from "./ThemeToggle";

describe("ThemeToggle", () => {
  it("flips the dark class on the document root and persists it", async () => {
    const user = userEvent.setup();
    document.documentElement.classList.remove("dark");
    localStorage.removeItem("theme");
    try {
      render(<ThemeToggle />);
      await user.click(screen.getByRole("button", { name: "Toggle theme" }));
      expect(document.documentElement.classList.contains("dark")).toBe(true);
      expect(localStorage.getItem("theme")).toBe("dark");
      await user.click(screen.getByRole("button", { name: "Toggle theme" }));
      expect(document.documentElement.classList.contains("dark")).toBe(false);
      expect(localStorage.getItem("theme")).toBe("light");
    } finally {
      document.documentElement.classList.remove("dark");
      localStorage.removeItem("theme");
    }
  });
});
