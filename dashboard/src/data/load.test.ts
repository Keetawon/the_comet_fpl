// The static read-model boundary fails closed: schema v4, cumulative-horizon semantics,
// and explicit plan ownership are
// required before any page can render optimizer plans.

import { afterEach, describe, expect, it, vi } from "vitest";
import sample from "@/data/sampleNextGw.json";
import horizonsSample from "@/data/samplePlayerHorizons.json";
import playersSample from "@/data/samplePlayers.json";

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

async function loadHorizonsPayload(payload: unknown) {
  vi.resetModules();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => payload,
    })),
  );
  const { loadPlayerHorizons } = await import("./load");
  return loadPlayerHorizons();
}

async function loadPlayersPayload(payload: unknown) {
  vi.resetModules();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | URL | Request) => {
      const url = String(input);
      return url.endsWith("/manifest.json")
        ? { ok: false, status: 404, json: async () => ({}) }
        : { ok: true, status: 200, json: async () => payload };
    }),
  );
  const { loadPlayers } = await import("./load");
  return loadPlayers();
}

function decodedHorizonsSample() {
  return {
    ...horizonsSample,
    players: horizonsSample.players.map((player) => ({
      ...player,
      horizons: player.horizons.map(
        ([gw_to, xp, p_le_2, p_ge_2, p_ge_4, p_ge_6, p_ge_10, p_ge_15]) => ({
          gw_to,
          xp,
          p_le_2,
          p_ge_2,
          p_ge_4,
          p_ge_6,
          p_ge_10,
          p_ge_15,
        }),
      ),
    })),
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("loadNextGw schema boundary", () => {
  it("accepts the current schema-v4 read model", async () => {
    await expect(loadPayload(sample)).resolves.toEqual({ plans: sample.plans });
  });

  it("rejects stale schema v2 even when architecture fields are present", async () => {
    const stale = { ...sample, json_schema_version: 2 };
    await expect(loadPayload(stale)).rejects.toThrow(
      /expected fpl.dashboard-next-gw version 4/,
    );
  });

  it("rejects a schema-v4 plan with missing ownership instead of inferring from V3", async () => {
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

describe("shared schema-v4 envelope", () => {
  it("accepts current players and rejects a mixed stale generation", async () => {
    await expect(loadPlayersPayload(playersSample)).resolves.toMatchObject({
      players: playersSample.players,
      manifest: null,
    });
    await expect(
      loadPlayersPayload({ ...playersSample, json_schema_version: 3 }),
    ).rejects.toThrow(/expected fpl.dashboard-players version 4/);
  });
});

describe("loadPlayerHorizons schema boundary", () => {
  it("decodes exact compact values to named UI records without deriving probabilities", async () => {
    await expect(loadHorizonsPayload(horizonsSample)).resolves.toEqual(decodedHorizonsSample());
  });

  it("rejects a stale schema even when the scalar fields look usable", async () => {
    const stale = { ...horizonsSample, json_schema_version: 3 };
    await expect(loadHorizonsPayload(stale)).rejects.toThrow(/expected version 4 cumulative/);
  });

  it("rejects non-monotone cumulative probability rows", async () => {
    const malformed = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    malformed.players[0].horizons[1][6] = 0.1;
    await expect(loadHorizonsPayload(malformed)).rejects.toThrow(/not a cumulative probability/);
  });

  it("allows only the one-unit six-decimal tolerance for rounded monotonic values", async () => {
    const withinTolerance = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    withinTolerance.players[0].horizons[1][1] = 7.399999;
    withinTolerance.players[0].horizons[1][2] = 0.250001;
    withinTolerance.players[0].horizons[1][7] = 0.099999;
    await expect(loadHorizonsPayload(withinTolerance)).resolves.toBeDefined();

    const outsideTolerance = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    outsideTolerance.players[0].horizons[1][7] = 0.099998;
    await expect(loadHorizonsPayload(outsideTolerance)).rejects.toThrow(
      /not a cumulative probability/,
    );
  });

  it("rejects threshold-tail values in the wrong order", async () => {
    const malformed = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    malformed.players[0].horizons[0][6] = 0.7;
    await expect(loadHorizonsPayload(malformed)).rejects.toThrow(/threshold tails are not ordered/);
  });

  it("rejects a wrong field dictionary, tuple length, or precision contract", async () => {
    const reordered = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    [reordered.horizon_fields[0], reordered.horizon_fields[1]] = [
      reordered.horizon_fields[1],
      reordered.horizon_fields[0],
    ];
    await expect(loadHorizonsPayload(reordered)).rejects.toThrow(/expected version 4 cumulative/);

    const shortTuple = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    shortTuple.players[0].horizons[0].pop();
    await expect(loadHorizonsPayload(shortTuple)).rejects.toThrow(/eight-number six-decimal tuple/);

    const expanded = JSON.parse(JSON.stringify(horizonsSample)) as unknown as {
      players: Array<{ horizons: unknown[] }>;
    };
    expanded.players[0].horizons[0] = {
      gw_to: 1,
      xp: 7.4,
      p_le_2: 0.25,
      p_ge_2: 0.8,
      p_ge_4: 0.65,
      p_ge_6: 0.5,
      p_ge_10: 0.25,
      p_ge_15: 0.1,
    };
    await expect(loadHorizonsPayload(expanded)).rejects.toThrow(/eight-number six-decimal tuple/);

    const overPrecise = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    overPrecise.players[0].horizons[0][7] = 0.1234567;
    await expect(loadHorizonsPayload(overPrecise)).rejects.toThrow(/eight-number six-decimal tuple/);
  });

  it("requires the six-decimal and exact-boundary semantics", async () => {
    const wrongPlaces = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    wrongPlaces.semantics.value_decimal_places = 5 as 6;
    await expect(loadHorizonsPayload(wrongPlaces)).rejects.toThrow(/expected version 4 cumulative/);

    const wrongBoundary = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    wrongBoundary.semantics.probability_boundary_policy = "rounded-boundaries" as "preserve-exact-zero-one-v1";
    await expect(loadHorizonsPayload(wrongBoundary)).rejects.toThrow(/expected version 4 cumulative/);
  });

  it("rejects raw PMFs or any other unversioned extra field", async () => {
    const malformed = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample & {
      players: Array<(typeof horizonsSample.players)[number] & { distribution?: number[] }>;
    };
    malformed.players[0].distribution = [0.5, 0.5];
    await expect(loadHorizonsPayload(malformed)).rejects.toThrow(/no valid identity\/horizons/);
  });

  it("rejects duplicate identities and negative cumulative xP", async () => {
    const duplicate = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    duplicate.players.push(JSON.parse(JSON.stringify(duplicate.players[0])));
    await expect(loadHorizonsPayload(duplicate)).rejects.toThrow(/repeated player/);

    const negative = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    negative.players[0].horizons[0][1] = -0.1;
    await expect(loadHorizonsPayload(negative)).rejects.toThrow(/not ordered cumulative values/);
  });

  it("rejects a missing endpoint or inconsistent run horizon", async () => {
    const gap = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    gap.players[0].horizons.splice(1, 1);
    await expect(loadHorizonsPayload(gap)).rejects.toThrow(/not ordered cumulative values/);

    const inconsistent = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    inconsistent.players[1].horizons.pop();
    await expect(loadHorizonsPayload(inconsistent)).rejects.toThrow(/do not share exact endpoints/);
  });

  it("keeps both score-two events inclusive", async () => {
    const malformed = JSON.parse(JSON.stringify(horizonsSample)) as typeof horizonsSample;
    malformed.players[0].horizons[0][2] = 0.1;
    await expect(loadHorizonsPayload(malformed)).rejects.toThrow(/inclusive score-2 overlap/);
  });
});
