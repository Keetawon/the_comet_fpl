import { describe, expect, it } from "vitest";
import {
  squadDraftHandoffHref,
  squadDraftHandoffRunId,
} from "@/lib/squadDraftHandoff";

describe("Squad Draft optimizer handoff", () => {
  it("round-trips an exact optimizer run id through the hash route", () => {
    const href = squadDraftHandoffHref("run id/with spaces");
    expect(href).toBe("#squad-draft?optimizer_run_id=run%20id%2Fwith%20spaces");
    expect(squadDraftHandoffRunId(href)).toBe("run id/with spaces");
  });

  it("returns null when no handoff was requested", () => {
    expect(squadDraftHandoffRunId("#squad-draft")).toBeNull();
    expect(squadDraftHandoffRunId("#next-gw?optimizer_run_id=run-1")).toBeNull();
  });

  it("rejects empty or ambiguous run ids", () => {
    expect(() => squadDraftHandoffRunId("#squad-draft?optimizer_run_id=")).toThrow(
      /invalid optimizer run id/i,
    );
    expect(() =>
      squadDraftHandoffRunId(
        "#squad-draft?optimizer_run_id=run-1&optimizer_run_id=run-2",
      ),
    ).toThrow(/invalid optimizer run id/i);
  });
});
