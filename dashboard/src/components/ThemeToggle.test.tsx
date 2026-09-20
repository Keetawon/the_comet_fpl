// Theme toggle: flipping it must move the `dark` class on the document root (what every
// token and dark: variant keys off) and persist the choice.

import { useEffect } from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initTheme, ThemeToggle } from "./ThemeToggle";

function setSystemTheme(dark: boolean) {
  vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: dark })));
}

function AppThemeOrder() {
  useEffect(() => initTheme(), []);
  return <ThemeToggle />;
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    localStorage.removeItem("theme");
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
    setSystemTheme(false);
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.removeItem("theme");
    document.documentElement.classList.remove("dark");
    document.documentElement.style.colorScheme = "";
  });

  it("flips the dark class on the document root and persists it", async () => {
    const user = userEvent.setup();
    render(<ThemeToggle />);
    const button = screen.getByRole("button", { name: "Switch to dark theme" });
    expect(button).toHaveClass("size-11");
    expect(button).toHaveAttribute("aria-pressed", "false");
    await user.click(button);
    expect(document.documentElement).toHaveClass("dark");
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(localStorage.getItem("theme")).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).not.toHaveClass("dark");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(localStorage.getItem("theme")).toBe("light");
  });

  it("changes a saved dark theme on the first click despite parent effect ordering", async () => {
    localStorage.setItem("theme", "dark");
    const user = userEvent.setup();
    render(<AppThemeOrder />);
    const button = screen.getByRole("button", { name: "Switch to light theme" });
    expect(button).toHaveAttribute("aria-pressed", "true");
    expect(document.documentElement).toHaveClass("dark");
    await user.click(button);
    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBe("light");
  });

  it("respects a saved light choice over a dark system preference", () => {
    localStorage.setItem("theme", "light");
    setSystemTheme(true);
    document.documentElement.classList.add("dark");
    render(<AppThemeOrder />);
    expect(document.documentElement).not.toHaveClass("dark");
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toHaveAttribute("aria-pressed", "false");
  });

  it("uses the dark system preference without storing an unchosen preference", async () => {
    setSystemTheme(true);
    const user = userEvent.setup();
    render(<AppThemeOrder />);
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("theme")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("ignores an invalid saved value and uses the system preference", () => {
    localStorage.setItem("theme", "unknown");
    setSystemTheme(true);
    initTheme();
    expect(document.documentElement).toHaveClass("dark");
  });

  it("still toggles when browser storage rejects both reads and writes", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Blocked", "SecurityError"); });
    setSystemTheme(true);
    const user = userEvent.setup();
    render(<AppThemeOrder />);
    await user.click(screen.getByRole("button", { name: "Switch to light theme" }));
    expect(document.documentElement).not.toHaveClass("dark");
    await user.click(screen.getByRole("button", { name: "Switch to dark theme" }));
    expect(document.documentElement).toHaveClass("dark");
  });

  it("defaults to light if no preference API exists", () => {
    vi.stubGlobal("matchMedia", undefined);
    expect(() => initTheme()).not.toThrow();
    render(<ThemeToggle />);
    expect(screen.getByRole("button", { name: "Switch to dark theme" })).toBeVisible();
    expect(document.documentElement).not.toHaveClass("dark");
  });
});
