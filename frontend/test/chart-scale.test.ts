import { describe, expect, it } from "vitest";

import { niceVolumeTicks } from "../src/lib/chart-scale";

describe("niceVolumeTicks", () => {
  it.each([
    [1180, [0, 250, 500, 750, 1000, 1250]],
    [47, [0, 10, 20, 30, 40, 50]],
    [3, [0, 1, 2, 3]],
    [0, [0, 1]],
    [-12, [0, 1]],
    [Number.NaN, [0, 1]],
    [Number.POSITIVE_INFINITY, [0, 1]],
  ])("returns readable ticks for %s", (maximum, expected) => {
    expect(niceVolumeTicks(maximum)).toEqual(expected);
  });

  it.each([0.2, 1, 2, 7, 18, 73, 312, 625, 937, 1250, 9999])(
    "covers every finite positive maximum: %s",
    (maximum) => {
      const ticks = niceVolumeTicks(maximum);
      expect(ticks[0]).toBe(0);
      expect(ticks.at(-1)).toBeGreaterThanOrEqual(maximum);
      expect(ticks).toEqual([...ticks].sort((left, right) => left - right));
      expect(new Set(ticks).size).toBe(ticks.length);
      expect(ticks.every(Number.isFinite)).toBe(true);
    },
  );
});
