import { afterEach, describe, expect, it, vi } from "vitest";
import { openCapturePreview } from "./capturePreview";

const info = { title: 'Players <script>alert(1)</script>', capturedAt: "2026-09-15T09:00:00Z" };
const capture = { blob: new Blob(["png"], { type: "image/png" }), filename: "players.png", width: 900, height: 600 };
afterEach(() => { vi.restoreAllMocks(); document.body.replaceChildren(); });

function previewWindow() {
  const frame = document.createElement("iframe");
  document.body.append(frame);
  const popup = frame.contentWindow!;
  vi.spyOn(window, "open").mockReturnValue(popup);
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:test-image");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  return popup;
}

describe("capture preview", () => {
  it("reports a blocked popup instead of silently losing the capture", () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    expect(() => openCapturePreview(info, false)).toThrow("Allow pop-ups");
  });

  it("offers a PNG fallback without auto-sharing, escapes text, and releases the image URL", async () => {
    const popup = previewWindow();
    const controller = openCapturePreview(info, false);
    expect(popup.opener).toBeNull();
    controller.ready(capture);
    expect(popup.document.querySelector("script")).toBeNull();
    expect(popup.document.querySelector("a")!.download).toBe("players.png");
    const buttons = [...popup.document.querySelectorAll("button")];
    buttons.find(b => b.textContent === "Actual size")!.click();
    expect(popup.document.querySelector("img")!.style.maxWidth).toBe("none");
    buttons.find(b => b.textContent === "Share image")!.click();
    expect(popup.document.body.textContent).toContain("Image sharing is unavailable");
    popup.dispatchEvent(new Event("pagehide"));
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:test-image");
  });

  it("shares only after the preview's user action and handles cancellation", async () => {
    const popup = previewWindow();
    const share = vi.fn().mockRejectedValue(new DOMException("cancel", "AbortError"));
    Object.defineProperty(popup.navigator, "share", { configurable: true, value: share });
    Object.defineProperty(popup.navigator, "canShare", { configurable: true, value: () => true });
    openCapturePreview(info, true).ready(capture);
    expect(share).not.toHaveBeenCalled();
    [...popup.document.querySelectorAll("button")].find(b => b.textContent === "Share image")!.click();
    await vi.waitFor(() => expect(popup.document.body.textContent).toContain("Sharing cancelled"));
    expect(Object.keys(share.mock.calls[0][0]).sort()).toEqual(["files", "title"]);
  });
});
