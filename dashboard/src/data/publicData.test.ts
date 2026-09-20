import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import players from "./samplePlayers.json";
import { sdpFixture } from "@/test/sdpFixture";

const pointerUrl = "https://data.thecometfpl.com/current.json";
const generation = "a".repeat(64);
const paths = [
  "data/manifest.json", "data/players.json", "data/player_actuals.json",
  "sdp/sdp_stats.json", "sdp/competitive_schedule.json", "sdp/publication_status.json",
];
const pointer = () => ({
  schema: "fpl.public-dashboard-current", schema_version: 1, generation_sha256: generation,
  base_path: `generations/${generation}`, published_at: "2026-09-17T06:34:00Z",
  files: Object.fromEntries(paths.map(path => [path, { sha256: "b".repeat(64), size_bytes: 123 }])),
});

beforeEach(() => { vi.resetModules(); vi.stubEnv("VITE_PUBLIC_DATA_POINTER", pointerUrl); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("public data generation resolution", () => {
  it("loads optional news from the already-pinned inventory even when the live pointer advances", async () => {
    const news = { schema: "fpl.public-news", schema_version: 1, semantics: "reported_news_not_forecast", generated_at: "2026-09-19T12:00:00Z", demo: false, sources: [], stories: [] };
    let livePointer = { ...pointer(), files: { ...pointer().files, "sdp/news_feed.json": { sha256: "d".repeat(64), size_bytes: 200 } } };
    const fetcher = vi.fn(async (url: string) => ({ ok: true, json: async () => url === pointerUrl ? livePointer : news }));
    vi.stubGlobal("fetch", fetcher);
    const { resolveDataUrl } = await import("./publicData");
    expect(await resolveDataUrl("data/players.json")).toContain(`/generations/${generation}/`);
    livePointer = { ...livePointer, generation_sha256: "c".repeat(64), base_path: `generations/${"c".repeat(64)}` };
    const { loadNewsFeed } = await import("./newsFeed");
    expect(await loadNewsFeed()).toEqual(news);
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual([pointerUrl, `https://data.thecometfpl.com/generations/${generation}/sdp/news_feed.json`]);
  });

  it("refuses optional news absent from the pinned inventory without a legacy or provider fallback", async () => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => pointer() }));
    vi.stubGlobal("fetch", fetcher);
    const { loadNewsFeed } = await import("./newsFeed");
    await expect(loadNewsFeed()).rejects.toThrow("does not contain sdp/news_feed.json");
    const { resolveDataUrl } = await import("./publicData");
    expect(await resolveDataUrl("data/players.json")).toContain(`/generations/${generation}/`);
    expect(fetcher).toHaveBeenCalledExactlyOnceWith(pointerUrl, expect.objectContaining({ redirect: "error" }));
  });

  it("pins a single concurrent pointer read across data, SDP and publication status for this session", async () => {
    let livePointer = pointer();
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => livePointer }));
    vi.stubGlobal("fetch", fetcher);
    const { resolveDataUrl } = await import("./publicData");
    expect(await Promise.all(paths.map(resolveDataUrl))).toEqual(
      paths.map(path => `https://data.thecometfpl.com/generations/${generation}/${path}`),
    );
    expect(fetcher).toHaveBeenCalledOnce();
    expect(fetcher).toHaveBeenCalledWith(pointerUrl, expect.objectContaining({ cache: "no-store", redirect: "error" }));
    livePointer = { ...pointer(), generation_sha256: "c".repeat(64), base_path: `generations/${"c".repeat(64)}` };
    expect(await resolveDataUrl("data/players.json")).toContain(`/generations/${generation}/`);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("leaves the exact legacy data and SDP URL conventions unchanged when unset or blank", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const { resolveDataUrl } = await import("./publicData");
    for (const configured of [undefined, "", " "]) {
      vi.stubEnv("VITE_PUBLIC_DATA_POINTER", configured);
      vi.stubEnv("BASE_URL", "/the_comet_fpl/");
      vi.stubEnv("VITE_DATA_BASE", undefined);
      vi.stubEnv("VITE_SDP_DATA_BASE", undefined);
      expect(await resolveDataUrl("data/players.json")).toBe("/data/players.json");
      expect(await resolveDataUrl("sdp/sdp_stats.json")).toBe("/the_comet_fpl/sdp/sdp_stats.json");
      vi.stubEnv("VITE_DATA_BASE", "https://legacy.test/data");
      vi.stubEnv("VITE_SDP_DATA_BASE", "https://legacy.test/sdp");
      expect(await resolveDataUrl("data/players.json")).toBe("https://legacy.test/data/players.json");
      expect(await resolveDataUrl("sdp/publication_status.json")).toBe("https://legacy.test/sdp/publication_status.json");
    }
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    "/data/players.json", "data/../players.json", "data\\players.json", "data/%2e%2e/players.json",
    "data/players.json?x=1", "data/players.json#x", "//other.test/data/players.json",
    "https://other.test/data/players.json", "sdp//sdp_stats.json", "data/nested/players.json",
  ])("rejects unsafe logical paths before making a request: %s", async path => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const { resolveDataUrl } = await import("./publicData");
    await expect(resolveDataUrl(path)).rejects.toThrow(/file path/);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it.each([
    { schema: "other" }, { schema_version: 2 }, { generation_sha256: "invalid" },
    { base_path: `generations/${"c".repeat(64)}` }, { base_path: `generations/${generation}/` },
    { base_path: "https://other.test/generation" }, { base_path: "../generation" },
    { published_at: "2026-09-17T06:34:00" }, { files: {} },
    { files: { "data/../players.json": { sha256: "b".repeat(64), size_bytes: 1 } } },
    { files: { "data/players.json": { sha256: "invalid", size_bytes: 1 } } },
    { files: { "data/players.json": { sha256: "b".repeat(64), size_bytes: -1 } } },
    { files: { "data/players.json": { sha256: "b".repeat(64), size_bytes: 1.5 } } },
    { files: { "data/players.json": { sha256: "b".repeat(64), size_bytes: 1, url: "https://other.test" } } },
  ])("rejects an invalid generation or inventory without a fallback: %j", async patch => {
    const fetcher = vi.fn(async () => ({ ok: true, json: async () => ({ ...pointer(), ...patch }) }));
    vi.stubGlobal("fetch", fetcher);
    const { resolveDataUrl } = await import("./publicData");
    await expect(resolveDataUrl("data/players.json")).rejects.toThrow(/generation/);
    await expect(resolveDataUrl("sdp/sdp_stats.json")).rejects.toThrow(/generation/);
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it.each([
    "http://data.thecometfpl.com/current.json", "https://user:secret@data.thecometfpl.com/current.json",
    `${pointerUrl}?token=value`, `${pointerUrl}#fragment`, "https://data.thecometfpl.com/a/../current.json",
    "https://data.thecometfpl.com/%2e/current.json",
  ])("rejects unsafe configured pointer URLs: %s", async endpoint => {
    vi.stubEnv("VITE_PUBLIC_DATA_POINTER", endpoint);
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const { resolveDataUrl } = await import("./publicData");
    await expect(resolveDataUrl("data/players.json")).rejects.toThrow(/pointer URL/);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("keeps a failed pointer failed until reload and refuses unlisted files", async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: false, status: 503 });
    vi.stubGlobal("fetch", fetcher);
    let { resolveDataUrl } = await import("./publicData");
    await expect(resolveDataUrl("data/players.json")).rejects.toThrow(/HTTP 503/);
    fetcher.mockResolvedValue({ ok: true, json: async () => pointer() });
    await expect(resolveDataUrl("sdp/sdp_stats.json")).rejects.toThrow(/HTTP 503/);
    expect(fetcher).toHaveBeenCalledOnce();
    vi.resetModules();
    ({ resolveDataUrl } = await import("./publicData"));
    await expect(resolveDataUrl("data/missing.json")).rejects.toThrow(/does not contain/);
  });

  it("routes the existing data and SDP loaders through the same generation and retains it after a file retry", async () => {
    const stats = sdpFixture();
    let failedPlayersOnce = false;
    const schedule = { schema_version: 1, semantics: "current_schedule_not_prediction", as_of: "2026-09-17T06:34:00Z", competitions: [], verified_team_codes: [] };
    const fetcher = vi.fn(async (url: string) => {
      if (url === pointerUrl) return { ok: true, json: async () => pointer() };
      expect(url).toContain(`/generations/${generation}/`);
      if (url.endsWith("/players.json") && !failedPlayersOnce) {
        failedPlayersOnce = true;
        return { ok: false, status: 503, json: async () => null };
      }
      const value = url.endsWith("/players.json") ? players
        : url.endsWith("/sdp_stats.json") ? stats : schedule;
      return { ok: !url.endsWith("/manifest.json"), status: 404, json: async () => value };
    });
    vi.stubGlobal("fetch", fetcher);
    const [{ loadPlayers }, { loadSdpStats }, { loadCompetitiveSchedule }] = await Promise.all([
      import("./load"), import("./sdpStats"), import("./competitiveSchedule"),
    ]);
    await expect(loadPlayers()).rejects.toThrow(/503/);
    const [playerData, statsData, scheduleData] = await Promise.all([loadPlayers(), loadSdpStats(), loadCompetitiveSchedule()]);
    expect(playerData.players).toEqual(players.players);
    expect(statsData).toEqual(stats);
    expect(scheduleData).toEqual(schedule);
    expect(fetcher.mock.calls.filter(([url]) => url === pointerUrl)).toHaveLength(1);
  });
});
