import { afterEach, describe, expect, it, vi } from "vitest";
import { loadNewsFeed, parseNewsFeed, safeNewsSourceUrl, type PublicNewsFeed } from "./newsFeed";

vi.mock("./publicData", () => ({ resolveDataUrl: vi.fn().mockResolvedValue("/sdp/news_feed.json") }));

const feed = (): PublicNewsFeed => ({
  schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-19T12:00:00Z", demo: false,
  sources: [{ source_id: "fpl", source_name: "FPL", source_kind: "fpl", status: "ok", last_checked_at: "2026-09-19T11:00:00Z", last_success_at: "2026-09-19T11:00:00Z", message: "Selected sources only." }],
  stories: [{ id: "a".repeat(64), source_id: "fpl", source_name: "FPL", source_kind: "fpl", source_url: "https://www.arsenal.com/news/update", source_record_id: "code:123", published_at: null, known_at: "2026-09-19T11:00:00Z", source_sha256: "b".repeat(64), season: "2026-27", team_code: 3, team_name: "Arsenal", player_code: 123, player_name: "Example", category: "injury", title: { en: "Example update", th: null }, summary: { en: "The manager hopes he can return.", th: null }, rendering: "source_text", ai_model: null, summarized_at: null }],
});

afterEach(() => vi.unstubAllGlobals());

describe("public news sidecar", () => {
  it("preserves missing publication, translation and exact identity fields", () => {
    expect(parseNewsFeed(feed())).toEqual(feed());
    const unresolved = feed();
    unresolved.stories[0].player_code = null;
    unresolved.stories[0].player_name = null;
    unresolved.stories[0].team_code = null;
    unresolved.stories[0].team_name = null;
    expect(parseNewsFeed(unresolved).stories[0].player_code).toBeNull();
  });
  it("accepts empty not-configured source coverage without inventing stories", () => {
    const value = feed(); value.stories = []; value.sources[0].status = "pending_key"; value.sources[0].last_success_at = null;
    expect(parseNewsFeed(value).stories).toEqual([]);
  });
  it.each(["http://www.arsenal.com/news", "https://127.0.0.1/news", "https://[::1]/news", "https://localhost/news", "https://server.internal/news", "https://user:secret@example.org/news", "javascript:alert(1)", "https://news.com/?manager_id=123", "https://news.com/?api_key=secret"])("blocks unsafe source URL %s", url => {
    expect(safeNewsSourceUrl(url)).toBe(false);
    const value = feed(); value.stories[0].source_url = url;
    expect(() => parseNewsFeed(value)).toThrow();
  });
  it("rejects private payload additions and any forecast field", () => {
    for (const field of ["manager_id", "private_note", "predicted_xp"]) {
      const value = feed(); Object.assign(value.stories[0], { [field]: "private" });
      expect(() => parseNewsFeed(value)).toThrow();
    }
  });
  it("rejects duplicate identities, absent sources, bad chronology and incomplete AI provenance", () => {
    const duplicate = feed(); duplicate.stories.push(duplicate.stories[0]); expect(() => parseNewsFeed(duplicate)).toThrow();
    const absent = feed(); absent.sources = []; expect(() => parseNewsFeed(absent)).toThrow();
    const future = feed(); future.stories[0].known_at = "2026-09-20T12:00:00Z"; expect(() => parseNewsFeed(future)).toThrow();
    const ai = feed(); ai.stories[0].rendering = "ai_summary"; expect(() => parseNewsFeed(ai)).toThrow();
    ai.stories[0].ai_model = "gpt-test"; ai.stories[0].summarized_at = "2026-09-19T11:30:00Z";
    ai.stories[0].title.th = "ข่าว"; ai.stories[0].summary.th = "ยังไม่ยืนยัน";
    expect(parseNewsFeed(ai).stories[0].rendering).toBe("ai_summary");
  });
  it("only accepts canonical X post links for X news", () => {
    const value = feed(); value.sources[0].source_kind = "x"; value.stories[0].source_kind = "x";
    value.stories[0].player_code = null; value.stories[0].player_name = null;
    expect(() => parseNewsFeed(value)).toThrow();
    value.stories[0].source_url = "https://x.com/club/status/123456";
    expect(parseNewsFeed(value).stories[0].source_kind).toBe("x");
  });
  it("fetches only the published optional file with bounded request", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => feed() }); vi.stubGlobal("fetch", fetcher);
    expect(await loadNewsFeed()).toEqual(feed());
    expect(fetcher).toHaveBeenCalledExactlyOnceWith("/sdp/news_feed.json", expect.objectContaining({ signal: expect.any(AbortSignal), redirect: "error" }));
  });
  it("leaves a missing optional file unavailable without provider or old-generation fallback", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 404 }); vi.stubGlobal("fetch", fetcher);
    await expect(loadNewsFeed()).rejects.toThrow("not available");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
