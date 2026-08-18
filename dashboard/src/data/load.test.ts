// The static read-model boundary fails closed: schema v3 and explicit plan ownership are
// required before any page can render optimizer plans.

import { afterEach, describe, expect, it, vi } from "vitest";
import sample from "@/data/sampleNextGw.json";

async function loadPayload(payload: unknown) {
  vi.resetModules();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    })),
  );
  const { loadNextGw } = await import("./load");
  return loadNextGw();
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("loadNextGw schema boundary", () => {
  it("accepts the current schema-v3 read model", async () => {
    await expect(loadPayload(sample)).resolves.toEqual({ plans: sample.plans });
  });

  it("rejects stale schema v2 even when architecture fields are present", async () => {
    const stale = { ...sample, json_schema_version: 2 };
    await expect(loadPayload(stale)).rejects.toThrow(
      /expected version 3 with explicit plan ownership/,
    );
  });

  it("rejects a schema-v3 plan with missing ownership instead of inferring from V3", async () => {
    const missingKind = JSON.parse(JSON.stringify(sample)) as {
      json_schema_version: number;
      plans: { plan_kind?: string }[];
    };
    delete missingKind.plans[0].plan_kind;

    await expect(loadPayload(missingKind)).rejects.toThrow(
      /has no valid plan_kind; ownership is never inferred/,
    );
  });
});
