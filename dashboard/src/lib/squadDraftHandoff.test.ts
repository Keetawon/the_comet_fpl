import { describe, expect, it } from "vitest";
import {
  clearSquadDraftHandoff,
  squadDraftHandoff,
  squadDraftHandoffHref,
  squadDraftHandoffRunId,
} from "@/lib/squadDraftHandoff";

describe("Squad Draft optimizer handoff", () => {
  it("round-trips an explicitly typed optimized handoff", () => {
    const href = squadDraftHandoffHref("run id/with spaces", {
      source: "optimized",
    });
    expect(href).toBe(
      "#squad-draft?optimizer_run_id=run+id%2Fwith+spaces&source=optimized",
    );
    expect(squadDraftHandoff(href)).toEqual({
      source: "optimized",
      optimizerRunId: "run id/with spaces",
      managerCaptureId: null,
    });
    expect(squadDraftHandoffRunId(href)).toBe("run id/with spaces");
  });

  it("round-trips the current manager squad with both immutable ids and a token", () => {
    const href = squadDraftHandoffHref("manager-plan-1", {
      source: "manager_current",
      managerCaptureId: "capture/1",
      serverToken: "lan secret",
    });
    expect(squadDraftHandoff(href)).toEqual({
      source: "manager_current",
      optimizerRunId: "manager-plan-1",
      managerCaptureId: "capture/1",
    });
    expect(href).toContain("source=manager_current");
    expect(href).toContain("manager_capture_id=capture%2F1");
    expect(href).toContain("server_token=lan+secret");
  });

  it("treats the legacy optimizer_run_id-only hash as optimized", () => {
    const href = squadDraftHandoffHref("legacy-1");
    expect(href).toBe("#squad-draft?optimizer_run_id=legacy-1");
    expect(squadDraftHandoff(href)).toEqual({
      source: "optimized",
      optimizerRunId: "legacy-1",
      managerCaptureId: null,
    });
  });

  it("returns null when no handoff was requested", () => {
    expect(squadDraftHandoff("#squad-draft")).toBeNull();
    expect(squadDraftHandoff("#squad-draft?server_token=secret")).toBeNull();
    expect(squadDraftHandoff("#next-gw?optimizer_run_id=run-1")).toBeNull();
  });

  it("rejects incomplete, incompatible, or ambiguous typed handoffs", () => {
    expect(() =>
      squadDraftHandoff("#squad-draft?optimizer_run_id=run-1&source=manager_current"),
    ).toThrow(/requires a manager capture id/i);
    expect(() =>
      squadDraftHandoff(
        "#squad-draft?optimizer_run_id=run-1&source=optimized&manager_capture_id=capture-1",
      ),
    ).toThrow(/cannot carry a manager capture id/i);
    expect(() =>
      squadDraftHandoff(
        "#squad-draft?optimizer_run_id=run-1&optimizer_run_id=run-2",
      ),
    ).toThrow(/invalid optimizer run id/i);
    expect(() =>
      squadDraftHandoffHref("run-1", { source: "manager_current" }),
    ).toThrow(/requires a manager capture id/i);
  });

  it("clears handoff provenance while retaining the fragment-only server token", () => {
    window.location.hash =
      "#squad-draft?optimizer_run_id=run-1&source=manager_current&" +
      "manager_capture_id=capture-1&server_token=lan-secret";

    clearSquadDraftHandoff();

    expect(window.location.hash).toBe("#squad-draft?server_token=lan-secret");
  });
});
