import { afterEach, expect, it, vi } from "vitest";
import { loadRestSummary } from "./restSummary";
import { resolveDataUrl } from "./publicData";

vi.mock("./publicData", () => ({ resolveDataUrl: vi.fn() }));
afterEach(() => { vi.clearAllMocks(); vi.unstubAllGlobals(); });

it("fetches only the pinned published sidecar with a bounded timeout", async () => {
  vi.mocked(resolveDataUrl).mockResolvedValue("https://data.example/generations/pinned/sdp/rest_summary.json");
  const fetch = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  await expect(loadRestSummary()).rejects.toThrow(/Invalid published rest summary/);
  expect(resolveDataUrl).toHaveBeenCalledWith("sdp/rest_summary.json");
  expect(fetch).toHaveBeenCalledWith("https://data.example/generations/pinned/sdp/rest_summary.json", { signal: expect.any(AbortSignal) });
});

it("does not fall back to a different generation when the sidecar is missing", async () => {
  vi.mocked(resolveDataUrl).mockRejectedValue(new Error("generation does not contain sdp/rest_summary.json"));
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  await expect(loadRestSummary()).rejects.toThrow(/does not contain/);
  expect(fetch).not.toHaveBeenCalled();
});
