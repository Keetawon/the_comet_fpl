import { afterEach, describe, expect, it, vi } from "vitest";
import {
  fetchPlanStatus,
  solvePlan,
  type PlanServerStatus,
} from "./planServer";
import {
  loadPlanServerToken,
  PLAN_SERVER_TOKEN_STORAGE_KEY,
  planServerTokenFromHash,
  rememberPlanServerToken,
} from "./planServerToken";

const status: PlanServerStatus = {
  busy: false,
  stage: null,
  last_error: null,
  last_result: null,
  worktree_clean: true,
  forecast_ready: true,
};

function response(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue(payload),
  } as unknown as Response;
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  window.location.hash = "";
  window.localStorage.clear();
});

describe("plan server token transport", () => {
  it("sends a trimmed token as a header on status and never in the URL", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(status));
    vi.stubGlobal("fetch", fetchMock);

    expect(await fetchPlanStatus("  lan-secret  ")).toEqual(status);

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8765/status",
      expect.objectContaining({
        headers: { "X-FPL-Plan-Token": "lan-secret" },
      }),
    );
    expect(String(fetchMock.mock.calls[0][0])).not.toContain("lan-secret");
  });

  it("sends the token on solve while keeping it out of the JSON body and URL", async () => {
    const result = {
      ok: true,
      optimizer_run_id: "run-1",
      decision_sha256: "abc",
      gw: 1,
      gw_expected_points: 60,
      horizon_expected_points: 300,
      hit_points: 0,
      squad_cost_tenths: 1000,
      captain: "Alpha",
      vice_captain: "Beta",
    };
    const fetchMock = vi.fn().mockResolvedValue(response(result));
    vi.stubGlobal("fetch", fetchMock);

    await solvePlan(
      { locks: [1], excludes: [2], minBenchAppearance: 0.25 },
      undefined,
      "lan-secret",
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8765/plan");
    expect(url).not.toContain("lan-secret");
    expect(init.headers).toEqual({
      "Content-Type": "application/json",
      "X-FPL-Plan-Token": "lan-secret",
    });
    expect(init.body).toBe(
      JSON.stringify({
        locks: [1],
        excludes: [2],
        min_bench_appearance: 0.25,
      }),
    );
  });

  it("omits the auth header for the loopback no-token flow", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response(status));
    vi.stubGlobal("fetch", fetchMock);

    await fetchPlanStatus(" ");

    expect(fetchMock.mock.calls[0][1]).toEqual(
      expect.objectContaining({ headers: {} }),
    );
  });
});

describe("plan server token source", () => {
  it("reads server_token only from the hash query and lets it override guarded storage", () => {
    window.localStorage.setItem(PLAN_SERVER_TOKEN_STORAGE_KEY, "stored-token");
    window.location.hash = "#plan-builder?run=custom-1&server_token=hash-token";

    expect(planServerTokenFromHash()).toBe("hash-token");
    expect(loadPlanServerToken()).toBe("hash-token");
  });

  it("falls back safely when localStorage reads or writes are denied", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(loadPlanServerToken()).toBe("");
    get.mockRestore();

    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(rememberPlanServerToken("lan-secret")).toBe(false);
    set.mockRestore();
  });
});
