import { afterEach, describe, expect, it, vi } from "vitest";
import { newsShareLinks, newsStoryUrl, shareNews } from "./newsShare";

afterEach(() => vi.unstubAllGlobals());

describe("public news sharing", () => {
  it("builds only canonical public identity without inheriting the manager or page filters", () => {
    const links = newsShareLinks("story_12", "th", "ข่าว & news");
    expect(links.url).toBe("https://www.thecometfpl.com/#news?story=story_12&lang=th");
    expect(new URL(links.line).searchParams.get("text")).toBe("ข่าว & news");
    expect(new URL(links.facebook).searchParams.get("u")).toBe(links.url);
    expect(new URL(links.facebook).searchParams.has("quote")).toBe(false);
  });
  it.each(["../private", "id?manager=5", "", "<script>"])("rejects an unsafe identity %s", id => {
    expect(() => newsStoryUrl(id, "en")).toThrow();
  });
  it("copies the permalink when native share is unavailable", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    expect(await shareNews("id", "en", "summary")).toBe("copied");
    expect(writeText).toHaveBeenCalledWith(newsStoryUrl("id", "en"));
  });
  it("does not post or copy on a cancelled native share", async () => {
    const writeText = vi.fn();
    vi.stubGlobal("navigator", { share: vi.fn().mockRejectedValue(new DOMException("Cancelled", "AbortError")), clipboard: { writeText } });
    expect(await shareNews("id", "en", "summary")).toBe("cancelled");
    expect(writeText).not.toHaveBeenCalled();
  });
  it("uses native share only on demand with public text and permalink", async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { share });
    expect(await shareNews("id", "th", "ข่าว")).toBe("shared");
    expect(share).toHaveBeenCalledWith({ title: "THE COMET · Premier League news", text: "ข่าว", url: newsStoryUrl("id", "th") });
  });
});
