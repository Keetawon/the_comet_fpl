import { afterEach, describe, expect, it, vi } from "vitest";
import { toBlob } from "html-to-image";
import { captureShareData, captureTable, cloneCaptureContent } from "./tableCapture";

vi.mock("html-to-image", () => ({ toBlob: vi.fn() }));
afterEach(() => { document.body.replaceChildren(); vi.restoreAllMocks(); });

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
    const blob = new Blob(["png"], { type: "image/png" });
    vi.mocked(toBlob).mockImplementation(async (sheet) => {
      expect(sheet.textContent).toContain("Arsenal 3 —");
      expect(sheet.textContent).not.toContain("Changed filter");
      expect(sheet.textContent).toContain("THE COMET");
      expect(sheet.textContent).toContain("GW5–14 · Weekly");
      expect(sheet.textContent).toContain("not a data refresh");
      return blob;
    });
    const result = captureTable(source, { title: "Club calendar", context: "GW5–14 · Weekly", capturedAt: "2026-09-15T09:00:00Z" });
    source.textContent = "Changed filter";
    expect((await result).filename).toBe("the-comet-club-calendar-2026-09-15.png");
    expect(document.body.children).toHaveLength(1);
    expect(source.textContent).toBe("Changed filter");
  });

  it("cleans up after rendering failure and sends only the image/title in a share", async () => {
    Object.defineProperty(document, "fonts", { configurable: true, value: { ready: Promise.resolve() } });
    vi.mocked(toBlob).mockRejectedValueOnce(new Error("render failed"));
    const source = document.createElement("div");
    document.body.append(source);
    await expect(captureTable(source, { title: "Draft", capturedAt: "2026-09-15T09:00:00Z" })).rejects.toThrow("render failed");
    expect(document.body.children).toHaveLength(1);
    const data = captureShareData({ blob: new Blob(["png"]), filename: "draft.png", width: 1, height: 1 }, "Draft");
    expect(Object.keys(data).sort()).toEqual(["files", "title"]);
    expect(data.files![0].name).toBe("draft.png");
    expect(data.files![0].type).toBe("image/png");
  });
});
