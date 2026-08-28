import { describe, expect, it } from "vitest";
import type { DashboardManifest } from "@/data/types";
import {
  compactInsightScope,
  formWindowScope,
  maxPriceTenthsScope,
  minAverageMinutesScope,
  minPriceTenthsScope,
  playerPastMetricScope,
  publishedInsightProvenance,
  teamPastMetricScope,
} from "./insights";

const manifest: DashboardManifest = {
  schema: "fpl.dashboard-read-models",
  json_schema_version: 8,
  generated_at: "2026-08-26T00:00:00Z",
  ease_index_formula_version: "fixture-ease-v1",
  run_ids: ["run-1"],
  runs: [{
    run_id: "run-1",
    as_of: "2026-08-21T16:00:00Z",
    season: "2026-27",
    gw_from: 1,
    gw_to: 5,
    horizon_gameweeks: 5,
  }],
  source: {
    export_schema: "fpl.bi-export",
    export_schema_version: 1,
    semantic_contract_version: 1,
    export_content_sha256: "b".repeat(64),
    export_created_at: "2026-08-26T00:00:00Z",
    database_sha256: "c".repeat(64),
  },
  files: {},
  content_sha256: "a".repeat(64),
};

describe("insight provenance helpers", () => {
  it("binds only an exact run carried by the genuine manifest", () => {
    expect(publishedInsightProvenance(manifest, {
      run_id: "run-1",
      season: "2026-27",
      gw_from: 1,
      gw_to: 5,
    })).toEqual({
      manifestSha256: "a".repeat(64),
      runId: "run-1",
      season: "2026-27",
      asOf: "2026-08-21T16:00:00Z",
    });
    expect(publishedInsightProvenance(manifest, {
      run_id: "other-run",
      season: "2026-27",
    })).toBeNull();
    expect(publishedInsightProvenance(
      { ...manifest, content_sha256: "not-a-hash" },
      manifest.runs[0],
    )).toBeNull();
  });

  it("normalizes only frozen optional scope values", () => {
    expect(compactInsightScope({ gw_from: 1, gw_to: undefined, position: "MID" })).toEqual({
      gw_from: 1,
      position: "MID",
    });
    expect(formWindowScope("last_3")).toBe(3);
    expect(formWindowScope("season_to_date")).toBe("season_to_date");
    expect(minPriceTenthsScope("6.51")).toBe(66);
    expect(maxPriceTenthsScope("6.59")).toBe(65);
    expect(minAverageMinutesScope("42.5")).toBe(42.5);
    expect(minPriceTenthsScope("")).toBeUndefined();
    expect(playerPastMetricScope("past_future", "xg_per_90")).toBe("xg_per_90");
    expect(playerPastMetricScope("value", "xg_per_90")).toBeUndefined();
    expect(teamPastMetricScope("past-future", "xgc")).toBe("xgc");
    expect(teamPastMetricScope("environment", "xgc")).toBeUndefined();
  });
});
