import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DecisionTableFullscreen } from "./DecisionTableFullscreen";

function setFullscreenElement(value: Element | null) {
  Object.defineProperty(document, "fullscreenElement", {
    configurable: true,
    value,
  });
}

afterEach(() => {
  delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen;
  setFullscreenElement(null);
  Object.defineProperty(document, "exitFullscreen", {
    configurable: true,
    value: undefined,
  });
  document.body.style.overflow = "";
});

describe("DecisionTableFullscreen", () => {
  it("enters and exits native fullscreen while preserving child state", async () => {
    const user = userEvent.setup();
    const outside = document.createElement("button");
    outside.textContent = "Outside native";
    document.body.append(outside);
    const requestFullscreen = vi.fn(async function (this: HTMLElement) {
      setFullscreenElement(this);
      document.dispatchEvent(new Event("fullscreenchange"));
    });
    const exitFullscreen = vi.fn(async () => {
      setFullscreenElement(null);
      document.dispatchEvent(new Event("fullscreenchange"));
    });
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: requestFullscreen,
    });
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });

    render(
      <DecisionTableFullscreen label="Players table">
        <label>
          State
          <input defaultValue="kept" />
        </label>
      </DecisionTableFullscreen>,
    );
    const input = screen.getByRole("textbox", { name: "State" });
    await user.clear(input);
    await user.type(input, "still here");
    await user.click(screen.getByRole("button", { name: "Enter Players table fullscreen" }));

    expect(requestFullscreen).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("dialog", { name: "Players table fullscreen" })).toBeInTheDocument();
    expect(outside.inert).toBe(true);
    expect(input).toHaveValue("still here");
    await user.click(screen.getByRole("button", { name: "Exit Players table fullscreen" }));
    expect(exitFullscreen).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Enter Players table fullscreen" })).toHaveFocus(),
    );
    expect(input).toHaveValue("still here");
    expect(outside.inert).toBe(false);
    outside.remove();

    delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen;
  });

  it("tracks a browser-originated native exit and never exits a foreign fullscreen element", async () => {
    const user = userEvent.setup();
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn(async function (this: HTMLElement) {
        setFullscreenElement(this);
        document.dispatchEvent(new Event("fullscreenchange"));
      }),
    });
    const exitFullscreen = vi.fn(async () => undefined);
    Object.defineProperty(document, "exitFullscreen", {
      configurable: true,
      value: exitFullscreen,
    });
    render(
      <DecisionTableFullscreen label="Audit table">
        <p>audit</p>
      </DecisionTableFullscreen>,
    );
    await user.click(screen.getByRole("button", { name: "Enter Audit table fullscreen" }));
    act(() => {
      setFullscreenElement(document.createElement("div"));
      document.dispatchEvent(new Event("fullscreenchange"));
    });
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Enter Audit table fullscreen" }),
      ).toBeInTheDocument(),
    );
    expect(exitFullscreen).not.toHaveBeenCalled();
    delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen;
  });

  it("falls back when native fullscreen is unavailable and exits with Escape", async () => {
    const user = userEvent.setup();
    delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen;
    const outside = document.createElement("button");
    outside.textContent = "Outside";
    document.body.append(outside);
    outside.focus();
    const { unmount } = render(
      <DecisionTableFullscreen label="Fixture matrix table">
        <button type="button">Inside</button>
      </DecisionTableFullscreen>,
    );

    await user.click(screen.getByRole("button", { name: "Enter Fixture matrix table fullscreen" }));
    expect(screen.getByRole("dialog", { name: "Fixture matrix table fullscreen" })).toHaveAttribute(
      "data-fullscreen-mode",
      "fallback",
    );
    expect(document.body.style.overflow).toBe("hidden");
    expect(outside.inert).toBe(true);
    const inside = screen.getByRole("button", { name: "Inside" });
    await user.tab({ shift: true });
    expect(inside).toHaveFocus();
    await user.tab();
    expect(
      screen.getByRole("button", { name: "Exit Fixture matrix table fullscreen" }),
    ).toHaveFocus();
    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Enter Fixture matrix table fullscreen" })).toHaveFocus(),
    );
    expect(document.body.style.overflow).toBe("");
    expect(outside.inert).toBe(false);
    unmount();
    outside.remove();
  });

  it("uses the fallback when requestFullscreen rejects", async () => {
    const user = userEvent.setup();
    Object.defineProperty(HTMLElement.prototype, "requestFullscreen", {
      configurable: true,
      value: vi.fn(async () => {
        throw new Error("denied");
      }),
    });
    render(
      <DecisionTableFullscreen label="Forecast table">
        <p>forecast</p>
      </DecisionTableFullscreen>,
    );
    await user.click(screen.getByRole("button", { name: "Enter Forecast table fullscreen" }));
    expect(screen.getByRole("dialog", { name: "Forecast table fullscreen" })).toHaveAttribute(
      "data-fullscreen-mode",
      "fallback",
    );
    delete (HTMLElement.prototype as { requestFullscreen?: unknown }).requestFullscreen;
  });
});
