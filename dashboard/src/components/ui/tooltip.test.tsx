import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./tooltip";

afterEach(() => {
  cleanup();
  Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
  document.querySelector('[data-fullscreen-mode="fallback"]')?.remove();
  document.querySelector('[data-test-native-fullscreen]')?.remove();
});

describe("tooltips above expanded tables", () => {
  it.each(["inline", "native", "fallback"])("keeps the tooltip in the visible %s layer", (mode) => {
    const root = document.createElement("div");
    if (mode === "native") root.dataset.testNativeFullscreen = "";
    if (mode === "fallback") root.dataset.fullscreenMode = mode;
    if (mode !== "inline") document.body.appendChild(root);
    Object.defineProperty(document, "fullscreenElement", { configurable: true, value: mode === "native" ? root : null });
    render(<TooltipProvider><Tooltip open><TooltipTrigger>Window</TooltipTrigger><TooltipContent>Dates and source</TooltipContent></Tooltip></TooltipProvider>);
    const tooltip = screen.getByRole("tooltip");
    expect((mode === "inline" ? document.body : root).contains(tooltip)).toBe(true);
  });
});
