// Direction of the shared difficulty scale: green = easier, red = harder, NULL = no colour.

import { describe, expect, it } from "vitest";
import {
  cleanSheetBucket,
  easeBucket,
  fdrBucket,
} from "./difficulty";

describe("easeBucket (100 = league average, higher = easier)", () => {
  it("maps high ease to the green end and low ease to the red end", () => {
    expect(easeBucket(130)).toBe("much-easier");
    expect(easeBucket(110)).toBe("easier");
    expect(easeBucket(100)).toBe("average");
    expect(easeBucket(90)).toBe("harder");
    expect(easeBucket(80)).toBe("much-harder");
  });

  it("returns null for unmeasured values instead of a fabricated colour", () => {
    expect(easeBucket(null)).toBeNull();
    expect(easeBucket(undefined)).toBeNull();
  });
});

describe("fdrBucket (official FDR runs opposite: 1 = easiest)", () => {
  it("inverts the direction relative to an ease index", () => {
    expect(fdrBucket(1)).toBe("much-easier");
    expect(fdrBucket(2)).toBe("easier");
    expect(fdrBucket(3)).toBe("average");
    expect(fdrBucket(4)).toBe("harder");
    expect(fdrBucket(5)).toBe("much-harder");
  });

  it("returns null when FDR is unmeasured", () => {
    expect(fdrBucket(null)).toBeNull();
  });
});

describe("cleanSheetBucket (anchored on the league mean)", () => {
  it("is greener above the anchor and redder below it", () => {
    expect(cleanSheetBucket(0.5, 0.25)).toBe("much-easier");
    expect(cleanSheetBucket(0.3, 0.25)).toBe("easier");
    expect(cleanSheetBucket(0.25, 0.25)).toBe("average");
    expect(cleanSheetBucket(0.2, 0.25)).toBe("harder");
    expect(cleanSheetBucket(0.1, 0.25)).toBe("much-harder");
  });

  it("returns null for unmeasured probability or a missing anchor", () => {
    expect(cleanSheetBucket(null, 0.25)).toBeNull();
    expect(cleanSheetBucket(0.3, 0)).toBeNull();
  });
});
