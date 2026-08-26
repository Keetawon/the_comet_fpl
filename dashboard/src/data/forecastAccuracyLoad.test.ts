import { afterEach, describe, expect, it, vi } from "vitest";
import playerSample from "./samplePlayerForecastVsActual.json";
import teamSample from "./sampleTeamForecastVsActual.json";

async function loadWith(payloads: Record<string, unknown>) {
  vi.resetModules();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const filename = String(input).split("/").at(-1) ?? "";
      const payload = payloads[filename];
      return payload == null
        ? { ok: false, status: 404, json: async () => ({}) }
        : { ok: true, status: 200, json: async () => payload };
    }),
  );
  return import("./load");
}

const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("schema-v6 forecast accuracy loaders", () => {
  it("accepts the exact player and team files without transporting PMFs", async () => {
    const loaders = await loadWith({
      "player_forecast_vs_actual.json": playerSample,
      "team_forecast_vs_actual.json": teamSample,
    });

    await expect(loaders.loadPlayerForecastVsActual()).resolves.toMatchObject({
      schema: "fpl.dashboard-player-forecast-vs-actual",
      json_schema_version: 6,
      has_outcomes: true,
    });
    await expect(loaders.loadTeamForecastVsActual()).resolves.toMatchObject({
      schema: "fpl.dashboard-team-forecast-vs-actual",
      json_schema_version: 6,
      has_outcomes: true,
    });
    expect("distribution" in playerSample.runs[0].observations[0]).toBe(false);
    expect("goals_for_distribution" in teamSample.runs[0].observations[0]).toBe(false);
  });

  it("rejects stale or ambiguous schema-v5 monitoring payloads", async () => {
    const stale = { ...playerSample, json_schema_version: 5 };
    const { loadPlayerForecastVsActual } = await loadWith({
      "player_forecast_vs_actual.json": stale,
    });
    await expect(loadPlayerForecastVsActual()).rejects.toThrow(
      /expected fpl\.dashboard-player-forecast-vs-actual version 6/,
    );
  });

  it("rejects a PMF field or any other unversioned observation key", async () => {
    const malformed = clone(playerSample) as typeof playerSample & {
      runs: Array<(typeof playerSample.runs)[number] & {
        observations: Array<(typeof playerSample.runs)[number]["observations"][number] & { distribution?: number[] }>;
      }>;
    };
    malformed.runs[0].observations[0].distribution = [0.5, 0.5];
    const { loadPlayerForecastVsActual } = await loadWith({
      "player_forecast_vs_actual.json": malformed,
    });
    await expect(loadPlayerForecastVsActual()).rejects.toThrow(/expected exact keys/);
  });

  it("accepts a null player team code when the stable team identity is complete", async () => {
    const nullableCode = clone(playerSample);
    (
      nullableCode.runs[0].observations[0] as unknown as {
        team_code: number | null;
      }
    ).team_code = null;
    const { loadPlayerForecastVsActual } = await loadWith({
      "player_forecast_vs_actual.json": nullableCode,
    });

    const loaded = await loadPlayerForecastVsActual();
    expect(loaded.runs[0].observations[0]).toMatchObject({
      team_id: 1,
      team_code: null,
      team_name: "Alpha FC",
    });
  });

  it("rejects missing or extra player observation team identity keys", async () => {
    const missingIdentity = clone(playerSample);
    delete (
      missingIdentity.runs[0].observations[0] as unknown as {
        team_name?: string;
      }
    ).team_name;
    const missingLoader = await loadWith({
      "player_forecast_vs_actual.json": missingIdentity,
    });
    await expect(missingLoader.loadPlayerForecastVsActual()).rejects.toThrow(/expected exact keys/);

    const extraIdentity = clone(playerSample);
    (
      extraIdentity.runs[0].observations[0] as unknown as {
        legacy_team_id?: number;
      }
    ).legacy_team_id = 1;
    const extraLoader = await loadWith({
      "player_forecast_vs_actual.json": extraIdentity,
    });
    await expect(extraLoader.loadPlayerForecastVsActual()).rejects.toThrow(/expected exact keys/);
  });

  it("fails closed when player coverage and scored observations disagree", async () => {
    const malformed = clone(playerSample);
    malformed.runs[0].coverage.scored_rows = 3;
    const { loadPlayerForecastVsActual } = await loadWith({
      "player_forecast_vs_actual.json": malformed,
    });
    await expect(loadPlayerForecastVsActual()).rejects.toThrow(/coverage is inconsistent|score rows do not reconcile|observation count/);
  });

  it("rejects an unsupported calibration event instead of interpreting it in JavaScript", async () => {
    const malformed = clone(teamSample) as unknown as {
      runs: Array<{ calibration: Array<{ event: string }> }>;
    };
    malformed.runs[0].calibration[0].event = "poisson_from_lambda";
    const { loadTeamForecastVsActual } = await loadWith({
      "team_forecast_vs_actual.json": malformed,
    });
    await expect(loadTeamForecastVsActual()).rejects.toThrow(/unsupported calibration event/);
  });

  it("rejects non-reciprocal finalized team sides", async () => {
    const malformed = clone(teamSample);
    malformed.runs[0].observations[1].actual_goals_against = 3;
    malformed.runs[0].observations[1].defence_residual = 1.2;
    const { loadTeamForecastVsActual } = await loadWith({
      "team_forecast_vs_actual.json": malformed,
    });
    await expect(loadTeamForecastVsActual()).rejects.toThrow(/sides are not reciprocal/);
  });

  it("rejects null/non-final clean-sheet outcomes and invalid probabilities", async () => {
    const malformed = clone(teamSample) as unknown as {
      runs: Array<{ observations: Array<{ actual_clean_sheet: boolean | null; probability_clean_sheet: number }> }>;
    };
    malformed.runs[0].observations[0].actual_clean_sheet = null;
    malformed.runs[0].observations[0].probability_clean_sheet = 1.2;
    const { loadTeamForecastVsActual } = await loadWith({
      "team_forecast_vs_actual.json": malformed,
    });
    await expect(loadTeamForecastVsActual()).rejects.toThrow(/probability must fall|actual_clean_sheet/);
  });
});
