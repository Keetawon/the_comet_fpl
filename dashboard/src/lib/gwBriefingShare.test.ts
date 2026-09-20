import { afterEach, expect, it, vi } from "vitest";
import { copyGwBriefing, downloadGwBriefing, gwBriefingLineUrl, prepareGwBriefingFacebook, shareGwBriefing } from "./gwBriefingShare";

const text = "THE COMET · GW5\nข่าวประจำสัปดาห์\nPublished forecast: 1.25 expected goals.\nSource: https://www.premierleague.com/";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.history.replaceState(null, "", "/");
});

it("shares the complete composed text natively without supplying a invented permalink or inheriting page state", async () => {
  window.history.replaceState(null, "", "/?manager=123#squad?bank=9");
  const share = vi.fn().mockResolvedValue(undefined);
  const writeText = vi.fn();
  vi.stubGlobal("navigator", { share, clipboard: { writeText } });
  expect(await shareGwBriefing(text)).toBe("shared");
  expect(share).toHaveBeenCalledWith({ title: "THE COMET · Gameweek briefing", text });
  expect(writeText).not.toHaveBeenCalled();
});

it("copies exact text when native sharing is absent or fails", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  expect(await shareGwBriefing(text)).toBe("copied");
  expect(writeText).toHaveBeenLastCalledWith(text);
  vi.stubGlobal("navigator", { share: vi.fn().mockRejectedValue(new Error("Unavailable")), clipboard: { writeText } });
  expect(await shareGwBriefing(text)).toBe("copied");
  expect(writeText).toHaveBeenLastCalledWith(text);
});

it("does not copy or post after cancellation and reports unavailable clipboard honestly", async () => {
  const writeText = vi.fn();
  vi.stubGlobal("navigator", { share: vi.fn().mockRejectedValue(new DOMException("Cancelled", "AbortError")), clipboard: { writeText } });
  expect(await shareGwBriefing(text)).toBe("cancelled");
  expect(writeText).not.toHaveBeenCalled();
  vi.stubGlobal("navigator", {});
  await expect(copyGwBriefing(text)).rejects.toThrow("Download the text instead");
});

it("encodes all LINE text with only the canonical site URL and rejects oversized links without truncating", () => {
  window.history.replaceState(null, "", "/?manager=123#private");
  const url = new URL(gwBriefingLineUrl(`${text}\n& ? # +`) ?? "");
  expect(url.origin).toBe("https://social-plugins.line.me");
  expect(url.searchParams.get("text")).toBe(`${text}\n& ? # +`);
  expect(url.searchParams.get("url")).toBe("https://www.thecometfpl.com/");
  expect([...url.searchParams.keys()].sort()).toEqual(["text", "url"]);
  expect(gwBriefingLineUrl("ก".repeat(1_000))).toBeNull();
});

it("prepares Facebook only after copying text and leaves opening and pasting to the user", async () => {
  window.history.replaceState(null, "", "/?manager=123#private");
  const writeText = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("navigator", { clipboard: { writeText } });
  const open = vi.spyOn(window, "open");
  const result = await prepareGwBriefingFacebook(text);
  expect(writeText).toHaveBeenCalledWith(text);
  const url = new URL(result.url);
  expect(url.origin).toBe("https://www.facebook.com");
  expect([...url.searchParams]).toEqual([["u", "https://www.thecometfpl.com/"]]);
  expect(result.instruction).toMatch(/paste the text/);
  expect(open).not.toHaveBeenCalled();
  writeText.mockRejectedValueOnce(new Error("Copy denied"));
  await expect(prepareGwBriefingFacebook(text)).rejects.toThrow("Copy denied");
});

it("downloads exact UTF-8 text to a fixed public filename and releases the temporary URL", async () => {
  vi.useFakeTimers();
  const create = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:briefing");
  const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    expect(this.download).toBe("the-comet-gameweek-briefing.txt");
    expect(this.href).toBe("blob:briefing");
    expect(this.isConnected).toBe(true);
  });
  downloadGwBriefing(text);
  const blob = create.mock.calls[0][0] as Blob;
  expect(blob.type).toBe("text/plain;charset=utf-8");
  expect(await blob.text()).toBe(text);
  expect(click).toHaveBeenCalledOnce();
  expect(document.querySelector("a[download]")).toBeNull();
  expect(revoke).not.toHaveBeenCalled();
  vi.runAllTimers();
  expect(revoke).toHaveBeenCalledWith("blob:briefing");
});

it("rejects blank briefings before invoking any share or clipboard operation", async () => {
  const share = vi.fn();
  const writeText = vi.fn();
  vi.stubGlobal("navigator", { share, clipboard: { writeText } });
  await expect(shareGwBriefing(" \n")).rejects.toThrow("no briefing text");
  await expect(prepareGwBriefingFacebook("")).rejects.toThrow("no briefing text");
  expect(() => gwBriefingLineUrl(" ")).toThrow("no briefing text");
  expect(() => downloadGwBriefing("")).toThrow("no briefing text");
  expect(share).not.toHaveBeenCalled();
  expect(writeText).not.toHaveBeenCalled();
});
