import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toSvg } from "html-to-image";
import { captureShareData, captureSvgToPng, captureTable, cloneCaptureContent } from "./tableCapture";

vi.mock("html-to-image", () => ({ toSvg: vi.fn() }));
beforeEach(() => {
  vi.spyOn(HTMLImageElement.prototype, "src", "set").mockImplementation(function (this: HTMLImageElement, value) {
    this.setAttribute("src", value);
    if (value) queueMicrotask(() => this.dispatchEvent(new Event("load")));
  });
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
    drawImage: vi.fn(), save: vi.fn(), translate: vi.fn(), rotate: vi.fn(),
    fillText: vi.fn(), restore: vi.fn(),
  } as unknown as CanvasRenderingContext2D);
  vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(callback => callback(new Blob(["png"], { type: "image/png" })));
});
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); vi.useRealTimers(); });

describe("table image capture", () => {
  it("retains displayed order, missing values and selection while expanding scroll bounds only on the clone", () => {
    const source = document.createElement("div");
    source.style.cssText = "overflow:auto;max-height:80px;width:200px";
    source.innerHTML = '<div style="height:80px;display:flex;flex-direction:column"><table><thead style="position:sticky;top:0"><tr><th>xP</th></tr></thead><tbody><tr><td>Beta —</td></tr><tr><td>Alpha 0</td></tr></tbody></table></div><input type="checkbox"><span hidden>Filtered out</span><span data-capture-exclude>manager-123</span><input type="password" value="secret">';
    document.body.append(source);
    Object.defineProperty(source, "scrollWidth", { value: 900 });
    source.querySelector("input")!.checked = true;
    const before = source.outerHTML;
    const copy = cloneCaptureContent(source);
    expect(copy.textContent).toBe("xPBeta —Alpha 0");
    expect(copy.querySelector("input")!.checked).toBe(true);
    expect(copy.querySelector("input[type=password]")).toBeNull();
    expect(copy.querySelector("thead")!.style.position).toBe("static");
    expect(copy.querySelector("div")!.style.height).toBe("auto");
    expect(copy.style.width).toBe("900px");
    expect(copy.style.maxHeight).toBe("none");
    expect(copy.style.overflow).toBe("visible");
    expect(source.outerHTML).toBe(before);
  });

  it("freezes rows before async rendering and adds a branded timestamp without altering source data", async () => {
    Object.defineProperty(document, "fonts", { configurable: true, value: { ready: Promise.resolve() } });
    const source = document.createElement("div");
    source.textContent = "Arsenal 3 —";
    document.body.append(source);
    vi.mocked(toSvg).mockImplementation(async (sheet, options) => {
      expect(sheet.textContent).toContain("Arsenal 3 —");
      expect(sheet.textContent).not.toContain("Changed filter");
      expect(sheet.textContent).toContain("THE COMET");
      expect(sheet.textContent).toContain("www.thecometfpl.com");
      expect(options?.includeStyleProperties).toEqual([]);
      expect(sheet.textContent).toContain("GW5–14 · Weekly");
      expect(sheet.textContent).toContain("not a data refresh");
      return "data:image/svg+xml,test";
    });
    const result = captureTable(source, { title: "Club calendar", context: "GW5–14 · Weekly", capturedAt: "2026-09-15T09:00:00Z" });
    source.textContent = "Changed filter";
    expect((await result).filename).toBe("the-comet-club-calendar-2026-09-15.png");
    expect(document.body.children).toHaveLength(1);
    expect(source.textContent).toBe("Changed filter");
  });

  it("cleans up after rendering failure and sends only the image/title in a share", async () => {
    Object.defineProperty(document, "fonts", { configurable: true, value: { ready: Promise.resolve() } });
    vi.mocked(toSvg).mockRejectedValueOnce(new Error("render failed"));
    const source = document.createElement("div");
    document.body.append(source);
    await expect(captureTable(source, { title: "Draft", capturedAt: "2026-09-15T09:00:00Z" })).rejects.toThrow("render failed");
    expect(document.body.children).toHaveLength(1);
    const data = captureShareData({ blob: new Blob(["png"]), filename: "draft.png", width: 1, height: 1 }, "Draft");
    expect(Object.keys(data).sort()).toEqual(["files", "title"]);
    expect(data.files![0].name).toBe("draft.png");
    expect(data.files![0].type).toBe("image/png");
  });

  it("finishes with suspended animation frames and an unrelated font that never loads", async () => {
    Object.defineProperty(document, "fonts", { configurable: true, value: { ready: new Promise(() => {}) } });
    const frame = vi.spyOn(window, "requestAnimationFrame").mockImplementation(() => 1);
    vi.mocked(toSvg).mockResolvedValueOnce("data:image/svg+xml,test");
    const source = document.createElement("div");
    document.body.append(source);
    const progress = vi.fn();
    const image = await captureTable(source, { title: "Players", capturedAt: "2026-09-16T02:00:00Z" }, progress);
    expect(image.blob.type).toBe("image/png");
    expect(frame).not.toHaveBeenCalled();
    expect(progress.mock.calls.map(([message]) => message.slice(0, 3))).toEqual(["1/3", "2/3", "3/3"]);
  });

  it("bounds a stuck resource/render and cleans up rather than leaving Preparing forever", async () => {
    vi.useFakeTimers();
    vi.mocked(toSvg).mockImplementationOnce(() => new Promise(() => {}));
    const source = document.createElement("div");
    document.body.append(source);
    const result = captureTable(source, { title: "Players", capturedAt: "2026-09-16T02:00:00Z" });
    const rejection = expect(result).rejects.toThrow("Capture took too long");
    await vi.advanceTimersByTimeAsync(20000);
    await rejection;
    expect(document.body.children).toHaveLength(1);
  });

  it("rejects an aborted PNG render before decoding", async () => {
    const controller = new AbortController();
    controller.abort(new Error("cancelled"));
    await expect(captureSvgToPng("data:image/svg+xml,test", 100, 200, controller.signal)).rejects.toThrow("cancelled");
    expect(HTMLCanvasElement.prototype.toBlob).not.toHaveBeenCalled();
  });
});
